/*
 * history.c -- the historian, SQLite, same schema as daemon/historian.py
 * (CONTRACT 13.4). OWNER: A4.
 *
 * Port of daemon/historian.py. Timestamps are epoch seconds -> int64 ms as
 * (int64_t)(now * 1000), exactly like the Python `int(now * 1000)`. The
 * table, index and SQL are the Python's, so `historian.py export` reads the
 * database this writes.
 *
 * Clock: every rule runs on the `now` the caller passes (observe/tick/query),
 * never the wall clock, so tests are deterministic. Retention is enforced on
 * the first tick (the daemon ticks right after start) and then hourly;
 * commits are batched at most every 5 s and everything is flushed at
 * destroy.
 */
#include "history.h"

#include <math.h>
#include <pthread.h>
#include <sqlite3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PERIOD_MIN_MS 100
#define PERIOD_MAX_MS 3600000
#define RETENTION_MIN_D 1
#define RETENTION_MAX_D 365
#define RETENTION_DEFAULT_D 7
#define PERIOD_DEFAULT_MS 1000
#define COMMIT_EVERY_S 5.0
#define PRUNE_EVERY_S 3600.0
#define POINTS_MAX 200
#define SECONDS_MAX 604800
#define SECONDS_PER_DAY 86400

typedef struct {
    double period_ms;
    double deadband;
} tagcfg;

typedef struct {
    char *tag;
    int64_t last_ms;
    double last_val;
} lastrec;

typedef struct {
    char *tag;
    int64_t ts;
    double value;
} sample;

struct hwd_history {
    pthread_mutex_t lock;
    sqlite3 *conn;
    int retention_days;
    bool has_star;
    tagcfg star;
    char **named;
    tagcfg *named_cfg;
    size_t n_named;
    lastrec *last;
    size_t n_last, cap_last;
    sample *buf;
    size_t n_buf, cap_buf;
    bool ticked;               /* the first tick prunes and starts the commit clock */
    double last_commit;
    double last_prune;
};

static bool is_int_number(const cJSON *n)
{
    return cJSON_IsNumber(n) && isfinite(n->valuedouble) && n->valuedouble == floor(n->valuedouble);
}

/* One "tags" entry; mirrors historian._require_tag_cfg. */
static int parse_tagcfg(const char *tag, const cJSON *t, tagcfg *out, char *err, size_t errlen)
{
    if (!cJSON_IsObject(t)) {
        if (err) snprintf(err, errlen, "history: bad entry for tag '%s'", tag);
        return -1;
    }
    for (const cJSON *k = t->child; k; k = k->next) {
        if (strcmp(k->string, "period_ms") != 0 && strcmp(k->string, "deadband") != 0) {
            if (err) snprintf(err, errlen, "history: tag '%s': unknown key '%s'", tag, k->string);
            return -1;
        }
    }
    out->period_ms = PERIOD_DEFAULT_MS;
    out->deadband = 0.0;
    const cJSON *p = cJSON_GetObjectItemCaseSensitive(t, "period_ms");
    if (p) {
        if (!cJSON_IsNumber(p) || !(p->valuedouble >= PERIOD_MIN_MS && p->valuedouble <= PERIOD_MAX_MS)) {
            if (err) snprintf(err, errlen, "history: period_ms for '%s' must be 100..3600000", tag);
            return -1;
        }
        out->period_ms = p->valuedouble;
    }
    const cJSON *d = cJSON_GetObjectItemCaseSensitive(t, "deadband");
    if (d) {
        if (!cJSON_IsNumber(d) || !isfinite(d->valuedouble) || d->valuedouble < 0) {
            if (err) snprintf(err, errlen, "history: deadband for '%s' must be >= 0", tag);
            return -1;
        }
        out->deadband = d->valuedouble;
    }
    return 0;
}

