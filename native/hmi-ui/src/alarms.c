// alarms.c -- manifest-driven alarm evaluation; the C port of
// native/hmi-gui/src/alarmengine.cpp (see alarms.h for the rules).
//
// One difference from the C++ engine, which sees a whole frame per call:
// the runtime hands over one changed tag at a time, so every definition
// keeps the last value seen for its tag and each call re-evaluates all
// definitions against that cache.
//
// CONTRACT 13.3 adds a life cycle per tag: normal -> (held delay_ms) ->
// active -> ack -> clears -> normal, with latching, deadband and shelving.
// evaluate() and tick() share one pass (reevaluate) so a delay or a shelve
// expiring in tick() follows exactly the rules a new value would.
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

typedef struct {
    char tag[HMI_ALARM_TAG_MAX];
    char label[96];
    char unit[32];
    threshold_t critical, warning;
    hmi_value_t last;   // last value delivered for `tag` (HMI_V_NULL until seen)
    // CONTRACT 13.3
    int priority;           // 1..4; 0 = the severity default (1 critical, 3 warning)
    bool latch;
    uint64_t delay_ms;      // 0 = raise at once
    double deadband;        // >= 0
    char message[160];      // "" = generate "<label> <value><unit>"
    bool holding;           // condition holds while not listed: waiting on delay_ms
    uint64_t hold_since;    // monotonic ms the condition started holding
    bool shelved;
    uint64_t shelved_until; // monotonic ms
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
    hmi_alarms_mono_fn mono;
    void *mono_user;
    hmi_journal_t *journal;   // not owned
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

// The 13.3 keys. Anything out of range (or of the wrong JSON type) keeps the
// default, so one bad key never drops the whole alarm.
static void read_v2_keys(const cJSON *d, def_t *def)
{
    const cJSON *j = cJSON_GetObjectItemCaseSensitive(d, "priority");
    if (cJSON_IsNumber(j)) {
        double p = cJSON_GetNumberValue(j);
        if (p >= 1 && p <= 4 && p == (double)(int)p) def->priority = (int)p;
    }
    def->latch = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(d, "latch"));
    j = cJSON_GetObjectItemCaseSensitive(d, "delay_ms");
    if (cJSON_IsNumber(j)) {
        double ms = cJSON_GetNumberValue(j);
        if (ms >= 0 && ms <= 600000) def->delay_ms = (uint64_t)ms;
    }
    j = cJSON_GetObjectItemCaseSensitive(d, "deadband");
    if (cJSON_IsNumber(j) && cJSON_GetNumberValue(j) >= 0) def->deadband = cJSON_GetNumberValue(j);
    j = cJSON_GetObjectItemCaseSensitive(d, "message");
    if (cJSON_IsString(j))
        snprintf(def->message, sizeof def->message, "%s", cJSON_GetStringValue(j));
}

