// registry.h -- the widget kit: one hmi_widget_ops_t per kit type.
//
// A widget implementation is a C file in src/widgets/ that builds LVGL
// objects for one type from the model, and re-applies a property when the
// runtime tells it to (a binding delivered a new value). It never reads
// tags, never talks to the daemon, never touches another widget: the runtime
// does all of that through this interface.
//
// FROZEN (Phase 3 contract).
#pragma once

#include "lvgl/lvgl.h"
#include "model.h"

typedef struct hmi_widget_ops {
    const char *type;      // kit type name, exactly as in kit_schema

    // Build the LVGL object tree for `w` under `parent`, sized and placed
    // from w->x/y/width/height (the runtime has already converted the page
    // coordinates; a child of a positioner gets its slot from the parent).
    // Apply every declared property (w->props) and the schema defaults for
    // the rest, then return the root object (stored in w->native by the
    // runtime). w->state is the widget's to allocate (freed in destroy).
    lv_obj_t *(*create)(hmi_widget_t *w, lv_obj_t *parent);

    // A property changed after creation (a binding delivered a value, a
    // threshold changed a state, the runtime set `visible`). Update the
    // LVGL objects in place. Unknown properties are ignored silently.
    void (*set_prop)(hmi_widget_t *w, const char *prop, const hmi_value_t *value);

    // Free w->state (the runtime deletes the LVGL objects). May be NULL.
    void (*destroy)(hmi_widget_t *w);
} hmi_widget_ops_t;

void hmi_registry_register(const hmi_widget_ops_t *ops);   // last wins
const hmi_widget_ops_t *hmi_registry_find(const char *type);
// Registers every kit widget (src/widgets/kit.c). Called once by the runtime.
void hmi_kit_register_all(void);

// -- helpers for widget implementations ---------------------------------------
// The effective value of a property: the model's declared value, else the
// kit schema default, else HMI_V_NULL. Never allocates; the pointer is valid
// for the widget's lifetime (defaults are parsed once per type).
const hmi_value_t *hmi_widget_get(const hmi_widget_t *w, const char *prop);
double hmi_widget_num(const hmi_widget_t *w, const char *prop, double def);
bool hmi_widget_bool(const hmi_widget_t *w, const char *prop, bool def);
const char *hmi_widget_str(const hmi_widget_t *w, const char *prop, const char *def);

// Resolve a project-relative asset ("assets/logo.png") to the path LVGL's
// file layer opens ("A:/opt/hmi_apps/current/assets/logo.png"). Returns buf.
const char *hmi_widget_asset_path(const hmi_widget_t *w, const char *relative, char *buf, size_t len);

// A widget that received a user interaction reports it here; the runtime
// runs the model's actions for that signal (write/pulse/navigate).
// `arg` is the signal's payload (a toggle's new state, a select's index) or NULL.
void hmi_widget_emit(hmi_widget_t *w, const char *signal, const hmi_value_t *arg);

// The generic part every widget shares, called by the runtime around create:
// position/size, visible, opacity, z-order. Widgets do not reimplement these.
void hmi_widget_apply_common(hmi_widget_t *w);
