/*
 * modbus.c -- the Modbus codec (modbus.h) and the backend serving "modbus" (TCP) and
 * "modbus_rtu" (CONTRACT 2.5, 14.2).
 * OWNER: A2.
 *
 * One link per section. Each live link runs its own poll thread; the thread
 * and set() share the link's mutex, held for one request/response at a time.
 *
 * TCP: connect (timeout_s), poll every tag each poll_interval_ms; any I/O
 * error (timeout, reset, malformed frame) closes the socket, sets every tag
 * of the link null/"bad", online false, and retries after reconnect_s.
 * A Modbus exception only fails that one tag.
 *
 * RTU: open the tty (raw, baud, parity, stop bits); a request waits timeout_s
 * for its reply and 3.5 character times separate frames. No answer / a bad
 * CRC fails that tag (one absent slave must not take the whole line down);
 * an OS error on the tty (unplugged) closes it, fails every tag and reopens
 * after reconnect_s. Online = the port is open and the last cycle got at
 * least one valid reply.
 *
 * Sim (--sim without --modbus-live): no I/O; tags read their safe_state (or
 * 0/false), online stays false, writes are stored as if read back.
 */
#include "modbus.h"
#include "backend.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <math.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/socket.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

/* ================================================================ codec */

int mb_type_registers(mb_type t)
{
    switch (t) {
    case MB_INT32: case MB_UINT32: case MB_FLOAT32: return 2;
    default: return 1;
    }
}

static uint32_t join_words(const uint16_t *regs, bool little_words)
{
    uint32_t hi = little_words ? regs[1] : regs[0];
    uint32_t lo = little_words ? regs[0] : regs[1];
    return (hi << 16) | lo;
}

double mb_decode(mb_type t, const uint16_t *regs, bool little_words)
{
    switch (t) {
    case MB_BOOL:   return regs[0] != 0;
    case MB_INT16:  return (double)(int16_t)regs[0];
    case MB_UINT16: return (double)regs[0];
    case MB_INT32:  return (double)(int32_t)join_words(regs, little_words);
    case MB_UINT32: return (double)join_words(regs, little_words);
    case MB_FLOAT32: {
        uint32_t w = join_words(regs, little_words);
        float f;
        memcpy(&f, &w, sizeof f);
        return (double)f;
    }
    }
    return 0;
}

static int64_t clamp_round(double v, int64_t lo, int64_t hi)
{
    if (isnan(v)) return 0;
    double r = nearbyint(v);
    if (r < (double)lo) return lo;
    if (r > (double)hi) return hi;
    return (int64_t)r;
}

int mb_encode(mb_type t, double raw, uint16_t *regs, bool little_words)
{
    uint32_t w = 0;
    switch (t) {
    case MB_BOOL:   regs[0] = raw != 0 ? 1 : 0; return 1;
    case MB_INT16:  regs[0] = (uint16_t)(int16_t)clamp_round(raw, INT16_MIN, INT16_MAX); return 1;
    case MB_UINT16: regs[0] = (uint16_t)clamp_round(raw, 0, UINT16_MAX); return 1;
    case MB_INT32:  w = (uint32_t)(int32_t)clamp_round(raw, INT32_MIN, INT32_MAX); break;
    case MB_UINT32: w = (uint32_t)clamp_round(raw, 0, UINT32_MAX); break;
    case MB_FLOAT32: { float f = (float)raw; memcpy(&w, &f, sizeof w); break; }
    }
    uint16_t hi = (uint16_t)(w >> 16), lo = (uint16_t)w;
    regs[0] = little_words ? lo : hi;
    regs[1] = little_words ? hi : lo;
    return 2;
}

static void put_u16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)(v >> 8); p[1] = (uint8_t)v; }
static uint16_t get_u16(const uint8_t *p)   { return (uint16_t)((p[0] << 8) | p[1]); }

/* PDU builders (function code first); return the PDU length. */
static size_t pdu_4(uint8_t *p, uint8_t fc, uint16_t a, uint16_t b)
{
    p[0] = fc; put_u16(p + 1, a); put_u16(p + 3, b);
    return 5;
}

static size_t pdu_write_multi(uint8_t *p, uint16_t addr, const uint16_t *regs, uint16_t count)
{
    p[0] = 16; put_u16(p + 1, addr); put_u16(p + 3, count);
    p[5] = (uint8_t)(2 * count);
    for (uint16_t i = 0; i < count; i++) put_u16(p + 6 + 2 * i, regs[i]);
    return 6 + 2 * (size_t)count;
}

static size_t mbap_wrap(uint8_t *buf, uint16_t tid, uint8_t unit, size_t pdu_len)
{
    put_u16(buf, tid);
    put_u16(buf + 2, 0);
    put_u16(buf + 4, (uint16_t)(pdu_len + 1));
    buf[6] = unit;
    return 7 + pdu_len;
}

size_t mb_req_read(uint8_t *buf, uint16_t tid, uint8_t unit, uint8_t fc, uint16_t addr, uint16_t count)
{
    return mbap_wrap(buf, tid, unit, pdu_4(buf + 7, fc, addr, count));
}

size_t mb_req_write_single(uint8_t *buf, uint16_t tid, uint8_t unit, uint8_t fc, uint16_t addr, uint16_t value)
{
    return mbap_wrap(buf, tid, unit, pdu_4(buf + 7, fc, addr, value));
}

size_t mb_req_write_multi(uint8_t *buf, uint16_t tid, uint8_t unit, uint16_t addr, const uint16_t *regs, uint16_t count)
{
    return mbap_wrap(buf, tid, unit, pdu_write_multi(buf + 7, addr, regs, count));
}

/* pdu = function code onwards. 0 / exception code / -1. */
static int parse_read_pdu(const uint8_t *pdu, size_t len, uint8_t fc,
                          uint16_t count, uint8_t *bits, uint16_t *regs)
{
    if (len < 2) return -1;
    if (pdu[0] == (fc | 0x80)) return pdu[1] ? pdu[1] : -1;
    if (pdu[0] != fc) return -1;
    size_t nbytes = pdu[1];
    if (fc == 1 || fc == 2) {
        if (nbytes != (size_t)((count + 7) / 8) || len < 2 + nbytes) return -1;
        for (uint16_t i = 0; i < count; i++)
            if (bits) bits[i] = (uint8_t)((pdu[2 + i / 8] >> (i % 8)) & 1);
        return 0;
    }
    if (fc == 3 || fc == 4) {
        if (nbytes != 2 * (size_t)count || len < 2 + nbytes) return -1;
        for (uint16_t i = 0; i < count; i++)
            if (regs) regs[i] = get_u16(pdu + 2 + 2 * i);
        return 0;
    }
    return -1;
}

static int parse_write_pdu(const uint8_t *pdu, size_t len, uint8_t fc)
{
    if (len < 2) return -1;
    if (pdu[0] == (fc | 0x80)) return pdu[1] ? pdu[1] : -1;
    if (pdu[0] != fc || len < 5) return -1;
    return 0;
}

