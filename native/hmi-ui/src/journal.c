// journal.c -- see journal.h (CONTRACT 13.3).
#include "journal.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <stdint.h>
#ifndef _WIN32
#include <unistd.h>
#endif

#include "cJSON.h"
#include "compat.h"
#include "log.h"

typedef struct hmi_journal {
    FILE *f;
    char path[HMI_JOURNAL_PATH_MAX];
    size_t max_bytes;
    int64_t last_sync_ms;   // wall-clock ms of the last fsync; -1 = unsynced
} journal_mem;

// Copy src to dst as a JSON string literal (including surrounding quotes),
// escaping the characters a JSON string must quote.
static void json_str(char *dst, size_t dstsz, const char *src)
{
    size_t j = 0;
    dst[j++] = '"';
    for (size_t i = 0; src[i] && j + 4 < dstsz; ++i) {
        unsigned char c = (unsigned char)src[i];
        switch (c) {
        case '"':  dst[j++] = '\\', dst[j++] = '"'; break;
        case '\\': dst[j++] = '\\', dst[j++] = '\\'; break;
        case '\n': dst[j++] = '\\', dst[j++] = 'n'; break;
        case '\r': dst[j++] = '\\', dst[j++] = 'r'; break;
        case '\t': dst[j++] = '\\', dst[j++] = 't'; break;
        default:
            if (c < 0x20) { snprintf(dst + j, dstsz - j, "\\u%04x", c); j += 6; }
            else dst[j++] = (char)c;
        }
    }
    if (j < dstsz) dst[j++] = '"';
    if (j < dstsz) dst[j] = '\0';
}

// Serialize one hmi_value_t to a compact JSON fragment ("9.5", "\"OPEN\"",
// "true", "null"). A list/unknown renders as the JSON null.
static void value_to_json(char *out, size_t outsz, const hmi_value_t *v)
{
    if (!v || v->kind == HMI_V_NULL) { snprintf(out, outsz, "null"); return; }
    switch (v->kind) {
    case HMI_V_NUM:  snprintf(out, outsz, "%g", v->n); break;
    case HMI_V_BOOL: snprintf(out, outsz, "%s", v->b ? "true" : "false"); break;
    case HMI_V_STR:  json_str(out, outsz, v->s ? v->s : ""); break;
    default:         snprintf(out, outsz, "null"); break;
    }
}

// Build one JSON object line into `out`.
static void format_line(char *out, size_t outsz, int64_t ts_ms, const char *event,
                        const char *tag, const char *label, const char *severity,
                        int priority, const hmi_value_t *value)
{
    char ev[64], tagbuf[HMI_JOURNAL_STR_MAX], labelbuf[HMI_JOURNAL_STR_MAX],
         sevbuf[HMI_JOURNAL_STR_MAX], val[HMI_JOURNAL_VALUE_MAX];
    json_str(ev, sizeof ev, event);
    json_str(tagbuf, sizeof tagbuf, tag);
    json_str(labelbuf, sizeof labelbuf, label);
    json_str(sevbuf, sizeof sevbuf, severity);
    value_to_json(val, sizeof val, value);
    snprintf(out, outsz, "{\"ts\":%lld,\"event\":%s,\"tag\":%s,\"label\":%s,\"severity\":%s,\"priority\":%d,\"value\":%s}\n",
             (long long)ts_ms, ev, tagbuf, labelbuf, sevbuf, priority, val);
}

static int64_t wall_ms(void)
{
    time_t t = time(NULL);
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (int64_t)t * 1000LL + ts.tv_nsec / 1000000;
}

// fsync at most once a second.
static void sync_if_due(journal_mem *m)
{
    int64_t now = wall_ms();
    if (now - m->last_sync_ms >= 1000) {
        if (fflush(m->f) != 0) {
            hmi_log(HMI_LOG_WARNING, "journal: flush failed");
            return;
        }
        if (fsync(fileno(m->f)) != 0)
            hmi_log(HMI_LOG_WARNING, "journal: fsync failed");
        m->last_sync_ms = now;
    }
}