int hwd_history_validate(const cJSON *hcfg, char *err, size_t errlen)
{
    if (err && errlen) err[0] = '\0';
    if (!err) errlen = 0;
    if (!cJSON_IsObject(hcfg)) {
        if (err) snprintf(err, errlen, "history: must be an object");
        return -1;
    }
    const cJSON *path = cJSON_GetObjectItemCaseSensitive(hcfg, "path");
    if (!cJSON_IsString(path) || !path->valuestring[0]) {
        if (err) snprintf(err, errlen, "history: path must be a non-empty string");
        return -1;
    }
    const cJSON *days = cJSON_GetObjectItemCaseSensitive(hcfg, "retention_days");
    if (days && (!is_int_number(days) || days->valuedouble < RETENTION_MIN_D ||
                 days->valuedouble > RETENTION_MAX_D)) {
        if (err) snprintf(err, errlen, "history: retention_days must be an integer 1..365");
        return -1;
    }
    const cJSON *tags = cJSON_GetObjectItemCaseSensitive(hcfg, "tags");
    if (tags && !cJSON_IsObject(tags)) {
        if (err) snprintf(err, errlen, "history: tags must be an object");
        return -1;
    }
    int n = 0;
    for (const cJSON *t = tags ? tags->child : NULL; t; t = t->next) {
        tagcfg tc;
        if (parse_tagcfg(t->string, t, &tc, err, errlen) != 0) return -1;
        n++;
    }
    if (n == 0) {
        if (err) snprintf(err, errlen, "history: tags must list at least one tag (or \"*\")");
        return -1;
    }
    return 0;
}

static int exec_sql(sqlite3 *db, const char *sql)
{
    char *msg = NULL;
    int rc = sqlite3_exec(db, sql, NULL, NULL, &msg);
    if (rc != SQLITE_OK) {
        HWD_ERROR("history: %s: %s", sql, msg ? msg : sqlite3_errstr(rc));
        sqlite3_free(msg);
    }
    return rc;
}

hwd_history *hwd_history_create(const cJSON *hcfg, char *err, size_t errlen)
{
    if (hwd_history_validate(hcfg, err, errlen) != 0) return NULL;
    hwd_history *h = calloc(1, sizeof *h);
    if (!h) {
        if (err) snprintf(err, errlen, "history: out of memory");
        return NULL;
    }
    pthread_mutex_init(&h->lock, NULL);
    const cJSON *days = cJSON_GetObjectItemCaseSensitive(hcfg, "retention_days");
    h->retention_days = days ? (int)days->valuedouble : RETENTION_DEFAULT_D;
    const cJSON *tags = cJSON_GetObjectItemCaseSensitive(hcfg, "tags");
    size_t n = (size_t)cJSON_GetArraySize(tags);
    h->named = calloc(n ? n : 1, sizeof *h->named);
    h->named_cfg = calloc(n ? n : 1, sizeof *h->named_cfg);
    if (!h->named || !h->named_cfg) {
        if (err) snprintf(err, errlen, "history: out of memory");
        hwd_history_destroy(h);
        return NULL;
    }
    for (const cJSON *t = tags->child; t; t = t->next) {
        tagcfg tc;
        parse_tagcfg(t->string, t, &tc, NULL, 0);
        if (strcmp(t->string, "*") == 0) {
            h->has_star = true;
            h->star = tc;
        } else {
            h->named[h->n_named] = strdup(t->string);
            h->named_cfg[h->n_named] = tc;
            h->n_named++;
        }
    }
    const char *path = cJSON_GetObjectItemCaseSensitive(hcfg, "path")->valuestring;
    int rc = sqlite3_open(path, &h->conn);
    if (rc != SQLITE_OK) {
        if (err)
            snprintf(err, errlen, "history: cannot open %s: %s", path,
                     h->conn ? sqlite3_errmsg(h->conn) : sqlite3_errstr(rc));
        hwd_history_destroy(h);
        return NULL;
    }
    sqlite3_busy_timeout(h->conn, 2000);
    if (exec_sql(h->conn, "CREATE TABLE IF NOT EXISTS samples "
                          "(tag TEXT NOT NULL, ts INTEGER NOT NULL, value REAL NOT NULL)") != SQLITE_OK ||
        exec_sql(h->conn, "CREATE INDEX IF NOT EXISTS idx_sample_ts ON samples (tag, ts)") != SQLITE_OK) {
        if (err) snprintf(err, errlen, "history: cannot create the samples table in %s", path);
        hwd_history_destroy(h);
        return NULL;
    }
    return h;
}

