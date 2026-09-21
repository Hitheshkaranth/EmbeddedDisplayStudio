// widgets/w_shslider.c -- kit widget ShSlider (Industrial, "Slider").
//
// Spec: ui/qml/Shadcn/ShSlider.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): value, minValue, maxValue, step, label, unit, valueWarning, valueFault, enabled, showTicks, tickCount, showValue, handleRadius, opacity, visible.
// Default size 250x64. Signals: valueChanged.
// Owner: W3 (wave 2).
#include <stdio.h>
#include <string.h>
#include <math.h>

#include "draw_util.h"
#include "registry.h"
#include "theme.h"

typedef struct shslider_state shslider_state_t;

static void slider_event_cb(lv_event_t *e);
static void update_fill_and_knob(shslider_state_t *st);
static void layout_ticks(shslider_state_t *st);
static lv_color_t get_value_color(shslider_state_t *st);

struct shslider_state {
    lv_obj_t *root;       // the root LVGL object
    lv_obj_t *track;
    lv_obj_t *fill;
    lv_obj_t *knob;
    lv_obj_t *label;
    lv_obj_t *valueText;
    lv_obj_t *slider;
    lv_obj_t *tick[10];
    int n_ticks;
    double value, minValue, maxValue, step;
    double valueWarning, valueFault;
    bool showTicks, showValue;
    int handleRadius;
    char unit[16];
};

static lv_color_t get_value_color(shslider_state_t *st)
{
    if (st->valueFault > 0 && st->value >= st->valueFault)
        return hmi_colour("destructive");
    if (st->valueWarning > 0 && st->value >= st->valueWarning)
        return hmi_colour("warning");
    return hmi_colour("brand");
}

static void update_visuals(shslider_state_t *st)
{
    lv_color_t vc = get_value_color(st);
    lv_obj_set_style_bg_color(st->fill, vc, 0);
    lv_obj_set_style_border_color(st->knob, vc, 0);
    lv_obj_set_style_text_color(st->valueText, vc, 0);
}

static void slider_event_cb(lv_event_t *e)
{
    hmi_widget_t *widget = (hmi_widget_t *)lv_event_get_user_data(e);
    if (!widget) return;
    shslider_state_t *st = widget->state;
    if (!st) return;
    double v = (double)lv_slider_get_value(st->slider);
    st->value = v;
    hmi_value_t val = hmi_value_num(v);
    hmi_widget_emit(widget, "valueChanged", &val);
    hmi_value_free(&val);
    lv_label_set_text_fmt(st->valueText, "%.*f %s",
        (st->step > 0 && st->step < 1) ? 2 : 0, v, st->unit);
    update_fill_and_knob(st);
    layout_ticks(st);
}

static void update_fill_and_knob(shslider_state_t *st)
{
    int trackW = (int)lv_obj_get_width(st->track);
    int knobR = st->handleRadius;
    int knobSize = knobR * 2;

    double frac = (st->maxValue > st->minValue) ?
        (st->value - st->minValue) / (st->maxValue - st->minValue) : 0;
    frac = fmax(0.0, fmin(1.0, frac));
    lv_obj_set_size(st->fill, (int32_t)(frac * trackW), lv_obj_get_height(st->fill));

    int knobX = (int32_t)(frac * (trackW - knobSize));
    lv_obj_set_pos(st->knob, knobX, lv_obj_get_y(st->knob));
}

