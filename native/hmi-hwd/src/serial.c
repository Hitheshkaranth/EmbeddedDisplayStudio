/*
 * serial.c -- USB and native serial ports with hotplug (CONTRACT 14.1, "serial").
 * OWNER: A3.
 *
 * Backend contract: register every tag in create(), poll() within a few ms,
 * a port that goes away marks present false + rx stale and reopens within a
 * second, sim mode publishes a line every 2 s.
 *
 * Each port is a tty opened O_RDWR|O_NOCTTY|O_NONBLOCK and set raw at its
 * baudrate/bytesize/parity/stopbits. `path` opens that node; `match` finds
 * the tty whose USB device has that idVendor/idProduct (and serial, when
 * given) under <HWD_SYSFS_ROOT or /sys>/class/tty/<name>/device/.. and opens
 * /dev/<name>, resolved again on every reopen (a replugged adapter may come
 * back under another name). poll() drains what arrived without blocking and
 * splits it on `eol` (default "\r\n"; a bare "\n" always ends a line too);
 * the last complete non-empty line, without its terminator, is
 * serial.<name>.rx and serial.<name>.rx_count counts them. A line longer than
 * `max_line` (default 256) bytes is cut there and published as a line, as
 * pyserial's read_until(size=...) does. A read error, EOF or POLLHUP means
 * unplugged: close, present false, rx keeps its value with quality "stale";
 * the port is retried every 0.5 s (back within 1 s of replug) and present
 * goes true when it opens.
 *
 * Sim (--sim): a port whose `path` opens is served for real (the acceptance
 * tests run the daemon with --sim against a pty); any other port is
 * simulated: present true, and every poll whose `now` crosses the next 2-s
 * mark receives the line "SIM <n>" (n = 1, 2, ...). HWD_SIM_FAIL on
 * serial.<name>.rx makes those reads null + "bad" (and counts an error).
 */
#include "backend.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <math.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <termios.h>
#include <unistd.h>

#define MAX_PORT_NAME 64
#define MAX_EOL 8
/* A missing port is retried this often, so it is back within 1 s of replug. */
#define RETRY_S 0.5

/* A single serial port. */
typedef struct {
    char name[MAX_PORT_NAME + 1];
    char t_present[HWD_MAX_TAG], t_rx[HWD_MAX_TAG], t_count[HWD_MAX_TAG];
    char path[256];           /* configured path; "" when matched */
    bool has_match;
    long vid, pid;
    char serial[128];         /* "" = any */
    char dev[300];            /* node currently / last opened */
    int baudrate, bytesize, stopbits;
    char parity;              /* 'N', 'E', 'O' */
    char eol[MAX_EOL + 1];
    size_t eol_len;
    size_t max_line;
    int fd;                   /* -1 while closed */
    bool present;
    bool sim;                 /* simulated port */
    int64_t rx_count;
    char *line;               /* max_line + 1 bytes */
    size_t len;
    double next_try;          /* mono time of the next open attempt */
    double next_mark;         /* sim: next 2 s boundary (0 = not started) */
    int64_t sim_n;
} port;

typedef struct {
    hwd_backend_opts opts;
    hwd_tagstore *store;
    port *ports; size_t n_ports;
    uint64_t errors;
} ser_t;

/* --- small cJSON helpers ------------------------------------------------ */

static const cJSON *json_find(const cJSON *o, const char *name)
{
    return (o && cJSON_IsObject(o)) ? cJSON_GetObjectItemCaseSensitive(o, name) : NULL;
}
static double json_num(const cJSON *o, const char *name, double def)
{
    const cJSON *v = json_find(o, name);
    return (v && cJSON_IsNumber(v)) ? v->valuedouble : def;
}
static const char *json_s(const cJSON *o, const char *name)
{
    const cJSON *v = json_find(o, name);
    return (v && cJSON_IsString(v) && v->valuestring) ? v->valuestring : NULL;
}
static bool json_int_ok(const cJSON *v)
{
    return v && cJSON_IsNumber(v) && v->valuedouble == floor(v->valuedouble)
        && fabs(v->valuedouble) < 1e9;
}

/* Port name rule [a-z0-9_]+ */
static bool port_name_ok(const char *s)
{
    if (!s || !*s || strlen(s) > MAX_PORT_NAME) return false;
    for (; *s; s++)
        if (!((*s >= 'a' && *s <= 'z') || (*s >= '0' && *s <= '9') || *s == '_')) return false;
    return true;
}

