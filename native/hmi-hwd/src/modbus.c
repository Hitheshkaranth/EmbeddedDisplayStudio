/*
 * modbus.c -- the Modbus codec (modbus.h) and the backend serving "modbus" (TCP) and
 * "modbus_rtu" (CONTRACT 2.5, 14.2).
 * OWNER: A2.
 */
#include "modbus.h"
#include "backend.h"

#include <ctype.h>
#include <math.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ---------------------------------------------------------------- codec */

int mb_type_registers(mb_type t)
{
    switch (t) {
    case MB_INT32: case MB_UINT32: case MB_FLOAT32: return 2;
    default: return 1;
    }
}

double mb_decode(mb_type t, const uint16_t *regs, bool little_words)
{
    switch (t) {
    case MB_BOOL:  return regs[0] != 0;
    case MB_INT16: { int16_t v = (int16_t)(regs[0] << 8 | regs[0] >> 8); return (double)v; }
    case MB_UINT16: return (double)regs[0];
    case MB_INT32: case MB_UINT32: case MB_FLOAT32: {
        uint32_t hi, lo, w;
        if (little_words) { hi = regs[1]; lo = regs[0]; }
        else              { hi = regs[0]; lo = regs[1]; }
        w = (hi << 16) | lo;
        if (t == MB_INT32)    return (double)(int32_t)w;
        if (t == MB_FLOAT32) { float f; memcpy(&f, &w, sizeof f); return (double)f; }
        return (double)w;
    }
    }
    return 0;
}

int mb_encode(mb_type t, double raw, uint16_t *regs, bool little_words)
{
    memset(regs, 0, (size_t)mb_type_registers(t) * sizeof regs[0]);
    switch (t) {
    case MB_BOOL:  regs[0] = raw ? 0xFFFF : 0x0000; return 1;
    case MB_INT16: case MB_UINT16: regs[0] = (uint16_t)raw; return 1;
    case MB_INT32: case MB_UINT32: case MB_FLOAT32: {
        uint32_t w;
        if (t == MB_FLOAT32)      { float f = (float)raw; memcpy(&w, &f, sizeof w); }
        else if (t == MB_INT32)   { w = (uint32_t)(int32_t)raw; }
        else                      { w = (uint32_t)raw; }
        if (little_words) { regs[0] = (uint16_t)w; regs[1] = (uint16_t)(w >> 16); }
        else              { regs[0] = (uint16_t)(w >> 16); regs[1] = (uint16_t)w; }
        return 2;
    }
    }
    return 0;
}

static void put_u16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)(v >> 8); p[1] = (uint8_t)v; }
static uint16_t get_u16(const uint8_t *p)   { return (uint16_t)((p[0] << 8) | p[1]); }

size_t mb_req_read(uint8_t *buf, uint16_t tid, uint8_t unit, uint8_t fc, uint16_t addr, uint16_t count)
{
    put_u16(buf, tid); put_u16(buf + 2, 0); put_u16(buf + 4, 6);
    buf[6] = (uint8_t)unit; buf[7] = (uint8_t)fc;
    put_u16(buf + 8, addr); put_u16(buf + 10, count);
    return 12;
}

size_t mb_req_write_single(uint8_t *buf, uint16_t tid, uint8_t unit, uint8_t fc, uint16_t addr, uint16_t value)
{
    put_u16(buf, tid); put_u16(buf + 2, 0); put_u16(buf + 4, 6);
    buf[6] = (uint8_t)unit; buf[7] = (uint8_t)fc;
    put_u16(buf + 8, addr); put_u16(buf + 10, value);
    return 12;
}

size_t mb_req_write_multi(uint8_t *buf, uint16_t tid, uint8_t unit, uint16_t addr, const uint16_t *regs, uint16_t count)
{
    put_u16(buf, tid); put_u16(buf + 2, 0);
    put_u16(buf + 4, (uint16_t)(7 + 2 * count));
    buf[6] = (uint8_t)unit; buf[7] = (uint8_t)16;
    put_u16(buf + 8, addr); put_u16(buf + 10, count);
    buf[12] = (uint8_t)(2 * count);
    for (int i = 0; i < count; i++) { put_u16(buf + 13 + 2 * i, regs[i]); }
    return (size_t)(13 + 2 * count);
}

