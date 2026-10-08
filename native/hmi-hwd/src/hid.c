/*
 * hid.c -- USB HID input, barcode scanners over evdev (CONTRACT 14.4, "hid").
 * OWNER: A4.
 *
 *   "hid": {"devices": {"scanner": {"match": {"vid": "0c2e", "pid": "0b61", "name": "Barcode"},
 *                                   "path": "/dev/input/event3", "grab": true, "eol": "enter"}}}
 *
 * Each device is opened O_RDONLY|O_NONBLOCK (any file or FIFO of
 * struct input_event works: the tests use a FIFO) and grabbed with
 * EVIOCGRAB when asked (a failed grab -- a FIFO is not an evdev node -- is
 * ignored). poll() drains the events: EV_KEY presses are decoded with a US
 * layout (shift tracked from LEFT/RIGHTSHIFT press/release), the eol key
 * (enter or tab) completes a scan -> hid.<n>.text, hid.<n>.count++.
 *
 * Hotplug: an evdev node that reports ENODEV/EOF is unplugged: present goes
 * false and the device is reopened (path, or `match` resolved through
 * <HWD_SYSFS_ROOT or /sys>/class/input/event*\/device/{name,id/vendor,
 * id/product}) at most once a second of `now`. EOF on a FIFO or a regular
 * file only means "no data yet".
 *
 * Tags: hid.<n>.present (bool), hid.<n>.text (string, null until a scan),
 * hid.<n>.count (int). None is writable.
 * Sim: present true, a scan "SIM-000n" every 5 s of `now`.
 */
#include "backend.h"
#include "periph.h"

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

#define HID_MAX_DEVICES 16
#define HID_TEXT_MAX 512
#define HID_RETRY_S 1.0
#define HID_SIM_EVERY_S 5.0

typedef struct {
    char name[48];
    char path[256];          /* configured path ("" when only match) */
    char vid[16], pid[16], match_name[128];
    bool has_match;
    bool grab;
    int eol_code;            /* KEY_ENTER or KEY_TAB */
    char t_present[HWD_MAX_TAG], t_text[HWD_MAX_TAG], t_count[HWD_MAX_TAG];

    int fd;
    bool is_evdev;           /* character device: EOF/ENODEV = unplugged */
    bool shift;
    char text[HID_TEXT_MAX];
    size_t tlen;
    unsigned char partial[sizeof(struct input_event)];
    size_t plen;
    int64_t count;
    double next_retry;
    double sim_next;
    bool logged_missing;
} hid_dev;

typedef struct {
    hwd_tagstore *store;
    bool sim;
    hid_dev dev[HID_MAX_DEVICES];
    int n;
    uint64_t errors;
} hid_backend;

/* ---- validation -------------------------------------------------------- */

static bool name_ok(const char *s)
{
    if (!s || !*s) return false;
    for (; *s; s++)
        if (!(islower((unsigned char)*s) || isdigit((unsigned char)*s) || *s == '_')) return false;
    return true;
}