/* "0403" / "0x0403": 1-4 hex digits -> value, or -1. */
static long parse_hex_id(const char *s)
{
    if (!s) return -1;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) s += 2;
    size_t n = strlen(s);
    if (n == 0 || n > 4) return -1;
    for (size_t i = 0; i < n; i++)
        if (!strchr("0123456789abcdefABCDEF", s[i])) return -1;
    return strtol(s, NULL, 16);
}

/* baudrate -> termios B<baud> flag; 0 when not in the table. */
static speed_t baud_speed(int baud)
{
    switch (baud) {
    case 50: return B50;           case 75: return B75;
    case 110: return B110;         case 134: return B134;
    case 150: return B150;         case 200: return B200;
    case 300: return B300;         case 600: return B600;
    case 1200: return B1200;       case 1800: return B1800;
    case 2400: return B2400;       case 4800: return B4800;
    case 9600: return B9600;       case 19200: return B19200;
    case 38400: return B38400;     case 57600: return B57600;
    case 115200: return B115200;   case 230400: return B230400;
    case 460800: return B460800;   case 500000: return B500000;
    case 576000: return B576000;   case 921600: return B921600;
    case 1000000: return B1000000; case 1152000: return B1152000;
    case 1500000: return B1500000; case 2000000: return B2000000;
    case 2500000: return B2500000; case 3000000: return B3000000;
    case 3500000: return B3500000; case 4000000: return B4000000;
    default: return (speed_t)0;
    }
}

/* ---- validate ---------------------------------------------------------- */

static int v_validate(const hwd_config *cfg, char *err, size_t errlen)
{
    if (errlen) err[0] = '\0';
    const cJSON *serial = cfg->serial;
    if (!serial) return 0;
    if (!cJSON_IsObject(serial)) { snprintf(err, errlen, "serial must be an object"); return -1; }
    const cJSON *ports = json_find(serial, "ports");
    if (!ports || !cJSON_IsObject(ports)) {
        snprintf(err, errlen, "serial.ports must be an object");
        return -1;
    }
    for (const cJSON *p = ports->child; p; p = p->next) {
        if (!port_name_ok(p->string)) {
            snprintf(err, errlen, "serial.ports: port name '%s' must match [a-z0-9_]+",
                     p->string ? p->string : "");
            return -1;
        }
        if (!cJSON_IsObject(p)) {
            snprintf(err, errlen, "serial.ports.%s must be an object", p->string);
            return -1;
        }
        const cJSON *path = json_find(p, "path");
        const cJSON *match = json_find(p, "match");
        if (!path && !match) {
            snprintf(err, errlen, "serial.ports.%s: needs path or match", p->string);
            return -1;
        }
        if (path && (!cJSON_IsString(path) || !path->valuestring[0])) {
            snprintf(err, errlen, "serial.ports.%s.path must be a non-empty string", p->string);
            return -1;
        }
        if (match) {
            if (!cJSON_IsObject(match) || parse_hex_id(json_s(match, "vid")) < 0
                || parse_hex_id(json_s(match, "pid")) < 0) {
                snprintf(err, errlen, "serial.ports.%s.match needs vid and pid as hex strings",
                         p->string);
                return -1;
            }
            const cJSON *sn = json_find(match, "serial");
            if (sn && !cJSON_IsString(sn)) {
                snprintf(err, errlen, "serial.ports.%s.match.serial must be a string", p->string);
                return -1;
            }
        }
        const cJSON *baud = json_find(p, "baudrate");
        if (baud && (!json_int_ok(baud) || baud_speed((int)baud->valuedouble) == 0)) {
            snprintf(err, errlen, "serial.ports.%s.baudrate is not a supported rate", p->string);
            return -1;
        }
        const cJSON *bs = json_find(p, "bytesize");
        if (bs && (!json_int_ok(bs) || bs->valuedouble < 5 || bs->valuedouble > 8)) {
            snprintf(err, errlen, "serial.ports.%s.bytesize must be 5..8", p->string);
            return -1;
        }
        const cJSON *par = json_find(p, "parity");
        if (par && (!cJSON_IsString(par) || strlen(par->valuestring) != 1
                    || !strchr("NEO", par->valuestring[0]))) {
            snprintf(err, errlen, "serial.ports.%s.parity must be N, E or O", p->string);
            return -1;
        }
        const cJSON *sb = json_find(p, "stopbits");
        if (sb && (!json_int_ok(sb) || (sb->valuedouble != 1 && sb->valuedouble != 2))) {
            snprintf(err, errlen, "serial.ports.%s.stopbits must be 1 or 2", p->string);
            return -1;
        }
        const cJSON *eol = json_find(p, "eol");
        if (eol && (!cJSON_IsString(eol) || !eol->valuestring[0]
                    || strlen(eol->valuestring) > MAX_EOL)) {
            snprintf(err, errlen, "serial.ports.%s.eol must be a string of 1..%d chars",
                     p->string, MAX_EOL);
            return -1;
        }
        const cJSON *ml = json_find(p, "max_line");
        if (ml && (!json_int_ok(ml) || ml->valuedouble < 1 || ml->valuedouble > 65536)) {
            snprintf(err, errlen, "serial.ports.%s.max_line must be 1..65536", p->string);
            return -1;
        }
    }
    return 0;
}

