// alarms.c -- manifest-driven alarm evaluation; the C port of
// native/hmi-gui/src/alarmengine.cpp (see alarms.h for the frozen rules).
//
// One difference from the C++ engine, which sees a whole frame per call:
// the runtime hands over one changed tag at a time, so every definition
// keeps the last value seen for its tag and each call re-evaluates all
// definitions against that cache.
#include "alarms.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "cJSON.h"
#include "compat.h"

typedef struct {
    char op[4];
    double value;
    bool present;       // op is a string and value a number (bools/strings never fire)
} threshold_t;

typedef struct {
    char tag[64];
    char label[96];
    char unit[32];
    threshold_t critical, warning;
    hmi_value_t last;   // last value delivered for `tag` (HMI_V_NULL until seen)
} def_t;

typedef struct {
    hmi_alarm_t alarm;
    long long order;    // activation sequence: the tie-breaker within one second
    bool seen;          // scratch: fired on this evaluate
} active_t;

struct hmi_alarms {
    def_t *defs;
    size_t ndefs;
    active_t *active;   // one per active tag, kept sorted after every change
    size_t nactive;
    long long seq;
    hmi_alarms_changed_cb cb;
    void *user;
    hmi_alarms_clock_fn clock;
    void *clock_user;
};

// -- definitions ------------------------------------------------------------

static void read_threshold(const cJSON *def, const char *key, threshold_t *t)
{
    memset(t, 0, sizeof *t);
    const cJSON *j = cJSON_GetObjectItemCaseSensitive(def, key);
    if (!cJSON_IsObject(j)) return;
    const cJSON *op = cJSON_GetObjectItemCaseSensitive(j, "op");
    const cJSON *value = cJSON_GetObjectItemCaseSensitive(j, "value");
    if (!cJSON_IsString(op) || !cJSON_IsNumber(value)) return;
    snprintf(t->op, sizeof t->op, "%s", cJSON_GetStringValue(op));
    t->value = cJSON_GetNumberValue(value);
    t->present = true;
}

static void load_defs(hmi_alarms_t *a, const cJSON *arr)
{
    if (!cJSON_IsArray(arr)) return;
    size_t n = (size_t)cJSON_GetArraySize(arr);
    a->defs = calloc(n ? n : 1, sizeof *a->defs);
    const cJSON *d;
    cJSON_ArrayForEach(d, arr) {
        // Entries that are not objects, or whose "tag" is not a string, are ignored.
        if (!cJSON_IsObject(d)) continue;
        const cJSON *tag = cJSON_GetObjectItemCaseSensitive(d, "tag");
        if (!cJSON_IsString(tag)) continue;
        def_t *def = &a->defs[a->ndefs++];
        snprintf(def->tag, sizeof def->tag, "%s", cJSON_GetStringValue(tag));
        const cJSON *label = cJSON_GetObjectItemCaseSensitive(d, "label");
        snprintf(def->label, sizeof def->label, "%s", cJSON_IsString(label) ? cJSON_GetStringValue(label) : def->tag);
        const cJSON *unit = cJSON_GetObjectItemCaseSensitive(d, "unit");
        snprintf(def->unit, sizeof def->unit, "%s", cJSON_IsString(unit) ? cJSON_GetStringValue(unit) : "");
        read_threshold(d, "critical", &def->critical);
        read_threshold(d, "warning", &def->warning);
        def->last = hmi_value_null();
    }
}

hmi_alarms_t *hmi_alarms_create_from_json(const char *alarms_json)
{
    hmi_alarms_t *a = calloc(1, sizeof *a);
    cJSON *arr = alarms_json ? cJSON_Parse(alarms_json) : NULL;
    load_defs(a, arr);
    cJSON_Delete(arr);
    return a;
}

hmi_alarms_t *hmi_alarms_create(const char *apps_dir)
{
    hmi_alarms_t *a = calloc(1, sizeof *a);
    if (!apps_dir) return a;
    char path[1024];
    snprintf(path, sizeof path, "%s/manifest.json", apps_dir);
    FILE *f = fopen(path, "rb");
    if (!f) return a;
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *text = malloc((size_t)len + 1);
    size_t got = text ? fread(text, 1, (size_t)len, f) : 0;
    fclose(f);
    if (text) {
        text[got] = '\0';
        cJSON *root = cJSON_Parse(text);
        if (cJSON_IsObject(root)) load_defs(a, cJSON_GetObjectItemCaseSensitive(root, "alarms"));
        cJSON_Delete(root);
        free(text);
    }
    return a;
}

