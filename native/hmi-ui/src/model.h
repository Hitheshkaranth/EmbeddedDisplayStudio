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
    // CONTRACT 13.2 (all optional in the file):
    int decimals;       // -1 = automatic; 0..6 = fixed decimals when the reading becomes text
    char *expr;         // "" = none; else the reading is this expression's value
    struct hmi_rule *rules; size_t nrules;   // file order; first match per prop wins
} hmi_binding_t;

// CONTRACT 13.2 rule: when the reading satisfies `when` ("> 80"), `prop` = `value`.
typedef struct hmi_rule {
    char *when;         // threshold text, parsed with hmi_bind_parse_threshold
    char *prop;
    hmi_value_t value;
} hmi_rule_t;

// One action. A signal with a list of actions (CONTRACT 13.1) loads as
// consecutive entries sharing `signal`, in list order.
typedef struct hmi_action {
    char *signal;       // "clicked", "toggled", "activated", "alarmActivated", ...
    char *kind;         // write | pulse | navigate | back | toggle | increment |
                        // decrement | ack | shelve  (13.1)
    char *tag;          // "" = none
    hmi_value_t value;  // write: the value; HMI_V_NULL = the control's own state
    int ms;             // pulse (default 250); shelve (default 600000)
    char *page;         // navigate: page id
    double step;        // increment/decrement, default 1
    bool has_min, has_max;
    double min, max;    // increment/decrement clamp
    char *confirm;      // "" = none; else ask before running the signal's list
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
    int idle_dim_s;     // CONTRACT 13.5 screen.idle; 0 = never
    int idle_dim_pct;   // 10..100, default 30
    int idle_off_s;     // 0 = never
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