/* ---- sysfs match ------------------------------------------------------- */

static const char *sysfs_root(void)
{
    const char *r = getenv("HWD_SYSFS_ROOT");
    return (r && r[0]) ? r : "/sys";
}

static bool read_attr(const char *path, char *buf, size_t n)
{
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return false;
    ssize_t got = read(fd, buf, n - 1);
    close(fd);
    if (got <= 0) return false;
    buf[got] = '\0';
    while (got > 0 && (buf[got - 1] == '\n' || buf[got - 1] == ' ' || buf[got - 1] == '\r'))
        buf[--got] = '\0';
    return true;
}

/* Does /sys/class/tty/<tty> belong to the USB device P->match names? The
 * idVendor of a cdc-acm tty sits one level above its `device` (the
 * interface), of a usb-serial tty (ftdi, cp210x) two levels. */
static bool tty_matches(const port *P, const char *ttydir)
{
    static const char *const up[] = {"", "/..", "/../..", "/../../.."};
    for (size_t i = 0; i < sizeof up / sizeof up[0]; i++) {
        char base[640], path[700], buf[160];
        snprintf(base, sizeof base, "%s/device%s", ttydir, up[i]);
        snprintf(path, sizeof path, "%s/idVendor", base);
        if (!read_attr(path, buf, sizeof buf)) continue;
        if (parse_hex_id(buf) != P->vid) return false;
        snprintf(path, sizeof path, "%s/idProduct", base);
        if (!read_attr(path, buf, sizeof buf) || parse_hex_id(buf) != P->pid) return false;
        if (P->serial[0]) {
            snprintf(path, sizeof path, "%s/serial", base);
            if (!read_attr(path, buf, sizeof buf) || strcmp(buf, P->serial) != 0) return false;
        }
        return true;
    }
    return false;
}

/* The device node for P: its path, or the first matching tty. */
static bool resolve(const port *P, char *dev, size_t n)
{
    if (!P->has_match) {
        snprintf(dev, n, "%s", P->path);
        return true;
    }
    char base[320];
    snprintf(base, sizeof base, "%s/class/tty", sysfs_root());
    DIR *d = opendir(base);
    if (!d) return false;
    bool found = false;
    struct dirent *e;
    while (!found && (e = readdir(d)) != NULL) {
        if (e->d_name[0] == '.') continue;
        char ttydir[600];
        snprintf(ttydir, sizeof ttydir, "%s/%s", base, e->d_name);
        if (tty_matches(P, ttydir)) {
            snprintf(dev, n, "/dev/%s", e->d_name);
            found = true;
        }
    }
    closedir(d);
    return found;
}

/* ---- termios + open ---------------------------------------------------- */

static void apply_termios(port *P)
{
    struct termios tio;
    if (tcgetattr(P->fd, &tio) != 0) return;   /* not a tty: use as is */
    cfmakeraw(&tio);
    speed_t spd = baud_speed(P->baudrate);
    if (spd) { cfsetispeed(&tio, spd); cfsetospeed(&tio, spd); }
    tio.c_cflag &= ~(tcflag_t)(CSIZE | CSTOPB | PARENB | PARODD | CRTSCTS);
    tio.c_cflag |= CLOCAL | CREAD;
    tio.c_cflag |= P->bytesize == 5 ? CS5 : P->bytesize == 6 ? CS6 : P->bytesize == 7 ? CS7 : CS8;
    if (P->stopbits == 2) tio.c_cflag |= CSTOPB;
    if (P->parity == 'E') tio.c_cflag |= PARENB;
    if (P->parity == 'O') tio.c_cflag |= PARENB | PARODD;
    tio.c_iflag &= ~(tcflag_t)(IXON | IXOFF | IXANY);
    tio.c_cc[VMIN] = 0;
    tio.c_cc[VTIME] = 0;
    tcsetattr(P->fd, TCSANOW, &tio);
}