/* MBAP checks; returns the PDU length or -1. */
static long mbap_pdu(const uint8_t *buf, size_t len, uint16_t tid)
{
    if (len < 9) return -1;
    if (get_u16(buf) != tid || get_u16(buf + 2) != 0) return -1;
    size_t plen = get_u16(buf + 4);
    if (plen < 3 || len < 6 + plen) return -1;
    return (long)plen - 1;
}

int mb_parse_read(const uint8_t *buf, size_t len, uint16_t tid, uint8_t fc,
                  uint16_t count, uint8_t *bits, uint16_t *regs)
{
    long n = mbap_pdu(buf, len, tid);
    if (n < 0) return -1;
    return parse_read_pdu(buf + 7, (size_t)n, fc, count, bits, regs);
}

int mb_parse_write(const uint8_t *buf, size_t len, uint16_t tid, uint8_t fc)
{
    long n = mbap_pdu(buf, len, tid);
    if (n < 0) return -1;
    return parse_write_pdu(buf + 7, (size_t)n, fc);
}

/* ---- RTU ---------------------------------------------------------------- */

uint16_t mb_crc16(const uint8_t *buf, size_t len)
{
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= buf[i];
        for (int k = 0; k < 8; k++)
            crc = (crc & 1) ? (uint16_t)((crc >> 1) ^ 0xA001) : (uint16_t)(crc >> 1);
    }
    return crc;
}

static size_t rtu_wrap(uint8_t *buf, uint8_t unit, size_t pdu_len)
{
    buf[0] = unit;
    uint16_t crc = mb_crc16(buf, 1 + pdu_len);
    buf[1 + pdu_len] = (uint8_t)(crc & 0xFF);
    buf[2 + pdu_len] = (uint8_t)(crc >> 8);
    return 3 + pdu_len;
}

size_t mb_rtu_req_read(uint8_t *buf, uint8_t unit, uint8_t fc, uint16_t addr, uint16_t count)
{
    return rtu_wrap(buf, unit, pdu_4(buf + 1, fc, addr, count));
}

size_t mb_rtu_req_write_single(uint8_t *buf, uint8_t unit, uint8_t fc, uint16_t addr, uint16_t value)
{
    return rtu_wrap(buf, unit, pdu_4(buf + 1, fc, addr, value));
}

size_t mb_rtu_req_write_multi(uint8_t *buf, uint8_t unit, uint16_t addr, const uint16_t *regs, uint16_t count)
{
    return rtu_wrap(buf, unit, pdu_write_multi(buf + 1, addr, regs, count));
}

static bool rtu_frame_ok(const uint8_t *buf, size_t len, uint8_t unit)
{
    if (len < 5 || buf[0] != unit) return false;
    uint16_t stored = (uint16_t)(buf[len - 2] | (buf[len - 1] << 8));
    return stored == mb_crc16(buf, len - 2);
}

int mb_rtu_parse_read(const uint8_t *buf, size_t len, uint8_t unit, uint8_t fc, uint16_t count,
                      uint8_t *bits, uint16_t *regs)
{
    if (!rtu_frame_ok(buf, len, unit)) return -1;
    return parse_read_pdu(buf + 1, len - 3, fc, count, bits, regs);
}

int mb_rtu_parse_write(const uint8_t *buf, size_t len, uint8_t unit, uint8_t fc)
{
    if (!rtu_frame_ok(buf, len, unit)) return -1;
    return parse_write_pdu(buf + 1, len - 3, fc);
}

/* ============================================================ the backend */

typedef struct {
    char tag[HWD_MAX_TAG + 1];
    mb_kind kind;
    mb_type type;
    uint16_t address;
    uint8_t unit;
    double scale, offset;
    bool little;
    bool writable;
    bool has_safe;
    hwd_value safe;
    char **enums;
    int nenum;
} mb_tag;

struct mb_backend;

typedef struct {
    struct mb_backend *be;
    bool rtu;
    bool live;
    const char *online_tag;
    /* TCP */
    char host[256];
    int port;
    /* RTU */
    char path[PATH_MAX];
    char vid[16], pid[16], serial[128];
    int baud, bytesize, stopbits;
    char parity;
    uint8_t unit_id;
    double timeout_s, poll_s, reconnect_s;
    mb_tag *tags;
    int ntags;
    /* runtime */
    pthread_t thread;
    bool thread_started;
    pthread_mutex_t mu;        /* fd and one transaction at a time */
    int fd;
    uint16_t tid;
    double last_io;            /* RTU: mono time the line went quiet */
} mb_link;

typedef struct mb_backend {
    hwd_tagstore *store;
    mb_link links[2];
    int nlinks;
    pthread_mutex_t stop_mu;
    pthread_cond_t stop_cv;
    bool stopping;
    atomic_uint_fast64_t errors;
} mb_backend;

/* ---- helpers ------------------------------------------------------------ */

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

static const char *json_repr(const cJSON *j, char *buf, size_t n)
{
    if (!j) { snprintf(buf, n, "None"); return buf; }
    char *s = cJSON_PrintUnformatted(j);
    snprintf(buf, n, "%s", s ? s : "?");
    free(s);
    return buf;
}

static bool parse_kind(const char *s, mb_kind *k)
{
    if (!s) return false;
    if (!strcmp(s, "coil"))     { *k = MB_COIL; return true; }
    if (!strcmp(s, "discrete")) { *k = MB_DISCRETE; return true; }
    if (!strcmp(s, "holding"))  { *k = MB_HOLDING; return true; }
    if (!strcmp(s, "input"))    { *k = MB_INPUT; return true; }
    return false;
}

static bool parse_type(const char *s, mb_type *t)
{
    if (!s) return false;
    if (!strcmp(s, "bool"))    { *t = MB_BOOL; return true; }
    if (!strcmp(s, "int16"))   { *t = MB_INT16; return true; }
    if (!strcmp(s, "uint16"))  { *t = MB_UINT16; return true; }
    if (!strcmp(s, "int32"))   { *t = MB_INT32; return true; }
    if (!strcmp(s, "uint32"))  { *t = MB_UINT32; return true; }
    if (!strcmp(s, "float32")) { *t = MB_FLOAT32; return true; }
    return false;
}

static speed_t baud_speed(int baud)
{
    switch (baud) {
    case 1200: return B1200;     case 2400: return B2400;     case 4800: return B4800;
    case 9600: return B9600;     case 19200: return B19200;   case 38400: return B38400;
    case 57600: return B57600;   case 115200: return B115200; case 230400: return B230400;
    case 460800: return B460800; case 500000: return B500000; case 576000: return B576000;
    case 921600: return B921600; case 1000000: return B1000000;
    default: return 0;
    }
}

/* ---- validation ------------------------------------------------------- */

