// widgets/w_shbutton.c -- kit widget ShButton (Basic, "Button").
//
// Spec: ui/qml/Shadcn/ShButton.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): text, variant, size, enabled, backgroundColor, textColor, borderColor, borderWidth, cornerRadius, opacity, visible.
// Default size 120x40. Signals: clicked.
// Owner: W3. Until implemented, create() returns NULL and the runtime
// draws a labelled placeholder.
#include "registry.h"
#include "theme.h"

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    (void)w; (void)parent;
    return NULL;   // TODO(W3): build the LVGL objects
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    (void)w; (void)prop; (void)value;   // TODO(W3): live property updates
}

const hmi_widget_ops_t hmi_widget_shbutton = {"ShButton", create, set_prop, NULL};
