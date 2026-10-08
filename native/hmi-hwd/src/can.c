/*
 * can.c -- SocketCAN signals and frames (CONTRACT 14.3, "can").
 * OWNER: A2.
 *
 * Live: a PF_CAN raw socket bound to `interface`, read by a thread; a frame
 * updates every signal with its id (raw -> signed when `signed` -> * scale +
 * offset; HWD_INT when scale 1 and offset 0, else HWD_FLOAT). poll() marks a
 * signal "stale" once it has not been seen for its timeout_ms, resends the
 * periodic transmit frames and refreshes sys.can_online from IFF_UP.
 * Writable signals share one 8-byte transmit frame per id; a write updates
 * its bits and sends the frame (then every period_ms when given).
 *
 * Sim (--sim): read-only signals ramp across their range (hwd_sim_ramp on
 * the `now` passed to poll) and writes are echoed back as received values;
 * online is true. A virtual interface that exists (vcan: no backing device
 * in sysfs) is used for real even with --sim -- it is not hardware, and it
 * is how the end-to-end tests drive the backend.
 */
#include "backend.h"
#include "periph.h"

#include <errno.h>
#include <math.h>
#include <net/if.h>
#include <poll.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include <linux/can.h>
#include <linux/can/raw.h>

typedef struct {
    char tag[HWD_MAX_TAG + 1];
    uint32_t id;
    bool ext;
    int start, len;
    bool big, is_signed;
    double scale, offset;
    double timeout_s;       /* 0: never stale */
    bool writable;
    int tx;                 /* index into tx frames (writable), else -1 */
    double lo, hi;          /* sim ramp range, engineering units */
    double last_rx;         /* mono */
    bool seen, stale;
} can_sig;

typedef struct {
    uint32_t id;
    bool ext;
    uint8_t data[8];
    double period_s;        /* 0: send on write only */
    double next;            /* mono time of the next periodic send */
    bool armed;             /* written at least once */
} can_txf;

typedef struct {
    hwd_tagstore *store;
    char ifname[IFNAMSIZ];
    bool live;
    can_sig *sigs;
    int nsig;
    can_txf *tx;
    int ntx;
    pthread_mutex_t mu;     /* fd, tx frames, signal rx state */
    int fd;
    pthread_t thread;
    bool thread_started;
    atomic_bool stop;
    atomic_uint_fast64_t errors;
    double next_online_check;
    int online;             /* -1 unknown */
} can_be;

/* ---- helpers --------------------------------------------------------------- */

static int fail(char *err, size_t errlen, const char *fmt, ...) __attribute__((format(printf, 3, 4)));
static int fail(char *err, size_t errlen, const char *fmt, ...)
{
    if (err && errlen) {
        va_list ap;
        va_start(ap, fmt);
        vsnprintf(err, errlen, fmt, ap);
        va_end(ap);
    }
    return -1;
}

static bool is_int(const cJSON *j)
{
    return cJSON_IsNumber(j) && j->valuedouble == floor(j->valuedouble) && fabs(j->valuedouble) < 9e15;
}

static double num(const cJSON *o, const char *k, double dflt)
{
    const cJSON *j = cJSON_GetObjectItemCaseSensitive(o, k);
    return cJSON_IsNumber(j) ? j->valuedouble : dflt;
}

/* id from a JSON string ("0x123", "291") or number. */
static bool json_id(const cJSON *j, bool ext, uint32_t *id)
{
    if (cJSON_IsString(j)) return can_parse_id(j->valuestring, ext, id);
    if (is_int(j) && j->valuedouble >= 0 && j->valuedouble <= (ext ? 0x1FFFFFFF : 0x7FF)) {
        *id = (uint32_t)j->valuedouble;
        return true;
    }
    return false;
}

/* Next DBC bit position of a Motorola signal (towards its LSB). */
static int motorola_next(int pos) { return (pos % 8 == 0) ? pos + 15 : pos - 1; }

static bool signal_fits(int start, int len, bool big)
{
    if (!big) return start + len <= 64;
    int pos = start;
    for (int i = 1; i < len; i++) {
        pos = motorola_next(pos);
        if (pos > 63) return false;
    }
    return true;
}

/* ---- validation ---------------------------------------------------------------- */