static int v_validate(const hwd_config *cfg, char *err, size_t errlen)
{
    const cJSON *hid = cfg ? cfg->hid : NULL;
    if (!hid) return 0;
    if (!cJSON_IsObject(hid)) { snprintf(err, errlen, "hid: must be an object"); return -1; }
    const cJSON *devs = cJSON_GetObjectItemCaseSensitive(hid, "devices");
    if (!cJSON_IsObject(devs)) { snprintf(err, errlen, "hid: devices must be an object"); return -1; }
    int n = 0;
    for (const cJSON *d = devs->child; d; d = d->next) {
        if (!name_ok(d->string)) {
            snprintf(err, errlen, "hid: device name '%s' must match [a-z0-9_]+", d->string);
            return -1;
        }
        if (strlen(d->string) >= sizeof(((hid_dev *)0)->name)) {
            snprintf(err, errlen, "hid: device name '%s' is too long", d->string);
            return -1;
        }
        if (!cJSON_IsObject(d)) { snprintf(err, errlen, "hid.%s: must be an object", d->string); return -1; }
        const cJSON *path = cJSON_GetObjectItemCaseSensitive(d, "path");
        const cJSON *match = cJSON_GetObjectItemCaseSensitive(d, "match");
        if (path && (!cJSON_IsString(path) || !path->valuestring[0] ||
                     strlen(path->valuestring) >= sizeof(((hid_dev *)0)->path))) {
            snprintf(err, errlen, "hid.%s: path must be a non-empty string", d->string);
            return -1;
        }
        if (match) {
            if (!cJSON_IsObject(match) || !match->child) {
                snprintf(err, errlen, "hid.%s: match must be an object with vid, pid and/or name", d->string);
                return -1;
            }
            for (const cJSON *k = match->child; k; k = k->next) {
                bool known = !strcmp(k->string, "vid") || !strcmp(k->string, "pid") || !strcmp(k->string, "name");
                if (!known || !cJSON_IsString(k) || !k->valuestring[0] || strlen(k->valuestring) >= 120) {
                    snprintf(err, errlen, "hid.%s: match.%s must be a non-empty string (vid, pid, name)",
                             d->string, k->string);
                    return -1;
                }
                if (strcmp(k->string, "name") != 0) {
                    const char *s = k->valuestring;
                    if (!strncasecmp(s, "0x", 2)) s += 2;
                    size_t len = strlen(s);
                    bool hex = len >= 1 && len <= 4;
                    for (size_t i = 0; hex && i < len; i++) hex = isxdigit((unsigned char)s[i]);
                    if (!hex) {
                        snprintf(err, errlen, "hid.%s: match.%s must be 1..4 hex digits", d->string, k->string);
                        return -1;
                    }
                }
            }
        }
        if (!path && !match) {
            snprintf(err, errlen, "hid.%s: needs a path or a match", d->string);
            return -1;
        }
        const cJSON *grab = cJSON_GetObjectItemCaseSensitive(d, "grab");
        if (grab && !cJSON_IsBool(grab)) { snprintf(err, errlen, "hid.%s: grab must be true/false", d->string); return -1; }
        const cJSON *eol = cJSON_GetObjectItemCaseSensitive(d, "eol");
        if (eol && (!cJSON_IsString(eol) ||
                    (strcmp(eol->valuestring, "enter") != 0 && strcmp(eol->valuestring, "tab") != 0))) {
            snprintf(err, errlen, "hid.%s: eol must be \"enter\" or \"tab\"", d->string);
            return -1;
        }
        if (++n > HID_MAX_DEVICES) { snprintf(err, errlen, "hid: at most %d devices", HID_MAX_DEVICES); return -1; }
    }
    return 0;
}

/* ---- device discovery -------------------------------------------------- */

static bool read_line(const char *path, char *buf, size_t n)
{
    FILE *f = fopen(path, "r");
    if (!f) return false;
    bool ok = fgets(buf, (int)n, f) != NULL;
    fclose(f);
    if (!ok) return false;
    buf[strcspn(buf, "\r\n")] = '\0';
    return true;
}

static unsigned long hexval(const char *s)
{
    return strtoul(s, NULL, 16);   /* accepts an optional 0x */
}

/* /dev/input/eventN of the first device matching vid/pid/name; false if none. */
static bool resolve_match(const hid_dev *d, char *out, size_t n)
{
    const char *root = getenv("HWD_SYSFS_ROOT");
    if (!root || !*root) root = "/sys";
    char dir[512];
    snprintf(dir, sizeof dir, "%s/class/input", root);
    DIR *dp = opendir(dir);
    if (!dp) return false;
    struct dirent *e;
    bool found = false;
    char best[64] = "";
    while ((e = readdir(dp)) != NULL) {
        if (strncmp(e->d_name, "event", 5) != 0) continue;
        char p[1200], v[160];
        if (d->vid[0]) {
            snprintf(p, sizeof p, "%s/%s/device/id/vendor", dir, e->d_name);
            if (!read_line(p, v, sizeof v) || hexval(v) != hexval(d->vid)) continue;
        }
        if (d->pid[0]) {
            snprintf(p, sizeof p, "%s/%s/device/id/product", dir, e->d_name);
            if (!read_line(p, v, sizeof v) || hexval(v) != hexval(d->pid)) continue;
        }
        if (d->match_name[0]) {
            snprintf(p, sizeof p, "%s/%s/device/name", dir, e->d_name);
            if (!read_line(p, v, sizeof v) || !strcasestr(v, d->match_name)) continue;
        }
        /* lowest event number wins, so the choice is stable */
        if (!found || strlen(e->d_name) < strlen(best) ||
            (strlen(e->d_name) == strlen(best) && strcmp(e->d_name, best) < 0)) {
            snprintf(best, sizeof best, "%s", e->d_name);
            found = true;
        }
    }
    closedir(dp);
    if (found) snprintf(out, n, "/dev/input/%s", best);
    return found;
}

