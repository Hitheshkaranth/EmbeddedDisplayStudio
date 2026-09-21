// widgets/w_shsegmentbar.c -- kit widget ShSegmentBar (Automotive, "Segment Bar").
// Spec: ui/qml/Shadcn/ShSegmentBar.qml: caption left (muted, 0.4 h), percent
// right (semibold 0.45 h, red when low), a row of `segments` cells between
// them (height 0.6 h, gap round(0.12 h), radius round(0.1 h)); filled cells
// accent (the first accentDeep), redline when low, autoTrack otherwise.
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    double value, minimumValue, maximumValue, lowLevel;
    int segments;
    bool showPercent;
    lv_obj_t *face, *caption, *percent;
} state_t;

static void draw_cb(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    state_t *st = w->state;
    hmi_draw_t d = hmi_draw_begin(e);
    double W = fmax(1, w->width), H = fmax(1, w->height);
    double span = fmax(0.0001, st->maximumValue - st->minimumValue);
    double fraction = fmax(0, fmin(1, (st->value - st->minimumValue) / span));
    int count = (int)fmax(1, fmin(60, st->segments));
    int filled = (int)fmin(count, floor(fraction * count + 0.5));
    bool low = st->lowLevel > 0 && st->value <= st->lowLevel;
    double gap = round(H * 0.12);
    double cellsH = round(H * 0.6);
    double left = 0, right = W;
    bool captionVisible = !lv_obj_has_flag(st->caption, LV_OBJ_FLAG_HIDDEN);
    if (captionVisible) left = lv_obj_get_width(st->caption) + round(H * 0.3);
    if (st->showPercent) right = W - lv_obj_get_width(st->percent) - round(H * 0.3);
    double width = fmax(1, right - left);
    double cellW = fmax(1, (width - gap * (count - 1)) / count);
    double y = round(H / 2 - cellsH / 2);
    int radius = (int)round(H * 0.1);
    for (int i = 0; i < count; ++i) {
        lv_color_t c = i >= filled ? hmi_colour("autoTrack")
                     : low ? hmi_colour("autoRedline")
                     : i == 0 ? hmi_colour("autoAccentDeep") : hmi_colour("autoAccent");
        hmi_draw_fill(&d, left + i * (cellW + gap), y, cellW, cellsH, c, LV_OPA_COVER, radius);
    }
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double H = fmax(1, w->height);
    double span = fmax(0.0001, st->maximumValue - st->minimumValue);
    double fraction = fmax(0, fmin(1, (st->value - st->minimumValue) / span));
    bool low = st->lowLevel > 0 && st->value <= st->lowLevel;
    const char *label = hmi_widget_str(w, "label", "");
    lv_label_set_text(st->caption, label);
    lv_obj_set_style_text_font(st->caption, hmi_font(hmi_px_min(H * 0.4, 7), 400), 0);
    if (label[0]) lv_obj_remove_flag(st->caption, LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(st->caption, LV_OBJ_FLAG_HIDDEN);
    lv_obj_align(st->caption, LV_ALIGN_LEFT_MID, 0, 0);
    lv_label_set_text_fmt(st->percent, "%d%%", (int)lround(fraction * 100));
    lv_obj_set_style_text_font(st->percent, hmi_font(hmi_px_min(H * 0.45, 7), 600), 0);
    lv_obj_set_style_text_color(st->percent, low ? hmi_colour("autoRed") : hmi_colour("autoText"), 0);
    if (st->showPercent) lv_obj_remove_flag(st->percent, LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(st->percent, LV_OBJ_FLAG_HIDDEN);
    lv_obj_align(st->percent, LV_ALIGN_RIGHT_MID, 0, 0);
    lv_obj_update_layout(st->face);
    lv_obj_invalidate(st->face);
}

static void read_model(hmi_widget_t *w)
{
    state_t *st = w->state;
    st->value = hmi_widget_num(w, "value", 60);
    st->minimumValue = hmi_widget_num(w, "minimumValue", 0);
    st->maximumValue = hmi_widget_num(w, "maximumValue", 100);
    st->segments = (int)hmi_widget_num(w, "segments", 12);
    st->lowLevel = hmi_widget_num(w, "lowLevel", 20);
    st->showPercent = hmi_widget_bool(w, "showPercent", true);
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *face = lv_obj_create(parent);
    lv_obj_remove_style_all(face);
    lv_obj_set_size(face, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(face, LV_OBJ_FLAG_SCROLLABLE);
    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;
    st->face = face;
    st->caption = hmi_make_label(face, 12, 400, hmi_colour("autoMuted"), "");
    st->percent = hmi_make_label(face, 12, 600, hmi_colour("autoText"), "");
    lv_obj_add_event_cb(face, draw_cb, LV_EVENT_DRAW_MAIN, w);
    read_model(w);
    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "value") == 0) st->value = hmi_value_as_num(value, st->value);
    else if (strcmp(prop, "minimumValue") == 0) st->minimumValue = hmi_value_as_num(value, st->minimumValue);
    else if (strcmp(prop, "maximumValue") == 0) st->maximumValue = hmi_value_as_num(value, st->maximumValue);
    else if (strcmp(prop, "segments") == 0) st->segments = (int)hmi_value_as_num(value, st->segments);
    else if (strcmp(prop, "lowLevel") == 0) st->lowLevel = hmi_value_as_num(value, st->lowLevel);
    else if (strcmp(prop, "showPercent") == 0) st->showPercent = hmi_value_as_bool(value, st->showPercent);
    else if (strcmp(prop, "label") != 0) return;
    layout(w);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shsegmentbar = {"ShSegmentBar", create, set_prop, destroy};