static int v_validate(const hwd_config *cfg, char *err, size_t errlen)
{
    if (err && errlen) err[0] = '\0';
    const cJSON *c = cfg->can;
    if (!c) return 0;
    if (!cJSON_IsObject(c)) return fail(err, errlen, "can config must be an object");
    const cJSON *ifn = cJSON_GetObjectItemCaseSensitive(c, "interface");
    if (!cJSON_IsString(ifn) || !ifn->valuestring[0] || strlen(ifn->valuestring) >= IFNAMSIZ)
        return fail(err, errlen, "can.interface must be an interface name (e.g. \"can0\")");
    const cJSON *sigs = cJSON_GetObjectItemCaseSensitive(c, "signals");
    if (!sigs) return 0;
    if (!cJSON_IsObject(sigs)) return fail(err, errlen, "can.signals must be an object");
    const cJSON *s;
    cJSON_ArrayForEach(s, sigs) {
        const char *n = s->string;
        if (!hwd_tag_valid(n)) return fail(err, errlen, "Invalid tag name '%s' in can.signals", n);
        if (!cJSON_IsObject(s)) return fail(err, errlen, "can.signal '%s' config must be an object", n);
        const cJSON *jx = cJSON_GetObjectItemCaseSensitive(s, "extended");
        if (jx && !cJSON_IsBool(jx)) return fail(err, errlen, "can.signal '%s': extended must be true or false", n);
        bool ext = cJSON_IsTrue(jx);
        uint32_t id;
        if (!json_id(cJSON_GetObjectItemCaseSensitive(s, "id"), ext, &id))
            return fail(err, errlen, "can.signal '%s': id must be a %s-bit CAN id (\"0x123\")", n, ext ? "29" : "11");
        const cJSON *jsb = cJSON_GetObjectItemCaseSensitive(s, "start_bit");
        if (!is_int(jsb) || jsb->valuedouble < 0 || jsb->valuedouble > 63)
            return fail(err, errlen, "can.signal '%s': start_bit must be 0..63", n);
        const cJSON *jl = cJSON_GetObjectItemCaseSensitive(s, "length");
        if (!is_int(jl) || jl->valuedouble < 1 || jl->valuedouble > 64)
            return fail(err, errlen, "can.signal '%s': length must be 1..64", n);
        const cJSON *jbo = cJSON_GetObjectItemCaseSensitive(s, "byte_order");
        if (jbo && (!cJSON_IsString(jbo) || (strcmp(jbo->valuestring, "little") && strcmp(jbo->valuestring, "big"))))
            return fail(err, errlen, "can.signal '%s': byte_order must be \"little\" or \"big\"", n);
        bool big = jbo && !strcmp(jbo->valuestring, "big");
        if (!signal_fits((int)jsb->valuedouble, (int)jl->valuedouble, big))
            return fail(err, errlen, "can.signal '%s': start_bit/length run past the 8-byte frame", n);
        const char *bools[] = {"signed", "writable"};
        for (int i = 0; i < 2; i++) {
            const cJSON *b = cJSON_GetObjectItemCaseSensitive(s, bools[i]);
            if (b && !cJSON_IsBool(b)) return fail(err, errlen, "can.signal '%s': %s must be true or false", n, bools[i]);
        }
        const cJSON *jsc = cJSON_GetObjectItemCaseSensitive(s, "scale");
        if (jsc && (!cJSON_IsNumber(jsc) || jsc->valuedouble == 0))
            return fail(err, errlen, "can.signal '%s': scale must be a non-zero number", n);
        const cJSON *jo = cJSON_GetObjectItemCaseSensitive(s, "offset");
        if (jo && !cJSON_IsNumber(jo)) return fail(err, errlen, "can.signal '%s': offset must be a number", n);
        const char *pos[] = {"timeout_ms", "period_ms"};
        for (int i = 0; i < 2; i++) {
            const cJSON *p = cJSON_GetObjectItemCaseSensitive(s, pos[i]);
            if (p && (!cJSON_IsNumber(p) || p->valuedouble <= 0))
                return fail(err, errlen, "can.signal '%s': %s must be a positive number", n, pos[i]);
        }
    }
    return 0;
}

/* ---- values ---------------------------------------------------------------------- */