static void set_present(hid_backend *b, hid_dev *d, bool present)
{
    hwd_value v = hwd_bool(present);
    hwd_tagstore_set(b->store, d->t_present, &v);
}

static bool dev_open(hid_backend *b, hid_dev *d)
{
    char path[256];
    if (d->path[0]) snprintf(path, sizeof path, "%s", d->path);
    else if (!resolve_match(d, path, sizeof path)) {
        if (!d->logged_missing) HWD_WARN("hid.%s: no input device matches", d->name);
        d->logged_missing = true;
        return false;
    }
    int fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) {
        if (!d->logged_missing) HWD_WARN("hid.%s: cannot open %s: %s", d->name, path, strerror(errno));
        d->logged_missing = true;
        b->errors++;
        return false;
    }
    struct stat st;
    d->is_evdev = fstat(fd, &st) == 0 && S_ISCHR(st.st_mode);
    if (d->grab && ioctl(fd, EVIOCGRAB, (void *)1) != 0)
        HWD_DEBUG("hid.%s: EVIOCGRAB on %s failed (%s), reading without a grab", d->name, path, strerror(errno));
    d->fd = fd;
    d->shift = false;
    d->tlen = 0;
    d->plen = 0;
    d->logged_missing = false;
    HWD_INFO("hid.%s: opened %s", d->name, path);
    set_present(b, d, true);
    return true;
}

static void dev_close(hid_dev *d)
{
    if (d->fd < 0) return;
    if (d->grab && d->is_evdev) ioctl(d->fd, EVIOCGRAB, (void *)0);
    close(d->fd);
    d->fd = -1;
}

/* ---- backend ----------------------------------------------------------- */

static void v_destroy(void *self);

static void *v_create(const hwd_config *cfg, hwd_tagstore *store, const hwd_backend_opts *opts,
                      char *err, size_t errlen)
{
    if (errlen) err[0] = '\0';
    if (!cfg || !cfg->hid) return NULL;
    if (v_validate(cfg, err, errlen) != 0) return NULL;
    hid_backend *b = calloc(1, sizeof *b);
    if (!b) { snprintf(err, errlen, "hid: out of memory"); return NULL; }
    b->store = store;
    b->sim = opts && opts->sim;
    const cJSON *devs = cJSON_GetObjectItemCaseSensitive(cfg->hid, "devices");
    for (const cJSON *j = devs->child; j && b->n < HID_MAX_DEVICES; j = j->next) {
        hid_dev *d = &b->dev[b->n++];
        d->fd = -1;
        snprintf(d->name, sizeof d->name, "%s", j->string);
        const cJSON *path = cJSON_GetObjectItemCaseSensitive(j, "path");
        if (cJSON_IsString(path)) snprintf(d->path, sizeof d->path, "%s", path->valuestring);
        const cJSON *match = cJSON_GetObjectItemCaseSensitive(j, "match");
        if (cJSON_IsObject(match)) {
            const char *s;
            d->has_match = true;
            if ((s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(match, "vid")))) snprintf(d->vid, sizeof d->vid, "%s", s);
            if ((s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(match, "pid")))) snprintf(d->pid, sizeof d->pid, "%s", s);
            if ((s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(match, "name")))) snprintf(d->match_name, sizeof d->match_name, "%s", s);
        }
        d->grab = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(j, "grab"));
        const char *eol = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(j, "eol"));
        d->eol_code = (eol && !strcmp(eol, "tab")) ? KEY_TAB : KEY_ENTER;
        snprintf(d->t_present, sizeof d->t_present, "hid.%s.present", j->string);
        snprintf(d->t_text, sizeof d->t_text, "hid.%s.text", j->string);
        snprintf(d->t_count, sizeof d->t_count, "hid.%s.count", j->string);
        if (!hwd_tagstore_register(store, d->t_present, hwd_bool(b->sim), false) ||
            !hwd_tagstore_register(store, d->t_text, hwd_null(), false) ||
            !hwd_tagstore_register(store, d->t_count, hwd_int(0), false)) {
            snprintf(err, errlen, "hid.%s: cannot register its tags", d->name);
            v_destroy(b);
            return NULL;
        }
        d->sim_next = -1;
        if (!b->sim && !dev_open(b, d) && opts && opts->strict) {
            snprintf(err, errlen, "hid.%s: device not available (strict)", d->name);
            v_destroy(b);
            return NULL;
        }
    }
    return b;
}

