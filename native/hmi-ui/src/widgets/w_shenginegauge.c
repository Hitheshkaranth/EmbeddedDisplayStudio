// widgets/w_shenginegauge.c -- kit widget ShEngineGauge (Avionics, "Engine Gauge").
//
// Spec: ui/qml/Shadcn/ShEngineGauge.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): value, minimumValue, maximumValue, greenLow, greenHigh, cautionHigh, label, units, opacity, visible.
// Default size 140x140. Signals: none.
// Owner: W4. Until implemented, create() returns NULL and the runtime
// draws a labelled placeholder.
#include "registry.h"
#include "theme.h"

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    (void)w; (void)parent;
    return NULL;   // TODO(W4): build the LVGL objects
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    (void)w; (void)prop; (void)value;   // TODO(W4): live property updates
}

const hmi_widget_ops_t hmi_widget_shenginegauge = {"ShEngineGauge", create, set_prop, NULL};
