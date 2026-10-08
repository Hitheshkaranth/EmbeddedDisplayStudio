/*
 * can.c -- SocketCAN signals and frames (CONTRACT 14.3, "can").
 * OWNER: A2. STUB written with the skeleton: every function compiles
 * and fails safe; the owner replaces the bodies (not the signatures).
 */
#include "backend.h"

static int v_validate(const hwd_config *cfg, char *err, size_t errlen)
{ (void)cfg; (void)err; (void)errlen; return 0; }
static void *v_create(const hwd_config *cfg, hwd_tagstore *store, const hwd_backend_opts *opts,
                      char *err, size_t errlen)
{ (void)cfg; (void)store; (void)opts; if (errlen) err[0] = '\0'; return NULL; }
static bool v_owns(void *self, const char *tag) { (void)self; (void)tag; return false; }
static hwd_err v_write(void *self, const char *tag, const hwd_value *v)
{ (void)self; (void)tag; (void)v; return HWD_ERR_NOT_WRITABLE; }
static hwd_err v_command(void *self, const char *cmd, const cJSON *msg, cJSON *reply)
{ (void)self; (void)cmd; (void)msg; (void)reply; return HWD_ERR_UNKNOWN_CMD; }
static uint64_t v_errors(void *self) { (void)self; return 0; }
static void v_destroy(void *self) { (void)self; }

const hwd_backend_ops hwd_backend_can = {
    "can", v_validate, v_create, NULL, NULL, v_owns, v_write, v_command, NULL, v_errors, v_destroy,
};

/* ---- periph.h CAN codec (A2) ------------------------------------------ */
#include "periph.h"

#include <ctype.h>
#include <stdlib.h>

/* A signal is a run of `length` bits starting at `start_bit` (inclusive),
 * counting down toward lower bit numbers. `start_bit` is the last bit in the
 * run; the signal occupies [start_bit - length + 1, start_bit]. */
uint64_t can_get_bits(const uint8_t data[8], int start_bit, int length, bool big_endian)
{
    if (length <= 0) return 0;
    if (!big_endian) {
        uint64_t raw = 0;
        int end = start_bit - length + 1;
        for (int b = start_bit; b >= end; b--)
            raw = (raw << 1) | ((data[b >> 3] >> (b & 7)) & 1);
        return raw;
    }
    /* Motorola: a bit at DBC number `n` (sawtooth) is (n & 7) from the LSB of
     * (7 - (n >> 3)). The MSB of the signal is at DBC number start_bit. */
    uint64_t raw = 0;
    for (int i = 0; i < length; i++) {
        int n = start_bit - i;
        int byte_index = 7 - (n >> 3);
        int bit = n & 7;
        raw = (raw << 1) | ((data[byte_index] >> bit) & 1);
    }
    return raw;
}

void can_set_bits(uint8_t data[8], int start_bit, int length, bool big_endian, uint64_t raw)
{
    if (length <= 0) return;
    if (!big_endian) {
        int end = start_bit - length + 1;
        for (int b = start_bit; b >= end; b--)
            data[b >> 3] = (uint8_t)((data[b >> 3] & ~(1 << (b & 7))) |
                                     ((uint64_t)(raw & 1) << (b & 7)));
        return;
    }
    for (int i = 0; i < length; i++) {
        int n = start_bit - i;
        int byte_index = 7 - (n >> 3);
        int bit = n & 7;
        data[byte_index] = (uint8_t)((data[byte_index] & ~(1 << bit)) |
                                     ((uint64_t)(raw & 1) << bit));
        raw >>= 1;
    }
}

int64_t can_sign_extend(uint64_t raw, int length)
{
    if (length < 0) length = 0;
    if (length >= 64) return (int64_t)raw;
    if (length <= 0) return 0;
    uint64_t mask = (length == 64) ? ~0ULL : ((uint64_t)1 << length) - 1;
    uint64_t v = raw & mask;
    if (v & ((uint64_t)1 << (length - 1)))
        return (int64_t)(v | (~mask));
    return (int64_t)v;
}

bool can_parse_id(const char *text, bool extended, uint32_t *id)
{
    if (!text || !id) return false;
    char *end = NULL;
    unsigned long v = strtoul(text, &end, 0);
    if (end == text || *end != '\0') return false;
    if (!extended && v > 0x7FF) return false;
    if (extended && v > 0x1FFFFFFF) return false;
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
    int n = 0;
    while (*text) {
        while (*text == ' ') text++;
        if (*text == '\0') return n;
        int hi = hex_val(*text);
        if (hi < 0 || text[1] == '\0' || text[1] == ' ') return -1;
        int lo = hex_val(text[1]);
        if (lo < 0) return -1;
        if (n >= 8) return -1;
        out[n++] = (uint8_t)((hi << 4) | lo);
        text += 2;
    }
    return n;
}