/* ---- buffering and commits ------------------------------------------- */

static int flush_locked(hwd_history *h)
{
    if (!h->n_buf || !h->conn) return 0;
    if (exec_sql(h->conn, "BEGIN") != SQLITE_OK) return 0;
    sqlite3_stmt *st = NULL;
    if (sqlite3_prepare_v2(h->conn, "INSERT INTO samples (tag, ts, value) VALUES (?, ?, ?)", -1, &st, NULL)
        != SQLITE_OK) {
        HWD_ERROR("history: insert: %s", sqlite3_errmsg(h->conn));
        exec_sql(h->conn, "ROLLBACK");
        return 0;
    }
    for (size_t i = 0; i < h->n_buf; i++) {
        sqlite3_bind_text(st, 1, h->buf[i].tag, -1, SQLITE_STATIC);
        sqlite3_bind_int64(st, 2, (sqlite3_int64)h->buf[i].ts);
        sqlite3_bind_double(st, 3, h->buf[i].value);
        if (sqlite3_step(st) != SQLITE_DONE) HWD_ERROR("history: insert: %s", sqlite3_errmsg(h->conn));
        sqlite3_reset(st);
    }
    sqlite3_finalize(st);
    if (exec_sql(h->conn, "COMMIT") != SQLITE_OK) {
        exec_sql(h->conn, "ROLLBACK");
        return 0;     /* keep the buffer: retried at the next commit */
    }
    int n = (int)h->n_buf;
    for (size_t i = 0; i < h->n_buf; i++) free(h->buf[i].tag);
    h->n_buf = 0;
    return n;
}

static void prune_locked(hwd_history *h, double now)
{
    if (!h->conn) return;
    sqlite3_int64 cutoff = (sqlite3_int64)((now - (double)h->retention_days * SECONDS_PER_DAY) * 1000.0);
    sqlite3_stmt *st = NULL;
    if (sqlite3_prepare_v2(h->conn, "DELETE FROM samples WHERE ts < ?", -1, &st, NULL) != SQLITE_OK) {
        HWD_ERROR("history: prune: %s", sqlite3_errmsg(h->conn));
        return;
    }
    sqlite3_bind_int64(st, 1, cutoff);
    if (sqlite3_step(st) != SQLITE_DONE) HWD_ERROR("history: prune: %s", sqlite3_errmsg(h->conn));
    else if (sqlite3_changes(h->conn) > 0) HWD_INFO("history: pruned %d sample(s)", sqlite3_changes(h->conn));
    sqlite3_finalize(st);
}

void hwd_history_destroy(hwd_history *h)
{
    if (!h) return;
    pthread_mutex_lock(&h->lock);
    flush_locked(h);
    if (h->conn) sqlite3_close(h->conn);
    h->conn = NULL;
    for (size_t i = 0; i < h->n_buf; i++) free(h->buf[i].tag);
    free(h->buf);
    for (size_t i = 0; i < h->n_last; i++) free(h->last[i].tag);
    free(h->last);
    for (size_t i = 0; i < h->n_named; i++) free(h->named[i]);
    free(h->named);
    free(h->named_cfg);
    pthread_mutex_unlock(&h->lock);
    pthread_mutex_destroy(&h->lock);
    free(h);
}

/* ---- logging rules ----------------------------------------------------- */