/* Try to open P now: true when open (fd set). */
static bool port_open(port *P)
{
    char dev[sizeof P->dev];
    if (!resolve(P, dev, sizeof dev)) { errno = ENODEV; return false; }
    int fd = open(dev, O_RDWR | O_NOCTTY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) return false;
    snprintf(P->dev, sizeof P->dev, "%s", dev);
    P->fd = fd;
    P->len = 0;
    apply_termios(P);
    return true;
}

static void port_close(port *P)
{
    if (P->fd >= 0) close(P->fd);
    P->fd = -1;
    P->len = 0;
}

/* ---- line handling ----------------------------------------------------- */

/* Keep a line valid UTF-8 for the JSON frame: invalid bytes become '?'. */
static void sanitize_utf8(char *s)
{
    unsigned char *p = (unsigned char *)s;
    while (*p) {
        int n = *p < 0x80 ? 1 : (*p & 0xE0) == 0xC0 ? 2 : (*p & 0xF0) == 0xE0 ? 3
              : (*p & 0xF8) == 0xF0 ? 4 : 0;
        bool ok = n > 0;
        for (int i = 1; ok && i < n; i++) ok = (p[i] & 0xC0) == 0x80;
        if (!ok) { *p++ = '?'; continue; }
        p += n;
    }
}

static void publish_line(ser_t *t, port *P, const char *text, size_t len)
{
    if (len == 0) return;
    char *s = malloc(len + 1);
    if (!s) return;
    memcpy(s, text, len);
    s[len] = '\0';
    for (size_t i = 0; i < len; i++) if (s[i] == '\0') s[i] = '?';
    sanitize_utf8(s);
    hwd_value v = hwd_str(s);
    free(s);
    hwd_tagstore_set(t->store, P->t_rx, &v);
    hwd_tagstore_set_quality(t->store, P->t_rx, NULL);
    hwd_value_clear(&v);
    P->rx_count++;
}

/* Feed received bytes through the line splitter. */
static void feed(ser_t *t, port *P, const char *buf, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        P->line[P->len++] = buf[i];
        size_t len = P->len;
        bool done = false;
        if (len >= P->eol_len && memcmp(P->line + len - P->eol_len, P->eol, P->eol_len) == 0) {
            len -= P->eol_len;
            done = true;
        } else if (buf[i] == '\n') {
            len--;
            if (len && P->line[len - 1] == '\r') len--;
            done = true;
        }
        if (done) {
            publish_line(t, P, P->line, len);
            P->len = 0;
        } else if (P->len >= P->max_line) {
            publish_line(t, P, P->line, P->len);   /* cut at max_line */
            P->len = 0;
        }
    }
}

/* ---- create ------------------------------------------------------------ */

static void destroy_op(void *self);

