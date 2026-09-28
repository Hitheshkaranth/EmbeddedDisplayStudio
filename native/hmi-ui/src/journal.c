// journal.c -- see journal.h (CONTRACT 13.3).
//
// The panel can lose power at any moment, so every line is flushed to the
// kernel at once; fsync (the flash write) is rate-limited to once a second
// to spare the eMMC. Rotation keeps exactly one old file, PATH.1.
#include "journal.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef _WIN32
#include <io.h>
#else
#include <unistd.h>
#endif

#include "cJSON.h"
#include "compat.h"
#include "log.h"

struct hmi_journal {
    FILE *f;
    char *path;
    size_t max_bytes;
    size_t written;               // size of the current PATH, including what a previous run left
    bool synced_once;
    unsigned long last_sync_ms;   // hmi_millis() of the last fsync
    bool write_error_logged;
};

hmi_journal_t *hmi_journal_open(const char *path, size_t max_bytes)
{
    if (!path || !*path) return NULL;
    FILE *f = fopen(path, "a");
    if (!f) {
        hmi_log(HMI_LOG_WARNING, "journal: cannot open %s", path);
        return NULL;
    }
    hmi_journal_t *j = calloc(1, sizeof *j);
    char *copy = malloc(strlen(path) + 1);
    if (!j || !copy) {
        free(j);
        free(copy);
        fclose(f);
        return NULL;
    }
    strcpy(copy, path);
    j->f = f;
    j->path = copy;
    j->max_bytes = max_bytes ? max_bytes : HMI_JOURNAL_MAX_BYTES;
    // CONTRACT 13.3 bounds the file, not a run: start from its size.
    if (fseek(f, 0, SEEK_END) == 0) {
        long size = ftell(f);
        if (size > 0) j->written = (size_t)size;
    }
    return j;
}

void hmi_journal_close(hmi_journal_t *j)
{
    if (!j) return;
    if (j->f) {
        fflush(j->f);
#ifdef _WIN32
        _commit(_fileno(j->f));
#else
        fsync(fileno(j->f));
#endif
        fclose(j->f);
    }
    free(j->path);
    free(j);
}

static char *old_path(const hmi_journal_t *j)
{
    size_t n = strlen(j->path) + 3;
    char *p = malloc(n);
    if (p) snprintf(p, n, "%s.1", j->path);
    return p;
}

static void sync_if_due(hmi_journal_t *j)
{
    unsigned long now = hmi_millis();
    if (j->synced_once && now - j->last_sync_ms < 1000) return;
#ifdef _WIN32
    _commit(_fileno(j->f));
#else
    fsync(fileno(j->f));
#endif
    j->synced_once = true;
    j->last_sync_ms = now;
}

// Once PATH has passed max_bytes, the next append renames it PATH.1
// (replacing that) and starts a new PATH, so PATH is never left empty.
static void rotate_if_full(hmi_journal_t *j)
{
    if (j->written <= j->max_bytes) return;
    char *old = old_path(j);
    if (!old) return;
    fclose(j->f);
    remove(old);   // Windows rename() does not replace
    if (rename(j->path, old) != 0) hmi_log(HMI_LOG_WARNING, "journal: cannot rotate %s", j->path);
    free(old);
    j->written = 0;
    j->f = fopen(j->path, "a");
    if (!j->f) hmi_log(HMI_LOG_WARNING, "journal: cannot reopen %s", j->path);
}

bool hmi_journal_append(hmi_journal_t *j, int64_t ts_ms, const char *event, const char *tag,
                        const char *label, const char *severity, int priority,
                        const hmi_value_t *value)
{
    if (!j) return false;
    if (j->f) rotate_if_full(j);
    if (!j->f) j->f = fopen(j->path, "a");   // a failed reopen after rotation retries here
    cJSON *o = cJSON_CreateObject();
    if (!o) return false;
    cJSON_AddNumberToObject(o, "ts", (double)ts_ms);
    cJSON_AddStringToObject(o, "event", event ? event : "");
    cJSON_AddStringToObject(o, "tag", tag ? tag : "");
    cJSON_AddStringToObject(o, "label", label ? label : "");
    cJSON_AddStringToObject(o, "severity", severity ? severity : "");
    cJSON_AddNumberToObject(o, "priority", priority);
    cJSON_AddItemToObject(o, "value", hmi_value_to_json(value));
    char *line = cJSON_PrintUnformatted(o);
    cJSON_Delete(o);
    bool ok = line && j->f && fputs(line, j->f) >= 0 && fputc('\n', j->f) != EOF && fflush(j->f) == 0;
    if (ok) j->written += strlen(line) + 1;
    free(line);
    if (!ok) {
        if (!j->write_error_logged)
            hmi_log(HMI_LOG_WARNING, "journal: cannot write %s", j->path);
        j->write_error_logged = true;
        return false;
    }
    sync_if_due(j);
    return true;
}

