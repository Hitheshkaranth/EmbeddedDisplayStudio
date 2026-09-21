// widgets/w_shfuelquantity.c -- kit widget ShFuelQuantity (Avionics, "Fuel Quantity").
//
// Spec: ui/qml/Shadcn/ShFuelQuantity.qml -- two side-by-side fuel tank bars
// (L/R) with low-level caution coloring.
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    lv_obj_t *face, *title;
    // Left side
    lv_obj_t *leftLabel, *leftFrame, *leftBar, *leftReadout;
    // Right side
    lv_obj_t *rightLabel, *rightFrame, *rightBar, *rightReadout;
    double leftValue, rightValue, capacity, lowLevel;
    char units_text[16];
} state_t;

static double clamp_val(double v, double lo, double hi) { return v < lo ? lo : v > hi ? hi : v; }

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    lv_color_t efisLine = hmi_colour("efisLine"), efisNormal = hmi_colour("efisNormal");
    lv_color_t efisCaution = hmi_colour("efisCaution"), mutedFg = hmi_colour("mutedForeground");
    lv_color_t efisText = hmi_colour("efisText");

    lv_obj_set_style_bg_color(st->face, hmi_colour("efisPanel"), 0);
    lv_obj_set_style_bg_opa(st->face, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(st->face, hmi_radius("radiusSm"), 0);

    lv_label_set_text(st->title, "FUEL QTY");
    lv_obj_set_style_text_font(st->title, hmi_font(hmi_font_size("fontSizeSm"), 600), 0);
    lv_obj_set_style_text_color(st->title, efisText, 0);
    lv_obj_align(st->title, LV_ALIGN_TOP_MID, 0, 0);

    // Row centred in the item, spacing 24; each Column: name, 44x58 frame, readout, spacing 3.
    const int barW = 44, barH = 58, gap = 24, colSpacing = 3;
    const lv_font_t *xs = hmi_font(hmi_font_size("fontSizeXs"), 400);
    int textH = lv_font_get_line_height(xs);
    int colH = textH + colSpacing + barH + colSpacing + textH;
    int rowW = barW * 2 + gap;
    int rowX = (int)round(W / 2 - rowW / 2.0), rowY = (int)round(H / 2 - colH / 2.0);
    double values[2] = {clamp_val(st->leftValue, 0, st->capacity), clamp_val(st->rightValue, 0, st->capacity)};
    double raws[2] = {st->leftValue, st->rightValue};
    const char *names[2] = {"L", "R"};
    lv_obj_t *labels[2] = {st->leftLabel, st->rightLabel};
    lv_obj_t *frames[2] = {st->leftFrame, st->rightFrame};
    lv_obj_t *bars[2] = {st->leftBar, st->rightBar};
    lv_obj_t *readouts[2] = {st->leftReadout, st->rightReadout};
    for (int i = 0; i < 2; ++i) {
        int cx = rowX + i * (barW + gap);
        bool low = raws[i] <= st->lowLevel;
        lv_label_set_text(labels[i], names[i]);
        lv_obj_set_style_text_font(labels[i], xs, 0);
        lv_obj_set_style_text_color(labels[i], mutedFg, 0);
        lv_obj_set_width(labels[i], barW);
        lv_obj_set_style_text_align(labels[i], LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_pos(labels[i], cx, rowY);
        int frameY = rowY + textH + colSpacing;
        lv_obj_set_pos(frames[i], cx, frameY);
        lv_obj_set_size(frames[i], barW, barH);
        lv_obj_set_style_bg_opa(frames[i], LV_OPA_TRANSP, 0);
        lv_obj_set_style_border_color(frames[i], efisLine, 0);
        lv_obj_set_style_border_width(frames[i], 1, 0);
        int fillH = st->capacity > 0 ? (int)round((barH - 4) * values[i] / st->capacity) : 0;
        lv_obj_set_size(bars[i], barW - 4, fillH);
        lv_obj_set_pos(bars[i], 2, barH - 2 - fillH);   // the bar is the frame's child
        lv_obj_set_style_bg_color(bars[i], low ? efisCaution : efisNormal, 0);
        lv_obj_set_style_bg_opa(bars[i], LV_OPA_COVER, 0);
        lv_label_set_text_fmt(readouts[i], "%.0f %s", values[i], st->units_text);
        lv_obj_set_style_text_font(readouts[i], xs, 0);
        lv_obj_set_style_text_color(readouts[i], low ? efisCaution : efisText, 0);
        lv_obj_set_width(readouts[i], barW + gap);
        lv_obj_set_style_text_align(readouts[i], LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_pos(readouts[i], cx - gap / 2, frameY + barH + colSpacing);
    }
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

    st->title = lv_label_create(face);
    lv_obj_remove_style_all(st->title);
    lv_label_set_long_mode(st->title, LV_LABEL_LONG_CLIP);

    // Left
    st->leftLabel = lv_label_create(face);
    lv_obj_remove_style_all(st->leftLabel);
    st->leftFrame = lv_obj_create(face);
    lv_obj_remove_style_all(st->leftFrame);
    st->leftBar = lv_obj_create(st->leftFrame);
    lv_obj_remove_style_all(st->leftBar);
    st->leftReadout = lv_label_create(face);
    lv_obj_remove_style_all(st->leftReadout);

    // Right
    st->rightLabel = lv_label_create(face);
    lv_obj_remove_style_all(st->rightLabel);
    st->rightFrame = lv_obj_create(face);
    lv_obj_remove_style_all(st->rightFrame);
    st->rightBar = lv_obj_create(st->rightFrame);
    lv_obj_remove_style_all(st->rightBar);
    st->rightReadout = lv_label_create(face);
    lv_obj_remove_style_all(st->rightReadout);

    st->leftValue = hmi_widget_num(w, "leftValue", 50);
    st->rightValue = hmi_widget_num(w, "rightValue", 50);
    st->capacity = hmi_widget_num(w, "capacity", 100);
    st->lowLevel = hmi_widget_num(w, "lowLevel", 15);
    snprintf(st->units_text, sizeof st->units_text, "%s", hmi_widget_str(w, "units", "KG"));

    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "leftValue") == 0) st->leftValue = hmi_value_as_num(value, st->leftValue);
    else if (strcmp(prop, "rightValue") == 0) st->rightValue = hmi_value_as_num(value, st->rightValue);
    else if (strcmp(prop, "capacity") == 0) st->capacity = hmi_value_as_num(value, st->capacity);
    else if (strcmp(prop, "lowLevel") == 0) st->lowLevel = hmi_value_as_num(value, st->lowLevel);
    else if (strcmp(prop, "units") == 0) { snprintf(st->units_text, sizeof st->units_text, "%s", hmi_value_as_str(value, "KG")); }
    else return;

    layout(w);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shfuelquantity = {"ShFuelQuantity", create, set_prop, destroy};