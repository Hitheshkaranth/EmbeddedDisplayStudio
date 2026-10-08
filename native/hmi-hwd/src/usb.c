/*
 * usb.c -- USB storage, export and device presence (CONTRACT 14.5, "usb").
 * OWNER: A4.
 *
 *   "usb": {"storage": {"mount_root": "/media", "auto_mount": false, "export_dir": "hmi-export"},
 *           "devices": true}
 *
 * Storage: the first /proc/mounts line (HWD_PROC_MOUNTS overrides the path)
 * whose device starts with /dev/sd and whose mount point is mount_root or
 * under it. Tags usb.storage.present (bool), usb.storage.path (string or
 * null), usb.storage.free_mb (float, statvfs; null without storage).
 * `devices: true`: usb.devices (int) = entries of
 * <HWD_SYSFS_ROOT or /sys>/bus/usb/devices/<entry> with an idVendor file.
 * Rescanned at most once a second of the `now` given to poll().
 *
 * auto_mount (real mode, root): an unmounted /dev/sd?1 is mounted (vfat,
 * exfat, ext4) at <mount_root>/usb0; when its node disappears it is lazily
 * unmounted.
 *
 * usb_export {"what": "logs"|"history"} writes
 * <path>/<export_dir>/<what>-<YYYYmmddTHHMMSSZ>.<txt|db> and answers
 * "file". logs: the core logs to stderr only (journald on the panel), so
 * the file holds a header (time, host) plus this backend's own ring of the
 * last 1000 lines it logged. history: an online copy (SQLite backup API) of
 * the database named by history.path. No storage: hw_error.
 *
 * Sim: storage present at a temporary directory; usb.devices 2.
 */
#include "backend.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <sqlite3.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <time.h>
#include <unistd.h>

#define USB_RESCAN_S 1.0
#define USB_RING 1000
#define USB_LINE 256

typedef struct {
    hwd_tagstore *store;
    bool sim;
    bool storage;              /* "storage" configured */
    bool devices;              /* "devices": true */
    bool auto_mount;
    char mount_root[256];
    char export_dir[128];
    char history_path[512];    /* history.path, "" when none */
    char sim_dir[64];

    bool scanned;
    double last_scan;
    bool present;
    char path[512];
    char mounted_dev[64];      /* what we auto-mounted, "" when nothing */
    char mounted_at[300];
    uint64_t errors;

    char ring[USB_RING][USB_LINE];
    int ring_head, ring_count;
} usb_backend;

static void ulog(usb_backend *b, int level, const char *fmt, ...)
{
    char line[USB_LINE];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    hwd_log(level, "%s", line);
    static const char *const L[] = {"DEBUG", "INFO", "WARNING", "ERROR"};
    char stamp[32];
    time_t t = time(NULL);
    struct tm tm;
    gmtime_r(&t, &tm);
    strftime(stamp, sizeof stamp, "%Y-%m-%dT%H:%M:%SZ", &tm);
    snprintf(b->ring[b->ring_head], USB_LINE, "%s %s %.200s", stamp, L[level < 0 ? 0 : level > 3 ? 3 : level], line);
    b->ring_head = (b->ring_head + 1) % USB_RING;
    if (b->ring_count < USB_RING) b->ring_count++;
}

/* ---- validation -------------------------------------------------------- */

static int v_validate(const hwd_config *cfg, char *err, size_t errlen)
{
    const cJSON *usb = cfg ? cfg->usb : NULL;
    if (!usb) return 0;
    if (!cJSON_IsObject(usb)) { snprintf(err, errlen, "usb: must be an object"); return -1; }
    for (const cJSON *k = usb->child; k; k = k->next) {
        if (strcmp(k->string, "storage") != 0 && strcmp(k->string, "devices") != 0) {
            snprintf(err, errlen, "usb: unknown key '%s'", k->string);
            return -1;
        }
    }
    const cJSON *st = cJSON_GetObjectItemCaseSensitive(usb, "storage");
    if (st) {
        if (!cJSON_IsObject(st)) { snprintf(err, errlen, "usb.storage: must be an object"); return -1; }
        const cJSON *root = cJSON_GetObjectItemCaseSensitive(st, "mount_root");
        if (root && (!cJSON_IsString(root) || root->valuestring[0] != '/' || strlen(root->valuestring) >= 200)) {
            snprintf(err, errlen, "usb.storage: mount_root must be an absolute path");
            return -1;
        }
        const cJSON *am = cJSON_GetObjectItemCaseSensitive(st, "auto_mount");
        if (am && !cJSON_IsBool(am)) { snprintf(err, errlen, "usb.storage: auto_mount must be true/false"); return -1; }
        const cJSON *ed = cJSON_GetObjectItemCaseSensitive(st, "export_dir");
        if (ed && (!cJSON_IsString(ed) || !ed->valuestring[0] || strlen(ed->valuestring) >= 100 ||
                   strstr(ed->valuestring, "..") || ed->valuestring[0] == '/')) {
            snprintf(err, errlen, "usb.storage: export_dir must be a relative directory name");
            return -1;
        }
    }
    const cJSON *dv = cJSON_GetObjectItemCaseSensitive(usb, "devices");
    if (dv && !cJSON_IsBool(dv)) { snprintf(err, errlen, "usb: devices must be true/false"); return -1; }
    return 0;
}