static int positive_number(const cJSON *sec, const char *sect, const char *key, char *err, size_t errlen)
{
    const cJSON *j = cJSON_GetObjectItemCaseSensitive(sec, key);
    char r[64];
    if (j && (!cJSON_IsNumber(j) || j->valuedouble <= 0))
        return fail(err, errlen, "%s.%s must be a positive number, got %s", sect, key, json_repr(j, r, sizeof r));
    return 0;
}

static int validate_tags(const cJSON *sec, const char *sect, const cJSON *other,
                         char *err, size_t errlen)
{
    const cJSON *tags = cJSON_GetObjectItemCaseSensitive(sec, "tags");
    if (!tags) return 0;
    if (!cJSON_IsObject(tags)) return fail(err, errlen, "%s.tags must be an object", sect);
    char r[96];
    const cJSON *tc;
    cJSON_ArrayForEach(tc, tags) {
        const char *name = tc->string;
        if (!hwd_tag_valid(name)) return fail(err, errlen, "Invalid tag name '%s' in %s.tags", name, sect);
        if (other && cJSON_GetObjectItemCaseSensitive(other, name))
            return fail(err, errlen, "%s.tag '%s' is also defined in modbus_rtu.tags", sect, name);
        if (!cJSON_IsObject(tc)) return fail(err, errlen, "%s.tag '%s' config must be an object", sect, name);
        mb_kind kind;
        const cJSON *jk = cJSON_GetObjectItemCaseSensitive(tc, "kind");
        if (!parse_kind(cJSON_GetStringValue(jk), &kind))
            return fail(err, errlen, "%s.tag '%s' kind must be one of coil/discrete/holding/input, got %s",
                        sect, name, json_repr(jk, r, sizeof r));
        const cJSON *ja = cJSON_GetObjectItemCaseSensitive(tc, "address");
        if (!is_int(ja) || ja->valuedouble < 0 || ja->valuedouble > 65535)
            return fail(err, errlen, "%s.tag '%s' address must be a non-negative int", sect, name);
        const cJSON *jt = cJSON_GetObjectItemCaseSensitive(tc, "type");
        const char *tname = jt ? cJSON_GetStringValue(jt) : "bool";
        mb_type type = MB_BOOL;
        bool bitkind = kind == MB_COIL || kind == MB_DISCRETE;
        if (bitkind) {
            if (!tname || strcmp(tname, "bool") != 0)
                return fail(err, errlen, "%s.tag '%s': kind '%s' requires type 'bool', got %s",
                            sect, name, jk->valuestring, json_repr(jt, r, sizeof r));
        } else if (!parse_type(tname, &type) || type == MB_BOOL) {
            return fail(err, errlen, "%s.tag '%s': kind '%s' type must be int16/uint16/int32/uint32/float32, got %s",
                        sect, name, jk->valuestring, json_repr(jt, r, sizeof r));
        }
        if (!bitkind && ja->valuedouble + mb_type_registers(type) - 1 > 65535)
            return fail(err, errlen, "%s.tag '%s' address must be a non-negative int", sect, name);
        const cJSON *jw = cJSON_GetObjectItemCaseSensitive(tc, "writable");
        if (jw && !cJSON_IsBool(jw)) return fail(err, errlen, "%s.tag '%s': writable must be true or false", sect, name);
        if (cJSON_IsTrue(jw) && kind != MB_COIL && kind != MB_HOLDING)
            return fail(err, errlen, "%s.tag '%s': writable=true only valid for coil/holding", sect, name);
        const cJSON *js = cJSON_GetObjectItemCaseSensitive(tc, "scale");
        if (js && (!cJSON_IsNumber(js) || js->valuedouble == 0))
            return fail(err, errlen, "%s.tag '%s': scale must be a non-zero number", sect, name);
        const cJSON *jo = cJSON_GetObjectItemCaseSensitive(tc, "offset");
        if (jo && !cJSON_IsNumber(jo)) return fail(err, errlen, "%s.tag '%s': offset must be a number", sect, name);
        const cJSON *jwo = cJSON_GetObjectItemCaseSensitive(tc, "word_order");
        if (jwo && (!cJSON_IsString(jwo) || (strcmp(jwo->valuestring, "big") && strcmp(jwo->valuestring, "little"))))
            return fail(err, errlen, "%s.tag '%s': word_order must be 'big' or 'little'", sect, name);
        const cJSON *je = cJSON_GetObjectItemCaseSensitive(tc, "enum");
        if (je) {
            if (bitkind || type == MB_FLOAT32)
                return fail(err, errlen, "%s.tag '%s': enum is only valid on holding/input integer types", sect, name);
            if (!cJSON_IsArray(je)) return fail(err, errlen, "%s.tag '%s': enum must be an array of strings", sect, name);
            const cJSON *e;
            cJSON_ArrayForEach(e, je)
                if (!cJSON_IsString(e)) return fail(err, errlen, "%s.tag '%s': enum must be an array of strings", sect, name);
        }
        const cJSON *jss = cJSON_GetObjectItemCaseSensitive(tc, "safe_state");
        if (jss && !cJSON_IsNumber(jss) && !cJSON_IsBool(jss) && !(je && cJSON_IsString(jss)))
            return fail(err, errlen, "%s.tag '%s': safe_state must be a number or bool", sect, name);
        const cJSON *ju = cJSON_GetObjectItemCaseSensitive(tc, "unit");
        if (ju && (!is_int(ju) || ju->valuedouble < 0 || ju->valuedouble > 255))
            return fail(err, errlen, "%s.tag '%s': unit must be 0..255, got %s", sect, name, json_repr(ju, r, sizeof r));
    }
    return 0;
}

static int validate_common(const cJSON *sec, const char *sect, char *err, size_t errlen)
{
    char r[64];
    const cJSON *ju = cJSON_GetObjectItemCaseSensitive(sec, "unit_id");
    if (ju && (!is_int(ju) || ju->valuedouble < 0 || ju->valuedouble > 255))
        return fail(err, errlen, "%s.unit_id must be a non-negative int (0..255), got %s", sect, json_repr(ju, r, sizeof r));
    if (positive_number(sec, sect, "timeout_s", err, errlen) ||
        positive_number(sec, sect, "poll_interval_ms", err, errlen) ||
        positive_number(sec, sect, "reconnect_s", err, errlen))
        return -1;
    return 0;
}

static int validate_tcp(const cJSON *m, const cJSON *rtu, char *err, size_t errlen)
{
    char r[64];
    if (!cJSON_IsObject(m)) return fail(err, errlen, "modbus config must be an object");
    const cJSON *host = cJSON_GetObjectItemCaseSensitive(m, "host");
    if (!cJSON_IsString(host) || !host->valuestring[0])
        return fail(err, errlen, "modbus.host must be a string, got %s", json_repr(host, r, sizeof r));
    const cJSON *port = cJSON_GetObjectItemCaseSensitive(m, "port");
    if (port && (!is_int(port) || port->valuedouble < 1 || port->valuedouble > 65535))
        return fail(err, errlen, "modbus.port must be 1..65535, got %s", json_repr(port, r, sizeof r));
    if (validate_common(m, "modbus", err, errlen)) return -1;
    const cJSON *other = cJSON_IsObject(rtu) ? cJSON_GetObjectItemCaseSensitive(rtu, "tags") : NULL;
    return validate_tags(m, "modbus", cJSON_IsObject(other) ? other : NULL, err, errlen);
}

