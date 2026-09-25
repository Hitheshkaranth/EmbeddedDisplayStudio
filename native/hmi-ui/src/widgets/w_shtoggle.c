// widgets/w_shtoggle.c -- kit widget ShToggle (Industrial, "Toggle").
//
// Spec: ui/qml/Shadcn/ShToggle.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): checked, label, onLabel, offLabel, enabled, opacity, visible.
// Default size 160x40. Signals: toggled.
#include <string.h>
#include "draw_util.h"
#include "registry.h"
#include "theme.h"

typedef struct {
    lv_obj_t *track;
    lv_obj_t *knob;
    lv_obj_t *label;
    lv_obj_t *status;
    bool checked;
    char onLabel[32];
    char offLabel[32];
} shtoggle_state_t;

static void update_status(shtoggle_state_t *st, bool checked)
{
    const char *txt = checked ? st->onLabel : st->offLabel;
    lv_label_set_text(st->status, txt);

    lv_color_t fg;
    if (checked) {
        fg = hmi_colour("success");
    } else {
        fg = hmi_colour("mutedForeground");
    }
    lv_obj_set_style_text_color(st->status, fg, 0);
}

static void update_colors(shtoggle_state_t *st, bool checked)
{
    lv_color_t trackBg, knobColor;
    if (checked) {
        trackBg = hmi_colour("brand");
        knobColor = hmi_colour("brandForeground");
    } else {
        trackBg = hmi_colour("secondary");
        knobColor = hmi_colour("foreground");
    }
    lv_obj_set_style_bg_color(st->track, trackBg, 0);
    lv_obj_set_style_bg_color(st->knob, knobColor, 0);
}

// The label line only takes room when there is a label (visible: text !== "").
static void set_label(shtoggle_state_t *st, const char *text)
{
    lv_label_set_text(st->label, text);
    if (text[0]) lv_obj_remove_flag(st->label, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(st->label, LV_OBJ_FLAG_HIDDEN);
}

// One place that makes the drawing match `checked`: the track state, the
// knob side, the colours and the ON/OFF text.
static void apply_checked(shtoggle_state_t *st, bool checked)
{
    st->checked = checked;
    if (checked) {
        lv_obj_add_state(st->track, LV_STATE_CHECKED);
        lv_obj_set_pos(st->knob, 40 - 20 - 2, 2);
    } else {
        lv_obj_clear_state(st->track, LV_STATE_CHECKED);
        lv_obj_set_pos(st->knob, 2, 2);
    }
    update_colors(st, checked);
    update_status(st, checked);
}

// A tap anywhere on the widget flips it, then reports (ShToggle.qml toggle()).
static void shtoggle_clicked_cb(lv_event_t *e)
{
    hmi_widget_t *widget = (hmi_widget_t *)lv_event_get_user_data(e);
    shtoggle_state_t *st = widget ? widget->state : NULL;
    if (!st) return;
    apply_checked(st, !st->checked);
    hmi_value_t v = hmi_value_bool(st->checked);
    hmi_widget_emit(widget, "toggled", &v);
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

    // Row: switch track + text column
    lv_obj_t *row = lv_obj_create(bg);
    lv_obj_remove_style_all(row);
    lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_all(row, 0, 0);
    lv_obj_set_style_pad_gap(row, 8, 0);
    lv_obj_set_size(row, lv_pct(100), lv_pct(100));
    lv_obj_set_pos(row, 8, 0);

    // Track (40x24)
    lv_obj_t *track = lv_obj_create(row);
    lv_obj_remove_style_all(track);
    lv_obj_set_size(track, 40, 24);
    lv_obj_set_style_radius(track, 12, 0);
    lv_obj_set_style_bg_color(track, hmi_colour("secondary"), 0);
    lv_obj_set_style_bg_opa(track, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(track, hmi_colour("border"), 0);
    lv_obj_set_style_border_width(track, 1, 0);

    // Knob (20x20, inside track at y=2)
    lv_obj_t *knob = lv_obj_create(track);
    lv_obj_remove_style_all(knob);
    lv_obj_set_size(knob, 20, 20);
    lv_obj_set_style_radius(knob, 10, 0);
    lv_obj_set_style_bg_color(knob, hmi_colour("foreground"), 0);
    lv_obj_set_style_bg_opa(knob, LV_OPA_COVER, 0);
    lv_obj_set_pos(knob, 2, 2);

    // Text column beside the track: the label (sm, hidden when empty) over
    // the ON/OFF status (xs), as ShToggle.qml's Column stacks them.
    lv_obj_t *col = lv_obj_create(row);
    lv_obj_remove_style_all(col);
    lv_obj_remove_flag(col, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_flex_flow(col, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_grow(col, 1);
    lv_obj_set_height(col, LV_SIZE_CONTENT);

    lv_obj_t *label = hmi_make_label(col, hmi_font_size("fontSizeSm"), 400, hmi_colour("foreground"), "");
    lv_label_set_long_mode(label, LV_LABEL_LONG_DOT);
    lv_obj_set_width(label, lv_pct(100));

    lv_obj_t *status = lv_label_create(col);
    lv_obj_remove_style_all(status);
    lv_obj_set_style_text_font(status, hmi_font(hmi_font_size("fontSizeXs"), 400), 0);
    lv_obj_set_style_text_color(status, hmi_colour("mutedForeground"), 0);
    lv_label_set_long_mode(status, LV_LABEL_LONG_DOT);
    lv_obj_set_width(status, lv_pct(100));

    shtoggle_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->track = track;
    st->knob = knob;
    st->label = label;
    st->status = status;
    st->checked = hmi_widget_bool(w, "checked", false);
    strncpy(st->onLabel, hmi_widget_str(w, "onLabel", "ON"), sizeof(st->onLabel) - 1);
    strncpy(st->offLabel, hmi_widget_str(w, "offLabel", "OFF"), sizeof(st->offLabel) - 1);

    apply_checked(st, st->checked);
    set_label(st, hmi_widget_str(w, "label", ""));

    // The whole widget is the hit area (the QML MouseArea fills it); the
    // children are not hit targets, so every tap lands on it.
    lv_obj_add_flag(bg, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_remove_flag(row, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_remove_flag(track, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_remove_flag(knob, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(bg, shtoggle_clicked_cb, LV_EVENT_CLICKED, w);

    w->state = st;
    return bg;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    shtoggle_state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "checked") == 0) {
        bool v = hmi_value_as_bool(value, st->checked);
        if (v != st->checked) apply_checked(st, v);
    } else if (strcmp(prop, "label") == 0) {
        set_label(st, hmi_value_as_str(value, ""));
    } else if (strcmp(prop, "onLabel") == 0) {
        strncpy(st->onLabel, hmi_value_as_str(value, "ON"), sizeof(st->onLabel) - 1);
        update_status(st, st->checked);
    } else if (strcmp(prop, "offLabel") == 0) {
        strncpy(st->offLabel, hmi_value_as_str(value, "OFF"), sizeof(st->offLabel) - 1);
        update_status(st, st->checked);
    }
}

static void destroy(hmi_widget_t *w)
{
    shtoggle_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_shtoggle = {"ShToggle", create, set_prop, destroy};