/* ---- scanning ---------------------------------------------------------- */

/* /proc/mounts escapes space, tab, newline and backslash as \ooo. */
static void unescape(char *s)
{
    char *w = s;
    for (char *r = s; *r; r++) {
        if (r[0] == '\\' && r[1] >= '0' && r[1] <= '7' && r[2] >= '0' && r[2] <= '7' && r[3] >= '0' && r[3] <= '7') {
            *w++ = (char)((r[1] - '0') * 64 + (r[2] - '0') * 8 + (r[3] - '0'));
            r += 3;
        } else {
            *w++ = *r;
        }
    }
    *w = '\0';
}

static const char *mounts_path(void)
{
    const char *p = getenv("HWD_PROC_MOUNTS");
    return (p && *p) ? p : "/proc/mounts";
}

static bool under_root(const char *mnt, const char *root)
{
    size_t n = strlen(root);
    while (n > 1 && root[n - 1] == '/') n--;
    if (strncmp(mnt, root, n) != 0) return false;
    return mnt[n] == '\0' || mnt[n] == '/' || (n == 1 && root[0] == '/');
}

/* First /dev/sd* mount under mount_root -> path; also reports whether
 * `dev` (if given) is mounted anywhere. */
static bool find_storage(usb_backend *b, char *path, size_t n, const char *dev, bool *dev_mounted)
{
    if (dev_mounted) *dev_mounted = false;
    FILE *f = fopen(mounts_path(), "r");
    if (!f) return false;
    char line[1024];
    bool found = false;
    while (fgets(line, sizeof line, f)) {
        char src[512], mnt[512];
        if (sscanf(line, "%511s %511s", src, mnt) != 2) continue;
        unescape(src);
        unescape(mnt);
        if (dev && dev_mounted && !strcmp(src, dev)) *dev_mounted = true;
        if (!found && !strncmp(src, "/dev/sd", 7) && under_root(mnt, b->mount_root)) {
            snprintf(path, n, "%s", mnt);
            found = true;
        }
    }
    fclose(f);
    return found;
}

static int count_usb_devices(void)
{
    const char *root = getenv("HWD_SYSFS_ROOT");
    if (!root || !*root) root = "/sys";
    char dir[512];
    snprintf(dir, sizeof dir, "%s/bus/usb/devices", root);
    DIR *dp = opendir(dir);
    if (!dp) return 0;
    int n = 0;
    struct dirent *e;
    while ((e = readdir(dp)) != NULL) {
        if (e->d_name[0] == '.') continue;
        char p[800];
        snprintf(p, sizeof p, "%s/%s/idVendor", dir, e->d_name);
        if (access(p, F_OK) == 0) n++;
    }
    closedir(dp);
    return n;
}

static void publish(usb_backend *b)
{
    hwd_value v = hwd_bool(b->present);
    hwd_tagstore_set(b->store, "usb.storage.present", &v);
    if (b->present) {
        hwd_value p = hwd_str(b->path);
        hwd_tagstore_set(b->store, "usb.storage.path", &p);
        hwd_value_clear(&p);
        struct statvfs sv;
        hwd_value fm = hwd_null();
        if (statvfs(b->path, &sv) == 0)
            fm = hwd_float((double)sv.f_bavail * (double)sv.f_frsize / (1024.0 * 1024.0));
        hwd_tagstore_set(b->store, "usb.storage.free_mb", &fm);
        hwd_tagstore_set_quality(b->store, "usb.storage.free_mb", fm.kind == HWD_NULL ? "bad" : NULL);
    } else {
        hwd_value nul = hwd_null();
        hwd_tagstore_set(b->store, "usb.storage.path", &nul);
        hwd_tagstore_set(b->store, "usb.storage.free_mb", &nul);
        hwd_tagstore_set_quality(b->store, "usb.storage.free_mb", NULL);
    }
}