static void scan_done(hid_backend *b, hid_dev *d)
{
    d->text[d->tlen] = '\0';
    hwd_value t = hwd_str(d->text);
    hwd_tagstore_set(b->store, d->t_text, &t);
    hwd_value_clear(&t);
    d->count++;
    hwd_value c = hwd_int(d->count);
    hwd_tagstore_set(b->store, d->t_count, &c);
    HWD_DEBUG("hid.%s: scan '%s'", d->name, d->text);
    d->tlen = 0;
}

static void handle_event(hid_backend *b, hid_dev *d, const struct input_event *ev)
{
    if (ev->type != EV_KEY) return;
    if (ev->code == KEY_LEFTSHIFT || ev->code == KEY_RIGHTSHIFT) {
        d->shift = ev->value != 0;          /* 1 press, 2 repeat, 0 release */
        return;
    }
    if (ev->value != 1) return;             /* presses only */
    if (ev->code == d->eol_code) {
        if (d->tlen > 0) scan_done(b, d);
        return;
    }
    char c = hid_key_char(ev->code, d->shift);
    if (c && d->tlen + 1 < sizeof d->text) d->text[d->tlen++] = c;
}

static void unplugged(hid_backend *b, hid_dev *d, double now, const char *why)
{
    HWD_WARN("hid.%s: device gone (%s)", d->name, why);
    dev_close(d);
    set_present(b, d, false);
    d->next_retry = now + HID_RETRY_S;
}

static void dev_read(hid_backend *b, hid_dev *d, double now)
{
    unsigned char buf[64 * sizeof(struct input_event)];
    for (int round = 0; round < 16; round++) {
        size_t have = d->plen;
        memcpy(buf, d->partial, have);
        ssize_t r = read(d->fd, buf + have, sizeof buf - have);
        if (r < 0) {
            if (errno == EINTR) continue;
            if (errno == EAGAIN || errno == EWOULDBLOCK) return;
            b->errors++;
            unplugged(b, d, now, strerror(errno));
            return;
        }
        if (r == 0) {
            if (d->is_evdev) unplugged(b, d, now, "end of file");
            return;                         /* FIFO without a writer / end of a file: no data */
        }
        size_t total = have + (size_t)r, off = 0;
        while (total - off >= sizeof(struct input_event)) {
            struct input_event ev;
            memcpy(&ev, buf + off, sizeof ev);
            handle_event(b, d, &ev);
            off += sizeof ev;
        }
        d->plen = total - off;
        memcpy(d->partial, buf + off, d->plen);
    }
}

static void v_poll(void *self, double now)
{
    hid_backend *b = self;
    if (!b) return;
    for (int i = 0; i < b->n; i++) {
        hid_dev *d = &b->dev[i];
        if (b->sim) {
            if (d->sim_next < 0) d->sim_next = now + HID_SIM_EVERY_S;
            if (now >= d->sim_next) {
                d->sim_next += HID_SIM_EVERY_S;
                if (d->sim_next <= now) d->sim_next = now + HID_SIM_EVERY_S;
                d->tlen = (size_t)snprintf(d->text, sizeof d->text, "SIM-%04lld", (long long)(d->count + 1));
                scan_done(b, d);
            }
            continue;
        }
        if (d->fd < 0) {
            if (now < d->next_retry) continue;
            d->next_retry = now + HID_RETRY_S;
            if (!dev_open(b, d)) continue;
        }
        dev_read(b, d, now);
    }
}

static bool v_owns(void *self, const char *tag)
{
    hid_backend *b = self;
    if (!b || !tag) return false;
    for (int i = 0; i < b->n; i++) {
        const hid_dev *d = &b->dev[i];
        if (!strcmp(tag, d->t_present) || !strcmp(tag, d->t_text) || !strcmp(tag, d->t_count)) return true;
    }
    return false;
}