static double raw_min(const can_sig *s)
{
    return s->is_signed ? -ldexp(1.0, s->len - 1) : 0.0;
}

static double raw_max(const can_sig *s)
{
    return s->is_signed ? ldexp(1.0, s->len - 1) - 1 : ldexp(1.0, s->len) - 1;
}

static hwd_value sig_value(const can_sig *s, const uint8_t data[8])
{
    uint64_t raw = can_get_bits(data, s->start, s->len, s->big);
    double r;
    int64_t ri = 0;
    bool fits = true;
    if (s->is_signed) { ri = can_sign_extend(raw, s->len); r = (double)ri; }
    else { r = (double)raw; fits = raw <= (uint64_t)INT64_MAX; ri = (int64_t)raw; }
    if (s->scale == 1.0 && s->offset == 0.0 && fits) return hwd_int(ri);
    return hwd_float(r * s->scale + s->offset);
}

/* engineering value -> raw bits; bad_value when it does not fit the signal. */
static hwd_err sig_raw(const can_sig *s, const hwd_value *v, uint64_t *bits)
{
    double eng;
    switch (v->kind) {
    case HWD_BOOL:  eng = v->u.b ? 1 : 0; break;
    case HWD_INT:   eng = (double)v->u.i; break;
    case HWD_FLOAT: eng = v->u.f; break;
    default: return HWD_ERR_BAD_VALUE;
    }
    if (!isfinite(eng)) return HWD_ERR_BAD_VALUE;
    double r = nearbyint((eng - s->offset) / s->scale);
    if (r < raw_min(s) || r > raw_max(s)) return HWD_ERR_BAD_VALUE;
    if (s->is_signed) *bits = (uint64_t)(int64_t)r;
    else *bits = r >= 9223372036854775808.0 ? (uint64_t)(r - 9223372036854775808.0) + (1ULL << 63) : (uint64_t)r;
    if (s->len < 64) *bits &= ((uint64_t)1 << s->len) - 1;
    return HWD_OK;
}

static void store(can_be *B, const char *tag, hwd_value v, const char *q)
{
    hwd_tagstore_set(B->store, tag, &v);
    hwd_tagstore_set_quality(B->store, tag, q);
    hwd_value_clear(&v);
}

/* ---- socket ---------------------------------------------------------------------- */

static bool iface_exists(const char *ifname)
{
    char p[64 + IFNAMSIZ];
    struct stat st;
    snprintf(p, sizeof p, "/sys/class/net/%s", ifname);
    return stat(p, &st) == 0;
}

/* A virtual CAN interface (vcan, vxcan): present and with no backing device. */
static bool iface_virtual(const char *ifname)
{
    char p[64 + IFNAMSIZ];
    struct stat st;
    snprintf(p, sizeof p, "/sys/class/net/%s/device", ifname);
    return iface_exists(ifname) && lstat(p, &st) != 0;
}

static int can_open(const char *ifname)
{
    unsigned idx = if_nametoindex(ifname);
    if (!idx) return -1;
    int fd = socket(PF_CAN, SOCK_RAW | SOCK_CLOEXEC | SOCK_NONBLOCK, CAN_RAW);
    if (fd < 0) return -1;
    struct sockaddr_can addr;
    memset(&addr, 0, sizeof addr);
    addr.can_family = AF_CAN;
    addr.can_ifindex = (int)idx;
    if (bind(fd, (struct sockaddr *)&addr, sizeof addr) != 0) {
        close(fd);
        return -1;
    }
    return fd;
}

/* Caller holds B->mu. 0 ok, -1 failed. */
static int send_frame(can_be *B, uint32_t id, bool ext, const uint8_t *data, int dlc)
{
    if (B->fd < 0) return -1;
    struct can_frame f;
    memset(&f, 0, sizeof f);
    f.can_id = ext ? (id & CAN_EFF_MASK) | CAN_EFF_FLAG : (id & CAN_SFF_MASK);
    f.can_dlc = (uint8_t)dlc;
    memcpy(f.data, data, (size_t)dlc);
    ssize_t w;
    do {
        w = send(B->fd, &f, sizeof f, MSG_DONTWAIT);
    } while (w < 0 && errno == EINTR);
    if (w != (ssize_t)sizeof f) {
        atomic_fetch_add(&B->errors, 1);
        return -1;
    }
    return 0;
}

