// alarms.c -- manifest-driven alarm evaluation; the C port of
// native/hmi-gui/src/alarmengine.cpp (see alarms.h for the rules).
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
#include "log.h"

typedef struct {
    char op[4];
    double value;
    bool present;       // op is a string and value a number (bools/strings never fire)
} threshold_t;

// CONTRACT 13.3: priority, latch, delay_ms, deadband, message.
typedef struct {
    char tag[HMI_ALARM_TAG_MAX];
    char label[96];
    char unit[32];
    threshold_t critical, warning;
    int priority;       // 1..4, 1 highest; 0 = not set (severity default)
    bool latch;
    long long delay_ms;   // 0 = raise immediately
    double deadband;      // 0 = none
    bool has_message;
    char message[160];    // manifest message, or empty = generate it
    hmi_value_t last;     // last value delivered for `tag` (HMI_V_NULL until seen)
} def_t;

typedef struct {
    hmi_alarm_t alarm;
    long long order;       // activation sequence: the within-second tie-breaker
    bool seen;             // scratch: fired on this evaluate
    int priority;          // resolved 1..4, for sorting
    long long raised_ms;         // monotonic ms the condition first raised
    long long delay_start_ms;    // monotonic ms the condition began holding
    long long delay_ms;          // this alarm's delay (0 = none)
    bool shelved;                // currently shelved
    long long shelve_until_ms;   // monotonic ms until which it is shelved
} active_t;

// A definition whose condition holds but has not yet raised: waiting on the
// 13.3 delay_ms. Kept separate from the active list so it is not visible until
// the delay elapses.
typedef struct {
    def_t *def;
    long long delay_ms;   // the definition's delay
    long long start_ms;   // monotonic ms the condition began holding
    long long order;      // activation sequence for ordering
    bool raised;          // already raised (waiting tick clears it)
    long long shelve_until_ms;  // monotonic ms until which the tag is shelved
    bool shelved;         // currently shelved
} pending_t;