/* auto_mount: mount the first unmounted /dev/sd?1 at <mount_root>/usb0. */
static void try_auto_mount(usb_backend *b)
{
    DIR *dp = opendir("/dev");
    if (!dp) return;
    struct dirent *e;
    char dev[64] = "";
    while ((e = readdir(dp)) != NULL) {
        const char *s = e->d_name;
        if (strlen(s) == 4 && !strncmp(s, "sd", 2) && s[2] >= 'a' && s[2] <= 'z' && s[3] == '1') {
            char cand[64];
            snprintf(cand, sizeof cand, "/dev/%s", s);
            bool mounted = false;
            char ignore[8];
            find_storage(b, ignore, sizeof ignore, cand, &mounted);
            if (!mounted && (!dev[0] || strcmp(cand, dev) < 0)) snprintf(dev, sizeof dev, "%s", cand);
        }
    }
    closedir(dp);
    if (!dev[0]) return;
    char target[300];
    snprintf(target, sizeof target, "%s/usb0", strcmp(b->mount_root, "/") ? b->mount_root : "");
    mkdir(b->mount_root, 0755);
    mkdir(target, 0755);
    static const char *const FS[] = {"vfat", "exfat", "ext4"};
    for (size_t i = 0; i < sizeof FS / sizeof FS[0]; i++) {
        if (mount(dev, target, FS[i], MS_NOSUID | MS_NODEV | MS_NOEXEC, NULL) == 0) {
            ulog(b, 1, "usb: mounted %s (%s) at %s", dev, FS[i], target);
            snprintf(b->mounted_dev, sizeof b->mounted_dev, "%s", dev);
            snprintf(b->mounted_at, sizeof b->mounted_at, "%s", target);
            return;
        }
    }
    ulog(b, 2, "usb: cannot mount %s at %s: %s", dev, target, strerror(errno));
    b->errors++;
}

static void auto_unmount_if_gone(usb_backend *b)
{
    if (!b->mounted_dev[0] || access(b->mounted_dev, F_OK) == 0) return;
    if (umount2(b->mounted_at, MNT_DETACH) == 0) ulog(b, 1, "usb: %s removed, unmounted %s", b->mounted_dev, b->mounted_at);
    else ulog(b, 2, "usb: unmount %s: %s", b->mounted_at, strerror(errno));
    b->mounted_dev[0] = '\0';
    b->mounted_at[0] = '\0';
}

static void scan(usb_backend *b)
{
    if (b->storage) {
        bool was = b->present;
        if (b->sim) {
            b->present = true;
            snprintf(b->path, sizeof b->path, "%s", b->sim_dir);
        } else {
            if (b->auto_mount) auto_unmount_if_gone(b);
            b->present = find_storage(b, b->path, sizeof b->path, NULL, NULL);
            if (!b->present && b->auto_mount) {
                try_auto_mount(b);
                b->present = find_storage(b, b->path, sizeof b->path, NULL, NULL);
            }
        }
        if (!b->present) b->path[0] = '\0';
        if (b->present != was) ulog(b, 1, b->present ? "usb: storage at %s" : "usb: storage removed%s", b->path);
        publish(b);
    }
    if (b->devices) {
        hwd_value v = hwd_int(b->sim ? 2 : count_usb_devices());
        hwd_tagstore_set(b->store, "usb.devices", &v);
    }
}

/* ---- backend ----------------------------------------------------------- */

static void v_destroy(void *self);