static void layout_ticks(shslider_state_t *st)
{
    int trackW = (int)lv_obj_get_width(st->track);
    int knobR = st->handleRadius;

    for (int i = 0; i < st->n_ticks; i++) {
        double x;
        if (st->n_ticks == 1) {
            x = (trackW - knobR * 2) / 2.0;
        } else {
            x = (i * (trackW - knobR * 2)) / (st->n_ticks - 1);
        }
        lv_obj_set_pos(st->tick[i], (int32_t)x, lv_obj_get_y(st->tick[i]));
        if (st->showTicks && st->n_ticks > 1) {
            lv_obj_clear_flag(st->tick[i], LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_add_flag(st->tick[i], LV_OBJ_FLAG_HIDDEN);
        }
    }
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    shslider_state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;

    // Root: a plain LVGL object sized from the model, transparent bg
    lv_obj_t *root = lv_obj_create(parent);
    lv_obj_remove_style_all(root);
    lv_obj_set_size(root, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(root, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(root, lv_color_hex(0x000000), 0);
    lv_obj_set_style_bg_opa(root, LV_OPA_TRANSP, 0);

    // Use flex column to match QML Column: anchors.fill, spacing: 5
    lv_obj_set_flex_flow(root, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_all(root, 4, 0);  // anchors.margins: 4
    lv_obj_set_style_pad_gap(root, 5, 0);  // spacing: 5
    lv_obj_set_size(root, lv_pct(100), lv_pct(100));

    st->root = root;

    // Top row: Row { width: parent.width; height: 20 }
    // Contains: Text(label) + Text(value)
    lv_obj_t *topRow = lv_obj_create(root);
    lv_obj_remove_style_all(topRow);
    lv_obj_set_flex_flow(topRow, LV_FLEX_FLOW_ROW);
    lv_obj_set_size(topRow, lv_pct(100), 20);
    lv_obj_set_style_pad_gap(topRow, 0, 0);

    st->label = hmi_make_label(topRow, hmi_font_size("fontSizeXs"), 400, hmi_colour("mutedForeground"), "");
    lv_obj_set_flex_grow(st->label, 1);
    lv_obj_set_style_width(st->label, lv_pct(50), 0);

    st->valueText = hmi_make_label(topRow, hmi_font_size("fontSizeSm"), 600, hmi_colour("brand"), "");
    lv_obj_set_flex_grow(st->valueText, 1);
    lv_obj_set_style_width(st->valueText, lv_pct(50), 0);
    lv_obj_set_style_text_align(st->valueText, LV_TEXT_ALIGN_RIGHT, 0);

    // Item { width: parent.width; height: 28 }
    lv_obj_t *trackContainer = lv_obj_create(root);
    lv_obj_remove_style_all(trackContainer);
    lv_obj_set_size(trackContainer, lv_pct(100), 28);
    lv_obj_set_style_bg_color(trackContainer, lv_color_hex(0x000000), 0);
    lv_obj_set_style_bg_opa(trackContainer, LV_OPA_TRANSP, 0);
    // Disable flex on trackContainer so we can position children absolutely
    lv_obj_set_layout(trackContainer, LV_LAYOUT_NONE);

    // Track: Rectangle { anchors.left/right/verticalCenter; height: 8; radius: 4 }
    lv_obj_t *track = lv_obj_create(trackContainer);
    lv_obj_remove_style_all(track);
    lv_obj_set_style_radius(track, 4, 0);
    lv_obj_set_style_bg_color(track, hmi_colour("secondary"), 0);
    lv_obj_set_style_bg_opa(track, LV_OPA_COVER, 0);

    // Fill: Rectangle { width: parent.width * fraction; height: parent.height; radius: 4 }
    lv_obj_t *fill = lv_obj_create(track);
    lv_obj_remove_style_all(fill);
    lv_obj_set_size(fill, 0, 8);
    lv_obj_set_style_radius(fill, 4, 0);
    lv_obj_set_style_bg_color(fill, hmi_colour("brand"), 0);
    lv_obj_set_style_bg_opa(fill, LV_OPA_COVER, 0);

    // Knob: Rectangle { width: handleRadius*2; height: width; radius: width/2; anchors.verticalCenter: parent }
    int knobSize = 24; // handleRadius * 2 = 12 * 2
    lv_obj_t *knob = lv_obj_create(trackContainer);
    lv_obj_remove_style_all(knob);
    lv_obj_set_size(knob, knobSize, knobSize);
    lv_obj_set_style_radius(knob, knobSize / 2, 0);
    lv_obj_set_style_bg_color(knob, hmi_colour("card"), 0);
    lv_obj_set_style_bg_opa(knob, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(knob, hmi_colour("brand"), 0);
    lv_obj_set_style_border_width(knob, 3, 0);

    // Invisible slider for interaction
    lv_obj_t *slider = lv_slider_create(trackContainer);
    lv_obj_remove_style_all(slider);
    lv_obj_set_size(slider, lv_pct(100), 28);
    lv_obj_set_style_bg_opa(slider, LV_OPA_TRANSP, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(slider, LV_OPA_TRANSP, LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(slider, LV_OPA_TRANSP, LV_PART_KNOB);
    lv_obj_set_style_pad_all(slider, 0, LV_PART_KNOB);

    // Ticks
    int tickCount = (int)hmi_widget_num(w, "tickCount", 5);
    bool showTicks = hmi_widget_bool(w, "showTicks", true);
    if (tickCount < 2) tickCount = 2;
    if (tickCount > 10) tickCount = 10;

    st->track = track;
    st->fill = fill;
    st->knob = knob;
    st->slider = slider;
    st->n_ticks = tickCount;
    st->showTicks = showTicks;
    st->showValue = hmi_widget_bool(w, "showValue", true);
    st->handleRadius = 12;
    st->value = hmi_widget_num(w, "value", 0);
    st->minValue = hmi_widget_num(w, "minValue", 0);
    st->maxValue = hmi_widget_num(w, "maxValue", 100);
    st->step = hmi_widget_num(w, "step", 1);
    st->valueWarning = hmi_widget_num(w, "valueWarning", 0);
    st->valueFault = hmi_widget_num(w, "valueFault", 0);
    strncpy(st->unit, hmi_widget_str(w, "unit", ""), sizeof(st->unit) - 1);

    for (int i = 0; i < 10; i++) {
        st->tick[i] = lv_label_create(trackContainer);
        lv_obj_remove_style_all(st->tick[i]);
        lv_obj_set_size(st->tick[i], 1, 8);
        lv_obj_set_style_bg_color(st->tick[i], hmi_colour("mutedForeground"), 0);
        lv_obj_set_style_bg_opa(st->tick[i], 0x73, 0);
        lv_obj_set_style_radius(st->tick[i], 0, 0);
        lv_obj_add_flag(st->tick[i], LV_OBJ_FLAG_HIDDEN);
    }

    lv_label_set_text(st->label, hmi_widget_str(w, "label", ""));

    char valStr[64];
    snprintf(valStr, sizeof valStr, "%.*f %s",
        (st->step > 0 && st->step < 1) ? 2 : 0, st->value, st->unit);
    lv_label_set_text(st->valueText, valStr);

    lv_slider_set_range(st->slider, (int32_t)st->minValue, (int32_t)st->maxValue);
    lv_slider_set_value(st->slider, (int32_t)st->value, LV_ANIM_OFF);

    update_visuals(st);

    lv_obj_add_event_cb(slider, slider_event_cb, LV_EVENT_VALUE_CHANGED, w);
    lv_obj_add_event_cb(slider, slider_event_cb, LV_EVENT_PRESSING, w);

    lv_obj_update_layout(root);

    // Position track: width = containerWidth - 2*handleRadius, x = handleRadius, y centered
    int containerW = (int)lv_obj_get_width(trackContainer);
    int knobR = st->handleRadius;
    int trackW = containerW - 2 * knobR;
    if (trackW < 8) trackW = 8;
    lv_obj_set_size(st->track, trackW, 8);
    lv_obj_set_pos(st->track, knobR, (28 - 8) / 2);

    // Position knob: x = trackX + fraction * (trackW - knobSize), y centered in container
    int knobX = (int32_t)(knobR + 0 * (trackW - knobSize));
    lv_obj_set_pos(st->knob, knobX, (28 - knobSize) / 2);

    // Position ticks at even intervals along the track
    for (int i = 0; i < st->n_ticks && i < 10; i++) {
        double x;
        if (st->n_ticks == 1) {
            x = knobR + (trackW - knobR * 2) / 2.0;
        } else {
            x = knobR + (i * (trackW - knobR * 2)) / (st->n_ticks - 1);
        }
        lv_obj_set_pos(st->tick[i], (int32_t)x, (28 - 8) / 2);
        if (st->showTicks && st->n_ticks > 1) {
            lv_obj_clear_flag(st->tick[i], LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_add_flag(st->tick[i], LV_OBJ_FLAG_HIDDEN);
        }
    }

    update_fill_and_knob(st);
    layout_ticks(st);

    return root;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    shslider_state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "value") == 0) {
        st->value = hmi_value_as_num(value, st->value);
        st->value = fmax(st->minValue, fmin(st->maxValue, st->value));
        lv_slider_set_value(st->slider, (int32_t)st->value, LV_ANIM_OFF);
        lv_obj_update_layout(st->root);
        update_fill_and_knob(st);
        layout_ticks(st);
        char valStr[64];
        snprintf(valStr, sizeof valStr, "%.*f %s",
            (st->step > 0 && st->step < 1) ? 2 : 0, st->value, st->unit);
        lv_label_set_text(st->valueText, valStr);
        update_visuals(st);
    } else if (strcmp(prop, "minValue") == 0) {
        st->minValue = hmi_value_as_num(value, st->minValue);
        lv_slider_set_range(st->slider, (int32_t)st->minValue, (int32_t)st->maxValue);
        lv_slider_set_value(st->slider, (int32_t)st->value, LV_ANIM_OFF);
        lv_obj_update_layout(st->root);
        update_fill_and_knob(st);
        layout_ticks(st);
    } else if (strcmp(prop, "maxValue") == 0) {
        st->maxValue = hmi_value_as_num(value, st->maxValue);
        lv_slider_set_range(st->slider, (int32_t)st->minValue, (int32_t)st->maxValue);
        lv_slider_set_value(st->slider, (int32_t)st->value, LV_ANIM_OFF);
        lv_obj_update_layout(st->root);
        update_fill_and_knob(st);
        layout_ticks(st);
    } else if (strcmp(prop, "step") == 0) {
        st->step = hmi_value_as_num(value, st->step);
    } else if (strcmp(prop, "label") == 0) {
        lv_label_set_text(st->label, hmi_value_as_str(value, ""));
    } else if (strcmp(prop, "unit") == 0) {
        strncpy(st->unit, hmi_value_as_str(value, ""), sizeof(st->unit) - 1);
        char valStr[64];
        snprintf(valStr, sizeof valStr, "%.*f %s",
            (st->step > 0 && st->step < 1) ? 2 : 0, st->value, st->unit);
        lv_label_set_text(st->valueText, valStr);
    } else if (strcmp(prop, "valueWarning") == 0) {
        st->valueWarning = hmi_value_as_num(value, st->valueWarning);
        update_visuals(st);
    } else if (strcmp(prop, "valueFault") == 0) {
        st->valueFault = hmi_value_as_num(value, st->valueFault);
        update_visuals(st);
    } else if (strcmp(prop, "showTicks") == 0) {
        st->showTicks = hmi_value_as_bool(value, st->showTicks);
        layout_ticks(st);
    } else if (strcmp(prop, "showValue") == 0) {
        st->showValue = hmi_value_as_bool(value, st->showValue);
        if (!st->showValue) lv_obj_add_flag(st->valueText, LV_OBJ_FLAG_HIDDEN);
        else lv_obj_clear_flag(st->valueText, LV_OBJ_FLAG_HIDDEN);
    }
}

static void destroy(hmi_widget_t *w)
{
    shslider_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_shslider = {"ShSlider", create, set_prop, destroy};