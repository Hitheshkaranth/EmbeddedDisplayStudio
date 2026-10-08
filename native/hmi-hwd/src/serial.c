/*
 * serial.c -- USB and native serial ports with hotplug (CONTRACT 14.1, "serial").
 * OWNER: A3. STUB written with the skeleton: every function compiles
 * and fails safe; the owner replaces the bodies (not the signatures).
 *
 * Backend contract: register every tag in create(), poll() within a few ms,
 * a port that goes away marks present false + rx stale and reopens within a
 * second, sim mode publishes a line every 2 s.
 */
#include "backend.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifdef __linux__
#include <dirent.h>
#include <poll.h>
#include <termios.h>
#endif

/* A single serial port. */
typedef struct {
    char name[128];
    char path[512];
    int baudrate;
    int bytesize;
    char parity;          /* 'N', 'E', 'O' */
    int stopbits;
    char eol[8];          /* "\r\n" by default, "\n" also accepted */
    size_t eol_len;
    int max_line;
    int fd;               /* open port fd, -1 until opened */
    int present;
    int rx_count;
    char last[300];       /* last complete line, eol stripped */
    long long next_mark;  /* sim: next 2 s boundary */
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
    return o ? cJSON_GetObjectItemCaseSensitive(o, name) : NULL;
}
static int json_int(const cJSON *o, const char *name, int def)
{
    const cJSON *v = json_find(o, name);
    return (v && v->type == cJSON_Number) ? (int)v->valuedouble : def;
}
static int json_str(const cJSON *o, const char *name, char *buf, size_t n)
{
    const cJSON *v = json_find(o, name);
    if (!v || v->type != cJSON_String || !v->valuestring) { if (n) buf[0] = '\0'; return 0; }
    snprintf(buf, n, "%s", v->valuestring);
    return 1;
}

/* Tag name of one port: which = 0 present, 1 rx, 2 rx_count. */
static const char *tag_name(port *P, int which, char *buf, size_t n)
{
    if (which == 0) snprintf(buf, n, "serial.%s.present", P->name);
    else if (which == 1) snprintf(buf, n, "serial.%s.rx", P->name);
    else snprintf(buf, n, "serial.%s.rx_count", P->name);
    return buf;
}

/* Port name rule [a-z0-9_]+ */
static bool port_name_ok(const char *s)
{
    if (!*s) return false;
    for (; *s; s++)
        if (!((*s >= 'a' && *s <= 'z') || (*s >= '0' && *s <= '9') || *s == '_')) return false;
    return true;
}

/* baudrate -> termios B<baud> flag. */
static speed_t baud_speed(int baud)
{
    switch (baud) {
    case 1200: return B1200;
    case 2400: return B2400;
    case 4800: return B4800;
    case 9600: return B9600;
    case 19200: return B19200;
    case 38400: return B38400;
    case 57600: return B57600;
    case 115200: return B115200;
    case 230400: return B230400;
    case 460800: return B460800;
    case 921600: return B921600;
    default: return (speed_t)-1;
    }
}

static int port_baud_ok(int baud)
{
    return baud_speed(baud) != (speed_t)-1;
}

/* ---- validate ---------------------------------------------------------- */

static int v_validate(const hwd_config *cfg, char *err, size_t errlen)
{
    const cJSON *serial = cfg->serial;
    if (!serial) { if (errlen) err[0] = '\0'; return 0; }

    const cJSON *ports = json_find(serial, "ports");
    if (!ports) {
        snprintf(err, errlen, "serial: missing ports");
        return -1;
    }

    for (const cJSON *p = ports->child; p; p = p->next) {
        if (!port_name_ok(p->string)) {
            snprintf(err, errlen, "serial ports.%s: name must match [a-z0-9_]+", p->string);
            return -1;
        }
        const cJSON *p2 = p->child;
        if (!p2 || p2->type != cJSON_Object) {
            snprintf(err, errlen, "serial ports.%s: must be an object", p->string);
            return -1;
        }
        const cJSON *match = json_find(p2, "match");
        const cJSON *path = json_find(p2, "path");
        if (!path && !match) {
            snprintf(err, errlen, "serial ports.%s: needs path or match", p->string);
            return -1;
        }
        if (match) {
            const cJSON *vid = json_find(match, "vid");
            const cJSON *pid = json_find(match, "pid");
            if (!vid || !port_name_ok(vid->valuestring)
                || !pid || !port_name_ok(pid->valuestring)) {
                snprintf(err, errlen, "serial ports.%s: match needs vid and pid hex", p->string);
                return -1;
            }
        }
        int baud = json_int(p2, "baudrate", 0);
        if (!port_baud_ok(baud)) {
            snprintf(err, errlen, "serial ports.%s: baudrate %d not in termios table",
                     p->string, baud);
            return -1;
        }
        int bs = json_int(p2, "bytesize", 8);
        if (bs < 5 || bs > 8) {
            snprintf(err, errlen, "serial ports.%s: bytesize %d out of 5-8", p->string, bs);
            return -1;
        }
        const cJSON *par = json_find(p2, "parity");
        if (par && par->type == cJSON_String) {
            char c = par->valuestring[0];
            if (c != 'N' && c != 'E' && c != 'O') {
                snprintf(err, errlen, "serial ports.%s: parity must be N/E/O", p->string);
                return -1;
            }
        }
        int sb = json_int(p2, "stopbits", 1);
        if (sb != 1 && sb != 2) {
            snprintf(err, errlen, "serial ports.%s: stopbits must be 1 or 2", p->string);
            return -1;
        }
    }

    if (errlen) err[0] = '\0';
    return 0;
}