static void *v_create(const hwd_config *cfg, hwd_tagstore *store, const hwd_backend_opts *opts,
                      char *err, size_t errlen)
{
    if (errlen) err[0] = '\0';
    if (!cfg || !cfg->usb) return NULL;
    if (v_validate(cfg, err, errlen) != 0) return NULL;
    usb_backend *b = calloc(1, sizeof *b);
    if (!b) { snprintf(err, errlen, "usb: out of memory"); return NULL; }
    b->store = store;
    b->sim = opts && opts->sim;
    const cJSON *st = cJSON_GetObjectItemCaseSensitive(cfg->usb, "storage");
    b->storage = cJSON_IsObject(st);
    b->devices = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(cfg->usb, "devices"));
    snprintf(b->mount_root, sizeof b->mount_root, "/media");
    snprintf(b->export_dir, sizeof b->export_dir, "hmi-export");
    if (b->storage) {
        const char *s;
        if ((s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(st, "mount_root"))))
            snprintf(b->mount_root, sizeof b->mount_root, "%s", s);
        if ((s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(st, "export_dir"))))
            snprintf(b->export_dir, sizeof b->export_dir, "%s", s);
        b->auto_mount = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(st, "auto_mount"));
    }
    const cJSON *hist = cfg->history ? cJSON_GetObjectItemCaseSensitive(cfg->history, "path") : NULL;
    if (cJSON_IsString(hist)) snprintf(b->history_path, sizeof b->history_path, "%s", hist->valuestring);

    if (b->storage && b->sim) {
        snprintf(b->sim_dir, sizeof b->sim_dir, "/tmp/hmi-usb-sim-XXXXXX");
        if (!mkdtemp(b->sim_dir)) {
            snprintf(err, errlen, "usb: cannot create the simulated storage: %s", strerror(errno));
            free(b);
            return NULL;
        }
    }
    bool ok = true;
    if (b->storage) {
        ok = ok && hwd_tagstore_register(store, "usb.storage.present", hwd_bool(false), false);
        ok = ok && hwd_tagstore_register(store, "usb.storage.path", hwd_null(), false);
        ok = ok && hwd_tagstore_register(store, "usb.storage.free_mb", hwd_null(), false);
    }
    if (b->devices) ok = ok && hwd_tagstore_register(store, "usb.devices", hwd_int(0), false);
    if (!ok) {
        snprintf(err, errlen, "usb: cannot register its tags");
        v_destroy(b);
        return NULL;
    }
    scan(b);
    return b;
}

static void v_poll(void *self, double now)
{
    usb_backend *b = self;
    if (!b) return;
    if (b->scanned && now - b->last_scan < USB_RESCAN_S && now >= b->last_scan) return;
    b->scanned = true;
    b->last_scan = now;
    scan(b);
}

static bool v_owns(void *self, const char *tag)
{
    usb_backend *b = self;
    if (!b || !tag) return false;
    if (b->storage && (!strcmp(tag, "usb.storage.present") || !strcmp(tag, "usb.storage.path") ||
                       !strcmp(tag, "usb.storage.free_mb")))
        return true;
    return b->devices && !strcmp(tag, "usb.devices");
}

static hwd_err v_write(void *self, const char *tag, const hwd_value *v)
{ (void)self; (void)tag; (void)v; return HWD_ERR_NOT_WRITABLE; }

/* mkdir -p */
static int mkdirs(const char *path)
{
    char tmp[700];
    snprintf(tmp, sizeof tmp, "%s", path);
    for (char *p = tmp + 1; *p; p++) {
        if (*p != '/') continue;
        *p = '\0';
        if (mkdir(tmp, 0755) != 0 && errno != EEXIST) return -1;
        *p = '/';
    }
    if (mkdir(tmp, 0755) != 0 && errno != EEXIST) return -1;
    return 0;
}

static int export_logs(usb_backend *b, const char *file)
{
    FILE *f = fopen(file, "w");
    if (!f) return -1;
    char host[256] = "";
    gethostname(host, sizeof host - 1);
    char stamp[32];
    time_t t = time(NULL);
    struct tm tm;
    gmtime_r(&t, &tm);
    strftime(stamp, sizeof stamp, "%Y-%m-%dT%H:%M:%SZ", &tm);
    fprintf(f, "# hmi-hwd %s log export, %s, host %s\n", HWD_VERSION, stamp, host);
    fprintf(f, "# the daemon logs to stderr (journalctl -u hmi-hwd); the lines below are the usb backend's last %d\n",
            USB_RING);
    int start = (b->ring_head - b->ring_count + USB_RING) % USB_RING;
    for (int i = 0; i < b->ring_count; i++) fprintf(f, "%s\n", b->ring[(start + i) % USB_RING]);
    int rc = ferror(f) ? -1 : 0;
    if (fflush(f) != 0) rc = -1;
    fsync(fileno(f));
    if (fclose(f) != 0) rc = -1;
    return rc;
}

