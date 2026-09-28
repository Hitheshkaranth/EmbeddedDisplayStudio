// actions.c -- see actions.h (CONTRACT 13.1).
//
#include "actions.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "alarms.h"
#include "compat.h"
#include "log.h"
#include "modal.h"
#include "runtime.h"
#include "tags.h"
#include "theme.h"

#include "lvgl/lvgl.h"

#define P_SIGNAL_MAX 64

// A single pending confirmation (13.1): the widget whose list has a `confirm`,
// its signal, a COPY of the arg, and the FIRST confirm text. `p_text` is NULL
// when nothing is pending (the test hook reads it).
static hmi_widget_t *p_widget;
static char p_signal[P_SIGNAL_MAX];
static hmi_value_t p_arg;
static const char *p_text;
static lv_obj_t *p_box;

// The msgbox's two footer buttons carry the slot index (0 = Cancel, 1 = OK)
// as user_data; a click answers the matching value and closes the box.
static void confirm_clicked(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED) return;
    hmi_actions_answer_confirm(lv_event_get_user_data(e) != NULL);
}

static void run_one(hmi_runtime_t *rt, hmi_widget_t *w, const char *signal,
                    const hmi_action_t *a, hmi_value_t *arg)
{
    hmi_tags_t *tags = hmi_runtime_tags(rt);
    struct hmi_alarms *alarms = hmi_runtime_alarms(rt);
    // Designs saved before 13.1: on the alarm table any write or pulse meant
    // "acknowledge the alarm the table hands over".
    if (strcmp(signal, "alarmActivated") == 0 &&
        (strcmp(a->kind, "write") == 0 || strcmp(a->kind, "pulse") == 0)) {
        if (hmi_alarms_acknowledge(alarms, hmi_value_as_str(arg, ""))) hmi_runtime_alarms_changed(rt);
        return;
    }
    if (strcmp(a->kind, "navigate") == 0) {
        hmi_runtime_navigate(rt, a->page);
    } else if (strcmp(a->kind, "back") == 0) {
        hmi_runtime_back(rt);
    } else if (strcmp(a->kind, "toggle") == 0) {
        if (!tags) {
            hmi_log(HMI_LOG_DEBUG, "action %s on %s ignored (no daemon link)", a->kind, w->id);
        } else {
            const hmi_value_t *cur = hmi_tags_value(tags, a->tag);
            hmi_value_t v = hmi_value_bool(!hmi_actions_truthy(cur));
            hmi_tags_write(tags, a->tag, &v);
            hmi_value_free(&v);
        }
    } else if (strcmp(a->kind, "increment") == 0 || strcmp(a->kind, "decrement") == 0) {
        if (!tags) {
            hmi_log(HMI_LOG_DEBUG, "action %s on %s ignored (no daemon link)", a->kind, w->id);
        } else {
            const hmi_value_t *cur = hmi_tags_value(tags, a->tag);
            double step = a->step;
            if (strcmp(a->kind, "decrement") == 0) step = -step;
            double curv = cur ? hmi_value_as_num(cur, 0.0) : 0.0;
            double v = curv + step;
            if (a->has_min) v = v < a->min ? a->min : v;
            if (a->has_max) v = v > a->max ? a->max : v;
            hmi_value_t val = hmi_value_num(v);
            hmi_tags_write(tags, a->tag, &val);
            hmi_value_free(&val);
        }
    } else if (strcmp(a->kind, "ack") == 0) {
        if (strcmp(a->tag, "*") == 0) {
            if (hmi_alarms_acknowledge_all(alarms)) hmi_runtime_alarms_changed(rt);
        } else {
            if (hmi_alarms_acknowledge(alarms, a->tag[0] ? a->tag
                        : hmi_value_as_str(arg, ""))) hmi_runtime_alarms_changed(rt);
        }
    } else if (strcmp(a->kind, "shelve") == 0) {
        int ms = a->ms ? a->ms : 600000;
        if (hmi_alarms_shelve(alarms, a->tag[0] ? a->tag
                    : hmi_value_as_str(arg, ""), ms)) hmi_runtime_alarms_changed(rt);
    } else if (!tags && (strcmp(a->kind, "pulse") == 0 || strcmp(a->kind, "write") == 0)) {
        hmi_log(HMI_LOG_DEBUG, "action %s on %s ignored (no daemon link)", a->kind, w->id);
    } else if (strcmp(a->kind, "pulse") == 0) {
        hmi_tags_pulse(tags, a->tag, a->ms);
    } else if (strcmp(a->kind, "write") == 0) {
        hmi_value_t v = a->value.kind != HMI_V_NULL ? hmi_value_copy(&a->value)
                      : arg ? hmi_value_copy(arg) : hmi_value_bool(true);
        hmi_tags_write(tags, a->tag, &v);
        hmi_value_free(&v);
    } else {
        hmi_log(HMI_LOG_WARNING, "action %s on %s: unknown kind, skipped", a->kind, w->id);
    }
}

// The kit's card and buttons, not LVGL's default light message box.
static void style_button(lv_obj_t *b, const char *bg, const char *fg)
{
    lv_obj_set_style_bg_color(b, hmi_colour(bg), 0);
    lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(b, hmi_radius("radiusMd"), 0);
    lv_obj_set_style_shadow_width(b, 0, 0);
    lv_obj_set_style_min_width(b, 96, 0);
    lv_obj_set_style_height(b, 40, 0);
    lv_obj_t *label = lv_obj_get_child(b, 0);
    if (label) {
        lv_obj_set_style_text_color(label, hmi_colour(fg), 0);
        lv_obj_set_style_text_font(label, hmi_font(hmi_font_size("fontSizeSm"), 500), 0);
    }
}