static int validate_rtu(const cJSON *m, char *err, size_t errlen)
{
    char r[64];
    if (!cJSON_IsObject(m)) return fail(err, errlen, "modbus_rtu config must be an object");
    const cJSON *path = cJSON_GetObjectItemCaseSensitive(m, "path");
    const cJSON *match = cJSON_GetObjectItemCaseSensitive(m, "match");
    if (path && (!cJSON_IsString(path) || !path->valuestring[0]))
        return fail(err, errlen, "modbus_rtu.path must be a string, got %s", json_repr(path, r, sizeof r));
    if (match) {
        if (!cJSON_IsObject(match)) return fail(err, errlen, "modbus_rtu.match must be an object with vid and pid");
        const char *keys[] = {"vid", "pid", "serial"};
        for (int i = 0; i < 3; i++) {
            const cJSON *k = cJSON_GetObjectItemCaseSensitive(match, keys[i]);
            if ((i < 2 && !cJSON_IsString(k)) || (k && !cJSON_IsString(k)))
                return fail(err, errlen, "modbus_rtu.match.%s must be a string", keys[i]);
        }
    }
    if (!path && !match) return fail(err, errlen, "modbus_rtu needs \"path\" or \"match\"");
    const cJSON *jb = cJSON_GetObjectItemCaseSensitive(m, "baudrate");
    if (jb && (!is_int(jb) || jb->valuedouble > INT_MAX || baud_speed((int)jb->valuedouble) == 0))
        return fail(err, errlen, "modbus_rtu.baudrate is not a supported rate, got %s", json_repr(jb, r, sizeof r));
    const cJSON *jp = cJSON_GetObjectItemCaseSensitive(m, "parity");
    if (jp && (!cJSON_IsString(jp) || (strcmp(jp->valuestring, "N") && strcmp(jp->valuestring, "E") &&
                                       strcmp(jp->valuestring, "O"))))
        return fail(err, errlen, "modbus_rtu.parity must be N, E or O, got %s", json_repr(jp, r, sizeof r));
    const cJSON *jst = cJSON_GetObjectItemCaseSensitive(m, "stopbits");
    if (jst && (!is_int(jst) || (jst->valuedouble != 1 && jst->valuedouble != 2)))
        return fail(err, errlen, "modbus_rtu.stopbits must be 1 or 2, got %s", json_repr(jst, r, sizeof r));
    const cJSON *jbs = cJSON_GetObjectItemCaseSensitive(m, "bytesize");
    if (jbs && (!is_int(jbs) || (jbs->valuedouble != 7 && jbs->valuedouble != 8)))
        return fail(err, errlen, "modbus_rtu.bytesize must be 7 or 8, got %s", json_repr(jbs, r, sizeof r));
    if (validate_common(m, "modbus_rtu", err, errlen)) return -1;
    return validate_tags(m, "modbus_rtu", NULL, err, errlen);
}

static int v_validate(const hwd_config *cfg, char *err, size_t errlen)
{
    if (err && errlen) err[0] = '\0';
    if (cfg->modbus && validate_tcp(cfg->modbus, cfg->modbus_rtu, err, errlen)) return -1;
    if (cfg->modbus_rtu && validate_rtu(cfg->modbus_rtu, err, errlen)) return -1;
    return 0;
}

/* ---- values -------------------------------------------------------------- */

static bool is_bit(const mb_tag *t) { return t->kind == MB_COIL || t->kind == MB_DISCRETE; }

/* raw register/bit value -> published value. */
static hwd_value raw_to_value(const mb_tag *t, double raw)
{
    if (is_bit(t)) return hwd_bool(raw != 0);
    if (t->nenum > 0 && raw >= 0 && raw < t->nenum && raw == floor(raw))
        return hwd_str(t->enums[(int)raw]);
    if (t->type != MB_FLOAT32 && t->scale == 1.0 && t->offset == 0.0) return hwd_int((int64_t)raw);
    return hwd_float(raw * t->scale + t->offset);
}

/* value as sent by a client -> raw (clamped to the type, as Python scale_write). */
static hwd_err value_to_raw(const mb_tag *t, const hwd_value *v, double *raw)
{
    double eng;
    switch (v->kind) {
    case HWD_BOOL:  eng = v->u.b ? 1 : 0; break;
    case HWD_INT:   eng = (double)v->u.i; break;
    case HWD_FLOAT: eng = v->u.f; break;
    case HWD_STR:
        for (int i = 0; i < t->nenum; i++)
            if (strcmp(t->enums[i], v->u.s) == 0) { *raw = i; return HWD_OK; }
        return HWD_ERR_BAD_VALUE;
    default: return HWD_ERR_BAD_VALUE;
    }
    if (!isfinite(eng)) return HWD_ERR_BAD_VALUE;
    if (is_bit(t)) { *raw = eng != 0 ? 1 : 0; return HWD_OK; }
    double r = (eng - t->offset) / t->scale;
    switch (t->type) {
    case MB_INT16:  *raw = (double)clamp_round(r, INT16_MIN, INT16_MAX); break;
    case MB_UINT16: *raw = (double)clamp_round(r, 0, UINT16_MAX); break;
    case MB_INT32:  *raw = (double)clamp_round(r, INT32_MIN, INT32_MAX); break;
    case MB_UINT32: *raw = (double)clamp_round(r, 0, UINT32_MAX); break;
    default:        *raw = r; break;
    }
    return HWD_OK;
}

static void store_value(mb_backend *B, const mb_tag *t, hwd_value v)
{
    hwd_tagstore_set(B->store, t->tag, &v);
    hwd_tagstore_set_quality(B->store, t->tag, NULL);
    hwd_value_clear(&v);
}

static void store_bad(mb_backend *B, const mb_tag *t)
{
    hwd_value n = hwd_null();
    hwd_tagstore_set(B->store, t->tag, &n);
    hwd_tagstore_set_quality(B->store, t->tag, "bad");
}

static void set_online(mb_link *L, bool on)
{
    hwd_value v = hwd_bool(on);
    hwd_tagstore_set(L->be->store, L->online_tag, &v);
}

static void link_down(mb_link *L)
{
    for (int i = 0; i < L->ntags; i++) store_bad(L->be, &L->tags[i]);
    set_online(L, false);
}