static void load_defs(hmi_alarms_t *a, const cJSON *arr)
{
    if (!cJSON_IsArray(arr)) return;
    size_t n = (size_t)cJSON_GetArraySize(arr);
    a->defs = calloc(n ? n : 1, sizeof *a->defs);
    if (!a->defs) return;
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
        read_v2_keys(d, def);
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
    char *text = len >= 0 ? malloc((size_t)len + 1) : NULL;
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

// Deadband (13.3): an active alarm clears only once the value is `deadband`
// past the threshold, away from the operator's direction: "> 80" with
// deadband 2 still holds at 79 and clears at <= 78; "< 10" clears at >= 12.
// Equality operators have no direction and ignore it.
static bool threshold_still_holds(double v, const threshold_t *t, double deadband)
{
    if (!t->present) return false;
    if (threshold_fired(v, t->op, t->value)) return true;
    if (deadband <= 0) return false;
    if (strcmp(t->op, ">") == 0 || strcmp(t->op, ">=") == 0) return v > t->value - deadband;
    if (strcmp(t->op, "<") == 0 || strcmp(t->op, "<=") == 0) return v < t->value + deadband;
    return false;
}

static uint64_t now_ms(const hmi_alarms_t *a)
{
    if (a->mono) return a->mono(a->mono_user);
    return (uint64_t)hmi_millis();   // CLOCK_MONOTONIC: immune to wall-clock steps
}

static int64_t wall_ms(void) { return hmi_wall_ms(); }

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

// The first definition for `tag`: it owns the tag's latch and shelve state
// (the first definition also wins the evaluation, as before).
static def_t *find_def(const hmi_alarms_t *a, const char *tag)
{
    for (size_t d = 0; d < a->ndefs; ++d)
        if (strcmp(a->defs[d].tag, tag) == 0) return &a->defs[d];
    return NULL;
}

static int default_priority(const def_t *def, const char *severity)
{
    if (def->priority) return def->priority;
    return strcmp(severity, "critical") == 0 ? 1 : 3;
}

static void make_message(const def_t *def, double v, char *out, size_t len)
{
    if (def->message[0]) snprintf(out, len, "%s", def->message);
    else snprintf(out, len, "%s %g%s", def->label, v, def->unit);
}

// Priority ascending (1 first); newest timestamp first; then activation order.
static int compare_active(const void *pa, const void *pb)
{
    const active_t *x = pa, *y = pb;
    if (x->alarm.priority != y->alarm.priority) return x->alarm.priority < y->alarm.priority ? -1 : 1;
    int ts = strcmp(y->alarm.timestamp, x->alarm.timestamp);
    if (ts) return ts;
    return x->order < y->order ? -1 : x->order > y->order ? 1 : 0;
}

static void notify(hmi_alarms_t *a)
{
    if (a->nactive > 1) qsort(a->active, a->nactive, sizeof *a->active, compare_active);
    if (a->cb) a->cb(a->user);
}

static void journal(hmi_alarms_t *a, const char *event, const char *tag, const char *label,
                    const char *severity, int priority, const hmi_value_t *value)
{
    if (a->journal)
        hmi_journal_append(a->journal, wall_ms(), event, tag, label, severity, priority, value);
}

static void journal_alarm(hmi_alarms_t *a, const char *event, const hmi_alarm_t *al, const hmi_value_t *value)
{
    journal(a, event, al->tag, al->label, al->severity, al->priority, value ? value : &al->value);
}

// Journals an event about a tag that is not listed (shelve/unshelve), under
// the severity its definition raises first.
static void journal_def(hmi_alarms_t *a, const char *event, const def_t *def)
{
    const char *sev = def->critical.present ? "critical" : "warning";
    journal(a, event, def->tag, def->label, sev, default_priority(def, sev), &def->last);
}

static void remove_active(hmi_alarms_t *a, active_t *act)
{
    size_t i = (size_t)(act - a->active);
    hmi_value_free(&act->alarm.value);
    memmove(&a->active[i], &a->active[i + 1], (a->nactive - i - 1) * sizeof *a->active);
    --a->nactive;
}

// Sets the listed alarm's severity, value, message and priority from `def`.
static void fill_alarm(hmi_alarm_t *al, const def_t *def, const char *severity, double v)
{
    snprintf(al->severity, sizeof al->severity, "%s", severity);
    hmi_value_free(&al->value);
    al->value = hmi_value_copy(&def->last);
    make_message(def, v, al->message, sizeof al->message);
    al->priority = default_priority(def, severity);
}

// One pass over every definition against its cached value at monotonic `now`.
// True when the listed set changed (the caller notifies once).
static bool reevaluate(hmi_alarms_t *a, uint64_t now)
{
    bool changed = false;
    for (size_t i = 0; i < a->nactive; ++i) a->active[i].seen = false;
    char tsbuf[24];   // the size of hmi_alarm_t.timestamp: nothing to truncate
    for (size_t d = 0; d < a->ndefs; ++d) {
        def_t *def = &a->defs[d];
        const def_t *owner = find_def(a, def->tag);
        active_t *act = find_active(a, def->tag);
        if (act && act->seen) continue;    // a second definition for the same tag: the first one won
        if (owner->shelved) { def->holding = false; continue; }
        bool valued = def->last.kind != HMI_V_NULL && def->last.kind != HMI_V_LIST;
        double v = valued ? hmi_value_as_num(&def->last, 0) : 0;
        const char *severity = NULL;
        if (valued) {
            if (def->critical.present && threshold_fired(v, def->critical.op, def->critical.value)) severity = "critical";
            else if (def->warning.present && threshold_fired(v, def->warning.op, def->warning.value)) severity = "warning";
        }
        if (act && !act->alarm.cleared && valued) {
            // The deadband keeps the listed severity until the value is far enough back.
            bool crit = strcmp(act->alarm.severity, "critical") == 0;
            if (crit && (!severity || strcmp(severity, "critical") != 0) &&
                threshold_still_holds(v, &def->critical, def->deadband))
                severity = "critical";
            else if (!severity && !crit && threshold_still_holds(v, &def->warning, def->deadband))
                severity = "warning";
        }
        if (!severity) {
            def->holding = false;
            continue;   // a listed alarm left unseen clears below
        }
        if (act && !act->alarm.cleared) {
            act->seen = true;
            if (strcmp(act->alarm.severity, severity) != 0) {
                fill_alarm(&act->alarm, def, severity, v);
                changed = true;
            }
            continue;
        }
        // Not listed, or latched and cleared: a (re)raise, after the on-delay.
        if (def->delay_ms > 0) {
            if (!def->holding) {
                def->holding = true;
                def->hold_since = now;
            }
            if (now - def->hold_since < def->delay_ms) {
                if (act) act->seen = true;   // a latched entry stays listed meanwhile
                continue;
            }
        }
        def->holding = false;
        if (!act) {
            active_t *grown = realloc(a->active, (a->nactive + 1) * sizeof *a->active);
            if (!grown) continue;
            a->active = grown;
            act = &a->active[a->nactive++];
            memset(act, 0, sizeof *act);
            snprintf(act->alarm.tag, sizeof act->alarm.tag, "%s", def->tag);
            snprintf(act->alarm.label, sizeof act->alarm.label, "%s", def->label);
            act->alarm.value = hmi_value_null();
        }
        fill_alarm(&act->alarm, def, severity, v);
        snprintf(act->alarm.timestamp, sizeof act->alarm.timestamp, "%s", now_text(a, tsbuf, sizeof tsbuf));
        act->alarm.acknowledged = false;
        act->alarm.cleared = false;
        act->order = ++a->seq;
        act->seen = true;
        journal_alarm(a, "raise", &act->alarm, NULL);
        changed = true;
    }
    // Anything listed that did not fire this time clears -- except a latched,
    // unacknowledged alarm, which stays listed as "cleared" with its value frozen.
    for (size_t i = 0; i < a->nactive;) {
        active_t *act = &a->active[i];
        if (act->seen) { ++i; continue; }
        const def_t *owner = find_def(a, act->alarm.tag);
        if (owner && owner->latch && !act->alarm.acknowledged) {
            if (!act->alarm.cleared) {
                act->alarm.cleared = true;
                journal_alarm(a, "clear", &act->alarm, &owner->last);
                changed = true;
            }
            ++i;
            continue;
        }
        if (!act->alarm.cleared) journal_alarm(a, "clear", &act->alarm, owner ? &owner->last : NULL);
        remove_active(a, act);
        changed = true;
    }
    return changed;
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
    bool changed = reevaluate(a, now_ms(a));
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

// Acknowledges one listed alarm; a latched alarm that already cleared goes.
// False when it was already acknowledged (nothing changed).
static bool ack_one(hmi_alarms_t *a, active_t *act)
{
    if (act->alarm.cleared) {
        journal_alarm(a, "ack", &act->alarm, NULL);
        remove_active(a, act);
        return true;
    }
    if (act->alarm.acknowledged) return false;
    act->alarm.acknowledged = true;
    journal_alarm(a, "ack", &act->alarm, NULL);
    return true;
}

bool hmi_alarms_acknowledge(hmi_alarms_t *a, const char *tag)
{
    active_t *act = tag ? find_active(a, tag) : NULL;
    if (!act || !ack_one(a, act)) return false;
    notify(a);
    return true;
}

// ---- wave 1 (CONTRACT 13.3) -----------------------------------------------

size_t hmi_alarms_acknowledge_all(hmi_alarms_t *a)
{
    size_t changed = 0;
    for (size_t i = 0; i < a->nactive;) {
        size_t before = a->nactive;
        if (ack_one(a, &a->active[i])) ++changed;
        if (a->nactive == before) ++i;   // removed: the next one moved into slot i
    }
    if (changed) notify(a);
    return changed;
}

bool hmi_alarms_shelve(hmi_alarms_t *a, const char *tag, int ms)
{
    if (!tag || ms < 1 || ms > 86400000) return false;
    def_t *def = find_def(a, tag);
    if (!def) return false;
    def->shelved = true;
    def->shelved_until = now_ms(a) + (uint64_t)ms;
    for (size_t d = 0; d < a->ndefs; ++d)
        if (strcmp(a->defs[d].tag, tag) == 0) a->defs[d].holding = false;
    active_t *act = find_active(a, tag);
    if (act) {
        journal_alarm(a, "shelve", &act->alarm, NULL);
        remove_active(a, act);
        notify(a);
    } else {
        journal_def(a, "shelve", def);
    }
    return true;
}

bool hmi_alarms_is_shelved(const hmi_alarms_t *a, const char *tag)
{
    const def_t *def = tag ? find_def(a, tag) : NULL;
    return def && def->shelved;
}

void hmi_alarms_tick(hmi_alarms_t *a)
{
    if (a->ndefs == 0) return;
    uint64_t now = now_ms(a);
    bool due = false;
    for (size_t d = 0; d < a->ndefs; ++d) {
        def_t *def = &a->defs[d];
        if (def->shelved && now >= def->shelved_until) {
            def->shelved = false;
            journal_def(a, "unshelve", def);
            due = true;   // re-evaluated on the last value below
        }
        if (def->holding) due = true;
    }
    if (due && reevaluate(a, now)) notify(a);
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
