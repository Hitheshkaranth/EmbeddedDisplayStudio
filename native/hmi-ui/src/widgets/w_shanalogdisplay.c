// widgets/w_shanalogdisplay.c -- kit widget ShAnalogDisplay (Industrial, "Analog Display").
//
// Spec: ui/qml/Shadcn/ShAnalogDisplay.qml -- a track bar with severity
// coloring, threshold markers, and a pointer.  vertical mode uses a tall
// track; horizontal (default) is wide.
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    lv_obj_t *face, *caption, *track, *fill, *pointer, *readout;
    // threshold markers inside track
    lv_obj_t *markers[4];
    double value, minValue, maxValue, normLow, normHigh, warnLow, warnHigh;
    char label_text[64];
    char unit_text[16];
    char severity_str[32];
    bool vertical;
} state_t;

static lv_color_t severity_color_for(double value, double warnLow, double warnHigh)
{
    if (value < warnLow || value > warnHigh) return hmi_colour("destructive");
    if (value < 20 || value > 80) return hmi_colour("warning"); // normLow/normHigh defaults
    return hmi_colour("success");
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);

    lv_color_t trackCol = hmi_colour("secondary");
    lv_color_t fgCol = hmi_colour("foreground");
    lv_color_t efisPanel = hmi_colour("efisPanel");

    double clamped = fmax(st->minValue, fmin(st->maxValue, st->value));
    double fraction = st->maxValue > st->minValue ? (clamped - st->minValue) / (st->maxValue - st->minValue) : 0;

    // Determine severity color
    lv_color_t sevColor;
    if (clamped < st->warnLow || clamped > st->warnHigh) sevColor = hmi_colour("destructive");
    else if (clamped < st->normLow || clamped > st->normHigh) sevColor = hmi_colour("warning");
    else sevColor = hmi_colour("success");

    /* Caption */
    lv_label_set_text(st->caption, st->label_text);
    lv_obj_set_style_text_font(st->caption, hmi_font(hmi_font_size("fontSizeXs"), 400), 0);
    lv_obj_set_style_text_color(st->caption, sevColor, 0);
    lv_obj_set_style_text_align(st->caption, LV_TEXT_ALIGN_CENTER, 0);
    if (st->label_text[0]) {
        lv_obj_set_size(st->caption, W, 16);
        lv_obj_align(st->caption, LV_ALIGN_TOP_MID, 0, 0);
        lv_obj_remove_flag(st->caption, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(st->caption, LV_OBJ_FLAG_HIDDEN);
    }

    /* Track dimensions */
    int trackMargin = 4;
    int readoutH = 20;
    int captionH = st->label_text[0] ? 16 : 0;
    int trackH, trackW;
    int trackX, trackY;

    if (st->vertical) {
        trackW = (int)W - 2 * trackMargin;
        trackH = (int)H - captionH - readoutH - 2 * trackMargin;
        trackX = trackMargin;
        trackY = captionH + trackMargin;
    } else {
        trackW = (int)W - 2 * trackMargin;
        trackH = (int)H - captionH - readoutH - 2 * trackMargin;
        trackX = trackMargin;
        trackY = captionH + trackMargin;
    }

    /* Track background */
    lv_obj_set_size(st->track, trackW, trackH);
    lv_obj_set_style_bg_color(st->track, trackCol, 0);
    lv_obj_set_style_bg_opa(st->track, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(st->track, hmi_radius("radiusSm"), 0);
    lv_obj_set_pos(st->track, trackX, trackY);

    /* Fill (severity-colored portion) */
    if (st->vertical) {
        int fillH = (int)(trackH * fraction);
        lv_obj_set_size(st->fill, trackW, fillH);
        lv_obj_set_style_bg_color(st->fill, sevColor, 0);
        lv_obj_set_style_bg_opa(st->fill, LV_OPA_COVER, 0);
        lv_obj_set_pos(st->fill, trackX, trackY + trackH - fillH);
    } else {
        int fillW = (int)(trackW * fraction);
        lv_obj_set_size(st->fill, fillW, trackH);
        lv_obj_set_style_bg_color(st->fill, sevColor, 0);
        lv_obj_set_style_bg_opa(st->fill, LV_OPA_COVER, 0);
        lv_obj_set_pos(st->fill, trackX, trackY);
    }

    /* Threshold markers */
    double markers_vals[4] = {st->warnLow, st->normLow, st->normHigh, st->warnHigh};
    for (int i = 0; i < 4; i++) {
        double frac = st->maxValue > st->minValue ? (markers_vals[i] - st->minValue) / (st->maxValue - st->minValue) : 0;
        if (frac >= 0 && frac <= 1) {
            lv_obj_set_style_bg_color(st->markers[i], fgCol, 0);
            lv_obj_set_style_bg_opa(st->markers[i], (lv_opa_t)(0.45 * 255), 0);
            if (st->vertical) {
                lv_obj_set_size(st->markers[i], trackW, 1);
                lv_obj_set_pos(st->markers[i], trackX, trackY + (int)(trackH * (1 - frac)));
            } else {
                lv_obj_set_size(st->markers[i], 1, trackH);
                lv_obj_set_pos(st->markers[i], trackX + (int)(trackW * frac), trackY);
            }
            lv_obj_remove_flag(st->markers[i], LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_add_flag(st->markers[i], LV_OBJ_FLAG_HIDDEN);
        }
    }

    /* Pointer */
    if (st->vertical) {
        lv_obj_set_size(st->pointer, trackW, 3);
        int py = trackY + (int)(trackH * (1 - fraction)) - 1;
        lv_obj_set_pos(st->pointer, trackX, py);
    } else {
        lv_obj_set_size(st->pointer, 3, trackH);
        int px = trackX + (int)(trackW * fraction) - 1;
        lv_obj_set_pos(st->pointer, px, trackY);
    }
    lv_obj_set_style_bg_color(st->pointer, fgCol, 0);
    lv_obj_set_style_bg_opa(st->pointer, LV_OPA_COVER, 0);

    /* Readout */
    char display[128];
    if (st->value != st->value) { // NaN check
        snprintf(display, sizeof display, "--");
    } else {
        snprintf(display, sizeof display, "%.1f%s", clamped, st->unit_text);
    }
    lv_label_set_text(st->readout, display);
    lv_obj_set_style_text_font(st->readout, hmi_font(hmi_font_size("fontSizeSm"), 600), 0);
    lv_obj_set_style_text_color(st->readout, sevColor, 0);
    lv_obj_set_style_text_align(st->readout, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_size(st->readout, W, readoutH);
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

    st->caption = lv_label_create(face);
    lv_obj_remove_style_all(st->caption);
    lv_label_set_long_mode(st->caption, LV_LABEL_LONG_CLIP);

    st->track = lv_obj_create(face);
    lv_obj_remove_style_all(st->track);
    lv_obj_remove_flag(st->track, LV_OBJ_FLAG_SCROLLABLE);

    st->fill = lv_obj_create(st->track);
    lv_obj_remove_style_all(st->fill);
    lv_obj_remove_flag(st->fill, LV_OBJ_FLAG_SCROLLABLE);

    st->pointer = lv_obj_create(face);
    lv_obj_remove_style_all(st->pointer);
    lv_obj_remove_flag(st->pointer, LV_OBJ_FLAG_SCROLLABLE);

    st->readout = lv_label_create(face);
    lv_obj_remove_style_all(st->readout);
    lv_label_set_long_mode(st->readout, LV_LABEL_LONG_CLIP);

    for (int i = 0; i < 4; i++) {
        st->markers[i] = lv_obj_create(st->track);
        lv_obj_remove_style_all(st->markers[i]);
        lv_obj_remove_flag(st->markers[i], LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_add_flag(st->markers[i], LV_OBJ_FLAG_HIDDEN);
    }

    st->value = hmi_widget_num(w, "value", 0);
    st->minValue = hmi_widget_num(w, "minValue", 0);
    st->maxValue = hmi_widget_num(w, "maxValue", 100);
    st->normLow = hmi_widget_num(w, "normLow", 20);
    st->normHigh = hmi_widget_num(w, "normHigh", 80);
    st->warnLow = hmi_widget_num(w, "warnLow", 10);
    st->warnHigh = hmi_widget_num(w, "warnHigh", 90);
    snprintf(st->label_text, sizeof st->label_text, "%s", hmi_widget_str(w, "label", ""));
    snprintf(st->unit_text, sizeof st->unit_text, "%s", hmi_widget_str(w, "unit", ""));
    st->vertical = hmi_widget_bool(w, "vertical", false);

    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "value") == 0) st->value = hmi_value_as_num(value, st->value);
    else if (strcmp(prop, "minValue") == 0) st->minValue = hmi_value_as_num(value, st->minValue);
    else if (strcmp(prop, "maxValue") == 0) st->maxValue = hmi_value_as_num(value, st->maxValue);
    else if (strcmp(prop, "normLow") == 0) st->normLow = hmi_value_as_num(value, st->normLow);
    else if (strcmp(prop, "normHigh") == 0) st->normHigh = hmi_value_as_num(value, st->normHigh);
    else if (strcmp(prop, "warnLow") == 0) st->warnLow = hmi_value_as_num(value, st->warnLow);
    else if (strcmp(prop, "warnHigh") == 0) st->warnHigh = hmi_value_as_num(value, st->warnHigh);
    else if (strcmp(prop, "unit") == 0) { snprintf(st->unit_text, sizeof st->unit_text, "%s", hmi_value_as_str(value, "")); }
    else if (strcmp(prop, "label") == 0) { snprintf(st->label_text, sizeof st->label_text, "%s", hmi_value_as_str(value, "")); }
    else if (strcmp(prop, "vertical") == 0) { st->vertical = hmi_value_as_bool(value, st->vertical); }
    else return;

    layout(w);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shanalogdisplay = {"ShAnalogDisplay", create, set_prop, destroy};