/* Sleep until `secs` passed or destroy() was called; true when stopping. */
static bool wait_stop(mb_backend *B, double secs)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    if (secs < 0) secs = 0;
    double whole = floor(secs);
    ts.tv_sec += (time_t)whole;
    ts.tv_nsec += (long)((secs - whole) * 1e9);
    if (ts.tv_nsec >= 1000000000L) { ts.tv_sec++; ts.tv_nsec -= 1000000000L; }
    pthread_mutex_lock(&B->stop_mu);
    while (!B->stopping) {
        if (pthread_cond_timedwait(&B->stop_cv, &B->stop_mu, &ts) == ETIMEDOUT) break;
    }
    bool s = B->stopping;
    pthread_mutex_unlock(&B->stop_mu);
    return s;
}

static bool stopping(mb_backend *B)
{
    pthread_mutex_lock(&B->stop_mu);
    bool s = B->stopping;
    pthread_mutex_unlock(&B->stop_mu);
    return s;
}

/* ---- byte I/O with a deadline ---------------------------------------------- */

static int wait_fd(int fd, short ev, double deadline)
{
    for (;;) {
        double left = deadline - hwd_mono();
        if (left <= 0) return 0;
        struct pollfd p = {.fd = fd, .events = ev};
        int r = poll(&p, 1, (int)ceil(left * 1000));
        if (r < 0 && errno == EINTR) continue;
        if (r < 0) return -1;
        if (r == 0) return 0;
        if (p.revents & POLLNVAL) return -1;
        return 1;      /* readable, writable, HUP or ERR: the read/write tells */
    }
}

static int write_all(int fd, const uint8_t *buf, size_t n, double deadline, bool sock)
{
    size_t off = 0;
    while (off < n) {
        ssize_t w = sock ? send(fd, buf + off, n - off, MSG_NOSIGNAL) : write(fd, buf + off, n - off);
        if (w > 0) { off += (size_t)w; continue; }
        if (w < 0 && errno == EINTR) continue;
        if (w < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            if (wait_fd(fd, POLLOUT, deadline) <= 0) return -1;
            continue;
        }
        return -1;
    }
    return 0;
}

/* Read exactly n bytes: 0 ok, -1 I/O error or EOF, -2 timeout. */
static int read_exact(int fd, uint8_t *buf, size_t n, double deadline)
{
    size_t off = 0;
    while (off < n) {
        ssize_t r = read(fd, buf + off, n - off);
        if (r > 0) { off += (size_t)r; continue; }
        if (r == 0) return -1;
        if (errno == EINTR) continue;
        if (errno != EAGAIN && errno != EWOULDBLOCK) return -1;
        int w = wait_fd(fd, POLLIN, deadline);
        if (w < 0) return -1;
        if (w == 0) return -2;
    }
    return 0;
}

/* ---- TCP link -------------------------------------------------------------- */

static int tcp_connect(const mb_link *L)
{
    char port[16];
    snprintf(port, sizeof port, "%d", L->port);
    struct addrinfo hints = {.ai_family = AF_UNSPEC, .ai_socktype = SOCK_STREAM}, *res = NULL;
    if (getaddrinfo(L->host, port, &hints, &res) != 0 || !res) return -1;
    int fd = -1;
    double deadline = hwd_mono() + L->timeout_s;
    for (struct addrinfo *a = res; a; a = a->ai_next) {
        fd = socket(a->ai_family, a->ai_socktype | SOCK_NONBLOCK | SOCK_CLOEXEC, a->ai_protocol);
        if (fd < 0) continue;
        int r = connect(fd, a->ai_addr, a->ai_addrlen);
        if (r < 0 && errno == EINPROGRESS) {
            int soerr = 0;
            socklen_t sl = sizeof soerr;
            if (wait_fd(fd, POLLOUT, deadline) == 1 &&
                getsockopt(fd, SOL_SOCKET, SO_ERROR, &soerr, &sl) == 0 && soerr == 0)
                r = 0;
        }
        if (r == 0) {
            int one = 1;
            setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
            break;
        }
        close(fd);
        fd = -1;
    }
    freeaddrinfo(res);
    return fd;
}

/* Send req and receive the reply with the same transaction id into resp.
 * Caller holds L->mu. 0 ok (length in *rlen), -1 link error. */
static int tcp_xfer(mb_link *L, const uint8_t *req, size_t n, uint8_t *resp, size_t *rlen)
{
    if (L->fd < 0) return -1;
    double deadline = hwd_mono() + L->timeout_s;
    uint16_t tid = get_u16(req);
    if (write_all(L->fd, req, n, deadline, true) < 0) return -1;
    for (;;) {
        if (read_exact(L->fd, resp, 7, deadline) != 0) return -1;
        size_t plen = get_u16(resp + 4);
        if (get_u16(resp + 2) != 0 || plen < 2 || plen > 254) return -1;
        if (read_exact(L->fd, resp + 7, plen - 1, deadline) != 0) return -1;
        if (get_u16(resp) == tid) { *rlen = 6 + plen; return 0; }
        /* a late reply to a request that timed out earlier: skip it */
    }
}

static void link_close(mb_link *L)
{
    if (L->fd >= 0) close(L->fd);
    L->fd = -1;
}

/* ---- RTU link -------------------------------------------------------------- */

static bool read_attr(const char *dir, const char *name, char *out, size_t n)
{
    char p[PATH_MAX + 64];
    snprintf(p, sizeof p, "%s/%s", dir, name);
    FILE *f = fopen(p, "r");
    if (!f) return false;
    bool ok = fgets(out, (int)n, f) != NULL;
    fclose(f);
    if (ok) out[strcspn(out, "\r\n")] = '\0';
    return ok;
}

/* Find /dev/<tty> whose USB device matches vid/pid(/serial) under sysfs
 * (HWD_SYSFS_ROOT overrides /sys, CONTRACT 14.1). */
static bool find_tty(const mb_link *L, char *out, size_t n)
{
    const char *root = getenv("HWD_SYSFS_ROOT");
    if (!root || !*root) root = "/sys";
    char cls[PATH_MAX];
    snprintf(cls, sizeof cls, "%s/class/tty", root);
    DIR *d = opendir(cls);
    if (!d) return false;
    struct dirent *e;
    bool found = false;
    while (!found && (e = readdir(d))) {
        if (e->d_name[0] == '.') continue;
        char dev[PATH_MAX + 512], real[PATH_MAX];
        snprintf(dev, sizeof dev, "%s/%s/device", cls, e->d_name);
        if (!realpath(dev, real)) continue;
        for (int up = 0; up < 6; up++) {
            char vid[32], pid[32], ser[160];
            if (read_attr(real, "idVendor", vid, sizeof vid) && read_attr(real, "idProduct", pid, sizeof pid)) {
                if (!strcasecmp(vid, L->vid) && !strcasecmp(pid, L->pid) &&
                    (!L->serial[0] || (read_attr(real, "serial", ser, sizeof ser) && !strcmp(ser, L->serial)))) {
                    snprintf(out, n, "/dev/%s", e->d_name);
                    found = true;
                }
                break;
            }
            char *slash = strrchr(real, '/');
            if (!slash || slash == real) break;
            *slash = '\0';
        }
    }
    closedir(d);
    return found;
}