void hmi_alarms_destroy(hmi_alarms_t *a)
{
    if (!a) return;
    for (size_t i = 0; i < a->ndefs; ++i) hmi_value_free(&a->defs[i].last);
    for (size_t i = 0; i < a->nactive; ++i) hmi_value_free(&a->active[i].alarm.value);
    free(a->defs);
    free(a->active);
    free(a);
}

void hmi_alarms_set_callback(hmi_alarms_t *a, hmi_alarms_changed_cb cb, void *user)
{
    a->cb = cb;
    a->user = user;
}

void hmi_alarms_set_clock(hmi_alarms_t *a, hmi_alarms_clock_fn now, void *user)
{
    a->clock = now;
    a->clock_user = user;
}

size_t hmi_alarms_tag_count(const hmi_alarms_t *a)
{
    // Unique tags in definition order.
    size_t count = 0;
    for (size_t i = 0; i < a->ndefs; ++i) {
        bool dup = false;
        for (size_t j = 0; j < i && !dup; ++j) dup = strcmp(a->defs[j].tag, a->defs[i].tag) == 0;
        if (!dup) ++count;
    }
    return count;
}

const char *hmi_alarms_tag(const hmi_alarms_t *a, size_t index)
{
    size_t count = 0;
    for (size_t i = 0; i < a->ndefs; ++i) {
        bool dup = false;
        for (size_t j = 0; j < i && !dup; ++j) dup = strcmp(a->defs[j].tag, a->defs[i].tag) == 0;
        if (dup) continue;
        if (count++ == index) return a->defs[i].tag;
    }
    return "";
}

// -- evaluation -------------------------------------------------------------

static bool threshold_fired(double value, const char *op, double threshold)
{
    if (strcmp(op, ">") == 0) return value > threshold;
    if (strcmp(op, ">=") == 0) return value >= threshold;
    if (strcmp(op, "<") == 0) return value < threshold;
    if (strcmp(op, "<=") == 0) return value <= threshold;
    if (strcmp(op, "==") == 0) return value == threshold;
    if (strcmp(op, "!=") == 0) return value != threshold;
    return false;
}

static const char *now_text(hmi_alarms_t *a, char *buf, size_t len)
{
    if (a->clock) return a->clock(a->clock_user);
    time_t t = time(NULL);
    struct tm tm;
    hmi_localtime(t, &tm);
    strftime(buf, len, "%Y-%m-%dT%H:%M:%S", &tm);
    return buf;
}

static active_t *find_active(const hmi_alarms_t *a, const char *tag)
{
    for (size_t i = 0; i < a->nactive; ++i)
        if (strcmp(a->active[i].alarm.tag, tag) == 0) return &a->active[i];
    return NULL;
}

// Critical first, then warning; newest timestamp first; then activation order.
static int compare_active(const void *pa, const void *pb)
{
    const active_t *x = pa, *y = pb;
    bool xc = strcmp(x->alarm.severity, "critical") == 0, yc = strcmp(y->alarm.severity, "critical") == 0;
    if (xc != yc) return xc ? -1 : 1;
    int ts = strcmp(y->alarm.timestamp, x->alarm.timestamp);
    if (ts) return ts;
    return x->order < y->order ? -1 : x->order > y->order ? 1 : 0;
}

static void notify(hmi_alarms_t *a)
{
    if (a->nactive > 1) qsort(a->active, a->nactive, sizeof *a->active, compare_active);
    if (a->cb) a->cb(a->user);
}

