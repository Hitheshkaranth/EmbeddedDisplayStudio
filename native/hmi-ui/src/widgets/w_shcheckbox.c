// widgets/w_shcheckbox.c -- kit widget ShCheckbox (Industrial, "Checkbox").
//
// Spec: ui/qml/Shadcn/ShCheckbox.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): checked, label, enabled, opacity, visible.
// Default size 160x32. Signals: checkedChanged.
// Owner: W3 (wave 2).
#include <string.h>

#include "draw_util.h"
#include "registry.h"
#include "theme.h"

typedef struct {
    lv_obj_t *bg;
    lv_obj_t *box;
    lv_obj_t *checkmark;
    lv_obj_t *label;
    bool checked;
} shcheckbox_state_t;

static void checkbox_click_cb(lv_event_t *e)
{
    hmi_widget_t *widget = (hmi_widget_t *)lv_event_get_user_data(e);
    if (!widget) return;
    shcheckbox_state_t *st = widget->state;
    if (!st) return;
    st->checked = !st->checked;
    if (st->checked) {
        lv_obj_add_state(st->box, LV_STATE_CHECKED);
        lv_obj_clear_flag(st->checkmark, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_clear_state(st->box, LV_STATE_CHECKED);
        lv_obj_add_flag(st->checkmark, LV_OBJ_FLAG_HIDDEN);
    }
    hmi_value_t v = hmi_value_bool(st->checked);
    hmi_widget_emit(widget, "checkedChanged", &v);
    hmi_value_free(&v);
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *bg = lv_obj_create(parent);
    lv_obj_remove_style_all(bg);
    lv_obj_set_size(bg, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(bg, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(bg, lv_color_hex(0x000000), 0);
    lv_obj_set_style_bg_opa(bg, LV_OPA_TRANSP, 0);

    // Use flex row to match QML Row
    lv_obj_set_flex_flow(bg, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_all(bg, 4, 0);  // anchors.leftMargin/rightMargin: Theme.spacing4
    lv_obj_set_style_pad_gap(bg, 8, 0);  // spacing: Theme.spacing8
    lv_obj_set_style_flex_main_place(bg, LV_FLEX_ALIGN_START, 0);
    lv_obj_set_style_flex_cross_place(bg, LV_FLEX_ALIGN_CENTER, 0);   // Row: anchors.verticalCenter
    lv_obj_set_style_flex_track_place(bg, LV_FLEX_ALIGN_CENTER, 0);

    // Box: 20x20, radiusSm
    lv_obj_t *box = lv_obj_create(bg);
    lv_obj_remove_style_all(box);
    lv_obj_set_size(box, 20, 20);
    lv_obj_set_style_radius(box, hmi_radius("radiusSm"), 0);
    lv_obj_set_style_bg_color(box, hmi_colour("card"), 0);
    lv_obj_set_style_bg_opa(box, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(box, hmi_colour("input"), 0);
    lv_obj_set_style_border_width(box, 1, 0);

    // Checkmark: text "\u2713" centered in box, only visible when checked
    lv_obj_t *checkmark = lv_label_create(box);
    lv_obj_remove_style_all(checkmark);
    lv_obj_set_style_text_font(checkmark, hmi_font(14, 700), 0);
    lv_obj_set_style_text_color(checkmark, hmi_colour("brandForeground"), 0);
    lv_label_set_text(checkmark, "\u2713");
    lv_obj_center(checkmark);
    lv_obj_add_flag(checkmark, LV_OBJ_FLAG_HIDDEN);

    // Label
    lv_obj_t *label = lv_label_create(bg);
    lv_obj_remove_style_all(label);
    lv_obj_set_style_text_font(label, hmi_font(hmi_font_size("fontSizeSm"), 400), 0);
    lv_obj_set_style_text_color(label, hmi_colour("foreground"), 0);
    lv_obj_set_flex_grow(label, 1);

    shcheckbox_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->bg = bg;
    st->box = box;
    st->checkmark = checkmark;
    st->label = label;
    st->checked = hmi_widget_bool(w, "checked", false);

    lv_label_set_text(label, hmi_widget_str(w, "label", ""));

    if (st->checked) {
        lv_obj_add_state(box, LV_STATE_CHECKED);
        lv_obj_clear_flag(checkmark, LV_OBJ_FLAG_HIDDEN);
    }

    // Make box and bg clickable
    lv_obj_add_event_cb(bg, checkbox_click_cb, LV_EVENT_CLICKED, w);
    lv_obj_add_flag(bg, LV_OBJ_FLAG_CLICKABLE);

    w->state = st;
    return bg;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    shcheckbox_state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "checked") == 0) {
        bool v = hmi_value_as_bool(value, st->checked);
        if (v != st->checked) {
            st->checked = v;
            if (v) {
                lv_obj_add_state(st->box, LV_STATE_CHECKED);
                lv_obj_clear_flag(st->checkmark, LV_OBJ_FLAG_HIDDEN);
            } else {
                lv_obj_clear_state(st->box, LV_STATE_CHECKED);
                lv_obj_add_flag(st->checkmark, LV_OBJ_FLAG_HIDDEN);
            }
        }
    } else if (strcmp(prop, "label") == 0) {
        lv_label_set_text(st->label, hmi_value_as_str(value, ""));
    }
}

static void destroy(hmi_widget_t *w)
{
    shcheckbox_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_shcheckbox = {"ShCheckbox", create, set_prop, destroy};