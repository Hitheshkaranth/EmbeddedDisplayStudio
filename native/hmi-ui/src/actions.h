// actions.h -- CONTRACT 13.1: what a widget signal does. FROZEN (wave 1, W1).
//
// A signal's actions are the widget's hmi_action_t entries whose `signal`
// matches, in model order; together they are one list that runs as a unit.
//
// Kinds and effects (13.1):
//   write      tags write `tag` = value; value NULL -> the signal's arg, else true
//   pulse      tags pulse `tag` for `ms`
//   navigate   hmi_runtime_navigate(rt, page)   (the runtime keeps the history)
//   back       hmi_runtime_back(rt)
//   toggle     write !hmi_actions_truthy(current value of `tag`) (never seen = false)
//   increment  write current + step, clamped to [min, max] when has_min/has_max
//   decrement  write current - step, clamped likewise (never seen = 0)
//   ack        acknowledge `tag`, else the arg's string; "*" = every alarm
//              (hmi_alarms_acknowledge / hmi_alarms_acknowledge_all), then
//              hmi_runtime_alarms_changed(rt) when anything changed
//   shelve     hmi_alarms_shelve(alarms, tag-or-arg, ms), then alarms_changed
//   legacy     on "alarmActivated", write/pulse mean ack of the arg's tag
// An unknown kind is logged (warning) and skipped; the rest of the list runs.
// Tag commands need hmi_runtime_tags(rt); without one they are logged at
// debug and skipped (headless renders), navigation and alarms still work.
//
// Confirmation: when any action of the list has a non-empty `confirm`, the
// list does not run yet. A modal dialog (lv_layer_top, claims modal.h owner
// "confirm") shows the FIRST such text with buttons "Cancel" and "OK"; OK runs
// the whole list (with the same arg), Cancel runs nothing; either closes the
// dialog and releases the modal slot. If the slot is taken (another dialog or
// a keypad is open) the list is refused: logged at warning, nothing runs.
#pragma once

#include <stdbool.h>

#include "model.h"
#include "runtime.h"
#include "value.h"

void hmi_actions_run(hmi_runtime_t *rt, hmi_widget_t *w, const char *signal, const hmi_value_t *arg);

// CONTRACT 13.1 truthy: bool as is; number != 0; string not "", "false", "0";
// null (or NULL) false; a list is true when non-empty.
bool hmi_actions_truthy(const hmi_value_t *v);

// Test hooks (and what the dialog's buttons call). The pending text is NULL
// when no confirmation is open; answer() does nothing then.
const char *hmi_actions_pending_confirm(void);
void hmi_actions_answer_confirm(bool ok);