struct hmi_alarms {
    def_t *defs;
    size_t ndefs;
    active_t *active;   // one per active tag, kept sorted after every change
    size_t nactive;
    pending_t *pending;   // definitions holding but not yet raised (delay)
    size_t npending;
    long long seq;
    hmi_alarms_changed_cb cb;
    void *user;
    hmi_alarms_clock_fn clock;
    void *clock_user;
    hmi_alarms_mono_fn mono;
    void *mono_user;
    hmi_journal_t *journal;
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

// CONTRACT 13.3: priority 1..4, 1 highest. Out-of-range falls back to 1.
static int clamp_priority(double p)
{
    int v = (int)p;
    if (p != (double)v) v = 1;
    if (v < 1) v = 1;
    if (v > 4) v = 4;
    return v;
}

// 13.3 table: the default priority is 1 for critical, 3 for warning; a
// manifest priority (non-zero) wins.
static int alarm_priority(const def_t *def, const char *severity)
{
    if (def->priority) return def->priority;
    return strcmp(severity, "critical") == 0 ? 1 : 3;
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
        // A truncated tag never matches a frame (or matches the wrong one):
        // say so and drop the definition rather than arm a dead alarm.
        if (strlen(cJSON_GetStringValue(tag)) >= HMI_ALARM_TAG_MAX) {
            hmi_log(HMI_LOG_WARNING, "alarms: tag longer than %d bytes ignored: %.40s...",
                    HMI_ALARM_TAG_MAX - 1, cJSON_GetStringValue(tag));
            continue;
        }
        def_t *def = &a->defs[a->ndefs++];
        snprintf(def->tag, sizeof def->tag, "%s", cJSON_GetStringValue(tag));
        const cJSON *label = cJSON_GetObjectItemCaseSensitive(d, "label");
        // A label longer than the field is cut to fit (display text only).
        snprintf(def->label, sizeof def->label, "%.*s", (int)sizeof def->label - 1,
                  cJSON_IsString(label) ? cJSON_GetStringValue(label) : def->tag);
        const cJSON *unit = cJSON_GetObjectItemCaseSensitive(d, "unit");
        snprintf(def->unit, sizeof def->unit, "%s", cJSON_IsString(unit) ? cJSON_GetStringValue(unit) : "");
        read_threshold(d, "critical", &def->critical);
        read_threshold(d, "warning", &def->warning);
        // CONTRACT 13.3: priority, latch, delay_ms, deadband, message.
        def->priority = 0;   // determined at activation from severity unless set
        cJSON *j = cJSON_GetObjectItemCaseSensitive(d, "priority");
        if (j) def->priority = clamp_priority(cJSON_GetNumberValue(j));
        def->latch = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(d, "latch"));
        j = cJSON_GetObjectItemCaseSensitive(d, "delay_ms");
        if (j) def->delay_ms = (long long)cJSON_GetNumberValue(j);
        j = cJSON_GetObjectItemCaseSensitive(d, "deadband");
        if (j) def->deadband = cJSON_GetNumberValue(j);
        def->has_message = false;
        j = cJSON_GetObjectItemCaseSensitive(d, "message");
        if (j && cJSON_IsString(j)) {
            snprintf(def->message, sizeof def->message, "%s", cJSON_GetStringValue(j));
            def->has_message = true;
        }
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

// Monotonic ms of "now" for the engine's timers, or 0 if none is set.
static long long now_ms(hmi_alarms_t *a)
{
    if (a->mono) return a->mono(a->mono_user);
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) return 0;
    return (long long)ts.tv_sec * 1000LL + ts.tv_nsec / 1000000;
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

static const def_t *find_def(const hmi_alarms_t *a, const char *tag)
{
    for (size_t d = 0; d < a->ndefs; ++d)
        if (strcmp(a->defs[d].tag, tag) == 0) return &a->defs[d];
    return NULL;
}

// A delayed definition is "pending": its condition holds, but the delay_ms has
// not elapsed, so it is not yet visible in the active list. A delay restarts
// whenever the value drops below the threshold again.
static pending_t *find_pending(const hmi_alarms_t *a, const char *tag)
{
    for (size_t i = 0; i < a->npending; ++i)
        if (a->pending[i].def && strcmp(a->pending[i].def->tag, tag) == 0) return &a->pending[i];
    return NULL;
}

// CONTRACT 13.3 message: the manifest text, else "<label> <value:%g><unit>".
static void make_message(const def_t *def, double v, char *out, size_t len)
{
    if (def->has_message) { snprintf(out, len, "%s", def->message); return; }
    snprintf(out, len, "%s %g%s", def->label, v, def->unit);
}

// Does `def`'s condition hold for value `v`, honoring deadband? With deadband,
// the alarm clears only when the value has moved `deadband` past the threshold,
// so a value still inside the deadband keeps the alarm active.
static bool condition_holds(const def_t *def, const char *severity, double v)
{
    threshold_t t = strcmp(severity, "critical") == 0 ? def->critical : def->warning;
    if (!t.present) return false;
    if (def->deadband <= 0.0) return threshold_fired(v, t.op, t.value);
    if (strcmp(t.op, ">") == 0)  return v > t.value || v < t.value - def->deadband;
    if (strcmp(t.op, ">=") == 0) return v > t.value || v <= t.value - def->deadband;
    if (strcmp(t.op, "<") == 0)  return v < t.value || v > t.value + def->deadband;
    if (strcmp(t.op, "<=") == 0) return v < t.value || v >= t.value + def->deadband;
    if (strcmp(t.op, "==") == 0) return v == t.value;
    if (strcmp(t.op, "!=") == 0) return v != t.value;
    return false;
}

// Critical first, then priority ascending, then newest timestamp first;
// the activation order breaks ties within the same second.
static int compare_active(const void *pa, const void *pb)
{
    const active_t *x = pa, *y = pb;
    if (x->priority != y->priority) return x->priority < y->priority ? -1 : 1;
    int ts = strcmp(y->alarm.timestamp, x->alarm.timestamp);
    if (ts) return ts;
    return x->order < y->order ? -1 : x->order > y->order ? 1 : 0;
}

static void notify(hmi_alarms_t *a)
{
    if (a->nactive > 1) qsort(a->active, a->nactive, sizeof *a->active, compare_active);
    if (a->cb) a->cb(a->user);
}

static long long now_ms_wall(hmi_alarms_t *a)
{
    (void)a;
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (long long)ts.tv_sec * 1000LL + ts.tv_nsec / 1000000;
}

// Journal one event (13.3). Never fails loudly; log once on error.
static void journal_event(hmi_alarms_t *a, const char *event, active_t *act)
{
    if (!a->journal) return;
    hmi_journal_append(a->journal, now_ms_wall(a), event, act->alarm.tag,
                       act->alarm.label, act->alarm.severity, act->priority,
                       &act->alarm.value);
}

bool hmi_alarms_evaluate(hmi_alarms_t *a, const char *const *tags, const hmi_value_t *values, size_t n)
{
    if (a->ndefs == 0) return false;
    long long now = now_ms(a);
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
    char tsbuf[32], message[160];
    for (size_t d = 0; d < a->ndefs; ++d) {
        const def_t *def = &a->defs[d];
        if (def->last.kind == HMI_V_NULL || def->last.kind == HMI_V_LIST) continue;
        double v = hmi_value_as_num(&def->last, 0);
        const char *severity = NULL;
        if (def->critical.present && threshold_fired(v, def->critical.op, def->critical.value)) severity = "critical";
        else if (def->warning.present && threshold_fired(v, def->warning.op, def->warning.value)) severity = "warning";
        if (!severity) continue;
        if (!condition_holds(def, severity, v)) continue;
        // A delay: the alarm is pending until the condition has held long enough.
        if (def->delay_ms > 0) {
            pending_t *p = find_pending(a, def->tag);
            if (!p) {
                pending_t *grown = realloc(a->pending, (a->npending + 1) * sizeof *a->pending);
                if (!grown) continue;
                a->pending = grown;
                p = &a->pending[a->npending++];
                memset(p, 0, sizeof *p);
                p->def = def;
                p->delay_ms = def->delay_ms;
                p->start_ms = now;
                p->order = ++a->seq;
            }
            continue;   // still holding; keep waiting on tick
        }
        active_t *act = find_active(a, def->tag);
        if (act) {
            if (act->seen) continue;    // a second definition for the same tag: the first one won
            act->seen = true;
            if (strcmp(act->alarm.severity, severity) != 0) {
                snprintf(act->alarm.severity, sizeof act->alarm.severity, "%s", severity);
                hmi_value_free(&act->alarm.value);
                act->alarm.value = hmi_value_copy(&def->last);
                make_message(def, v, message, sizeof message);
                snprintf(act->alarm.message, sizeof act->alarm.message, "%s", message);
                act->priority = alarm_priority(def, severity);
                act->alarm.priority = act->priority;
                changed = true;
            }
            continue;
        }
        // New raise. Register immediately (no delay).
        active_t *grown = realloc(a->active, (a->nactive + 1) * sizeof *a->active);
        if (!grown) continue;
        a->active = grown;
        act = &a->active[a->nactive++];
        memset(act, 0, sizeof *act);
        snprintf(act->alarm.tag, sizeof act->alarm.tag, "%s", def->tag);
        snprintf(act->alarm.label, sizeof act->alarm.label, "%s", def->label);
        snprintf(act->alarm.severity, sizeof act->alarm.severity, "%s", severity);
        act->alarm.value = hmi_value_copy(&def->last);
        make_message(def, v, message, sizeof message);
        snprintf(act->alarm.message, sizeof act->alarm.message, "%s", message);
        snprintf(act->alarm.timestamp, sizeof act->alarm.timestamp, "%s", now_text(a, tsbuf, sizeof tsbuf));
        act->alarm.acknowledged = false;
        act->priority = alarm_priority(def, severity);
        act->alarm.priority = act->priority;
        act->raised_ms = now;
        act->order = ++a->seq;
        act->seen = true;
        journal_event(a, "raise", act);
        changed = true;
    }
    // 3. pending definitions that no longer hold restart on the next value.
    for (size_t i = 0; i < a->npending;) {
        pending_t *p = &a->pending[i];
        if (p->def && p->def->last.kind != HMI_V_NULL && p->def->last.kind != HMI_V_LIST) {
            double pv = hmi_value_as_num(&p->def->last, 0);
            if (!p->def->critical.present && !p->def->warning.present) continue;
            // Recompute the severity the pending entry was waiting on.
            if ((p->def->critical.present && threshold_fired(pv, p->def->critical.op, p->def->critical.value)) ||
                (p->def->warning.present && threshold_fired(pv, p->def->warning.op, p->def->warning.value)))
                continue;   // still holding
        }
        // Condition dropped: drop the pending entry; it restarts on the next
        // value that holds again.
        free(p);
        memmove(&a->pending[i], &a->pending[i + 1], (a->npending - i - 1) * sizeof *a->pending);
        --a->npending;
    }
    // 4. anything active that did not fire this time: it clears, except a
    //    latched (and unacknowledged) alarm that stays listed, value frozen.
    for (size_t i = 0; i < a->nactive;) {
        if (a->active[i].seen) { ++i; continue; }
        def_t *def = find_def(a, a->active[i].alarm.tag);
        bool latch = def && def->latch && !a->active[i].alarm.acknowledged;
        if (latch) {
            // Freeze the value/message and mark the alarm cleared.
            if (a->active[i].alarm.value.kind != HMI_V_NULL) {
                // keep the frozen value; clear the "condition held" bookkeeping
            }
            if (!a->active[i].alarm.cleared) {
                a->active[i].alarm.cleared = true;
                changed = true;
            }
            ++i;
            continue;
        }
        journal_event(a, "clear", &a->active[i]);
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
    for (size_t i = 0; i < a->nactive; ++i) {
        packed[i] = a->active[i].alarm;   // value is borrowed, not owned
        packed[i].priority = a->active[i].priority;
        packed[i].cleared = a->active[i].alarm.cleared;
    }
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
        row.count = 9;
        row.items = calloc(9, sizeof *row.items);
        if (!row.items) { row.count = 0; list.items[i] = row; continue; }
        row.items[0] = hmi_value_str(al->tag);
        row.items[1] = hmi_value_str(al->label);
        row.items[2] = hmi_value_str(al->severity);
        row.items[3] = hmi_value_copy(&al->value);
        row.items[4] = hmi_value_str(al->message);
        row.items[5] = hmi_value_str(al->timestamp);
        row.items[6] = hmi_value_bool(al->acknowledged);
        row.items[7] = hmi_value_num((double)al->priority);
        row.items[8] = hmi_value_str(al->cleared ? "cleared" : "active");
        list.items[i] = row;
    }
    return list;
}

bool hmi_alarms_acknowledge(hmi_alarms_t *a, const char *tag)
{
    active_t *act = tag ? find_active(a, tag) : NULL;
    if (!act) return false;
    // A latched alarm that has already cleared is removed by its ack (13.3).
    if (act->alarm.cleared) {
        journal_event(a, "ack", act);
        hmi_value_free(&act->alarm.value);
        memmove(act, act + 1, ((a->nactive - 1) - (size_t)(act - a->active)) * sizeof *a->active);
        --a->nactive;
        notify(a);
        return true;
    }
    act->alarm.acknowledged = true;
    journal_event(a, "ack", act);
    notify(a);
    return true;
}

// ---- wave 1 (CONTRACT 13.3): W3 implements -------------------------------

size_t hmi_alarms_acknowledge_all(hmi_alarms_t *a)
{
    size_t changed = 0;
    for (size_t i = 0; i < a->nactive;) {
        // Acknowledging removes a cleared (latched) alarm; marks the rest.
        bool clear = a->active[i].alarm.cleared;
        if (clear) {
            journal_event(a, "ack", &a->active[i]);
            hmi_value_free(&a->active[i].alarm.value);
            memmove(&a->active[i], &a->active[i + 1], (a->nactive - i - 1) * sizeof *a->active);
            --a->nactive;
            ++changed;
            continue;
        }
        if (!a->active[i].alarm.acknowledged) {
            a->active[i].alarm.acknowledged = true;
            journal_event(a, "ack", &a->active[i]);
            ++changed;
        }
        ++i;
    }
    if (changed) notify(a);
    return changed;
}

bool hmi_alarms_shelve(hmi_alarms_t *a, const char *tag, int ms)
{
    if (tag == NULL || ms < 1 || ms > 86400000) return false;
    const def_t *def = find_def(a, tag);
    if (!def) return false;    // shelve on a tag with no definition does nothing
    long long now = now_ms(a);
    active_t *act = find_active(a, tag);
    // Shelving removes the alarm from the active list and stops it raising
    // until the shelve expires; on expiry the tick re-evaluates on the last
    // value. The shelve state is remembered via the pending entry below.
    if (act) {
        journal_event(a, "shelve", act);
        hmi_value_free(&act->alarm.value);
        memmove(act, act + 1, ((a->nactive - 1) - (size_t)(act - a->active)) * sizeof *a->active);
        --a->nactive;
        if (a->cb) a->cb(a->user);
        return true;
    }
    // Not currently active: record a pending shelve so the tick can restore it
    // when the shelve expires.
    pending_t *p = find_pending(a, tag);
    if (!p) {
        pending_t *grown = realloc(a->pending, (a->npending + 1) * sizeof *a->pending);
        if (!grown) return false;
        a->pending = grown;
        p = &a->pending[a->npending++];
        memset(p, 0, sizeof *p);
        p->def = def;
        p->shelve_until_ms = now + ms;
        p->shelved = true;
        p->order = ++a->seq;
        return true;
    }
    p->shelve_until_ms = now + ms;
    p->shelved = true;
    return true;
}

bool hmi_alarms_is_shelved(const hmi_alarms_t *a, const char *tag)
{
    active_t *act = tag ? find_active(a, tag) : NULL;
    return act != NULL && act->shelved;
}

void hmi_alarms_tick(hmi_alarms_t *a)
{
    long long now = now_ms(a);
    bool changed = false;
    // Delay gate: pending definitions whose condition has held long enough now
    // raise. They must still hold; evaluate() only tracked the hold start.
    for (size_t i = 0; i < a->npending;) {
        pending_t *p = &a->pending[i];
        if (!p->def) { free(p); memmove(&a->pending[i], &a->pending[i + 1], (a->npending - i - 1) * sizeof *a->pending); --a->npending; continue; }
        if (now - p->start_ms < p->delay_ms) { ++i; continue; }
        // The delay has elapsed and the condition still holds: raise it.
        const def_t *def = p->def;
        const char *severity = NULL;
        if (def->critical.present && threshold_fired(hmi_value_as_num(&def->last, 0), def->critical.op, def->critical.value)) severity = "critical";
        else if (def->warning.present && threshold_fired(hmi_value_as_num(&def->last, 0), def->warning.op, def->warning.value)) severity = "warning";
        if (!severity) { free(p); memmove(&a->pending[i], &a->pending[i + 1], (a->npending - i - 1) * sizeof *a->pending); --a->npending; continue; }
        active_t *grown = realloc(a->active, (a->nactive + 1) * sizeof *a->active);
        if (!grown) { ++i; continue; }
        a->active = grown;
        active_t *act = &a->active[a->nactive++];
        memset(act, 0, sizeof *act);
        snprintf(act->alarm.tag, sizeof act->alarm.tag, "%s", def->tag);
        snprintf(act->alarm.label, sizeof act->alarm.label, "%s", def->label);
        snprintf(act->alarm.severity, sizeof act->alarm.severity, "%s", severity);
        act->alarm.value = hmi_value_copy(&def->last);
        char msg[160];
        make_message(def, hmi_value_as_num(&def->last, 0), msg, sizeof msg);
        snprintf(act->alarm.message, sizeof act->alarm.message, "%s", msg);
        snprintf(act->alarm.timestamp, sizeof act->alarm.timestamp, "%s", now_text(a, msg, sizeof msg));
        act->alarm.acknowledged = false;
        act->priority = alarm_priority(def, severity);
        act->alarm.priority = act->priority;
        act->raised_ms = now;
        act->order = p->order;
        free(p);
        memmove(&a->pending[i], &a->pending[i + 1], (a->npending - i - 1) * sizeof *a->pending);
        --a->npending;
        journal_event(a, "raise", act);
        changed = true;
        // Restart the scan: the active array just grew and pending shifted.
    }
    // Shelve expiry: clear the shelve and re-evaluate on the last value.
    for (size_t i = 0; i < a->nactive;) {
        active_t *act = &a->active[i];
        if (act->shelved && now >= act->shelve_until_ms) {
            act->shelved = false;
            journal_event(a, "unshelve", act);
            const def_t *def = find_def(a, act->alarm.tag);
            if (def && def->last.kind != HMI_V_NULL && def->last.kind != HMI_V_LIST) {
                double v = hmi_value_as_num(&def->last, 0);
                const char *sev = NULL;
                if (def->critical.present && threshold_fired(v, def->critical.op, def->critical.value)) sev = "critical";
                else if (def->warning.present && threshold_fired(v, def->warning.op, def->warning.value)) sev = "warning";
                if (sev && condition_holds(def, sev, v)) {
                    act->raised_ms = now;
                    act->order = ++a->seq;
                    journal_event(a, "raise", act);
                    changed = true;
                } else if (sev) {
                    act->seen = true;   // will be handled by evaluate's clearing
                }
            }
            ++i;
            continue;
        }
        ++i;
    }
    if (changed) notify(a);
}

void hmi_alarms_set_monotonic(hmi_alarms_t *a, hmi_alarms_mono_fn now, void *user)
{
    a->mono = now;
    a->mono_user = user;
}

void hmi_alarms_set_journal(hmi_alarms_t *a, hmi_journal_t *j)
{
    a->journal = j;
}

hmi_journal_t *hmi_alarms_journal(const hmi_alarms_t *a)
{
    return a->journal;
}