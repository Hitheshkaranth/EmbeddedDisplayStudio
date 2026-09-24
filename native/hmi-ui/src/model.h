// model.h -- the .edsui project as C structures.
//
// A deployed bundle carries project.edsui (the Designer's source model). The
// runtime loads it directly: pages of widgets, each with a type from the
// kit schema, geometry, properties, bindings (tag -> property, with
// scaling, units and thresholds) and actions (signal -> write/pulse/navigate).
// hmi_project_load() is the only producer; nothing else allocates these.
//
// Runtime-private per-widget state hangs off
// hmi_widget_t::native / ::state; the model itself is never mutated after load.
#pragma once

#include <stdbool.h>
#include <stddef.h>

#include "value.h"

typedef struct hmi_prop {
    char *name;
    hmi_value_t value;
} hmi_prop_t;

typedef struct hmi_binding {
    char *prop;         // the widget property this binding drives
    char *tag;          // daemon tag, e.g. "eng.rpm"; "" = unbound
    char *format;       // Qt-style "%1 km" or ""; "" = none
    double multiplier;  // display = tag * multiplier + offset
    double offset;
    char *unit;         // "" = none; derives the widget's unit/units property
    char *warning;      // threshold text "> 6.5", "" = none
    char *critical;
} hmi_binding_t;

typedef struct hmi_action {
    char *signal;       // "clicked", "toggled", "activated", "alarmActivated", ...
    char *kind;         // "write" | "pulse" | "navigate"
    char *tag;          // write/pulse
    hmi_value_t value;  // write: the value; HMI_V_NULL = the control's own state
    int ms;             // pulse
    char *page;         // navigate: page id
} hmi_action_t;

typedef struct hmi_widget {
    char *type;         // kit type, e.g. "ShClusterGauge"
    char *id;
    double x, y, width, height;
    int z;
    bool locked;
    hmi_prop_t *props; size_t nprops;
    hmi_binding_t *bindings; size_t nbindings;
    hmi_action_t *actions; size_t nactions;
    struct hmi_widget **children; size_t nchildren;
    struct hmi_widget *parent;      // NULL at page level
    // Runtime-owned, NULL after load: the LVGL object and the kit's state.
    void *native;
    void *state;
} hmi_widget_t;

typedef struct hmi_page {
    char *id;
    char *name;
    hmi_widget_t **widgets; size_t nwidgets;
} hmi_page_t;

typedef struct hmi_project {
    char *name;
    int width, height;
    char *background;   // "#rrggbb"
    char *theme;        // "dark" | "light"
    char *dir;          // directory of the .edsui (assets/ resolve against it)
    hmi_page_t **pages; size_t npages;
} hmi_project_t;

// Loads <path>. On failure returns NULL and writes a one-line reason to err.
hmi_project_t *hmi_project_load(const char *path, char *err, size_t errlen);
void hmi_project_free(hmi_project_t *p);

// Lookups. Missing -> NULL. hmi_widget_prop returns the *declared* value;
// defaults from the kit schema are the registry's business.
const hmi_value_t *hmi_widget_prop(const hmi_widget_t *w, const char *name);
const hmi_binding_t *hmi_widget_binding(const hmi_widget_t *w, const char *prop);
hmi_page_t *hmi_project_page(const hmi_project_t *p, const char *id);
// Depth-first visit of every widget of a page (children after their parent).
typedef void (*hmi_widget_visitor_t)(hmi_widget_t *w, void *user);
void hmi_page_visit(hmi_page_t *page, hmi_widget_visitor_t fn, void *user);
size_t hmi_page_widget_count(const hmi_page_t *page);
