// widgets/w_shnumdisplay.c -- kit widget ShNumDisplay (Industrial, "Numeric Display").
// Spec: ui/qml/Shadcn/ShNumDisplay.qml: a Column filling the item, spacing
// 2: the label (16 px high, centred, xs, mutedForeground); a 42 px row with
// the value (xxxl semibold, coloured by the thresholds) and the unit (sm,
// muted) 4 px apart, centred; a 24x3 bar in the value colour, centred.
#include <math.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    double value, warningLow, warningHigh, faultLow, faultHigh;
    int decimalPlaces;
    lv_obj_t *face, *label, *number, *unit, *bar;
} state_t;

static lv_color_t value_colour(hmi_widget_t *w)
{
    state_t *st = w->state;
    if (isnan(st->value)) return hmi_colour("mutedForeground");
    lv_opa_t opa;
    const char *normal = hmi_widget_str(w, "normalColor", "");
    const char *warning = hmi_widget_str(w, "warningColor", "");
    const char *fault = hmi_widget_str(w, "faultColor", "");
    if (st->value < st->faultLow || st->value >= st->faultHigh)
        return fault[0] ? hmi_colour_hex(fault, &opa) : hmi_colour("destructive");
    if (st->value < st->warningLow || st->value >= st->warningHigh)
        return warning[0] ? hmi_colour_hex(warning, &opa) : hmi_colour("warning");
    return normal[0] ? hmi_colour_hex(normal, &opa) : hmi_colour("success");
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width);
    lv_color_t vc = value_colour(w);
    lv_label_set_text(st->label, hmi_widget_str(w, "label", ""));
    lv_obj_set_width(st->label, (int)W);
    lv_obj_set_style_text_align(st->label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_pos(st->label, 0, 0);
    if (isnan(st->value)) lv_label_set_text(st->number, "--");
    else lv_label_set_text_fmt(st->number, "%.*f", st->decimalPlaces, st->value);
    lv_obj_set_style_text_color(st->number, vc, 0);
    lv_label_set_text(st->unit, hmi_widget_str(w, "unit", ""));
    lv_obj_update_layout(st->face);
    int numW = lv_obj_get_width(st->number), unitW = lv_obj_get_width(st->unit);
    int rowW = numW + (unitW ? 4 + unitW : 0);
    int rowY = 16 + 2;                       // label height 16, spacing 2
    int numH = lv_obj_get_height(st->number), unitH = lv_obj_get_height(st->unit);
    int x = (int)round(W / 2 - rowW / 2.0);
    lv_obj_set_pos(st->number, x, rowY + 21 - numH / 2);
    lv_obj_set_pos(st->unit, x + numW + 4, rowY + 21 - unitH / 2);
    lv_obj_set_style_bg_color(st->bar, vc, 0);
    lv_obj_set_pos(st->bar, (int)round(W / 2 - 12), rowY + 42 + 2);
}

static void read_model(hmi_widget_t *w)
{
    state_t *st = w->state;
    st->value = hmi_widget_num(w, "value", 0);
    st->decimalPlaces = (int)hmi_widget_num(w, "decimalPlaces", 2);
    st->warningLow = hmi_widget_num(w, "warningLow", 0);
    st->warningHigh = hmi_widget_num(w, "warningHigh", 100);
    st->faultLow = hmi_widget_num(w, "faultLow", 0);
    st->faultHigh = hmi_widget_num(w, "faultHigh", 1000);
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
    st->label = hmi_make_label(face, hmi_font_size("fontSizeXs"), 400, hmi_colour("mutedForeground"), "");
    st->number = hmi_make_label(face, hmi_font_size("fontSizeXxxl"), 600, hmi_colour("success"), "");
    st->unit = hmi_make_label(face, hmi_font_size("fontSizeSm"), 400, hmi_colour("mutedForeground"), "");
    st->bar = lv_obj_create(face);
    lv_obj_remove_style_all(st->bar);
    lv_obj_set_size(st->bar, 24, 3);
    lv_obj_set_style_radius(st->bar, 2, 0);
    lv_obj_set_style_bg_opa(st->bar, LV_OPA_COVER, 0);
    read_model(w);
    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "value") == 0) st->value = hmi_value_as_num(value, st->value);
    else if (strcmp(prop, "decimalPlaces") == 0) st->decimalPlaces = (int)hmi_value_as_num(value, st->decimalPlaces);
    else if (strcmp(prop, "warningLow") == 0) st->warningLow = hmi_value_as_num(value, st->warningLow);
    else if (strcmp(prop, "warningHigh") == 0) st->warningHigh = hmi_value_as_num(value, st->warningHigh);
    else if (strcmp(prop, "faultLow") == 0) st->faultLow = hmi_value_as_num(value, st->faultLow);
    else if (strcmp(prop, "faultHigh") == 0) st->faultHigh = hmi_value_as_num(value, st->faultHigh);
    else if (strcmp(prop, "unit") == 0 || strcmp(prop, "label") == 0) {
        layout(w);
        lv_label_set_text(strcmp(prop, "unit") == 0 ? st->unit : st->label, hmi_value_as_str(value, ""));
        return;
    } else if (strcmp(prop, "normalColor") != 0 && strcmp(prop, "warningColor") != 0 && strcmp(prop, "faultColor") != 0) return;
    layout(w);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shnumdisplay = {"ShNumDisplay", create, set_prop, destroy};