static int rtu_open(mb_link *L)
{
    char path[PATH_MAX];
    if (L->path[0]) snprintf(path, sizeof path, "%s", L->path);
    else if (!find_tty(L, path, sizeof path)) return -1;
    int fd = open(path, O_RDWR | O_NOCTTY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) return -1;
    struct termios tio;
    if (tcgetattr(fd, &tio) != 0) { close(fd); return -1; }
    cfmakeraw(&tio);
    speed_t sp = baud_speed(L->baud);
    cfsetispeed(&tio, sp);
    cfsetospeed(&tio, sp);
    tio.c_cflag &= ~(tcflag_t)(CSIZE | PARENB | PARODD | CSTOPB | CRTSCTS);
    tio.c_cflag |= (tcflag_t)((L->bytesize == 7 ? CS7 : CS8) | CLOCAL | CREAD);
    if (L->parity == 'E') tio.c_cflag |= PARENB;
    if (L->parity == 'O') tio.c_cflag |= PARENB | PARODD;
    if (L->stopbits == 2) tio.c_cflag |= CSTOPB;
    tio.c_cc[VMIN] = 0;
    tio.c_cc[VTIME] = 0;
    if (tcsetattr(fd, TCSANOW, &tio) != 0) { close(fd); return -1; }
    tcflush(fd, TCIOFLUSH);
    HWD_INFO("modbus_rtu: opened %s at %d baud", path, L->baud);
    return fd;
}

static double rtu_char_s(const mb_link *L)
{
    int bits = 1 + L->bytesize + (L->parity != 'N') + L->stopbits;
    return (double)bits / (double)L->baud;
}

/* 3.5 character times between frames (fixed 1.75 ms above 19200 baud). */
static double rtu_gap_s(const mb_link *L)
{
    return L->baud > 19200 ? 0.00175 : 3.5 * rtu_char_s(L);
}

/* Send one RTU request and read its reply (fc decides the length). Caller
 * holds L->mu. 0 ok, -1 link error (tty gone), -2 no/garbled answer. */
static int rtu_xfer(mb_link *L, const uint8_t *req, size_t n, uint8_t fc, uint8_t *resp, size_t *rlen)
{
    if (L->fd < 0) return -1;
    double wait = L->last_io + rtu_gap_s(L) - hwd_mono();
    if (wait > 0) {
        struct timespec ts = {0, (long)(wait * 1e9)};
        nanosleep(&ts, NULL);
    }
    tcflush(L->fd, TCIFLUSH);
    double deadline = hwd_mono() + L->timeout_s + (double)n * rtu_char_s(L);
    if (write_all(L->fd, req, n, deadline, false) < 0) { L->last_io = hwd_mono(); return -1; }
    size_t have = 0, need = 5;
    int rc = 0;
    while (have < need) {
        ssize_t r = read(L->fd, resp + have, need - have);
        if (r > 0) {
            have += (size_t)r;
            if (have >= 3) {
                if (resp[1] & 0x80) need = 5;
                else if (fc <= 4) need = 5 + (size_t)resp[2];
                else need = 8;
            }
            continue;
        }
        if (r < 0 && errno == EINTR) continue;
        if (r < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EIO) { rc = -1; break; }
        int w = wait_fd(L->fd, POLLIN, deadline);
        if (w < 0) { rc = -1; break; }
        if (w == 0) { rc = -2; break; }
        if (r < 0 && errno == EIO) {
            /* pty with no peer / unplugged adapter: give it the timeout, then fail the link */
            struct timespec ts = {0, 10000000L};
            nanosleep(&ts, NULL);
            if (hwd_mono() >= deadline) { rc = -1; break; }
        }
    }
    L->last_io = hwd_mono();
    if (rc == 0) *rlen = have;
    return rc;
}

/* ---- one request, either link ------------------------------------------- */

/* Read one tag: 0 ok (*raw set), >0 Modbus exception, -1 link error, -2 no answer. */
static int link_read(mb_link *L, const mb_tag *t, double *raw)
{
    uint8_t fc = t->kind == MB_COIL ? 1 : t->kind == MB_DISCRETE ? 2 : t->kind == MB_HOLDING ? 3 : 4;
    uint16_t count = is_bit(t) ? 1 : (uint16_t)mb_type_registers(t->type);
    uint8_t req[300], resp[300], bits[8] = {0};
    uint16_t regs[4] = {0};
    size_t rlen = 0;
    int rc;
    pthread_mutex_lock(&L->mu);
    if (L->rtu) {
        size_t n = mb_rtu_req_read(req, t->unit, fc, t->address, count);
        rc = rtu_xfer(L, req, n, fc, resp, &rlen);
        if (rc == 0) {
            rc = mb_rtu_parse_read(resp, rlen, t->unit, fc, count, bits, regs);
            if (rc < 0) rc = -2;
        }
    } else {
        L->tid++;
        size_t n = mb_req_read(req, L->tid, t->unit, fc, t->address, count);
        rc = tcp_xfer(L, req, n, resp, &rlen);
        if (rc == 0) rc = mb_parse_read(resp, rlen, L->tid, fc, count, bits, regs);
    }
    if (rc == -1) link_close(L);
    pthread_mutex_unlock(&L->mu);
    if (rc == 0) *raw = is_bit(t) ? bits[0] : mb_decode(t->type, regs, t->little);
    return rc;
}

/* Write raw to one tag: 0 ok, >0 exception, -1 link error / down, -2 no answer. */
static int link_write(mb_link *L, const mb_tag *t, double raw)
{
    uint16_t regs[2] = {0, 0};
    uint8_t fc;
    int nregs = 1;
    if (t->kind == MB_COIL) {
        fc = 5;
        regs[0] = raw != 0 ? 0xFF00 : 0x0000;
    } else {
        nregs = mb_encode(t->type, raw, regs, t->little);
        /* 1 or 2 registers, never more: also what lets the optimiser see
         * regs[] is never read past its end. */
        if (nregs < 1 || nregs > 2) return -1;
        fc = nregs == 1 ? 6 : 16;
    }
    uint8_t req[300], resp[300];
    size_t rlen = 0, n;
    int rc;
    pthread_mutex_lock(&L->mu);
    if (L->fd < 0) {
        rc = -1;
    } else if (L->rtu) {
        n = fc == 16 ? mb_rtu_req_write_multi(req, t->unit, t->address, regs, (uint16_t)nregs)
                     : mb_rtu_req_write_single(req, t->unit, fc, t->address, regs[0]);
        rc = rtu_xfer(L, req, n, fc, resp, &rlen);
        if (rc == 0) {
            rc = mb_rtu_parse_write(resp, rlen, t->unit, fc);
            if (rc < 0) rc = -2;
        }
    } else {
        L->tid++;
        n = fc == 16 ? mb_req_write_multi(req, L->tid, t->unit, t->address, regs, (uint16_t)nregs)
                     : mb_req_write_single(req, L->tid, t->unit, fc, t->address, regs[0]);
        rc = tcp_xfer(L, req, n, resp, &rlen);
        if (rc == 0) rc = mb_parse_write(resp, rlen, L->tid, fc);
    }
    if (rc == -1) link_close(L);
    pthread_mutex_unlock(&L->mu);
    return rc;
}