static const tagcfg *cfg_for(hwd_history *h, const char *tag)
{
    for (size_t i = 0; i < h->n_named; i++)
        if (strcmp(h->named[i], tag) == 0) return &h->named_cfg[i];
    return h->has_star ? &h->star : NULL;
}

bool hwd_history_logs(hwd_history *h, const char *tag)
{
    if (!h || !tag) return false;
    pthread_mutex_lock(&h->lock);
    bool r = cfg_for(h, tag) != NULL;
    pthread_mutex_unlock(&h->lock);
    return r;
}

static bool buffer_append(hwd_history *h, const char *tag, int64_t ts, double value)
{
    if (h->n_buf == h->cap_buf) {
        size_t cap = h->cap_buf ? h->cap_buf * 2 : 64;
        sample *nb = realloc(h->buf, cap * sizeof *nb);
        if (!nb) return false;
        h->buf = nb;
        h->cap_buf = cap;
    }
    char *t = strdup(tag);
    if (!t) return false;
    h->buf[h->n_buf++] = (sample){t, ts, value};
    return true;
}

bool hwd_history_observe(hwd_history *h, const char *tag, const hwd_value *v, double now)
{
    if (!h || !tag || !v) return false;
    double value;
    if (v->kind == HWD_INT) value = (double)v->u.i;
    else if (v->kind == HWD_FLOAT) value = v->u.f;
    else return false;                    /* null, bool, string: not logged */
    if (!isfinite(value)) return false;
    bool kept = false;
    pthread_mutex_lock(&h->lock);
    const tagcfg *cfg = cfg_for(h, tag);
    if (!cfg) goto out;
    int64_t ts_ms = (int64_t)(now * 1000.0);
    lastrec *last = NULL;
    for (size_t i = 0; i < h->n_last; i++)
        if (strcmp(h->last[i].tag, tag) == 0) { last = &h->last[i]; break; }
    if (!last) {                          /* a tag's first value is always stored */
        if (h->n_last == h->cap_last) {
            size_t cap = h->cap_last ? h->cap_last * 2 : 16;
            lastrec *nl = realloc(h->last, cap * sizeof *nl);
            if (!nl) goto out;
            h->last = nl;
            h->cap_last = cap;
        }
        char *t = strdup(tag);
        if (!t) goto out;
        if (!buffer_append(h, tag, ts_ms, value)) { free(t); goto out; }
        h->last[h->n_last++] = (lastrec){t, ts_ms, value};
        kept = true;
        goto out;
    }
    double elapsed_ms = (double)(ts_ms - last->last_ms);
    bool moved = fabs(value - last->last_val) > cfg->deadband;
    if (elapsed_ms >= cfg->period_ms && (moved || elapsed_ms >= 60.0 * cfg->period_ms)) {
        if (!buffer_append(h, tag, ts_ms, value)) goto out;
        last->last_ms = ts_ms;
        last->last_val = value;
        kept = true;
    }
out:
    pthread_mutex_unlock(&h->lock);
    return kept;
}

void hwd_history_tick(hwd_history *h, double now)
{
    if (!h) return;
    pthread_mutex_lock(&h->lock);
    if (!h->ticked) {
        /* Retention at start; the commit clock starts now. */
        h->ticked = true;
        prune_locked(h, now);
        h->last_prune = now;
        h->last_commit = now;
    } else {
        if (now - h->last_prune >= PRUNE_EVERY_S) {
            prune_locked(h, now);
            h->last_prune = now;
        }
        if (now - h->last_commit >= COMMIT_EVERY_S) {
            flush_locked(h);
            h->last_commit = now;
        }
    }
    pthread_mutex_unlock(&h->lock);
}

/* ---- query ------------------------------------------------------------- */

typedef struct {
    int64_t ts;
    double value;
} row;

static bool rows_push(row **rows, size_t *n, size_t *cap, int64_t ts, double value)
{
    if (*n == *cap) {
        size_t c = *cap ? *cap * 2 : 256;
        row *nr = realloc(*rows, c * sizeof *nr);
        if (!nr) return false;
        *rows = nr;
        *cap = c;
    }
    (*rows)[(*n)++] = (row){ts, value};
    return true;
}