static void *v_create(const hwd_config *cfg, hwd_tagstore *store, const hwd_backend_opts *opts,
                      char *err, size_t errlen)
{
    if (errlen) err[0] = '\0';
    const cJSON *ports = json_find(cfg->serial, "ports");
    if (!ports) return NULL;

    ser_t *t = calloc(1, sizeof *t);
    if (!t) { snprintf(err, errlen, "serial: out of memory"); return NULL; }
    t->opts = *opts;
    t->store = store;
    size_t count = (size_t)cJSON_GetArraySize(ports);
    t->ports = count ? calloc(count, sizeof *t->ports) : NULL;
    if (count && !t->ports) { free(t); snprintf(err, errlen, "serial: out of memory"); return NULL; }

    for (const cJSON *p = ports->child; p && t->n_ports < count; p = p->next) {
        port *P = &t->ports[t->n_ports++];
        P->fd = -1;
        snprintf(P->name, sizeof P->name, "%s", p->string ? p->string : "");
        snprintf(P->t_present, sizeof P->t_present, "serial.%s.present", P->name);
        snprintf(P->t_rx, sizeof P->t_rx, "serial.%s.rx", P->name);
        snprintf(P->t_count, sizeof P->t_count, "serial.%s.rx_count", P->name);
        P->baudrate = (int)json_num(p, "baudrate", 9600);
        P->bytesize = (int)json_num(p, "bytesize", 8);
        P->stopbits = (int)json_num(p, "stopbits", 1);
        const char *par = json_s(p, "parity");
        P->parity = par && par[0] ? par[0] : 'N';
        const char *eol = json_s(p, "eol");
        snprintf(P->eol, sizeof P->eol, "%s", eol && eol[0] ? eol : "\r\n");
        P->eol_len = strlen(P->eol);
        double ml = json_num(p, "max_line", 256);
        P->max_line = ml >= 1 ? (size_t)ml : 256;
        P->line = malloc(P->max_line + 1);
        if (!P->line) { snprintf(err, errlen, "serial: out of memory"); destroy_op(t); return NULL; }
        const char *path = json_s(p, "path");
        snprintf(P->path, sizeof P->path, "%s", path ? path : "");
        const cJSON *match = json_find(p, "match");
        if (match && !path) {
            P->has_match = true;
            P->vid = parse_hex_id(json_s(match, "vid"));
            P->pid = parse_hex_id(json_s(match, "pid"));
            const char *sn = json_s(match, "serial");
            snprintf(P->serial, sizeof P->serial, "%s", sn ? sn : "");
        }

        if (opts->sim) {
            /* A real node at `path` is served for real, anything else simulated. */
            P->sim = !(P->path[0] && port_open(P));
            P->present = true;
        } else if (port_open(P)) {
            P->present = true;
        } else {
            char what[400];
            if (P->has_match)
                snprintf(what, sizeof what, "no tty matches vid %04lx pid %04lx%s%s", P->vid,
                         P->pid, P->serial[0] ? " serial " : "", P->serial);
            else
                snprintf(what, sizeof what, "%s: %s", P->path, strerror(errno));
            if (opts->strict) {
                snprintf(err, errlen, "serial port %s: %s", P->name, what);
                destroy_op(t);
                return NULL;
            }
            HWD_WARN("serial port %s not present (%s); retrying", P->name, what);
            P->next_try = hwd_mono() + RETRY_S;
        }
        if (P->fd >= 0) HWD_INFO("serial port %s open on %s", P->name, P->dev);

        hwd_tagstore_register(store, P->t_present, hwd_bool(P->present), false);
        hwd_tagstore_register(store, P->t_rx, hwd_null(), false);
        hwd_tagstore_register(store, P->t_count, hwd_int(0), false);
    }
    return t;
}

/* ---- owns -------------------------------------------------------------- */

static bool owns(void *self, const char *tag)
{
    ser_t *t = self;
    if (!t || !tag) return false;
    for (size_t i = 0; i < t->n_ports; i++) {
        const port *P = &t->ports[i];
        if (strcmp(tag, P->t_present) == 0 || strcmp(tag, P->t_rx) == 0
            || strcmp(tag, P->t_count) == 0)
            return true;
    }
    return false;
}

/* ---- poll -------------------------------------------------------------- */

static void poll_sim(ser_t *t, port *P, double now)
{
    if (P->next_mark == 0.0) P->next_mark = floor(now / 2.0) * 2.0 + 2.0;
    if (now < P->next_mark) return;
    P->next_mark = floor(now / 2.0) * 2.0 + 2.0;
    P->sim_n++;
    if (hwd_sim_fails(P->t_rx)) {
        hwd_value v = hwd_null();
        hwd_tagstore_set(t->store, P->t_rx, &v);
        hwd_tagstore_set_quality(t->store, P->t_rx, "bad");
        t->errors++;
        return;
    }
    char line[48];
    int n = snprintf(line, sizeof line, "SIM %lld", (long long)P->sim_n);
    publish_line(t, P, line, (size_t)n < P->max_line ? (size_t)n : P->max_line);
}

static void unplugged(ser_t *t, port *P, const char *why)
{
    HWD_WARN("serial port %s (%s) lost: %s", P->name, P->dev, why);
    port_close(P);
    P->present = false;
    t->errors++;
    hwd_tagstore_set_quality(t->store, P->t_rx, "stale");
    P->next_try = hwd_mono() + RETRY_S;
}

