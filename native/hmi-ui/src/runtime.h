// runtime.h -- ties the model, the kit, the binding engine and the daemon
// link together: builds a page's LVGL tree, routes tag changes into
// bindings, runs actions for widget signals, navigates between pages.
//
// FROZEN (Phase 3 contract). Owner of runtime.c: the architect (skeleton
// complete); W2 extends hmi_runtime_signal / navigation if bind.c needs it.
#pragma once

#include <stdbool.h>

#include "bind.h"
#include "lvgl/lvgl.h"
#include "model.h"
#include "tags.h"

typedef struct hmi_runtime hmi_runtime_t;

// Builds the first page on `screen`. `tags` may be NULL (headless renders).
// `apps_dir` locates manifest.json for the alarm definitions (may be NULL).
hmi_runtime_t *hmi_runtime_create(hmi_project_t *project, lv_obj_t *screen, hmi_tags_t *tags, const char *apps_dir);
void hmi_runtime_destroy(hmi_runtime_t *rt);

// Request page `id`; the switch happens on the next hmi_runtime_tick()
// (never inside a binding delivery or a widget event). false when unknown.
bool hmi_runtime_navigate(hmi_runtime_t *rt, const char *id);
// Main-loop hook: applies a pending navigation. Call every loop iteration.
void hmi_runtime_tick(hmi_runtime_t *rt);
const char *hmi_runtime_current_page(const hmi_runtime_t *rt);

// Called by the tag engine callbacks (main.c wires them).
void hmi_runtime_on_tag(hmi_runtime_t *rt, const char *tag, const hmi_value_t *value);
void hmi_runtime_on_online(hmi_runtime_t *rt, bool online);

// A widget signal (from hmi_widget_emit): run the model's actions.
void hmi_runtime_signal(hmi_widget_t *w, const char *signal, const hmi_value_t *arg);

// The runtime that owns `w` (widgets do not need this; the probe does).
hmi_runtime_t *hmi_runtime_of(const hmi_widget_t *w);
hmi_tags_t *hmi_runtime_tags(const hmi_runtime_t *rt);
const hmi_project_t *hmi_runtime_project(const hmi_runtime_t *rt);
