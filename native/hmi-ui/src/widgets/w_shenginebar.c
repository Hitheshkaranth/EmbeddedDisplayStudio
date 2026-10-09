// widgets/w_shenginebar.c -- kit widget ShEngineBar (Avionics, "Engine Bar").
//
// Spec: ui/qml/Shadcn/ShEngineBar.qml -- a vertical bar gauge with caution
// and warning markers, label and readout.  orientation "horizontal" is a
// vitals row (label | thin rounded bar | value), barColor overrides the
// normal/caution/warning fill colour.
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
    char barColor[32];      // "" = colour by value
    bool horizontal;
} state_t;

static double clamp_val(double v, double lo, double hi) { return v < lo ? lo : v > hi ? hi : v; }

/* ShEngineBar.qml's "hrow": text min(fontSizeSm, 0.5 h) px; the label
   (efisText, medium) at the left, at most 0.3 w, elided; the value with its
   units (efisText, semibold) right-aligned in at most 0.25 w; between them,
   8 px from each, a bar min(10, max(4, 0.22 h)) px tall with round ends on
   an efisLine track at 18 %, filled from the left in the bar colour. No
   panel, no markers. */
static void layout_horizontal(hmi_widget_t *w, double clamped, double fraction, lv_color_t barColor)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    int fs = (int)fmax(7, fmin(hmi_font_size("fontSizeSm"), lround(H * 0.5)));
    int barH = (int)lround(fmin(10, fmax(4, H * 0.22)));

    lv_obj_set_style_bg_opa(st->face, LV_OPA_TRANSP, 0);
    lv_obj_add_flag(st->cautionLine, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(st->warningLine, LV_OBJ_FLAG_HIDDEN);

    int labelW = 0;
    lv_label_set_text(st->label, st->label_text);
    lv_obj_set_style_text_font(st->label, hmi_font(fs, 500), 0);
    lv_obj_set_style_text_color(st->label, hmi_colour("efisText"), 0);
    lv_obj_set_style_text_align(st->label, LV_TEXT_ALIGN_LEFT, 0);
    lv_label_set_long_mode(st->label, LV_LABEL_LONG_DOT);
    if (st->label_text[0]) {
        lv_obj_set_width(st->label, LV_SIZE_CONTENT);
        lv_obj_update_layout(st->label);
        labelW = (int)fmin(lv_obj_get_width(st->label), W * 0.3);
        lv_obj_set_width(st->label, labelW);
        lv_obj_remove_flag(st->label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_align(st->label, LV_ALIGN_LEFT_MID, 0, 0);
    } else {
        lv_obj_add_flag(st->label, LV_OBJ_FLAG_HIDDEN);
    }

    lv_label_set_text_fmt(st->readout, "%.0f%s", clamped, st->units_text);
    lv_obj_set_style_text_font(st->readout, hmi_font(fs, 600), 0);
    lv_obj_set_style_text_color(st->readout, hmi_colour("efisText"), 0);
    lv_label_set_long_mode(st->readout, LV_LABEL_LONG_DOT);
    lv_obj_set_width(st->readout, LV_SIZE_CONTENT);
    lv_obj_update_layout(st->readout);
    int valueW = (int)fmin(lv_obj_get_width(st->readout), W * 0.25);
    lv_obj_set_width(st->readout, valueW);
    lv_obj_set_style_text_align(st->readout, LV_TEXT_ALIGN_RIGHT, 0);
    lv_obj_align(st->readout, LV_ALIGN_RIGHT_MID, 0, 0);

    int x0 = st->label_text[0] ? labelW + 8 : 0;
    int trackW = (int)fmax(1, (W - valueW) - 8 - x0);
    lv_obj_set_size(st->well_frame, trackW, barH);
    lv_obj_set_style_bg_color(st->well_frame, hmi_colour("efisLine"), 0);
    lv_obj_set_style_bg_opa(st->well_frame, (lv_opa_t)(0.18 * 255), 0);
    lv_obj_set_style_border_width(st->well_frame, 0, 0);
    lv_obj_set_style_radius(st->well_frame, LV_RADIUS_CIRCLE, 0);
    lv_obj_align(st->well_frame, LV_ALIGN_LEFT_MID, x0, 0);

    int fillW = (int)lround(trackW * fraction);
    lv_obj_set_size(st->valueBar, fillW, barH);
    lv_obj_set_style_bg_color(st->valueBar, barColor, 0);
    lv_obj_set_style_bg_opa(st->valueBar, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(st->valueBar, LV_RADIUS_CIRCLE, 0);
    lv_obj_align(st->valueBar, LV_ALIGN_LEFT_MID, 0, 0);
    if (fillW > 0) lv_obj_remove_flag(st->valueBar, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(st->valueBar, LV_OBJ_FLAG_HIDDEN);
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    double span = fmax(0.0001, st->maximumValue - st->minimumValue);
    double clamped = clamp_val(st->value, st->minimumValue, st->maximumValue);
    double fraction = (clamped - st->minimumValue) / span;

    lv_color_t barColor;
    lv_opa_t customOpa = 0;
    lv_color_t custom = st->barColor[0] ? hmi_colour_hex(st->barColor, &customOpa) : lv_color_black();
    if (st->barColor[0] && customOpa > 0) barColor = custom;
    else if (st->value >= st->warningValue) barColor = hmi_colour("efisWarning");
    else if (st->value >= st->cautionValue) barColor = hmi_colour("efisCaution");
    else barColor = hmi_colour("efisNormal");

    if (st->horizontal) {
        layout_horizontal(w, clamped, fraction, barColor);
        return;
    }
    // The markers need a well at least 20 px tall; on a shorter one (a
    // vertical bar squeezed into a row) they ran through the label and value.
    {
        int wellHProbe = (int)fmax(1, H) - 25 - 20 - 5;
        if (wellHProbe >= 20) {
            lv_obj_remove_flag(st->cautionLine, LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(st->warningLine, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_add_flag(st->cautionLine, LV_OBJ_FLAG_HIDDEN);
            lv_obj_add_flag(st->warningLine, LV_OBJ_FLAG_HIDDEN);
        }
    }
    lv_obj_set_style_text_align(st->readout, LV_TEXT_ALIGN_LEFT, 0);
    lv_obj_set_width(st->readout, LV_SIZE_CONTENT);

    /* Background */
    lv_obj_set_style_bg_color(st->face, hmi_colour("efisPanel"), 0);
    lv_obj_set_style_bg_opa(st->face, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(st->face, hmi_radius("radiusSm"), 0);

    /* Label */
    /* Label: the bar's width at most -- a long name ("Power / Regen") on a
       76 px bar takes a smaller face, then an ellipsis, never the next widget. */
    lv_label_set_text(st->label, st->label_text);
    double labelFs = hmi_font_size("fontSizeSm");
    size_t labelLen = strlen(st->label_text);
    if (labelLen > 0 && labelLen * labelFs * 0.6 > W)
        labelFs = fmax(8, W / (labelLen * 0.6));
    lv_obj_set_style_text_font(st->label, hmi_font((int)labelFs, 600), 0);
    lv_obj_set_style_text_color(st->label, hmi_colour("efisText"), 0);
    lv_obj_set_width(st->label, (int32_t)W);
    lv_label_set_long_mode(st->label, LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_align(st->label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_remove_flag(st->label, LV_OBJ_FLAG_HIDDEN);
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
    lv_obj_set_style_radius(st->valueBar, 0, 0);
    lv_obj_remove_flag(st->valueBar, LV_OBJ_FLAG_HIDDEN);
    lv_obj_align(st->well_frame, LV_ALIGN_TOP_MID, 0, wellPad);

    /* Value bar (inner) */
    int valBarH = (int)((wellH - 4) * fraction);
    lv_obj_set_size(st->valueBar, wellW - 4, valBarH);
    lv_obj_set_style_bg_color(st->valueBar, barColor, 0);
    lv_obj_set_style_bg_opa(st->valueBar, LV_OPA_COVER, 0);
    lv_obj_align(st->valueBar, LV_ALIGN_BOTTOM_MID, 0, 2);

    /* Caution line */
    double cautionFrac = (st->cautionValue - st->minimumValue) / span;
    int cautionY = wellPad + (int)((wellH - 2) * (1 - cautionFrac));   // the QML: y in the well
    lv_obj_set_size(st->cautionLine, wellW + 8, 2);
    lv_obj_set_style_bg_color(st->cautionLine, hmi_colour("efisCaution"), 0);
    lv_obj_set_style_bg_opa(st->cautionLine, LV_OPA_COVER, 0);
    lv_obj_align(st->cautionLine, LV_ALIGN_TOP_MID, 0, cautionY);

    /* Warning line */
    double warningFrac = (st->warningValue - st->minimumValue) / span;
    int warningY = wellPad + (int)((wellH - 2) * (1 - warningFrac));
    lv_obj_set_size(st->warningLine, wellW + 8, 2);
    lv_obj_set_style_bg_color(st->warningLine, hmi_colour("efisWarning"), 0);
    lv_obj_set_style_bg_opa(st->warningLine, LV_OPA_COVER, 0);
    lv_obj_align(st->warningLine, LV_ALIGN_TOP_MID, 0, warningY);

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
    snprintf(st->barColor, sizeof st->barColor, "%s", hmi_widget_str(w, "barColor", ""));
    st->horizontal = strcmp(hmi_widget_str(w, "orientation", "vertical"), "horizontal") == 0;

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
    else if (strcmp(prop, "units") == 0)
        snprintf(st->units_text, sizeof st->units_text, "%s", hmi_value_as_str(value, ""));
    else if (strcmp(prop, "barColor") == 0)
        snprintf(st->barColor, sizeof st->barColor, "%s", hmi_value_as_str(value, ""));
    else if (strcmp(prop, "orientation") == 0)
        st->horizontal = strcmp(hmi_value_as_str(value, "vertical"), "horizontal") == 0;
    else if (strcmp(prop, "label") == 0)   // through layout(), which fits it to the bar
        snprintf(st->label_text, sizeof st->label_text, "%s", hmi_value_as_str(value, ""));
    else return;

    layout(w);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shenginebar = {"ShEngineBar", create, set_prop, destroy};