static void poll_real(ser_t *t, port *P)
{
    if (P->fd < 0) {
        double m = hwd_mono();
        if (m < P->next_try) return;
        P->next_try = m + RETRY_S;
        if (!port_open(P)) return;
        P->present = true;
        hwd_tagstore_set_quality(t->store, P->t_rx, NULL);
        HWD_INFO("serial port %s back on %s", P->name, P->dev);
    }
    for (int rounds = 0; rounds < 16; rounds++) {
        struct pollfd pfd = {.fd = P->fd, .events = POLLIN};
        int rc = poll(&pfd, 1, 0);
        if (rc == 0) return;
        if (rc < 0) {
            if (errno == EINTR) return;
            unplugged(t, P, strerror(errno));
            return;
        }
        if (pfd.revents & POLLIN) {
            char buf[1024];
            ssize_t n = read(P->fd, buf, sizeof buf);
            if (n > 0) { feed(t, P, buf, (size_t)n); continue; }
            if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) return;
            unplugged(t, P, n == 0 ? "end of file" : strerror(errno));
            return;
        }
        if (pfd.revents & (POLLHUP | POLLERR | POLLNVAL)) {
            unplugged(t, P, "hangup");
            return;
        }
        return;
    }
}

static void poll_op(void *self, double now)
{
    ser_t *t = self;
    if (!t) return;
    for (size_t i = 0; i < t->n_ports; i++) {
        port *P = &t->ports[i];
        if (P->sim) poll_sim(t, P, now);
        else poll_real(t, P);
        hwd_value present = hwd_bool(P->present);
        hwd_tagstore_set(t->store, P->t_present, &present);
        hwd_value rxn = hwd_int(P->rx_count);
        hwd_tagstore_set(t->store, P->t_count, &rxn);
    }
}

/* ---- write ------------------------------------------------------------- */

static hwd_err write_op(void *self, const char *tag, const hwd_value *v)
{
    (void)self; (void)tag; (void)v;
    return HWD_ERR_NOT_WRITABLE;
}

/* ---- command ----------------------------------------------------------- */

static hwd_err command_op(void *self, const char *cmd, const cJSON *msg, cJSON *reply)
{
    (void)reply;
    if (!cmd || strcmp(cmd, "serial_tx") != 0) return HWD_ERR_UNKNOWN_CMD;
    ser_t *t = self;
    if (!t) return HWD_ERR_HW_ERROR;
    const char *name = json_s(msg, "port");
    const char *data = json_s(msg, "data");
    if (!name || !data) { t->errors++; return HWD_ERR_BAD_VALUE; }
    port *P = NULL;
    for (size_t i = 0; i < t->n_ports && !P; i++)
        if (strcmp(t->ports[i].name, name) == 0) P = &t->ports[i];
    if (!P) { t->errors++; return HWD_ERR_HW_ERROR; }
    if (P->sim) return HWD_OK;                       /* simulated: accepted, dropped */
    if (P->fd < 0) { t->errors++; return HWD_ERR_HW_ERROR; }
    size_t len = strlen(data), off = 0;
    double deadline = hwd_mono() + 0.5;
    while (off < len) {
        ssize_t rc = write(P->fd, data + off, len - off);
        if (rc > 0) { off += (size_t)rc; continue; }
        if (rc < 0 && (errno == EAGAIN || errno == EINTR) && hwd_mono() < deadline) {
            struct pollfd pfd = {.fd = P->fd, .events = POLLOUT};
            poll(&pfd, 1, 20);
            continue;
        }
        t->errors++;
        HWD_WARN("serial port %s: write failed: %s", P->name, rc < 0 ? strerror(errno) : "timeout");
        return HWD_ERR_HW_ERROR;
    }
    return HWD_OK;
}

/* ---- errors ------------------------------------------------------------ */

static uint64_t errors_op(void *self)
{
    ser_t *t = self;
    return t ? t->errors : 0;
}

/* ---- destroy ----------------------------------------------------------- */

static void destroy_op(void *self)
{
    ser_t *t = self;
    if (!t) return;
    for (size_t i = 0; i < t->n_ports; i++) {
        port_close(&t->ports[i]);
        free(t->ports[i].line);
    }
    free(t->ports);
    free(t);
}

const hwd_backend_ops hwd_backend_serial = {
    "serial", v_validate, v_create, NULL, poll_op, owns, write_op, command_op,
    NULL, errors_op, destroy_op,
};
