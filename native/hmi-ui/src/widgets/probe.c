// widgets/probe.c -- HmiProbe: the conformance suite's eyes and hands.
//
// Not a Designer widget. A probe-app.edsui places it with bindings and
// actions; it draws nothing and
//   * logs `INFO - hmi-ui - App Log: PROBE <prop>=<value>` whenever a bound
//     property is delivered (so a test sees tag values reach the UI), and
//   * emits the signal "changed" with the new value whenever its `trigger`
//     property changes, so the model's actions (write/pulse/navigate) can
//     be driven from the fake daemon by changing a ctl.* tag.
// The "App Log:" prefix matches Hmi.log() in the QML loaders, so
// tests/native/loader_harness.py's probe_lines() reads these unchanged.
#include <string.h>

#include "log.h"
#include "registry.h"

typedef struct { hmi_value_t trigger; } probe_state_t;

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *obj = lv_obj_create(parent);
    lv_obj_remove_style_all(obj);
    lv_obj_add_flag(obj, LV_OBJ_FLAG_HIDDEN);
    probe_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->trigger = hmi_value_null();
    w->state = st;
    return obj;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    hmi_log(HMI_LOG_INFO, "App Log: PROBE %s=%s", prop, hmi_value_debug(value));
    if (strcmp(prop, "trigger") == 0) {
        probe_state_t *st = w->state;
        if (!hmi_value_equal(&st->trigger, value)) {
            hmi_value_free(&st->trigger);
            st->trigger = hmi_value_copy(value);
            if (value->kind != HMI_V_NULL)
                hmi_widget_emit(w, "changed", value);
        }
    }
}

static void destroy(hmi_widget_t *w)
{
    probe_state_t *st = w->state;
    if (st) { hmi_value_free(&st->trigger); lv_free(st); }
}

const hmi_widget_ops_t hmi_widget_probe = {"HmiProbe", create, set_prop, destroy};
