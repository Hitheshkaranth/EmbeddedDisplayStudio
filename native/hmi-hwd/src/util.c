/*
 * util.c -- shared helpers declared in hwd.h and backend.h: error names,
 * tag values, the tag-name rule, clocks, logging and the simulation hooks.
 * Written with the skeleton; workers use it and do not change it.
 */
#define _GNU_SOURCE
#include "hwd.h"
#include "backend.h"

#include <ctype.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

int hwd_log_level = 1;

static const char *const ERR_NAMES[] = {
    NULL, "bad_json", "not_an_object", "too_large", "unknown_cmd", "unknown_tag",
    "not_writable", "bad_value", "hw_error", "rate_limited", "no_history",
};

const char *hwd_err_name(hwd_err err)
{
    if ((int)err < 0 || (size_t)err >= sizeof ERR_NAMES / sizeof ERR_NAMES[0])
        return "hw_error";
    return ERR_NAMES[err];
}

hwd_value hwd_null(void) { hwd_value v = {HWD_NULL, {0}}; return v; }
hwd_value hwd_bool(bool b) { hwd_value v = {HWD_BOOL, {0}}; v.u.b = b; return v; }
hwd_value hwd_int(int64_t i) { hwd_value v = {HWD_INT, {0}}; v.u.i = i; return v; }
hwd_value hwd_float(double f)
{
    /* JSON has no NaN/Inf: a non-finite reading is a failed one. */
    if (!isfinite(f)) return hwd_null();
    hwd_value v = {HWD_FLOAT, {0}};
    v.u.f = f;
    return v;
}
hwd_value hwd_str(const char *s)
{
    hwd_value v = {HWD_STR, {0}};
    v.u.s = strdup(s ? s : "");
    if (!v.u.s) return hwd_null();
    return v;
}

void hwd_value_clear(hwd_value *v)
{
    if (!v) return;
    if (v->kind == HWD_STR) free(v->u.s);
    *v = hwd_null();
}

hwd_value hwd_value_copy(const hwd_value *v)
{
    if (!v) return hwd_null();
    if (v->kind == HWD_STR) return hwd_str(v->u.s);
    return *v;
}

bool hwd_value_equal(const hwd_value *a, const hwd_value *b)
{
    if (a->kind != b->kind) return false;
    switch (a->kind) {
    case HWD_NULL: return true;
    case HWD_BOOL: return a->u.b == b->u.b;
    case HWD_INT: return a->u.i == b->u.i;
    case HWD_FLOAT: return a->u.f == b->u.f;
    case HWD_STR: return strcmp(a->u.s, b->u.s) == 0;
    }
    return false;
}

/* ^[a-z][a-z0-9]*(\.[a-z0-9_]+)+$ */
bool hwd_tag_valid(const char *tag)
{
    if (!tag || !*tag || strlen(tag) > HWD_MAX_TAG) return false;
    const char *p = tag;
    if (!(*p >= 'a' && *p <= 'z')) return false;
    p++;
    while (*p && *p != '.') {
        if (!((*p >= 'a' && *p <= 'z') || (*p >= '0' && *p <= '9'))) return false;
        p++;
    }
    int segments = 0;
    while (*p == '.') {
        p++;
        int n = 0;
        while (*p && *p != '.') {
            if (!((*p >= 'a' && *p <= 'z') || (*p >= '0' && *p <= '9') || *p == '_')) return false;
            p++;
            n++;
        }
        if (n == 0) return false;
        segments++;
    }
    return *p == '\0' && segments >= 1;
}

double hwd_now(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (double)ts.tv_sec + ts.tv_nsec / 1e9;
}

double hwd_mono(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + ts.tv_nsec / 1e9;
}

void hwd_log(int level, const char *fmt, ...)
{
    static const char *const NAMES[] = {"DEBUG", "INFO", "WARNING", "ERROR"};
    if (level < hwd_log_level) return;
    if (level < 0) level = 0;
    if (level > 3) level = 3;
    char stamp[32];
    time_t t = time(NULL);
    struct tm tm;
    localtime_r(&t, &tm);
    strftime(stamp, sizeof stamp, "%Y-%m-%d %H:%M:%S", &tm);
    fprintf(stderr, "%s hmi-hwd %s ", stamp, NAMES[level]);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
}

/* HWD_SIM_FAIL="tag1,tag2": parsed once, compared by whole name. */
bool hwd_sim_fails(const char *tag)
{
    const char *env = getenv("HWD_SIM_FAIL");
    if (!env || !*env || !tag) return false;
    size_t n = strlen(tag);
    const char *p = env;
    while (*p) {
        while (*p == ',' || isspace((unsigned char)*p)) p++;
        const char *start = p;
        while (*p && *p != ',' && !isspace((unsigned char)*p)) p++;
        if ((size_t)(p - start) == n && strncmp(start, tag, n) == 0) return true;
    }
    return false;
}

/* A triangle between lo and hi, one full sweep up and down per period. */
double hwd_sim_ramp(double now, double lo, double hi, double period_s)
{
    if (period_s <= 0) period_s = 10.0;
    double phase = fmod(now, period_s) / period_s;   /* 0..1 */
    double k = phase < 0.5 ? phase * 2.0 : (1.0 - phase) * 2.0;
    return lo + (hi - lo) * k;
}
