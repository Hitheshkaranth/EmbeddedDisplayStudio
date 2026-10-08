/*
 * hwd.h -- shared definitions for hmi-hwd, the C hardware daemon (Layer 1).
 *
 * hmi-hwd is the C port of daemon/hmi_hwd.py. It owns GPIO, ADC, UART and
 * Modbus TCP and speaks the CONTRACT section 2 wire protocol (JSON over UDP,
 * loopback) to hmi-ui. daemon/hmi_hwd.py stays the reference implementation:
 * where this file and the Python disagree, the Python and docs/CONTRACT.md
 * win, and the acceptance tests (tests/test_daemon_protocol.py et al. run
 * with HMI_HWD_CMD=native/hmi-hwd/out/hmi-hwd) decide.
 *
 * FROZEN: workers implement the .c files; they do not change this header.
 */
#ifndef HWD_H
#define HWD_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define HWD_VERSION "0.2.0"

/* CONTRACT 2: one JSON object per datagram, at most this many bytes. */
#define HWD_MAX_DGRAM 8192
/* CONTRACT 2.2: an `id` is opaque, at most 64 characters. */
#define HWD_MAX_ID 64
/* CONTRACT 2.5: ^[a-z][a-z0-9]*(\.[a-z0-9_]+)+$ */
#define HWD_MAX_TAG 96
#define HWD_MAX_TAGS 512
#define HWD_MAX_SUBSCRIBERS 32
/* CONTRACT 2.2: pulse ms range. */
#define HWD_PULSE_MIN_MS 1
#define HWD_PULSE_MAX_MS 10000
/* Discovery (Studio "Find panels"): a broadcast {"cmd":"discover"} on this
 * UDP port is answered with a hello (see daemon.h). */
#define HWD_DISCOVERY_PORT 47800

/* CONTRACT 2.3: the closed set of ack error codes, in this order. */
typedef enum {
    HWD_OK = 0,
    HWD_ERR_BAD_JSON,
    HWD_ERR_NOT_AN_OBJECT,
    HWD_ERR_TOO_LARGE,
    HWD_ERR_UNKNOWN_CMD,
    HWD_ERR_UNKNOWN_TAG,
    HWD_ERR_NOT_WRITABLE,
    HWD_ERR_BAD_VALUE,
    HWD_ERR_HW_ERROR,
    HWD_ERR_RATE_LIMITED,
    HWD_ERR_NO_HISTORY,
} hwd_err;

/* "bad_json", "not_an_object", ... (NULL for HWD_OK). */
const char *hwd_err_name(hwd_err err);

/* A tag's value as published: CONTRACT 2.4 says a failed read is null,
 * never omitted. Strings are for enum-mapped Modbus registers and uart.rx. */
typedef enum { HWD_NULL = 0, HWD_BOOL, HWD_INT, HWD_FLOAT, HWD_STR } hwd_kind;

typedef struct {
    hwd_kind kind;
    union {
        bool b;
        int64_t i;
        double f;
        char *s;      /* owned by the value; hwd_value_clear frees it */
    } u;
} hwd_value;

hwd_value hwd_null(void);
hwd_value hwd_bool(bool b);
hwd_value hwd_int(int64_t i);
hwd_value hwd_float(double f);
hwd_value hwd_str(const char *s);          /* copies s */
void hwd_value_clear(hwd_value *v);
hwd_value hwd_value_copy(const hwd_value *v);
bool hwd_value_equal(const hwd_value *a, const hwd_value *b);

/* CONTRACT 2.5 tag-name rule. */
bool hwd_tag_valid(const char *tag);

/* Wall clock (CLOCK_REALTIME) and monotonic seconds. */
double hwd_now(void);
double hwd_mono(void);

/* Logging to stderr: "LEVEL message". hwd_log_level is set from
 * --log-level (0 DEBUG, 1 INFO, 2 WARNING, 3 ERROR). */
extern int hwd_log_level;
void hwd_log(int level, const char *fmt, ...);
#define HWD_DEBUG(...) hwd_log(0, __VA_ARGS__)
#define HWD_INFO(...) hwd_log(1, __VA_ARGS__)
#define HWD_WARN(...) hwd_log(2, __VA_ARGS__)
#define HWD_ERROR(...) hwd_log(3, __VA_ARGS__)

#endif