// When the current file passes max_bytes, rename it to PATH.1 (replacing any
// stale PATH.1) and reopen PATH. A single append past the limit starts a new
// PATH without producing a (near-)empty PATH.1.
static void rotate_if_needed(journal_mem *m)
{
    fseek(m->f, 0, SEEK_END);
    long sz = ftell(m->f);
    fseek(m->f, 0, SEEK_SET);
    if ((size_t)sz == 0) return;
    if ((size_t)sz <= m->max_bytes) return;
    fclose(m->f);
    char old[HMI_JOURNAL_PATH_MAX + 32];
    snprintf(old, sizeof old, "%s.1", m->path);
    remove(old);
    if (rename(m->path, old) != 0) {
        hmi_log(HMI_LOG_WARNING, "journal: rotation rename failed");
        return;
    }
    m->f = fopen(m->path, "a");
    m->last_sync_ms = -1;
}

hmi_journal_t *hmi_journal_open(const char *path, size_t max_bytes)
{
    if (!path || !*path) return NULL;
    FILE *f = fopen(path, "a");
    if (!f) {
        hmi_log(HMI_LOG_WARNING, "journal: cannot open '%s'", path);
        return NULL;
    }
    journal_mem *j = malloc(sizeof *j);
    if (!j) { fclose(f); return NULL; }
    j->f = f;
    snprintf(j->path, sizeof j->path, "%s", path);
    j->max_bytes = max_bytes ? max_bytes : HMI_JOURNAL_MAX_BYTES;
    j->last_sync_ms = -1;
    return (hmi_journal_t *)j;
}

void hmi_journal_close(hmi_journal_t *j)
{
    if (!j) return;
    journal_mem *m = (journal_mem *)j;
    if (m->f) fclose(m->f);
    free(m);
}

bool hmi_journal_append(hmi_journal_t *j, int64_t ts_ms, const char *event, const char *tag,
                        const char *label, const char *severity, int priority,
                        const hmi_value_t *value)
{
    if (!j) return false;
    journal_mem *m = (journal_mem *)j;

    char line[HMI_JOURNAL_LINE_MAX];
    format_line(line, sizeof line, ts_ms, event, tag, label, severity, priority, value);

    sync_if_due(m);
    rotate_if_needed(m);
    if (fputs(line, m->f) == EOF) {
        hmi_log(HMI_LOG_WARNING, "journal: write error");
        return false;
    }
    if (fflush(m->f) != 0) {
        hmi_log(HMI_LOG_WARNING, "journal: flush error");
        return false;
    }
    return true;
}

// Parse one line into a 9-field history row (CONTRACT 13.3); false to skip.
static bool parse_to_row(const char *line, hmi_value_t *row)
{
    cJSON *o = cJSON_Parse(line);
    if (!cJSON_IsObject(o)) { cJSON_Delete(o); return false; }

    const cJSON *j;
    const char *label = NULL, *severity = NULL, *event = NULL, *tag = NULL;
    cJSON *val = NULL;
    int priority = 3;
    if ((j = cJSON_GetObjectItemCaseSensitive(o, "tag"))) tag = cJSON_GetStringValue(j);
    if ((j = cJSON_GetObjectItemCaseSensitive(o, "label"))) label = cJSON_GetStringValue(j);
    if ((j = cJSON_GetObjectItemCaseSensitive(o, "severity"))) severity = cJSON_GetStringValue(j);
    if ((j = cJSON_GetObjectItemCaseSensitive(o, "event"))) event = cJSON_GetStringValue(j);
    if ((j = cJSON_GetObjectItemCaseSensitive(o, "value"))) val = j;
    if ((j = cJSON_GetObjectItemCaseSensitive(o, "priority"))) priority = j->valueint;

    fprintf(stderr, "DBG parse: val=%p tag=%s valnum=%g\n", (void*)val, tag ? tag : "-", val ? cJSON_GetNumberValue(val) : -1);

    char tsbuf[24]; tsbuf[0] = '\0';
    if ((j = cJSON_GetObjectItemCaseSensitive(o, "ts"))) {
        time_t t = (time_t)(j->valuedouble / 1000);
        struct tm tm;
        hmi_localtime(t, &tm);
        strftime(tsbuf, sizeof tsbuf, "%Y-%m-%dT%H:%M:%S", &tm);
    }

    row->kind = HMI_V_LIST;
    row->count = 9;
    row->items = calloc(9, sizeof *row->items);
    if (!row->items) { cJSON_Delete(o); return false; }
    row->items[0] = hmi_value_str(tag ? tag : "");
    row->items[1] = hmi_value_str(label ? label : "");
    row->items[2] = hmi_value_str(severity ? severity : "");
    row->items[3] = val ? hmi_value_from_json(val) : hmi_value_null();
    if (row->items[3].kind == HMI_V_NULL && val && cJSON_IsNumber(val))
        row->items[3] = hmi_value_num(val->valuedouble);
    if (row->items[3].kind == HMI_V_NULL && val && cJSON_IsNumber(val))
        row->items[3] = hmi_value_num(val->valuedouble);
    row->items[4] = hmi_value_str(event ? event : "");
    row->items[5] = hmi_value_str(tsbuf);
    row->items[6] = hmi_value_bool(true);
    row->items[7] = hmi_value_num((double)priority);
    row->items[8] = hmi_value_str("cleared");

    cJSON_Delete(o);
    fprintf(stderr, "DBG parse done: items3 kind=%d n=%g\n", row->items[3].kind, (double)row->items[3].n);
    return true;
}

