// widgets/w_shtelltale.c -- kit widget ShTelltale (Automotive, "Telltale").
//
// Spec: ui/qml/Shadcn/ShTelltale.qml -- one indicator lamp: a line icon in
// the lamp colour with a soft glow when lit, dim when not, and a 1 Hz blink.
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "icons.h"
#include "registry.h"

typedef struct {
    lv_obj_t *glow, *lamp, *label;
    void *timer;
    char icon_name[64];
    char label_text[64];
    char color[16];
    bool lit;
    bool blink;
    bool dark;
} state_t;

static void blink_timer_cb(lv_timer_t *t)
{
    hmi_widget_t *w = (hmi_widget_t *)lv_timer_get_user_data(t);
    state_t *st = w->state;
    if (!st || !st->lit) return;
    st->dark = !st->dark;
    lv_obj_set_style_opa(st->lamp, st->dark ? (lv_opa_t)(0.15 * 255) : LV_OPA_COVER, 0);
}

static lv_color_t get_lamp_color(const char *color)
{
    if (strcmp(color, "amber") == 0) return hmi_colour("autoAmber");
    if (strcmp(color, "green") == 0) return hmi_colour("autoGreen");
    if (strcmp(color, "red") == 0) return hmi_colour("autoRed");
    if (strcmp(color, "blue") == 0) return hmi_colour("autoBlue");
    return hmi_colour("autoText");
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    double d = fmin(W, H);
    bool hasLabel = st->label_text[0] != '\0';
    int iconSz = (int)round(d * (hasLabel ? 0.5 : 0.62));

    /* Lamp */
    hmi_icon_set(st->lamp, st->icon_name, iconSz,
                 st->lit ? get_lamp_color(st->color) : hmi_colour("autoMuted"));
    if (!st->lit) {
        lv_obj_set_style_opa(st->lamp, (lv_opa_t)(0.35 * 255), 0);
    } else if (st->blink) {
        lv_obj_set_style_opa(st->lamp, st->dark ? (lv_opa_t)(0.15 * 255) : LV_OPA_COVER, 0);
    } else {
        lv_obj_set_style_opa(st->lamp, LV_OPA_COVER, 0);
    }
    int vertOff = hasLabel ? (int)round(d * 0.12) : 0;
    lv_obj_set_pos(st->lamp, (int)(W / 2 - iconSz / 2), (int)(H / 2 - iconSz / 2 - vertOff));

    /* Glow */
    double glowSize = d * (hasLabel ? 0.75 : 0.95);
    lv_obj_set_size(st->glow, (int)glowSize, (int)glowSize);
    lv_obj_set_style_radius(st->glow, (int)(glowSize / 2), 0);
    lv_obj_set_style_bg_color(st->glow, get_lamp_color(st->color), 0);
    lv_obj_set_style_bg_opa(st->glow, st->lit ? (lv_opa_t)(0.18 * 255) : 0, 0);
    lv_obj_center(st->glow);
    if (st->lit) {
        lv_obj_remove_flag(st->glow, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_opa(st->glow, lv_obj_get_style_opa(st->lamp, 0), 0);
    } else {
        lv_obj_add_flag(st->glow, LV_OBJ_FLAG_HIDDEN);
    }

    /* Label */
    lv_label_set_text(st->label, st->label_text);
    int labelFs = hmi_px_min(d * 0.18, 7);
    lv_obj_set_style_text_font(st->label, hmi_font(labelFs, 500), 0);
    lv_obj_set_style_text_color(st->label, hmi_colour("autoMuted"), 0);
    lv_obj_set_style_text_align(st->label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_pos(st->label, 0, iconSz / 2 + vertOff + 2);
    lv_obj_set_size(st->label, W, H - iconSz / 2 - vertOff - 2);

    if (hasLabel) lv_obj_remove_flag(st->label, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(st->label, LV_OBJ_FLAG_HIDDEN);
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *root = lv_obj_create(parent);
    lv_obj_remove_style_all(root);
    lv_obj_set_size(root, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(root, LV_OBJ_FLAG_SCROLLABLE);

    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;

    /* Glow */
    st->glow = lv_obj_create(root);
    lv_obj_remove_style_all(st->glow);
    lv_obj_remove_flag(st->glow, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(st->glow, LV_OBJ_FLAG_HIDDEN);

    /* Lamp icon */
    st->lamp = hmi_icon_create(root, "", 16, hmi_colour("autoText"));

    /* Label */
    st->label = lv_label_create(root);
    lv_obj_remove_style_all(st->label);
    lv_label_set_long_mode(st->label, LV_LABEL_LONG_CLIP);

    snprintf(st->icon_name, sizeof st->icon_name, "%s", hmi_widget_str(w, "icon", "bulb"));
    snprintf(st->label_text, sizeof st->label_text, "%s", hmi_widget_str(w, "label", ""));
    snprintf(st->color, sizeof st->color, "%s", hmi_widget_str(w, "color", "amber"));
    st->lit = hmi_widget_bool(w, "lit", true);
    st->blink = hmi_widget_bool(w, "blink", false);

    layout(w);

    /* Blink timer */
    if (st->lit && st->blink) {
        st->timer = (void*)lv_timer_create(blink_timer_cb, 500, w);
        st->dark = true;
    } else {
        st->timer = NULL;
        st->dark = false;
    }

    return root;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "icon") == 0) {
        snprintf(st->icon_name, sizeof st->icon_name, "%s", hmi_value_as_str(value, ""));
        layout(w);
    } else if (strcmp(prop, "color") == 0) {
        snprintf(st->color, sizeof st->color, "%s", hmi_value_as_str(value, ""));
        layout(w);
    } else if (strcmp(prop, "lit") == 0) {
        bool newLit = hmi_value_as_bool(value, st->lit);
        st->lit = newLit;
        if (newLit && st->blink && !st->timer) {
            st->timer = (void*)lv_timer_create(blink_timer_cb, 500, w);
            st->dark = true;
        } else if (!newLit) {
            if (st->timer) { lv_timer_delete((lv_timer_t*)st->timer); st->timer = NULL; }
            st->dark = false;
        } else if (!st->blink && st->timer) {
            lv_timer_delete((lv_timer_t*)st->timer); st->timer = NULL;
            st->dark = false;
        }
        layout(w);
    } else if (strcmp(prop, "blink") == 0) {
        bool newBlink = hmi_value_as_bool(value, st->blink);
        st->blink = newBlink;
        if (st->lit && newBlink && !st->timer) {
            st->timer = (void*)lv_timer_create(blink_timer_cb, 500, w);
            st->dark = true;
        } else if (!newBlink && st->timer) {
            lv_timer_delete((lv_timer_t*)st->timer); st->timer = NULL;
            st->dark = false;
        }
        layout(w);
    } else if (strcmp(prop, "label") == 0) {
        snprintf(st->label_text, sizeof st->label_text, "%s", hmi_value_as_str(value, ""));
        layout(w);
    }
}

static void destroy(hmi_widget_t *w)
{
    state_t *st = w->state;
    if (st) {
        if (st->timer) lv_timer_delete((lv_timer_t *)st->timer);
        lv_free(st);
    }
}

const hmi_widget_ops_t hmi_widget_shtelltale = {"ShTelltale", create, set_prop, destroy};