// -- reading back ------------------------------------------------------------

static char *read_file(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *text = len >= 0 ? malloc((size_t)len + 1) : NULL;
    size_t got = text ? fread(text, 1, (size_t)len, f) : 0;
    fclose(f);
    if (text) text[got] = '\0';
    return text;
}

// One journal line as a ShAlarmTable history item; false for a line that is
// not a journal object.
static bool line_to_item(const char *line, hmi_value_t *out)
{
    cJSON *o = cJSON_Parse(line);
    if (!cJSON_IsObject(o)) {
        cJSON_Delete(o);
        return false;
    }
    const cJSON *ts = cJSON_GetObjectItemCaseSensitive(o, "ts");
    const cJSON *pr = cJSON_GetObjectItemCaseSensitive(o, "priority");
    const char *tag = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, "tag"));
    const char *label = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, "label"));
    const char *sev = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, "severity"));
    const char *event = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, "event"));
    char stamp[24] = "";
    if (cJSON_IsNumber(ts)) {
        struct tm tm;
        hmi_localtime((time_t)(cJSON_GetNumberValue(ts) / 1000.0), &tm);
        strftime(stamp, sizeof stamp, "%Y-%m-%dT%H:%M:%S", &tm);
    }
    hmi_value_t item = hmi_value_null();
    item.kind = HMI_V_LIST;
    item.items = calloc(9, sizeof *item.items);
    if (!item.items) {
        cJSON_Delete(o);
        return false;
    }
    item.count = 9;
    item.items[0] = hmi_value_str(tag ? tag : "");
    item.items[1] = hmi_value_str(label ? label : "");
    item.items[2] = hmi_value_str(sev ? sev : "");
    item.items[3] = hmi_value_from_json(cJSON_GetObjectItemCaseSensitive(o, "value"));
    item.items[4] = hmi_value_str(event ? event : "");
    item.items[5] = hmi_value_str(stamp);
    item.items[6] = hmi_value_bool(true);
    item.items[7] = hmi_value_num(cJSON_IsNumber(pr) ? cJSON_GetNumberValue(pr) : 3);
    item.items[8] = hmi_value_str("cleared");
    cJSON_Delete(o);
    *out = item;
    return true;
}

// Appends the newest items of `path` to `list`, newest first, until it holds `n`.
static void collect(const char *path, size_t n, hmi_value_t *list)
{
    if (list->count >= n) return;
    char *text = read_file(path);
    if (!text) return;
    char *end = text + strlen(text);
    while (end > text && list->count < n) {
        char *p = end;
        while (p > text && p[-1] != '\n') --p;   // start of the last line before `end`
        char *next_end = p > text ? p - 1 : text;
        *end = '\0';
        if (end > p && end[-1] == '\r') end[-1] = '\0';
        hmi_value_t item;
        if (*p && line_to_item(p, &item)) list->items[list->count++] = item;
        end = next_end;
    }
    free(text);
}

hmi_value_t hmi_journal_recent(hmi_journal_t *j, size_t n)
{
    hmi_value_t out = hmi_value_null();
    out.kind = HMI_V_LIST;
    if (!j || n == 0) return out;
    out.items = calloc(n, sizeof *out.items);
    if (!out.items) return out;
    collect(j->path, n, &out);
    char *old = old_path(j);
    if (old) collect(old, n, &out);
    free(old);
    if (out.count == 0) {
        free(out.items);
        out.items = NULL;
    }
    return out;
}