/* An online, consistent copy of the live database (SQLite backup API). */
static int export_history(usb_backend *b, const char *file, char *why, size_t n)
{
    sqlite3 *src = NULL, *dst = NULL;
    int rc = sqlite3_open_v2(b->history_path, &src, SQLITE_OPEN_READONLY, NULL);
    if (rc == SQLITE_OK) rc = sqlite3_open(file, &dst);
    if (rc == SQLITE_OK) {
        sqlite3_backup *bk = sqlite3_backup_init(dst, "main", src, "main");
        if (!bk) rc = sqlite3_errcode(dst);
        else {
            do {
                rc = sqlite3_backup_step(bk, 256);
                if (rc == SQLITE_BUSY || rc == SQLITE_LOCKED) sqlite3_sleep(20);
            } while (rc == SQLITE_OK || rc == SQLITE_BUSY || rc == SQLITE_LOCKED);
            sqlite3_backup_finish(bk);
            if (rc == SQLITE_DONE) rc = SQLITE_OK;
        }
    }
    if (rc != SQLITE_OK) snprintf(why, n, "%s", sqlite3_errstr(rc));
    sqlite3_close(src);
    sqlite3_close(dst);
    if (rc == SQLITE_OK) {
        int fd = open(file, O_RDONLY);
        if (fd >= 0) { fsync(fd); close(fd); }
    }
    return rc == SQLITE_OK ? 0 : -1;
}

static hwd_err v_command(void *self, const char *cmd, const cJSON *msg, cJSON *reply)
{
    usb_backend *b = self;
    if (!b || !cmd || strcmp(cmd, "usb_export") != 0) return HWD_ERR_UNKNOWN_CMD;
    const char *what = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(msg, "what"));
    bool logs = what && !strcmp(what, "logs"), history = what && !strcmp(what, "history");
    if (!logs && !history) return HWD_ERR_BAD_VALUE;
    if (history && !b->history_path[0]) return HWD_ERR_NO_HISTORY;
    if (!b->storage) return HWD_ERR_HW_ERROR;
    /* Look again now: the stick may have gone since the last poll. */
    scan(b);
    if (!b->present) return HWD_ERR_HW_ERROR;

    char dir[700];
    snprintf(dir, sizeof dir, "%s/%s", b->path, b->export_dir);
    if (mkdirs(dir) != 0) {
        ulog(b, 3, "usb_export: cannot create %s: %s", dir, strerror(errno));
        b->errors++;
        return HWD_ERR_HW_ERROR;
    }
    char stamp[32];
    time_t t = time(NULL);
    struct tm tm;
    gmtime_r(&t, &tm);
    strftime(stamp, sizeof stamp, "%Y%m%dT%H%M%SZ", &tm);
    char file[800];
    snprintf(file, sizeof file, "%s/%s-%s.%s", dir, what, stamp, logs ? "txt" : "db");
    char why[128] = "";
    int rc = logs ? export_logs(b, file) : export_history(b, file, why, sizeof why);
    if (rc != 0) {
        ulog(b, 3, "usb_export: writing %s failed: %s", file, why[0] ? why : strerror(errno));
        unlink(file);
        b->errors++;
        return HWD_ERR_HW_ERROR;
    }
    ulog(b, 1, "usb_export: wrote %s", file);
    if (reply) cJSON_AddStringToObject(reply, "file", file);
    return HWD_OK;
}

static uint64_t v_errors(void *self)
{
    usb_backend *b = self;
    return b ? b->errors : 0;
}

static void rm_tree(const char *path)
{
    DIR *dp = opendir(path);
    if (dp) {
        struct dirent *e;
        while ((e = readdir(dp)) != NULL) {
            if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
            char p[1024];
            snprintf(p, sizeof p, "%s/%s", path, e->d_name);
            struct stat st;
            if (lstat(p, &st) == 0 && S_ISDIR(st.st_mode)) rm_tree(p);
            else unlink(p);
        }
        closedir(dp);
    }
    rmdir(path);
}

static void v_destroy(void *self)
{
    usb_backend *b = self;
    if (!b) return;
    if (b->sim_dir[0]) rm_tree(b->sim_dir);
    free(b);
}

const hwd_backend_ops hwd_backend_usb = {
    "usb", v_validate, v_create, NULL, v_poll, v_owns, v_write, v_command, NULL, v_errors, v_destroy,
};