// Read a file's newest `n` lines as history rows, newest first.
static hmi_value_t read_rows(const char *path, size_t n)
{
    FILE *f = fopen(path, "rb");
    hmi_value_t out = hmi_value_null();
    if (!f) return out;

    // Buffer each line, newest first: the last line is the most recent.
    // Count total lines, then read them in reverse.
    char *lines[16384];
    size_t total = 0, cap = 0;
    char *buf = malloc(4096);
    size_t bufsz = 4096;
    ssize_t len;
    while ((len = getline(&buf, &bufsz, f)) != -1) {
        if (total < sizeof lines / sizeof lines[0]) {
            char *copy = malloc((size_t)len + 1);
            if (copy) { memcpy(copy, buf, (size_t)len); copy[len] = '\0'; lines[total] = copy; }
        }
        ++total;
    }
    free(buf);
    fclose(f);

    size_t want = n < total ? n : total;
    out.kind = HMI_V_LIST;
    out.items = calloc(want ? want : 1, sizeof *out.items);
    out.count = 0;
    for (size_t i = 0; i < want && out.count < want; ++i) {
        char *line = lines[total - 1 - i];   // newest first
        if (!line) continue;
        char *nl = strchr(line, '\n'); if (nl) *nl = '\0';
        char *cr = strchr(line, '\r'); if (cr) *cr = '\0';
        if (line[0]) {
            hmi_value_t row;
            if (parse_to_row(line, &row)) out.items[out.count++] = row;
        }
        free(line);
    }
    fprintf(stderr, "DBG read_rows(%s): count=%d item0items3kind=%d n=%g\n", path, out.count, out.count ? out.items[0].items[3].kind : -1, out.count ? (double)out.items[0].items[3].n : -1);
    return out;
}

hmi_value_t hmi_journal_recent(hmi_journal_t *j, size_t n)
{
    if (!j) {
        hmi_value_t out = hmi_value_null();
        out.kind = HMI_V_LIST;
        return out;
    }
    journal_mem *m = (journal_mem *)j;

    // PATH (newest lines) then PATH.1 (older), concatenated.
    hmi_value_t out = read_rows(m->path, n);
    char oldpath[HMI_JOURNAL_PATH_MAX];
    snprintf(oldpath, sizeof oldpath, "%s.1", m->path);
    hmi_value_t old = read_rows(oldpath, n);
    if (old.count == 0) return out;
    fprintf(stderr, "DBG merge: out.count=%d old.count=%d out0i3kind=%d\n", out.count, old.count, out.items ? out.items[0].items[3].kind : -1);

    // Concatenate: every line in PATH.1 predates the rotation, so it is older
    // than everything currently in PATH. Both files are newest-first.
    size_t total = out.count + old.count;
    size_t want = n < total ? n : total;
    hmi_value_t merged = hmi_value_null();
    merged.kind = HMI_V_LIST;
    merged.items = calloc(want ? want : 1, sizeof *merged.items);
    if (!merged.items) {
        free(out.items);
        free(old.items);
        out.items = NULL;
        old.items = NULL;
        out.count = 0;
        old.count = 0;
        return out;
    }
    size_t k = 0;
    for (size_t i = 0; i < out.count && k < want; ++i) merged.items[k++] = *out.items[i];
    for (size_t i = 0; i < old.count && k < want; ++i) merged.items[k++] = *old.items[i];
    merged.count = want;
    free(out.items);
    free(old.items);
    out.items = NULL;
    old.items = NULL;
    out.count = 0;
    old.count = 0;
    return merged;
}