static void style_confirm(lv_obj_t *box, lv_obj_t *text, lv_obj_t *cancel, lv_obj_t *ok)
{
    lv_obj_t *backdrop = lv_obj_get_parent(box);
    if (backdrop && backdrop != lv_layer_top()) {
        lv_obj_set_style_bg_color(backdrop, lv_color_black(), 0);
        lv_obj_set_style_bg_opa(backdrop, LV_OPA_50, 0);
    }
    lv_obj_set_width(box, 420);
    lv_obj_set_style_bg_color(box, hmi_colour("card"), 0);
    lv_obj_set_style_bg_opa(box, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(box, hmi_colour("border"), 0);
    lv_obj_set_style_border_width(box, 1, 0);
    lv_obj_set_style_radius(box, hmi_radius("radiusLg"), 0);
    lv_obj_set_style_pad_all(box, 20, 0);
    lv_obj_set_style_shadow_width(box, 0, 0);
    lv_obj_t *footer = lv_msgbox_get_footer(box);
    if (footer) {
        lv_obj_set_style_bg_opa(footer, LV_OPA_TRANSP, 0);
        lv_obj_set_style_pad_top(footer, 12, 0);
        lv_obj_set_flex_align(footer, LV_FLEX_ALIGN_END, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    }
    if (text) {
        lv_obj_set_style_text_color(text, hmi_colour("foreground"), 0);
        lv_obj_set_style_text_font(text, hmi_font(hmi_font_size("fontSizeBase"), 500), 0);
    }
    style_button(cancel, "secondary", "secondaryForeground");
    style_button(ok, "primary", "primaryForeground");
}

void hmi_actions_run(hmi_runtime_t *rt, hmi_widget_t *w, const char *signal, const hmi_value_t *arg)
{
    if (!rt || !w || !signal) return;
    bool need = false;
    const char *confirm = NULL;
    for (size_t i = 0; i < w->nactions; ++i) {
        const hmi_action_t *a = &w->actions[i];
        if (strcmp(a->signal, signal) != 0) continue;
        if (a->confirm && a->confirm[0]) { need = true; if (!confirm) confirm = a->confirm; }
    }
    if (need) {   // show the FIRST confirm text and run only after an answer
        // One popup at a time (13.5): a second confirmation is refused; lists
        // without one still run below whatever is open.
        if (!hmi_modal_claim("confirm")) {
            hmi_log(HMI_LOG_WARNING, "action on %s: %s is open, confirmation refused", w->id,
                    hmi_modal_owner() ? hmi_modal_owner() : "a dialog");
            return;
        }
        p_widget = w;
        snprintf(p_signal, sizeof p_signal, "%s", signal);
        p_arg = arg ? hmi_value_copy(arg) : hmi_value_null();
        p_text = confirm;
        lv_obj_t *box = p_box = lv_msgbox_create(NULL);
        lv_obj_t *text = lv_msgbox_add_text(box, p_text);
        lv_obj_t *cancel = lv_msgbox_add_footer_button(box, "Cancel");
        lv_obj_t *ok = lv_msgbox_add_footer_button(box, "OK");
        style_confirm(box, text, cancel, ok);
        lv_obj_add_event_cb(cancel, confirm_clicked, LV_EVENT_CLICKED, NULL);
        lv_obj_add_event_cb(ok, confirm_clicked, LV_EVENT_CLICKED, (void *)1);
        return;
    }
    for (size_t i = 0; i < w->nactions; ++i) {
        const hmi_action_t *a = &w->actions[i];
        if (strcmp(a->signal, signal) != 0) continue;
        hmi_value_t saved; hmi_value_t *argp = NULL;
        if (arg) { saved = hmi_value_copy(arg); argp = &saved; }
        run_one(rt, w, signal, a, argp);
        if (argp) hmi_value_free(argp);
    }
}

bool hmi_actions_truthy(const hmi_value_t *v)
{
    if (!v) return false;
    switch (v->kind) {
    case HMI_V_NULL: return false;
    case HMI_V_BOOL: return v->b;
    case HMI_V_NUM:  return v->n != 0.0;
    case HMI_V_LIST: return v->count > 0;
    case HMI_V_STR: {
        const char *s = v->s;
        return s && s[0] && strcmp(s, "false") != 0 && strcmp(s, "0") != 0;
    }
    }
    return false;
}

const char *hmi_actions_pending_confirm(void) { return p_text; }

void hmi_actions_answer_confirm(bool ok)
{
    if (!p_text) return;
    if (ok) {
        hmi_runtime_t *rt = hmi_runtime_of(p_widget);
        if (rt)
            for (size_t i = 0; i < p_widget->nactions; ++i) {
                const hmi_action_t *a = &p_widget->actions[i];
                if (strcmp(a->signal, p_signal) != 0) continue;
                run_one(rt, p_widget, p_signal, a, &p_arg);
            }
    }
    // Deleted after the event that answered it has finished with it.
    if (p_box) lv_msgbox_close_async(p_box);   // the box and its modal backdrop
    p_box = NULL;
    hmi_modal_release("confirm");
    hmi_value_free(&p_arg);
    p_text = NULL; p_widget = NULL;
}