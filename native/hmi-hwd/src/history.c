/*
 * history.c -- the historian, SQLite, same schema as daemon/historian.py
 * (CONTRACT 13.4). OWNER: A4.
 *
 * Port of daemon/historian.py. Timestamps are epoch seconds -> int64 ms as
 * (int64_t)(now * 1000), exactly like the Python `int(now * 1000)`.
 */
#define _GNU_SOURCE
#include "history.h"

#include <cJSON.h>
#include <math.h>
#include <sqlite3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PERIOD_MIN_MS 100
#define PERIOD_MAX_MS 3600000
#define RETENTION_MIN_D 1
#define RETENTION_MAX_D 365
#define COMMIT_EVERY_S 5.0
#define PRUNE_EVERY_S 3600.0
#define POINTS_MAX 200
#define SECONDS_MAX 604800
#define SECONDS_PER_DAY 86400

typedef struct {
    int period_ms;
    double deadband;
} tagcfg;

struct hwd_history {
    sqlite3 *conn;
    int retention_days;
    int has_star;
    tagcfg star_cfg;
    char **named;
    tagcfg *named_cfg;
    size_t n_named;
    char **last_tag;
    tagcfg *last_cfg;
    sqlite3_int64 *last_ms;
    double *last_val;
    size_t n_last;
    char **buf_tag;
    sqlite3_int64 *buf_ts;
    double *buf_val;
    size_t n_buf;
    double last_commit;
    double last_prune;
};