static hwd_err v_write(void *self, const char *tag, const hwd_value *v)
{ (void)self; (void)tag; (void)v; return HWD_ERR_NOT_WRITABLE; }

static hwd_err v_command(void *self, const char *cmd, const cJSON *msg, cJSON *reply)
{ (void)self; (void)cmd; (void)msg; (void)reply; return HWD_ERR_UNKNOWN_CMD; }

static uint64_t v_errors(void *self)
{
    hid_backend *b = self;
    return b ? b->errors : 0;
}

static void v_destroy(void *self)
{
    hid_backend *b = self;
    if (!b) return;
    for (int i = 0; i < b->n; i++) dev_close(&b->dev[i]);
    free(b);
}

const hwd_backend_ops hwd_backend_hid = {
    "hid", v_validate, v_create, NULL, v_poll, v_owns, v_write, v_command, NULL, v_errors, v_destroy,
};

/* ---- periph.h HID keymap (A4) ----------------------------------------- */

/* US layout. Index by evdev key code: unshifted, shifted. */
char hid_key_char(int code, bool shift)
{
    static const struct { int code; char lo, hi; } MAP[] = {
        {KEY_1, '1', '!'}, {KEY_2, '2', '@'}, {KEY_3, '3', '#'}, {KEY_4, '4', '$'},
        {KEY_5, '5', '%'}, {KEY_6, '6', '^'}, {KEY_7, '7', '&'}, {KEY_8, '8', '*'},
        {KEY_9, '9', '('}, {KEY_0, '0', ')'},
        {KEY_MINUS, '-', '_'}, {KEY_EQUAL, '=', '+'},
        {KEY_LEFTBRACE, '[', '{'}, {KEY_RIGHTBRACE, ']', '}'}, {KEY_BACKSLASH, '\\', '|'},
        {KEY_SEMICOLON, ';', ':'}, {KEY_APOSTROPHE, '\'', '"'}, {KEY_GRAVE, '`', '~'},
        {KEY_COMMA, ',', '<'}, {KEY_DOT, '.', '>'}, {KEY_SLASH, '/', '?'},
        {KEY_SPACE, ' ', ' '},
        {KEY_Q, 'q', 'Q'}, {KEY_W, 'w', 'W'}, {KEY_E, 'e', 'E'}, {KEY_R, 'r', 'R'},
        {KEY_T, 't', 'T'}, {KEY_Y, 'y', 'Y'}, {KEY_U, 'u', 'U'}, {KEY_I, 'i', 'I'},
        {KEY_O, 'o', 'O'}, {KEY_P, 'p', 'P'},
        {KEY_A, 'a', 'A'}, {KEY_S, 's', 'S'}, {KEY_D, 'd', 'D'}, {KEY_F, 'f', 'F'},
        {KEY_G, 'g', 'G'}, {KEY_H, 'h', 'H'}, {KEY_J, 'j', 'J'}, {KEY_K, 'k', 'K'},
        {KEY_L, 'l', 'L'},
        {KEY_Z, 'z', 'Z'}, {KEY_X, 'x', 'X'}, {KEY_C, 'c', 'C'}, {KEY_V, 'v', 'V'},
        {KEY_B, 'b', 'B'}, {KEY_N, 'n', 'N'}, {KEY_M, 'm', 'M'},
        /* keypad digits type digits too (scanners in "keypad" mode) */
        {KEY_KP0, '0', '0'}, {KEY_KP1, '1', '1'}, {KEY_KP2, '2', '2'}, {KEY_KP3, '3', '3'},
        {KEY_KP4, '4', '4'}, {KEY_KP5, '5', '5'}, {KEY_KP6, '6', '6'}, {KEY_KP7, '7', '7'},
        {KEY_KP8, '8', '8'}, {KEY_KP9, '9', '9'}, {KEY_KPMINUS, '-', '-'}, {KEY_KPPLUS, '+', '+'},
        {KEY_KPDOT, '.', '.'}, {KEY_KPASTERISK, '*', '*'}, {KEY_KPSLASH, '/', '/'},
    };
    for (size_t i = 0; i < sizeof MAP / sizeof MAP[0]; i++)
        if (MAP[i].code == code) return shift ? MAP[i].hi : MAP[i].lo;
    return 0;
}