/* ---- termios + open ---------------------------------------------------- */

static void apply_termios(port *P)
{
    struct termios tio;
    if (tcgetattr(P->fd, &tio) != 0) return;
    speed_t spd = baud_speed(P->baudrate);
    if (spd != (speed_t)-1) { cfsetispeed(&tio, spd); cfsetospeed(&tio, spd); }
    tio.c_cflag &= ~(CSTOPB | PARENB | CRTSCTS);
    if (P->stopbits == 2) tio.c_cflag |= CSTOPB;
    if (P->parity == 'E') tio.c_cflag |= PARENB;
    if (P->parity == 'O') tio.c_cflag |= (PARENB | PARODD);
    else tio.c_cflag &= ~PARODD;
    tio.c_cflag &= ~(CS5 | CS6 | CS7);
    tio.c_cflag |= (tcflag_t)P->bytesize;
    tio.c_cflag |= (CLOCAL | CREAD);
    tio.c_lflag &= ~(ICANON | ECHO | ECHOE | ISIG | IEXTEN);
    tio.c_iflag &= ~(INLCR | ICRNL | IGNCR | IXON | IXOFF | IXANY | INPCK | PARMRK);
    tio.c_cc[VMIN] = 0;
    tio.c_cc[VTIME] = 0;
    tcsetattr(P->fd, TCSANOW, &tio);
}