/* ---- poll threads ------------------------------------------------------------ */

static const char *link_name(const mb_link *L) { return L->rtu ? "modbus_rtu" : "modbus"; }

static bool link_lost(mb_link *L, bool *was_up)
{
    if (*was_up)
        HWD_WARN("%s: link lost, retrying every %.1fs", link_name(L), L->reconnect_s);
    *was_up = false;
    pthread_mutex_lock(&L->mu);
    link_close(L);
    pthread_mutex_unlock(&L->mu);
    atomic_fetch_add(&L->be->errors, 1);
    link_down(L);
    return wait_stop(L->be, L->reconnect_s);
}

static void *link_thread(void *arg)
{
    mb_link *L = arg;
    mb_backend *B = L->be;
    bool was_up = false, warned = false;
    while (!stopping(B)) {
        pthread_mutex_lock(&L->mu);
        bool open = L->fd >= 0;
        pthread_mutex_unlock(&L->mu);
        if (!open) {
            int fd = L->rtu ? rtu_open(L) : tcp_connect(L);
            if (fd < 0) {
                if (!warned)
                    HWD_WARN("%s: cannot open %s, retrying every %.1fs", link_name(L),
                             L->rtu ? (L->path[0] ? L->path : "the matched serial port") : L->host,
                             L->reconnect_s);
                warned = true;
                if (link_lost(L, &was_up)) break;
                continue;
            }
            pthread_mutex_lock(&L->mu);
            L->fd = fd;
            L->last_io = hwd_mono();
            pthread_mutex_unlock(&L->mu);
            if (!L->rtu) HWD_INFO("modbus: connected to %s:%d", L->host, L->port);
            warned = false;
        }
        double start = hwd_mono();
        bool err = false;
        int good = 0;
        for (int i = 0; i < L->ntags && !err && !stopping(B); i++) {
            mb_tag *t = &L->tags[i];
            double raw = 0;
            int rc = link_read(L, t, &raw);
            if (rc == 0) {
                store_value(B, t, raw_to_value(t, raw));
                good++;
            } else if (rc == -1) {
                err = true;
            } else {
                store_bad(B, t);
                atomic_fetch_add(&B->errors, 1);
            }
        }
        if (err) {
            if (link_lost(L, &was_up)) break;
            continue;
        }
        was_up = true;
        set_online(L, !L->rtu || good > 0 || L->ntags == 0);
        double left = start + L->poll_s - hwd_mono();
        if (wait_stop(B, left > 0.001 ? left : 0.001)) break;
    }
    return NULL;
}

/* ---- create / start / write / destroy ---------------------------------------- */

static mb_tag *find_tag(mb_backend *B, const char *tag, mb_link **link)
{
    for (int l = 0; l < B->nlinks; l++)
        for (int i = 0; i < B->links[l].ntags; i++)
            if (strcmp(B->links[l].tags[i].tag, tag) == 0) {
                if (link) *link = &B->links[l];
                return &B->links[l].tags[i];
            }
    return NULL;
}

static double num(const cJSON *o, const char *k, double dflt)
{
    const cJSON *j = cJSON_GetObjectItemCaseSensitive(o, k);
    return cJSON_IsNumber(j) ? j->valuedouble : dflt;
}

static const char *str(const cJSON *o, const char *k)
{
    return cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, k));
}

static void free_link(mb_link *L)
{
    for (int i = 0; i < L->ntags; i++) {
        for (int k = 0; k < L->tags[i].nenum; k++) free(L->tags[i].enums[k]);
        free(L->tags[i].enums);
        hwd_value_clear(&L->tags[i].safe);
    }
    free(L->tags);
    L->tags = NULL;
    L->ntags = 0;
}

static void v_destroy(void *self);

static bool load_link(mb_backend *B, mb_link *L, const cJSON *sec, bool rtu, const hwd_backend_opts *opts)
{
    L->be = B;
    L->rtu = rtu;
    L->live = !opts->sim || opts->modbus_live;
    L->online_tag = rtu ? "sys.modbus_rtu_online" : "sys.modbus_online";
    L->fd = -1;
    L->unit_id = (uint8_t)num(sec, "unit_id", 1);
    L->timeout_s = num(sec, "timeout_s", rtu ? 0.5 : 1.0);
    L->poll_s = num(sec, "poll_interval_ms", 200) / 1000.0;
    L->reconnect_s = num(sec, "reconnect_s", rtu ? 2.0 : 5.0);
    if (rtu) {
        const cJSON *m = cJSON_GetObjectItemCaseSensitive(sec, "match");
        const char *s;
        if ((s = str(sec, "path"))) snprintf(L->path, sizeof L->path, "%s", s);
        if ((s = str(m, "vid"))) snprintf(L->vid, sizeof L->vid, "%s", s);
        if ((s = str(m, "pid"))) snprintf(L->pid, sizeof L->pid, "%s", s);
        if ((s = str(m, "serial"))) snprintf(L->serial, sizeof L->serial, "%s", s);
        L->baud = (int)num(sec, "baudrate", 9600);
        if (baud_speed(L->baud) == 0) L->baud = 9600;
        L->bytesize = (int)num(sec, "bytesize", 8);
        L->stopbits = (int)num(sec, "stopbits", 1);
        const char *par = str(sec, "parity");
        L->parity = par ? par[0] : 'N';
    } else {
        const char *h = str(sec, "host");
        snprintf(L->host, sizeof L->host, "%s", h ? h : "127.0.0.1");
        L->port = (int)num(sec, "port", 502);
    }
    const cJSON *tags = cJSON_GetObjectItemCaseSensitive(sec, "tags");
    int n = cJSON_IsObject(tags) ? cJSON_GetArraySize(tags) : 0;
    L->tags = calloc((size_t)(n > 0 ? n : 1), sizeof *L->tags);
    if (!L->tags) return false;
    const cJSON *tc;
    if (n > 0) cJSON_ArrayForEach(tc, tags) {
        mb_tag *t = &L->tags[L->ntags++];
        snprintf(t->tag, sizeof t->tag, "%s", tc->string);
        t->kind = MB_HOLDING;
        parse_kind(str(tc, "kind"), &t->kind);
        if (is_bit(t) || !parse_type(str(tc, "type"), &t->type)) t->type = MB_BOOL;
        t->address = (uint16_t)num(tc, "address", 0);
        t->unit = (uint8_t)num(tc, "unit", L->unit_id);
        t->scale = num(tc, "scale", 1.0);
        if (t->scale == 0) t->scale = 1.0;
        t->offset = num(tc, "offset", 0.0);
        const char *wo = str(tc, "word_order");
        t->little = wo && !strcmp(wo, "little");
        t->writable = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(tc, "writable"));
        const cJSON *je = cJSON_GetObjectItemCaseSensitive(tc, "enum");
        int ne = cJSON_IsArray(je) ? cJSON_GetArraySize(je) : 0;
        if (ne > 0) {
            t->enums = calloc((size_t)ne, sizeof *t->enums);
            if (!t->enums) return false;
            const cJSON *e;
            cJSON_ArrayForEach(e, je) {
                if (t->nenum >= ne) break;
                t->enums[t->nenum] = strdup(cJSON_IsString(e) ? e->valuestring : "");
                if (!t->enums[t->nenum]) return false;
                t->nenum++;
            }
        }
        const cJSON *js = cJSON_GetObjectItemCaseSensitive(tc, "safe_state");
        t->safe = hwd_null();
        if (cJSON_IsBool(js)) { t->safe = hwd_bool(cJSON_IsTrue(js)); t->has_safe = true; }
        else if (cJSON_IsNumber(js)) { t->safe = hwd_float(js->valuedouble); t->has_safe = true; }
        else if (cJSON_IsString(js)) { t->safe = hwd_str(js->valuestring); t->has_safe = true; }
    }
    return true;
}