static int parse_read_pdu(const uint8_t *pdu, size_t len, uint8_t fc,
                          uint16_t count, uint8_t *bits, uint16_t *regs)
{
    if (len < 3) return -1;
    if (pdu[1] != fc || (pdu[1] & 0x80)) {
        uint8_t exc = pdu[2];
        return exc ? (int)exc : -1;
    }
    switch (fc) {
    case 1: case 2: {
        size_t nbytes = pdu[2];
        if (len < 3 + nbytes) return -1;
        if (nbytes > (size_t)((count + 7) / 8)) return -1;
        for (size_t i = 0; i < (size_t)count; i++) {
            if (bits) {
                uint8_t b = (i < nbytes) ? (pdu[3 + (i >> 3)] >> (i & 7)) & 1 : 0;
                bits[i] = (uint8_t)b;
            }
        }
        return 0;
    }
    case 3: case 4: {
        size_t nbytes = pdu[2];
        if (len < 3 + nbytes) return -1;
        size_t nregs = nbytes / 2;
        if (nregs > (size_t)count) return -1;
        for (size_t i = 0; i < nregs; i++) {
            if (regs) regs[i] = get_u16(pdu + 3 + 2 * i);
        }
        return 0;
    }
    default:
        return -1;
    }
}

int mb_parse_read(const uint8_t *buf, size_t len, uint16_t tid, uint8_t fc,
                  uint16_t count, uint8_t *bits, uint16_t *regs)
{
    if (len < 8) return -1;
    if (get_u16(buf) != tid) return -1;
    size_t plen = get_u16(buf + 4);
    if (plen < 2) return -1;
    if (len < 6 + plen) return -1;
    return parse_read_pdu(buf + 6, len - 6, fc, count, bits, regs);
}

static int parse_write_pdu(const uint8_t *pdu, size_t len, uint8_t fc)
{
    if (len < 4) return -1;
    return (pdu[1] == fc && !(pdu[1] & 0x80)) ? 0 : -1;
}

int mb_parse_write(const uint8_t *buf, size_t len, uint16_t tid, uint8_t fc)
{
    if (len < 8) return -1;
    if (get_u16(buf) != tid || get_u16(buf + 4) == 0) return -1;
    if (buf[7] != fc || (buf[7] & 0x80)) {
        uint8_t exc = len > 8 ? buf[8] : 0;
        return exc ? (int)exc : -1;
    }
    return 0;
}

uint16_t mb_crc16(const uint8_t *buf, size_t len)
{
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= buf[i];
        for (int k = 0; k < 8; k++)
            crc = (uint16_t)((crc >> 1) ^ (0xA001 & -(int)(crc & 1)));
    }
    return crc;
}

size_t mb_rtu_req_read(uint8_t *buf, uint8_t unit, uint8_t fc, uint16_t addr, uint16_t count)
{
    buf[0] = unit; buf[1] = fc; put_u16(buf + 2, addr); put_u16(buf + 4, count);
    uint16_t crc = mb_crc16(buf, 6);
    buf[6] = (uint8_t)(crc & 0xFF); buf[7] = (uint8_t)(crc >> 8);
    return 8;
}

size_t mb_rtu_req_write_single(uint8_t *buf, uint8_t unit, uint8_t fc, uint16_t addr, uint16_t value)
{
    buf[0] = unit; buf[1] = fc; put_u16(buf + 2, addr); put_u16(buf + 4, value);
    uint16_t crc = mb_crc16(buf, 6);
    buf[6] = (uint8_t)(crc & 0xFF); buf[7] = (uint8_t)(crc >> 8);
    return 8;
}

size_t mb_rtu_req_write_multi(uint8_t *buf, uint8_t unit, uint16_t addr, const uint16_t *regs, uint16_t count)
{
    size_t p = 0;
    buf[p++] = unit; buf[p++] = 16;
    put_u16(buf + p, addr); p += 2;
    put_u16(buf + p, count); p += 2;
    buf[p++] = (uint8_t)(2 * count);
    for (int i = 0; i < count; i++) put_u16(buf + p, regs[i]); p += 2;
    uint16_t crc = mb_crc16(buf, p);
    buf[p++] = (uint8_t)(crc & 0xFF); buf[p++] = (uint8_t)(crc >> 8);
    return p;
}

int mb_rtu_parse_read(const uint8_t *buf, size_t len, uint8_t unit, uint8_t fc, uint16_t count,
                      uint8_t *bits, uint16_t *regs)
{
    if (len < 8) return -1;
    if (buf[0] != unit) return -1;
    uint16_t stored = get_u16(buf + len - 2), have = mb_crc16(buf, len - 2);
    if (stored != have) return -1;
    return parse_read_pdu(buf + 1, len - 3, fc, count, bits, regs);
}

int mb_rtu_parse_write(const uint8_t *buf, size_t len, uint8_t unit, uint8_t fc)
{
    if (len < 8) return -1;
    if (buf[0] != unit) return -1;
    uint16_t stored = get_u16(buf + len - 2), have = mb_crc16(buf, len - 2);
    if (stored != have) return -1;
    return parse_write_pdu(buf + 1, len - 3, fc);
}

/* ---------------------------------------------------------------- types */