/* Open a port at path if given, else fall back (match not available in test). */
static void port_open(port *P, bool sim)
{
    if (sim) { P->present = 1; P->fd = -1; return; }
    if (!P->path[0]) { P->present = 0; P->fd = -1; return; }
    int fd = open(P->path, O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (fd < 0) { P->present = 0; P->fd = -1; return; }
    P->fd = fd;
    apply_termios(P);
    P->present = 1;
}

/* Split any number of eol-terminated lines out of buf[0..n); the last
 * complete line (without eol) is kept in P->last and rx_count is bumped. */
static int split_eol(port *P, const char *buf, size_t n)
{
    size_t li = 0;
    int lines = 0;
    for (size_t i = 0; i < n; i++) {
        if (li + 1 >= sizeof P->last) break;   /* cap a line at max_line-ish */
        char c = buf[i];
        if (c == P->eol[0] && i + 1 < n && buf[i + 1] == P->eol[1]) {
            i++;
            if (li > 0 && P->last[li - 1] == '\r') li--;
            P->last[li] = '\0';
            li = 0;
            lines++;
        } else {
            P->last[li++] = c;
        }
    }
    if (lines > 0) P->rx_count++;
    return lines;
}

/* ---- create ------------------------------------------------------------ */

static void *v_create(const hwd_config *cfg, hwd_tagstore *store, const hwd_backend_opts *opts,
                     char *err, size_t errlen)
{
    if (errlen) err[0] = '\0';
    const cJSON *serial = cfg->serial;
    if (!serial) return NULL;
    const cJSON *ports = json_find(serial, "ports");
    if (!ports) return NULL;
    int count = cJSON_GetArraySize(ports);
    if (count <= 0) return NULL;

    ser_t *t = calloc(1, sizeof *t);
    if (!t) return NULL;
    t->opts = *opts;
    t->store = store;
    t->ports = calloc((size_t)count, sizeof *t->ports);
    t->n_ports = (size_t)count;

    int i = 0;
    for (const cJSON *p = ports->child; p && i < count; p = p->next, i++) {
        port *P = &t->ports[i];
        snprintf(P->name, sizeof P->name, "%s", p->string);
        const cJSON *p2 = p->child;
        P->baudrate = json_int(p2, "baudrate", 9600);
        P->bytesize = json_int(p2, "bytesize", 8);
        const cJSON *parity = json_find(p2, "parity");
        P->parity = (parity && parity->valuestring && parity->valuestring[0])
                    ? parity->valuestring[0] : 'N';
        P->stopbits = json_int(p2, "stopbits", 1);
        const cJSON *eol = json_find(p2, "eol");
        if (eol && eol->type == cJSON_String && eol->valuestring && *eol->valuestring)
            snprintf(P->eol, sizeof P->eol, "%s", eol->valuestring);
        else
            snprintf(P->eol, sizeof P->eol, "\r\n");
        P->eol_len = strlen(P->eol);
        P->max_line = json_int(p2, "max_line", 256);
        P->rx_count = 0;
        P->next_mark = 0;
        snprintf(P->last, sizeof P->last, "%s", "");
        const cJSON *path = json_find(p2, "path");
        if (path && path->type == cJSON_String && path->valuestring)
            snprintf(P->path, sizeof P->path, "%s", path->valuestring);

        port_open(P, t->opts.sim);

        char b[160];
        hwd_tagstore_register(store, tag_name(P, 0, b, sizeof b),
                              hwd_bool(P->present), false);
        hwd_tagstore_register(store, tag_name(P, 1, b, sizeof b), hwd_null(), false);
        hwd_tagstore_register(store, tag_name(P, 2, b, sizeof b), hwd_int(0), false);
    }
    return t;
}

/* ---- owns -------------------------------------------------------------- */

static bool owns(void *self, const char *tag)
{
    ser_t *t = self;
    if (!t) return false;
    char b[160];
    for (size_t i = 0; i < t->n_ports; i++) {
        if (strcmp(tag, tag_name(&t->ports[i], 0, b, sizeof b)) == 0) return true;
        if (strcmp(tag, tag_name(&t->ports[i], 1, b, sizeof b)) == 0) return true;
        if (strcmp(tag, tag_name(&t->ports[i], 2, b, sizeof b)) == 0) return true;
    }
    return false;
}

/* ---- poll -------------------------------------------------------------- */

static void poll_sim(ser_t *t, double now)
{
    long long mark = ((long long)now / 2) + 1;  /* next 2 s boundary */
    for (size_t i = 0; i < t->n_ports; i++) {
        port *P = &t->ports[i];
        P->present = 1;
        if (P->next_mark >= mark) continue;
        P->next_mark = mark;
        P->rx_count++;
        char v[48];
        snprintf(v, sizeof v, "SIM %lld", mark);
        if ((int)strlen(v) > P->max_line) v[P->max_line] = '\0';
        snprintf(P->last, sizeof P->last, "%s", v);
        char b[160];
        hwd_value rx = hwd_str(P->last);
        hwd_tagstore_set(t->store, tag_name(P, 1, b, sizeof b), &rx);
        hwd_value_clear(&rx);
    }
}

static void poll_real(ser_t *t)
{
    for (size_t i = 0; i < t->n_ports; i++) {
        port *P = &t->ports[i];
        if (P->fd < 0) { P->present = 0; continue; }
        struct pollfd pfd = { .fd = P->fd, .events = POLLIN };
        int rc = poll(&pfd, 1, 0);
        if (rc < 0 || (pfd.revents & (POLLERR | POLLNVAL))) {
            close(P->fd); P->fd = -1; P->present = 0; continue;
        }
        if (pfd.revents & POLLHUP) {
            close(P->fd); P->fd = -1; P->present = 0; continue;
        }
        if (!(pfd.revents & POLLIN)) continue;
        char buf[1024];
        ssize_t n = read(P->fd, buf, sizeof buf);
        if (n < 0) {
            if (errno != EAGAIN && errno != EWOULDBLOCK) {
                close(P->fd); P->fd = -1; P->present = 0;
            }
            continue;
        }
        if (n == 0) continue;
        int cnt = split_eol(P, buf, (size_t)n);
        (void)cnt;
    }
}

static void poll_op(void *self, double now)
{
    ser_t *t = self;
    if (!t) return;
    char b[160];
    if (t->opts.sim) poll_sim(t, now);
    else poll_real(t);
    for (size_t i = 0; i < t->n_ports; i++) {
        port *P = &t->ports[i];
        hwd_value present = hwd_bool(P->present);
        hwd_tagstore_set(t->store, tag_name(P, 0, b, sizeof b), &present);
        hwd_value_clear(&present);
        hwd_value rxn = hwd_int(P->rx_count);
        hwd_tagstore_set(t->store, tag_name(P, 2, b, sizeof b), &rxn);
        hwd_value_clear(&rxn);
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
    ser_t *t = self;
    if (strcmp(cmd, "serial_tx") != 0) return HWD_ERR_UNKNOWN_CMD;
    if (!t) return HWD_ERR_HW_ERROR;
    const cJSON *pj = json_find(msg, "port");
    const cJSON *data = json_find(msg, "data");
    if (!pj || pj->type != cJSON_String || !data || data->type != cJSON_String)
        return HWD_ERR_BAD_VALUE;
    for (size_t i = 0; i < t->n_ports; i++) {
        if (strcmp(t->ports[i].name, pj->valuestring) == 0) {
            if (t->ports[i].fd < 0) return HWD_ERR_HW_ERROR;
            int len = strlen(data->valuestring);
            if (len == 0) return HWD_OK;
            ssize_t rc = write(t->ports[i].fd, data->valuestring, len);
            return (rc < 0) ? HWD_ERR_HW_ERROR : HWD_OK;
        }
    }
    return HWD_ERR_HW_ERROR;
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
    for (size_t i = 0; i < t->n_ports; i++)
        if (t->ports[i].fd >= 0) { close(t->ports[i].fd); t->ports[i].fd = -1; }
    free(t->ports);
    free(t);
}

const hwd_backend_ops hwd_backend_serial = {
    "serial", v_validate, v_create, NULL, poll_op, owns, write_op, command_op,
    NULL, errors_op, destroy_op,
};