static void on_frame(can_be *B, const struct can_frame *f)
{
    if (f->can_id & (CAN_RTR_FLAG | CAN_ERR_FLAG)) return;
    bool ext = (f->can_id & CAN_EFF_FLAG) != 0;
    uint32_t id = f->can_id & (ext ? CAN_EFF_MASK : CAN_SFF_MASK);
    uint8_t data[8] = {0};
    memcpy(data, f->data, f->can_dlc <= 8 ? f->can_dlc : 8);
    double now = hwd_mono();
    for (int i = 0; i < B->nsig; i++) {
        can_sig *s = &B->sigs[i];
        if (s->id != id || s->ext != ext) continue;
        pthread_mutex_lock(&B->mu);
        s->last_rx = now;
        s->seen = true;
        s->stale = false;
        pthread_mutex_unlock(&B->mu);
        store(B, s->tag, sig_value(s, data), NULL);
    }
}

static void nap(can_be *B, double secs)
{
    double end = hwd_mono() + secs;
    while (!atomic_load(&B->stop) && hwd_mono() < end) {
        struct timespec ts = {0, 50000000L};
        nanosleep(&ts, NULL);
    }
}

static void *reader(void *arg)
{
    can_be *B = arg;
    bool warned = false;
    while (!atomic_load(&B->stop)) {
        pthread_mutex_lock(&B->mu);
        int fd = B->fd;
        pthread_mutex_unlock(&B->mu);
        if (fd < 0) {
            fd = can_open(B->ifname);
            if (fd < 0) {
                if (!warned) HWD_WARN("can: cannot open %s, retrying", B->ifname);
                warned = true;
                nap(B, 1.0);
                continue;
            }
            warned = false;
            HWD_INFO("can: listening on %s", B->ifname);
            pthread_mutex_lock(&B->mu);
            B->fd = fd;
            pthread_mutex_unlock(&B->mu);
        }
        struct pollfd p = {.fd = fd, .events = POLLIN};
        int r = poll(&p, 1, 200);
        if (r <= 0) continue;
        for (;;) {
            struct can_frame f;
            ssize_t n = read(fd, &f, sizeof f);
            if (n == (ssize_t)sizeof f) { on_frame(B, &f); continue; }
            if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) break;
            if (n < 0 && errno == ENETDOWN) { nap(B, 0.2); break; }   /* down: it comes back */
            /* the interface went away (ENODEV) or a short read: reopen */
            atomic_fetch_add(&B->errors, 1);
            pthread_mutex_lock(&B->mu);
            if (B->fd == fd) { close(fd); B->fd = -1; }
            pthread_mutex_unlock(&B->mu);
            nap(B, 0.5);
            break;
        }
    }
    return NULL;
}

/* ---- backend ops --------------------------------------------------------------- */

static void v_destroy(void *self);

static int open_tx(can_be *B, uint32_t id, bool ext, double period_s)
{
    for (int i = 0; i < B->ntx; i++)
        if (B->tx[i].id == id && B->tx[i].ext == ext) {
            if (period_s > 0 && (B->tx[i].period_s == 0 || period_s < B->tx[i].period_s))
                B->tx[i].period_s = period_s;
            return i;
        }
    can_txf *t = &B->tx[B->ntx];
    memset(t, 0, sizeof *t);
    t->id = id;
    t->ext = ext;
    t->period_s = period_s;
    return B->ntx++;
}