static cJSON *sample_json(int64_t ts, double value)
{
    cJSON *pair = cJSON_CreateArray();
    cJSON_AddItemToArray(pair, cJSON_CreateNumber((double)ts));
    cJSON_AddItemToArray(pair, cJSON_CreateNumber(value));
    return pair;
}

/* NULL when seconds/points are out of range (the Python raises ValueError;
 * the daemon answers bad_value). */
cJSON *hwd_history_query(hwd_history *h, const char *tag, int seconds, int points, double now)
{
    if (!h || !tag) return NULL;
    if (seconds < 1 || seconds > SECONDS_MAX || points < 1 || points > POINTS_MAX) return NULL;
    int64_t now_ms = (int64_t)(now * 1000.0);
    int64_t lo_ms = now_ms - (int64_t)seconds * 1000;
    row *rows = NULL;
    size_t n = 0, cap = 0;

    pthread_mutex_lock(&h->lock);
    sqlite3_stmt *st = NULL;
    if (h->conn &&
        sqlite3_prepare_v2(h->conn,
                           "SELECT ts, value FROM samples WHERE tag = ? AND ts > ? AND ts <= ? ORDER BY ts ASC",
                           -1, &st, NULL) == SQLITE_OK) {
        sqlite3_bind_text(st, 1, tag, -1, SQLITE_TRANSIENT);
        sqlite3_bind_int64(st, 2, (sqlite3_int64)lo_ms);
        sqlite3_bind_int64(st, 3, (sqlite3_int64)now_ms);
        while (sqlite3_step(st) == SQLITE_ROW)
            rows_push(&rows, &n, &cap, (int64_t)sqlite3_column_int64(st, 0), sqlite3_column_double(st, 1));
        sqlite3_finalize(st);
    } else if (h->conn) {
        HWD_ERROR("history: query: %s", sqlite3_errmsg(h->conn));
    }
    /* Merge buffered samples over what was committed. */
    for (size_t i = 0; i < h->n_buf; i++)
        if (strcmp(h->buf[i].tag, tag) == 0 && h->buf[i].ts > lo_ms && h->buf[i].ts <= now_ms)
            rows_push(&rows, &n, &cap, h->buf[i].ts, h->buf[i].value);
    pthread_mutex_unlock(&h->lock);

    /* Stable sort by ts (Python's list.sort is stable); the input is two
     * sorted runs, so insertion sort is cheap. */
    for (size_t i = 1; i < n; i++) {
        row r = rows[i];
        size_t j = i;
        while (j > 0 && rows[j - 1].ts > r.ts) { rows[j] = rows[j - 1]; j--; }
        rows[j] = r;
    }

    cJSON *out = cJSON_CreateArray();
    if (n <= (size_t)points) {
        for (size_t i = 0; i < n; i++) cJSON_AddItemToArray(out, sample_json(rows[i].ts, rows[i].value));
        free(rows);
        return out;
    }
    /* Partition (lo_ms, now_ms] into `points` equal (lo, hi] buckets; keep
     * each non-empty bucket's last sample. */
    double span = (double)(now_ms - lo_ms);
    long *last = malloc((size_t)points * sizeof *last);
    if (!last) { free(rows); return out; }
    for (int i = 0; i < points; i++) last[i] = -1;
    for (size_t i = 0; i < n; i++) {
        long idx = span > 0 ? (long)ceil((double)(rows[i].ts - lo_ms) * points / span) - 1 : 0;
        if (idx < 0) idx = 0;
        if (idx >= points) idx = points - 1;
        last[idx] = (long)i;
    }
    for (int i = 0; i < points; i++)
        if (last[i] >= 0) cJSON_AddItemToArray(out, sample_json(rows[last[i]].ts, rows[last[i]].value));
    free(last);
    free(rows);
    return out;
}