static void *v_create(const hwd_config *cfg, hwd_tagstore *store, const hwd_backend_opts *opts,
                      char *err, size_t errlen)
{
    if (err && errlen) err[0] = '\0';
    if (!cfg->modbus && !cfg->modbus_rtu) return NULL;
    mb_backend *B = calloc(1, sizeof *B);
    if (!B) { fail(err, errlen, "modbus: out of memory"); return NULL; }
    B->store = store;
    pthread_mutex_init(&B->stop_mu, NULL);
    pthread_condattr_t ca;
    pthread_condattr_init(&ca);
    pthread_condattr_setclock(&ca, CLOCK_MONOTONIC);
    pthread_cond_init(&B->stop_cv, &ca);
    pthread_condattr_destroy(&ca);
    atomic_init(&B->errors, 0);

    const cJSON *secs[2] = {cfg->modbus, cfg->modbus_rtu};
    for (int s = 0; s < 2; s++) {
        if (!secs[s]) continue;
        mb_link *L = &B->links[B->nlinks++];
        pthread_mutex_init(&L->mu, NULL);
        if (!load_link(B, L, secs[s], s == 1, opts)) {
            fail(err, errlen, "%s: out of memory", s ? "modbus_rtu" : "modbus");
            v_destroy(B);
            return NULL;
        }
        for (int i = 0; i < L->ntags; i++) {
            mb_tag *t = &L->tags[i];
            hwd_value init = hwd_null();
            bool failed = false;
            if (!L->live) {
                /* sim: the safe_state (or 0/false), as if it had been read back */
                double raw = 0;
                if (!t->has_safe || value_to_raw(t, &t->safe, &raw) != HWD_OK) raw = 0;
                failed = hwd_sim_fails(t->tag);
                if (!failed) init = raw_to_value(t, raw);
            }
            bool ok = hwd_tagstore_register(store, t->tag, init, t->writable);
            hwd_value_clear(&init);
            if (!ok) {
                fail(err, errlen, "%s: cannot register tag '%s'", link_name(L), t->tag);
                v_destroy(B);
                return NULL;
            }
            if (failed) hwd_tagstore_set_quality(store, t->tag, "bad");
        }
        hwd_tagstore_register(store, L->online_tag, hwd_bool(false), false);
        if (L->live && L->rtu && opts->strict) {
            int fd = rtu_open(L);
            if (fd < 0) {
                fail(err, errlen, "modbus_rtu: cannot open %s", L->path[0] ? L->path : "the matched serial port");
                v_destroy(B);
                return NULL;
            }
            L->fd = fd;
            L->last_io = hwd_mono();
        }
    }
    return B;
}

static void v_start(void *self)
{
    mb_backend *B = self;
    if (!B) return;
    for (int l = 0; l < B->nlinks; l++) {
        mb_link *L = &B->links[l];
        if (!L->live || L->thread_started) continue;
        if (pthread_create(&L->thread, NULL, link_thread, L) == 0) L->thread_started = true;
        else HWD_ERROR("%s: cannot start the poll thread", link_name(L));
    }
}

static bool v_owns(void *self, const char *tag)
{
    mb_backend *B = self;
    if (!B || !tag) return false;
    for (int l = 0; l < B->nlinks; l++)
        if (!strcmp(B->links[l].online_tag, tag)) return true;
    return find_tag(B, tag, NULL) != NULL;
}

static hwd_err v_write(void *self, const char *tag, const hwd_value *v)
{
    mb_backend *B = self;
    mb_link *L = NULL;
    mb_tag *t = (B && tag) ? find_tag(B, tag, &L) : NULL;
    if (!t || !t->writable) return HWD_ERR_NOT_WRITABLE;
    double raw = 0;
    hwd_err e = value_to_raw(t, v, &raw);
    if (e != HWD_OK) return e;
    if (L->live) {
        int rc = link_write(L, t, raw);
        if (rc != 0) {
            atomic_fetch_add(&B->errors, 1);
            HWD_WARN("%s: write to %s failed (%s %d)", link_name(L), tag,
                     rc > 0 ? "exception" : rc == -1 ? "link down" : "no answer", rc);
            return HWD_ERR_HW_ERROR;
        }
    }
    store_value(B, t, raw_to_value(t, raw));
    return HWD_OK;
}

static hwd_err v_command(void *self, const char *cmd, const cJSON *msg, cJSON *reply)
{ (void)self; (void)cmd; (void)msg; (void)reply; return HWD_ERR_UNKNOWN_CMD; }

static void v_safe_state(void *self)
{
    mb_backend *B = self;
    if (!B) return;
    for (int l = 0; l < B->nlinks; l++)
        for (int i = 0; i < B->links[l].ntags; i++) {
            mb_tag *t = &B->links[l].tags[i];
            if (t->writable && t->has_safe) v_write(B, t->tag, &t->safe);
        }
}

static uint64_t v_errors(void *self)
{
    mb_backend *B = self;
    return B ? (uint64_t)atomic_load(&B->errors) : 0;
}

static void v_destroy(void *self)
{
    mb_backend *B = self;
    if (!B) return;
    pthread_mutex_lock(&B->stop_mu);
    B->stopping = true;
    pthread_cond_broadcast(&B->stop_cv);
    pthread_mutex_unlock(&B->stop_mu);
    for (int l = 0; l < B->nlinks; l++) {
        mb_link *L = &B->links[l];
        if (L->thread_started) pthread_join(L->thread, NULL);
        link_close(L);
        pthread_mutex_destroy(&L->mu);
        free_link(L);
    }
    pthread_cond_destroy(&B->stop_cv);
    pthread_mutex_destroy(&B->stop_mu);
    free(B);
}

const hwd_backend_ops hwd_backend_modbus = {
    "modbus", v_validate, v_create, v_start, NULL, v_owns, v_write, v_command, v_safe_state, v_errors, v_destroy,
};