typedef enum { MB_KIND_COIL, MB_KIND_DISCRETE, MB_KIND_HOLDING, MB_KIND_INPUT } mb_kind_t;
typedef enum { MB_T_INT16, MB_T_UINT16, MB_T_INT32, MB_T_UINT32, MB_T_FLOAT32 } mb_type_t;

typedef struct {
    char tag[HWD_MAX_TAG];
    mb_kind_t kind;
    uint16_t address;
    mb_type_t type;
    double scale, offset;
    int little_words;
    int writable;
    const cJSON *e0, *e1, *e2, *e3;  /* enum entries */
    int safe_state;
} mb_tag;

typedef struct {
    int ntags;
    mb_tag tags[HWD_MAX_TAGS];
} mb_cfg;

static mb_type_t type_of(const char *s)
{
    if (!s) return MB_T_INT16;
    if (!strcmp(s, "int16"))    return MB_T_INT16;
    if (!strcmp(s, "uint16"))   return MB_T_UINT16;
    if (!strcmp(s, "int32"))    return MB_T_INT32;
    if (!strcmp(s, "uint32"))   return MB_T_UINT32;
    if (!strcmp(s, "float32"))  return MB_T_FLOAT32;
    return MB_T_INT16;
}

#define NREG(t)  (t == MB_T_INT32 || t == MB_T_UINT32 || t == MB_T_FLOAT32 ? 2 : 1)

static hwd_value value_from_reg(mb_type_t type, double raw, double scale, double offset,
                                const cJSON *e0, const cJSON *e1, const cJSON *e2, const cJSON *e3)
{
    hwd_value v;
    if (type == MB_T_FLOAT32) return hwd_float(raw * scale + offset);
    int64_t iv = (int64_t)lround(raw);
    double eng = raw * scale + offset;
    if (e3 && iv >= 0 && iv <= 3 && e3->valuestring) { v = hwd_str(e3->valuestring); v.kind = HWD_STR; return v; }
    if (e2 && iv >= 0 && iv <= 2 && e2->valuestring) { v = hwd_str(e2->valuestring); v.kind = HWD_STR; return v; }
    if (e1 && iv >= 0 && iv <= 1 && e1->valuestring) { v = hwd_str(e1->valuestring); v.kind = HWD_STR; return v; }
    if (e0 && iv == 0 && e0->valuestring) { v = hwd_str(e0->valuestring); v.kind = HWD_STR; return v; }
    if (scale == 1.0 && offset == 0.0) { v.kind = HWD_INT; v.u.i = iv; }
    else { v.kind = HWD_FLOAT; v.u.f = eng; }
    return v;
}

/* ------------------------------------------------------------- validation */

static int bad(char *err, size_t errlen, const char *m)
{
    if (err && errlen) snprintf(err, errlen, "%s", m);
    return -1;
}

static int validate_tag(const cJSON *t, char *err, size_t errlen)
{
    const cJSON *kind = cJSON_GetObjectItemCaseSensitive(t, "kind");
    if (!cJSON_IsString(kind)) return bad(err, errlen, "kind missing");
    const char *k = cJSON_GetStringValue(kind);
    if (!strcmp(k, "holding") && !strcmp(cJSON_GetStringValue(kind), "holding")) { }
    mb_kind_t kind_t;
    if      (!strcmp(k, "holding")) kind_t = MB_KIND_HOLDING;
    else if (!strcmp(k, "input"))   kind_t = MB_KIND_INPUT;
    else if (!strcmp(k, "coil"))    kind_t = MB_KIND_COIL;
    else if (!strcmp(k, "discrete"))kind_t = MB_KIND_DISCRETE;
    else return bad(err, errlen, "modbus tag kind must be one of holding/input/coil/discrete");

    const cJSON *addr = cJSON_GetObjectItemCaseSensitive(t, "address");
    if (!cJSON_IsNumber(addr) || addr->valuedouble < 0) return bad(err, errlen, "modbus address must be a non-negative integer");

    mb_type_t type_t;
    const cJSON *type = cJSON_GetObjectItemCaseSensitive(t, "type");
    if (t == MB_KIND_COIL || t == MB_KIND_DISCRETE) {
        return bad(err, errlen, "coil/discrete require no integer type");
    }
    if (!cJSON_IsString(type)) return bad(err, errlen, "modbus tag type missing");
    type_t = type_of(cJSON_GetStringValue(type));
    /* holding/input accept any integer or float type. */

    const cJSON *wp = cJSON_GetObjectItemCaseSensitive(t, "writable");
    /* writable only valid for coil/holding; enforced by caller for holding. */

    const cJSON *enumv = cJSON_GetObjectItemCaseSensitive(t, "enum");
    if (cJSON_IsArray(enumv)) {
        if (type_t == MB_T_FLOAT32) return bad(err, errlen, "modbus enum only allowed on integer types");
    }
    (void)kind_t;
    (void)wp;
    return 0;
}