static void *v_create(const hwd_config *cfg, hwd_tagstore *st, const hwd_backend_opts *opts,
                      char *err, size_t errlen)
{
    if (err && errlen) err[0] = '\0';
    const cJSON *c = cfg->can;
    if (!c) return NULL;
    can_be *B = calloc(1, sizeof *B);
    if (!B) { fail(err, errlen, "can: out of memory"); return NULL; }
    B->store = st;
    B->fd = -1;
    B->online = -1;
    pthread_mutex_init(&B->mu, NULL);
    atomic_init(&B->stop, false);
    atomic_init(&B->errors, 0);
    const char *ifn = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(c, "interface"));
    snprintf(B->ifname, sizeof B->ifname, "%s", ifn ? ifn : "can0");
    B->live = !opts->sim || iface_virtual(B->ifname);

    const cJSON *sigs = cJSON_GetObjectItemCaseSensitive(c, "signals");
    int n = cJSON_IsObject(sigs) ? cJSON_GetArraySize(sigs) : 0;
    B->sigs = calloc((size_t)(n > 0 ? n : 1), sizeof *B->sigs);
    B->tx = calloc((size_t)(n > 0 ? n : 1), sizeof *B->tx);
    if (!B->sigs || !B->tx) { fail(err, errlen, "can: out of memory"); v_destroy(B); return NULL; }
    const cJSON *j;
    if (n > 0) cJSON_ArrayForEach(j, sigs) {
        can_sig *s = &B->sigs[B->nsig++];
        snprintf(s->tag, sizeof s->tag, "%s", j->string);
        s->ext = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(j, "extended"));
        json_id(cJSON_GetObjectItemCaseSensitive(j, "id"), s->ext, &s->id);
        s->start = (int)num(j, "start_bit", 0);
        s->len = (int)num(j, "length", 1);
        if (s->len < 1 || s->len > 64) s->len = 1;
        const char *bo = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(j, "byte_order"));
        s->big = bo && !strcmp(bo, "big");
        s->is_signed = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(j, "signed"));
        s->scale = num(j, "scale", 1.0);
        if (s->scale == 0) s->scale = 1.0;
        s->offset = num(j, "offset", 0.0);
        s->timeout_s = num(j, "timeout_ms", 0) / 1000.0;
        s->writable = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(j, "writable"));
        s->tx = s->writable ? open_tx(B, s->id, s->ext, num(j, "period_ms", 0) / 1000.0) : -1;
        double a = raw_min(s) * s->scale + s->offset, b = raw_max(s) * s->scale + s->offset;
        s->lo = a < b ? a : b;
        s->hi = a < b ? b : a;
        hwd_value init = hwd_null();
        if (!B->live && s->writable) {        /* sim: the (all-zero) transmit frame, echoed */
            uint8_t zero[8] = {0};
            init = sig_value(s, zero);
        }
        bool ok = hwd_tagstore_register(st, s->tag, init, s->writable);
        hwd_value_clear(&init);
        if (!ok) { fail(err, errlen, "can: cannot register tag '%s'", s->tag); v_destroy(B); return NULL; }
    }
    hwd_tagstore_register(st, "sys.can_online", hwd_bool(!B->live), false);
    if (B->live && opts->strict) {
        B->fd = can_open(B->ifname);
        if (B->fd < 0) { fail(err, errlen, "can: cannot open interface %s", B->ifname); v_destroy(B); return NULL; }
    }
    return B;
}

static void v_start(void *self)
{
    can_be *B = self;
    if (!B || !B->live || B->thread_started) return;
    if (pthread_create(&B->thread, NULL, reader, B) == 0) B->thread_started = true;
    else HWD_ERROR("can: cannot start the reader thread");
}

static void sim_poll(can_be *B, double now)
{
    for (int i = 0; i < B->nsig; i++) {
        can_sig *s = &B->sigs[i];
        if (s->writable) continue;
        if (hwd_sim_fails(s->tag)) { store(B, s->tag, hwd_null(), "bad"); continue; }
        double eng = hwd_sim_ramp(now + i, s->lo, s->hi, 10.0);
        hwd_value v = hwd_float(eng);
        uint64_t raw;
        if (sig_raw(s, &v, &raw) == HWD_OK) {
            uint8_t data[8] = {0};
            can_set_bits(data, s->start, s->len, s->big, raw);
            store(B, s->tag, sig_value(s, data), NULL);
        }
    }
}

