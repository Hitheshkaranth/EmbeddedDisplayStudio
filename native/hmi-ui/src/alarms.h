// alarms.h -- manifest-driven alarm evaluation on every telemetry frame.
//
// The C port of native/hmi-gui/src/alarmengine.{h,cpp} (itself the port of
// gui/hmi_loader/tagengine.py lines 478-660). Read alarmengine.h's header
// comment: the rules there are frozen and apply here verbatim. Alarm
// definitions come from the bundle's manifest.json "alarms" array:
//   {"tag": "ai.pot", "label": "Input Voltage", "unit": "V",
//    "warning":  {"op": ">", "value": 2.5},
//    "critical": {"op": ">", "value": 3.0}}
// Rules: critical first, then warning; a missing/null frame value clears
// the alarm; an alarm that stays active keeps its timestamp and
// acknowledged flag; severity change updates severity/value/message and
// counts as a change; the change callback fires only when something
// changed; active list sorted critical first, then newest timestamp first;
// acknowledge() on an unknown/inactive tag does nothing.
//
// ShAlarmTable receives the active alarms through hmi_alarms_active_value():
// an HMI_V_LIST of lists [tag, label, severity, value, message, timestamp,
// acknowledged] (fixed order), delivered on the widget's "alarms" property
// by the runtime whenever the set changes.
//
// FROZEN (wave 2 contract). Owner of alarms.c: W4.
#pragma once

#include <stdbool.h>
#include <stddef.h>

#include "value.h"

typedef struct hmi_alarms hmi_alarms_t;

typedef struct {
    char tag[64];
    char label[96];
    char severity[16];     // "critical" | "warning"
    hmi_value_t value;     // raw frame value, type preserved
    char message[160];     // "<label> <value:%g><unit>"
    char timestamp[24];    // "YYYY-MM-DDTHH:MM:SS" local time, set on activation
    bool acknowledged;
} hmi_alarm_t;

typedef void (*hmi_alarms_changed_cb)(void *user);

// Load the definitions from <apps_dir>/manifest.json (missing file or no
// "alarms": an engine with no definitions). Never fails.
hmi_alarms_t *hmi_alarms_create(const char *apps_dir);
// The same from the "alarms" array's JSON text (tests; malformed: no definitions).
hmi_alarms_t *hmi_alarms_create_from_json(const char *alarms_json);
void hmi_alarms_destroy(hmi_alarms_t *a);
void hmi_alarms_set_callback(hmi_alarms_t *a, hmi_alarms_changed_cb cb, void *user);
// Test hook: replaces the local-time clock used for activation timestamps
// (returns "YYYY-MM-DDTHH:MM:SS"). NULL restores the real clock.
typedef const char *(*hmi_alarms_clock_fn)(void *user);
void hmi_alarms_set_clock(hmi_alarms_t *a, hmi_alarms_clock_fn now, void *user);

// The tags the definitions reference (for the runtime's interest list).
size_t hmi_alarms_tag_count(const hmi_alarms_t *a);
const char *hmi_alarms_tag(const hmi_alarms_t *a, size_t i);

// One telemetry update: `tags`/`values` are the entries that arrived (the
// runtime passes each changed tag on its own; a full frame is fine too).
// The engine remembers the last value of every alarm tag, so a tag absent
// from this call keeps its previous value; one never seen, or delivered as
// HMI_V_NULL (a failed read), makes its alarms inactive. Returns true (and
// fires the callback) when the active set changed.
bool hmi_alarms_evaluate(hmi_alarms_t *a, const char *const *tags, const hmi_value_t *values, size_t n);

// Sorted active alarms; the array is valid until the next evaluate/acknowledge
// and is owned by the engine: do not free it or the hmi_value_t values inside
// (they are borrowed). For a copy to keep, use hmi_alarms_active_value().
const hmi_alarm_t *hmi_alarms_active(const hmi_alarms_t *a, size_t *count);
// The same as the HMI_V_LIST ShAlarmTable is bound to (caller frees).
hmi_value_t hmi_alarms_active_value(const hmi_alarms_t *a);

// Marks an active alarm acknowledged; true when one was.
bool hmi_alarms_acknowledge(hmi_alarms_t *a, const char *tag);