bool hmi_alarms_evaluate(hmi_alarms_t *a, const char *const *tags, const hmi_value_t *values, size_t n)
{
    if (a->ndefs == 0) return false;
    // 1. remember the delivered values
    for (size_t i = 0; i < n; ++i)
        for (size_t d = 0; d < a->ndefs; ++d)
            if (strcmp(a->defs[d].tag, tags[i]) == 0) {
                hmi_value_free(&a->defs[d].last);
                a->defs[d].last = hmi_value_copy(&values[i]);
            }
    // 2. evaluate every definition against its cached value
    bool changed = false;
    for (size_t i = 0; i < a->nactive; ++i) a->active[i].seen = false;
    char tsbuf[32];
    for (size_t d = 0; d < a->ndefs; ++d) {
        const def_t *def = &a->defs[d];
        if (def->last.kind == HMI_V_NULL || def->last.kind == HMI_V_LIST) continue;
        double v = hmi_value_as_num(&def->last, 0);
        const char *severity = NULL;
        if (def->critical.present && threshold_fired(v, def->critical.op, def->critical.value)) severity = "critical";
        else if (def->warning.present && threshold_fired(v, def->warning.op, def->warning.value)) severity = "warning";
        if (!severity) continue;
        char message[160];
        snprintf(message, sizeof message, "%s %g%s", def->label, v, def->unit);
        active_t *act = find_active(a, def->tag);
        if (act) {
            if (act->seen) continue;    // a second definition for the same tag: the first one won
            act->seen = true;
            if (strcmp(act->alarm.severity, severity) != 0) {
                snprintf(act->alarm.severity, sizeof act->alarm.severity, "%s", severity);
                hmi_value_free(&act->alarm.value);
                act->alarm.value = hmi_value_copy(&def->last);
                snprintf(act->alarm.message, sizeof act->alarm.message, "%s", message);
                changed = true;
            }
            continue;
        }
        active_t *grown = realloc(a->active, (a->nactive + 1) * sizeof *a->active);
        if (!grown) continue;
        a->active = grown;
        act = &a->active[a->nactive++];
        memset(act, 0, sizeof *act);
        snprintf(act->alarm.tag, sizeof act->alarm.tag, "%s", def->tag);
        snprintf(act->alarm.label, sizeof act->alarm.label, "%s", def->label);
        snprintf(act->alarm.severity, sizeof act->alarm.severity, "%s", severity);
        act->alarm.value = hmi_value_copy(&def->last);
        snprintf(act->alarm.message, sizeof act->alarm.message, "%s", message);
        snprintf(act->alarm.timestamp, sizeof act->alarm.timestamp, "%s", now_text(a, tsbuf, sizeof tsbuf));
        act->alarm.acknowledged = false;
        act->order = ++a->seq;
        act->seen = true;
        changed = true;
    }
    // 3. anything active that did not fire this time clears
    for (size_t i = 0; i < a->nactive;) {
        if (a->active[i].seen) { ++i; continue; }
        hmi_value_free(&a->active[i].alarm.value);
        memmove(&a->active[i], &a->active[i + 1], (a->nactive - i - 1) * sizeof *a->active);
        --a->nactive;
        changed = true;
    }
    if (changed) notify(a);
    return changed;
}

const hmi_alarm_t *hmi_alarms_active(const hmi_alarms_t *a, size_t *count)
{
    if (count) *count = a->nactive;
    // active_t starts with the hmi_alarm_t, but the stride differs: hand out a
    // packed copy so callers can index it as hmi_alarm_t[].
    static hmi_alarm_t *packed;
    static size_t packed_cap;
    if (a->nactive > packed_cap) {
        free(packed);
        packed = calloc(a->nactive, sizeof *packed);
        packed_cap = packed ? a->nactive : 0;
    }
    if (!packed) { if (count) *count = 0; return NULL; }
    for (size_t i = 0; i < a->nactive; ++i) packed[i] = a->active[i].alarm;   // value is borrowed, not owned
    return packed;
}

hmi_value_t hmi_alarms_active_value(const hmi_alarms_t *a)
{
    hmi_value_t list = hmi_value_null();
    list.kind = HMI_V_LIST;
    list.count = a->nactive;
    list.items = a->nactive ? calloc(a->nactive, sizeof *list.items) : NULL;
    if (!list.items) { list.count = 0; return list; }
    for (size_t i = 0; i < a->nactive; ++i) {
        const hmi_alarm_t *al = &a->active[i].alarm;
        hmi_value_t row = hmi_value_null();
        row.kind = HMI_V_LIST;
        row.count = 7;
        row.items = calloc(7, sizeof *row.items);
        if (!row.items) { row.count = 0; list.items[i] = row; continue; }
        row.items[0] = hmi_value_str(al->tag);
        row.items[1] = hmi_value_str(al->label);
        row.items[2] = hmi_value_str(al->severity);
        row.items[3] = hmi_value_copy(&al->value);
        row.items[4] = hmi_value_str(al->message);
        row.items[5] = hmi_value_str(al->timestamp);
        row.items[6] = hmi_value_bool(al->acknowledged);
        list.items[i] = row;
    }
    return list;
}

bool hmi_alarms_acknowledge(hmi_alarms_t *a, const char *tag)
{
    active_t *act = tag ? find_active(a, tag) : NULL;
    if (!act) return false;
    act->alarm.acknowledged = true;
    notify(a);
    return true;
}
