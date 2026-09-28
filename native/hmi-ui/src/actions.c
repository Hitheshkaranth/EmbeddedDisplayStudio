// actions.c -- see actions.h (CONTRACT 13.1).
//
// SKELETON (wave 1): carries the pre-13.1 behaviour moved out of runtime.c
// (write / pulse / navigate / legacy ack) so nothing regresses while W1
// implements the rest: back, toggle, increment, decrement, ack, shelve,
// truthy, and the confirmation dialog.
#include "actions.h"

#include <string.h>

#include "alarms.h"
#include "log.h"
#include "tags.h"

void hmi_actions_run(hmi_runtime_t *rt, hmi_widget_t *w, const char *signal, const hmi_value_t *arg)
{
    if (!rt || !w || !signal) return;
    hmi_tags_t *tags = hmi_runtime_tags(rt);
    for (size_t i = 0; i < w->nactions; ++i) {
        const hmi_action_t *a = &w->actions[i];
        if (strcmp(a->signal, signal) != 0) continue;
        if (strcmp(a->kind, "navigate") == 0) {
            hmi_runtime_navigate(rt, a->page);
        } else if (strcmp(signal, "alarmActivated") == 0) {
            // The table hands over the alarm tag; any action here means "acknowledge".
            if (hmi_alarms_acknowledge(hmi_runtime_alarms(rt), hmi_value_as_str(arg, "")))
                hmi_runtime_alarms_changed(rt);
        } else if (!tags) {
            hmi_log(HMI_LOG_DEBUG, "action %s on %s ignored (no daemon link)", a->kind, w->id);
        } else if (strcmp(a->kind, "pulse") == 0) {
            hmi_tags_pulse(tags, a->tag, a->ms);
        } else {   // write: the model's value, else the signal's argument, else true
            hmi_value_t v = a->value.kind != HMI_V_NULL ? hmi_value_copy(&a->value)
                          : arg ? hmi_value_copy(arg) : hmi_value_bool(true);
            hmi_tags_write(tags, a->tag, &v);
            hmi_value_free(&v);
        }
    }
}

bool hmi_actions_truthy(const hmi_value_t *v)
{
    (void)v;
    return false;   // W1
}

const char *hmi_actions_pending_confirm(void) { return NULL; }   // W1

void hmi_actions_answer_confirm(bool ok) { (void)ok; }   // W1