static void v_poll(void *self, double now)
{
    can_be *B = self;
    if (!B) return;
    if (!B->live) { sim_poll(B, now); return; }
    double mono = hwd_mono();
    pthread_mutex_lock(&B->mu);
    for (int i = 0; i < B->nsig; i++) {
        can_sig *s = &B->sigs[i];
        if (s->timeout_s > 0 && s->seen && !s->stale && mono - s->last_rx > s->timeout_s) {
            s->stale = true;
            hwd_tagstore_set_quality(B->store, s->tag, "stale");
        }
    }
    for (int i = 0; i < B->ntx; i++) {
        can_txf *t = &B->tx[i];
        if (!t->armed || t->period_s <= 0 || mono < t->next) continue;
        send_frame(B, t->id, t->ext, t->data, 8);
        t->next += t->period_s;
        if (t->next < mono) t->next = mono + t->period_s;
    }
    bool check = mono >= B->next_online_check;
    int fd = B->fd;
    pthread_mutex_unlock(&B->mu);
    if (check) {
        B->next_online_check = mono + 0.25;
        bool up = false;
        if (fd >= 0) {
            struct ifreq ifr;
            memset(&ifr, 0, sizeof ifr);
            snprintf(ifr.ifr_name, sizeof ifr.ifr_name, "%s", B->ifname);
            up = ioctl(fd, SIOCGIFFLAGS, &ifr) == 0 && (ifr.ifr_flags & IFF_UP);
        }
        if ((int)up != B->online) {
            B->online = up;
            store(B, "sys.can_online", hwd_bool(up), NULL);
        }
    }
}

static can_sig *find_sig(can_be *B, const char *tag)
{
    for (int i = 0; i < B->nsig; i++)
        if (!strcmp(B->sigs[i].tag, tag)) return &B->sigs[i];
    return NULL;
}

static bool v_owns(void *self, const char *tag)
{
    can_be *B = self;
    if (!B || !tag) return false;
    return !strcmp(tag, "sys.can_online") || find_sig(B, tag) != NULL;
}

static hwd_err v_write(void *self, const char *tag, const hwd_value *v)
{
    can_be *B = self;
    can_sig *s = (B && tag) ? find_sig(B, tag) : NULL;
    if (!s || !s->writable || s->tx < 0) return HWD_ERR_NOT_WRITABLE;
    uint64_t raw;
    hwd_err e = sig_raw(s, v, &raw);
    if (e != HWD_OK) return e;
    uint8_t data[8];
    int rc = 0;
    pthread_mutex_lock(&B->mu);
    can_txf *t = &B->tx[s->tx];
    can_set_bits(t->data, s->start, s->len, s->big, raw);
    memcpy(data, t->data, 8);
    if (!t->armed) t->next = hwd_mono();
    t->armed = true;
    if (B->live) {
        rc = send_frame(B, t->id, t->ext, t->data, 8);
        if (t->period_s > 0) t->next = hwd_mono() + t->period_s;
    }
    pthread_mutex_unlock(&B->mu);
    if (rc != 0) return HWD_ERR_HW_ERROR;
    /* sim echoes it as received; live, the bus value is what we sent */
    store(B, s->tag, sig_value(s, data), NULL);
    return HWD_OK;
}

static hwd_err v_command(void *self, const char *cmd, const cJSON *msg, cJSON *reply)
{
    can_be *B = self;
    if (!B || !cmd || strcmp(cmd, "can_tx") != 0) return HWD_ERR_UNKNOWN_CMD;
    const cJSON *jx = cJSON_GetObjectItemCaseSensitive(msg, "extended");
    if (jx && !cJSON_IsBool(jx)) return HWD_ERR_BAD_VALUE;
    bool ext = cJSON_IsTrue(jx);
    uint32_t id;
    if (!json_id(cJSON_GetObjectItemCaseSensitive(msg, "id"), ext, &id)) return HWD_ERR_BAD_VALUE;
    const cJSON *jd = cJSON_GetObjectItemCaseSensitive(msg, "data");
    uint8_t data[8] = {0};
    int n = 0;
    if (jd) {
        if (!cJSON_IsString(jd)) return HWD_ERR_BAD_VALUE;
        n = can_parse_hex(jd->valuestring, data);
        if (n < 0) return HWD_ERR_BAD_VALUE;
    }
    if (!B->live) return HWD_OK;
    pthread_mutex_lock(&B->mu);
    int rc = send_frame(B, id, ext, data, n);
    pthread_mutex_unlock(&B->mu);
    (void)reply;
    return rc == 0 ? HWD_OK : HWD_ERR_HW_ERROR;
}

static uint64_t v_errors(void *self)
{
    can_be *B = self;
    return B ? (uint64_t)atomic_load(&B->errors) : 0;
}

