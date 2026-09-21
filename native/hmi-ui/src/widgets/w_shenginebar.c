// widgets/w_shenginebar.c -- kit widget ShEngineBar (Avionics, "Engine Bar").
//
// Spec: ui/qml/Shadcn/ShEngineBar.qml -- a vertical bar gauge with caution
// and warning markers, label and readout.
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    lv_obj_t *face, *label, *well, *valueBar, *cautionLine, *warningLine, *readout;
    lv_obj_t *well_frame;
    double value, minimumValue, maximumValue, cautionValue, warningValue;
    char label_text[32];
    char units_text[16];
} state_t;

static double clamp_val(double v, double lo, double hi) { return v < lo ? lo : v > hi ? hi : v; }

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    double span = fmax(0.0001, st->maximumValue - st->minimumValue);
    double clamped = clamp_val(st->value, st->minimumValue, st->maximumValue);
    double fraction = (clamped - st->minimumValue) / span;

    lv_color_t barColor;
    if (st->value >= st->warningValue) barColor = hmi_colour("efisWarning");
    else if (st->value >= st->cautionValue) barColor = hmi_colour("efisCaution");
    else barColor = hmi_colour("efisNormal");

    /* Background */
    lv_obj_set_style_bg_color(st->face, hmi_colour("efisPanel"), 0);
    lv_obj_set_style_bg_opa(st->face, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(st->face, hmi_radius("radiusSm"), 0);

    /* Label */
    lv_label_set_text(st->label, st->label_text);
    lv_obj_set_style_text_font(st->label, hmi_font(hmi_font_size("fontSizeSm"), 600), 0);
    lv_obj_set_style_text_color(st->label, hmi_colour("efisText"), 0);
    lv_obj_align(st->label, LV_ALIGN_TOP_MID, 0, 0);

    /* Well frame */
    int wellW = 18, wellPad = 25, valueTextH = 20;
    int wellH = (int)H - wellPad - valueTextH - 5;
    lv_obj_set_size(st->well_frame, wellW, wellH);
    lv_obj_set_style_bg_color(st->well_frame, lv_color_hex(0x000000), 0);
    lv_obj_set_style_bg_opa(st->well_frame, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_color(st->well_frame, hmi_colour("efisLine"), 0);
    lv_obj_set_style_border_width(st->well_frame, 1, 0);
    lv_obj_set_style_radius(st->well_frame, 0, 0);
    lv_obj_align(st->well_frame, LV_ALIGN_TOP_MID, 0, wellPad);

    /* Value bar (inner) */
    int valBarH = (int)((wellH - 4) * fraction);
    lv_obj_set_size(st->valueBar, wellW - 4, valBarH);
    lv_obj_set_style_bg_color(st->valueBar, barColor, 0);
    lv_obj_set_style_bg_opa(st->valueBar, LV_OPA_COVER, 0);
    lv_obj_align(st->valueBar, LV_ALIGN_BOTTOM_MID, 0, 2);

    /* Caution line */
    double cautionFrac = (st->cautionValue - st->minimumValue) / span;
    int cautionY = (int)((wellH - 4) * (1 - cautionFrac));
    lv_obj_set_size(st->cautionLine, wellW + 8, 2);
    lv_obj_set_style_bg_color(st->cautionLine, hmi_colour("efisCaution"), 0);
    lv_obj_set_style_bg_opa(st->cautionLine, LV_OPA_COVER, 0);
    lv_obj_align(st->cautionLine, LV_ALIGN_TOP_MID, -4, cautionY);

    /* Warning line */
    double warningFrac = (st->warningValue - st->minimumValue) / span;
    int warningY = (int)((wellH - 4) * (1 - warningFrac));
    lv_obj_set_size(st->warningLine, wellW + 8, 2);
    lv_obj_set_style_bg_color(st->warningLine, hmi_colour("efisWarning"), 0);
    lv_obj_set_style_bg_opa(st->warningLine, LV_OPA_COVER, 0);
    lv_obj_align(st->warningLine, LV_ALIGN_TOP_MID, -4, warningY);

    /* Readout */
    lv_label_set_text_fmt(st->readout, "%.0f%s", clamped, st->units_text);
    lv_obj_set_style_text_font(st->readout, hmi_font(hmi_font_size("fontSizeSm"), 600), 0);
    lv_obj_set_style_text_color(st->readout, barColor, 0);
    lv_obj_align(st->readout, LV_ALIGN_BOTTOM_MID, 0, 0);
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

    st->label = lv_label_create(face);
    lv_obj_remove_style_all(st->label);
    lv_label_set_long_mode(st->label, LV_LABEL_LONG_CLIP);

    st->well_frame = lv_obj_create(face);
    lv_obj_remove_style_all(st->well_frame);
    lv_obj_remove_flag(st->well_frame, LV_OBJ_FLAG_SCROLLABLE);

    st->valueBar = lv_obj_create(st->well_frame);
    lv_obj_remove_style_all(st->valueBar);
    lv_obj_remove_flag(st->valueBar, LV_OBJ_FLAG_SCROLLABLE);

    st->cautionLine = lv_obj_create(face);
    lv_obj_remove_style_all(st->cautionLine);
    lv_obj_remove_flag(st->cautionLine, LV_OBJ_FLAG_SCROLLABLE);

    st->warningLine = lv_obj_create(face);
    lv_obj_remove_style_all(st->warningLine);
    lv_obj_remove_flag(st->warningLine, LV_OBJ_FLAG_SCROLLABLE);

    st->readout = lv_label_create(face);
    lv_obj_remove_style_all(st->readout);
    lv_label_set_long_mode(st->readout, LV_LABEL_LONG_CLIP);

    st->value = hmi_widget_num(w, "value", 0);
    st->minimumValue = hmi_widget_num(w, "minimumValue", 0);
    st->maximumValue = hmi_widget_num(w, "maximumValue", 100);
    st->cautionValue = hmi_widget_num(w, "cautionValue", 80);
    st->warningValue = hmi_widget_num(w, "warningValue", 90);
    snprintf(st->label_text, sizeof st->label_text, "%s", hmi_widget_str(w, "label", "N1"));
    snprintf(st->units_text, sizeof st->units_text, "%s", hmi_widget_str(w, "units", "%"));

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
    else if (strcmp(prop, "cautionValue") == 0) st->cautionValue = hmi_value_as_num(value, st->cautionValue);
    else if (strcmp(prop, "warningValue") == 0) st->warningValue = hmi_value_as_num(value, st->warningValue);
    else if (strcmp(prop, "units") == 0) { lv_label_set_text(st->readout, hmi_value_as_str(value, "%")); }
    else if (strcmp(prop, "label") == 0) { lv_label_set_text(st->label, hmi_value_as_str(value, "")); return; }
    else return;

    layout(w);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shenginebar = {"ShEngineBar", create, set_prop, destroy};