static void v_destroy(void *self)
{
    can_be *B = self;
    if (!B) return;
    atomic_store(&B->stop, true);
    if (B->thread_started) pthread_join(B->thread, NULL);
    if (B->fd >= 0) close(B->fd);
    pthread_mutex_destroy(&B->mu);
    free(B->sigs);
    free(B->tx);
    free(B);
}

const hwd_backend_ops hwd_backend_can = {
    "can", v_validate, v_create, v_start, v_poll, v_owns, v_write, v_command, NULL, v_errors, v_destroy,
};

/* ---- periph.h CAN codec (A2) ------------------------------------------ */

static int bit_at(const uint8_t data[8], int pos) { return (data[pos >> 3] >> (pos & 7)) & 1; }

static void put_bit(uint8_t data[8], int pos, int b)
{
    if (b) data[pos >> 3] |= (uint8_t)(1u << (pos & 7));
    else data[pos >> 3] &= (uint8_t)~(1u << (pos & 7));
}

/* little (Intel): start_bit is the LSB, the signal runs up from it.
 * big (Motorola): start_bit is the MSB in the DBC sawtooth numbering, the
 * signal runs down through the byte and on into the next byte's bit 7. */
uint64_t can_get_bits(const uint8_t data[8], int start_bit, int length, bool big_endian)
{
    if (length <= 0 || length > 64 || start_bit < 0 || start_bit > 63) return 0;
    uint64_t raw = 0;
    if (!big_endian) {
        for (int i = 0; i < length && start_bit + i < 64; i++)
            raw |= (uint64_t)bit_at(data, start_bit + i) << i;
        return raw;
    }
    int pos = start_bit;
    for (int i = 0; i < length; i++) {
        raw = (raw << 1) | (uint64_t)(pos < 64 ? bit_at(data, pos) : 0);
        pos = motorola_next(pos);
    }
    return raw;
}

void can_set_bits(uint8_t data[8], int start_bit, int length, bool big_endian, uint64_t raw)
{
    if (length <= 0 || length > 64 || start_bit < 0 || start_bit > 63) return;
    if (!big_endian) {
        for (int i = 0; i < length && start_bit + i < 64; i++)
            put_bit(data, start_bit + i, (int)((raw >> i) & 1));
        return;
    }
    int pos = start_bit;
    for (int i = 0; i < length && pos < 64; i++) {
        put_bit(data, pos, (int)((raw >> (length - 1 - i)) & 1));
        pos = motorola_next(pos);
    }
}

int64_t can_sign_extend(uint64_t raw, int length)
{
    if (length >= 64) return (int64_t)raw;
    if (length <= 0) return 0;
    uint64_t mask = ((uint64_t)1 << length) - 1;
    uint64_t v = raw & mask;
    if (v & ((uint64_t)1 << (length - 1))) v |= ~mask;
    return (int64_t)v;
}

bool can_parse_id(const char *text, bool extended, uint32_t *id)
{
    if (!text || !id) return false;
    const char *p = text;
    int base = 10;
    if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) { base = 16; p += 2; }
    if (!*p) return false;
    uint64_t v = 0;
    for (; *p; p++) {
        int d;
        if (*p >= '0' && *p <= '9') d = *p - '0';
        else if (base == 16 && *p >= 'a' && *p <= 'f') d = *p - 'a' + 10;
        else if (base == 16 && *p >= 'A' && *p <= 'F') d = *p - 'A' + 10;
        else return false;
        v = v * (uint64_t)base + (uint64_t)d;
        if (v > 0x1FFFFFFF) return false;
    }
    if (v > (extended ? 0x1FFFFFFFu : 0x7FFu)) return false;
    *id = (uint32_t)v;
    return true;
}

static int hex_val(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

int can_parse_hex(const char *text, uint8_t out[8])
{
    if (!text) return -1;
    int n = 0;
    const char *p = text;
    for (;;) {
        while (*p == ' ') p++;
        if (!*p) return n;
        int hi = hex_val(p[0]);
        int lo = hi < 0 ? -1 : hex_val(p[1]);
        if (lo < 0 || n >= 8) return -1;
        out[n++] = (uint8_t)((hi << 4) | lo);
        p += 2;
    }
}
