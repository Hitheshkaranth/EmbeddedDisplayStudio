// widgets/w_shenginegauge.c -- kit widget ShEngineGauge (Aviation, "Engine Gauge").
//
// Spec: ui/qml/Shadcn/ShEngineGauge.qml and faces/canvas/EngineGaugeFace.qml:
// four coloured bands over 240 degrees opening downward, a needle and hub,
// then a Column at the bottom: "<value> <units>" (semibold, fontSizeSm)
// over the label (fontSizeXs, mutedForeground).
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    double value, minimumValue, maximumValue, greenLow, greenHigh, cautionHigh;
    lv_obj_t *face, *readout, *label;
} state_t;

static double clamp(double v, double lo, double hi) { return v < lo ? lo : v > hi ? hi : v; }

static void draw_cb(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    state_t *st = w->state;
    hmi_draw_t d = hmi_draw_begin(e);
    double W = w->width, H = w->height;
    double cx = W / 2, cy = H / 2;
    double dim = W < H ? W : H;
    double r = dim / 2 - dim * 0.12;
    double stroke = fmax(4, dim * 0.11);
    double span = fmax(0.0001, st->maximumValue - st->minimumValue);
    double clamped = clamp(st->value, st->minimumValue, st->maximumValue);
    const double start = 150, sweep = 240;
    lv_color_t caution = hmi_colour("efisCaution"), normal = hmi_colour("efisNormal");
    lv_color_t warning = hmi_colour("efisWarning"), line = hmi_colour("efisLine");

#define BAND(from, to, col) do { \
        double a0 = start + sweep * ((from) - st->minimumValue) / span; \
        double a1 = start + sweep * ((to) - st->minimumValue) / span; \
        hmi_draw_arc(&d, cx, cy, r, stroke, a0, a1, col, LV_OPA_COVER); } while (0)
    BAND(st->minimumValue, st->greenLow, caution);
    BAND(st->greenLow, st->greenHigh, normal);
    BAND(st->greenHigh, st->cautionHigh, caution);
    BAND(st->cautionHigh, st->maximumValue, warning);
#undef BAND

    double a = (start + sweep * (clamped - st->minimumValue) / span) * M_PI / 180;
    double len = r - stroke * 0.6;
    hmi_draw_line(&d, cx, cy, cx + cos(a) * len, cy + sin(a) * len, fmax(2, dim * 0.025), line, LV_OPA_COVER);
    hmi_draw_disc(&d, cx, cy, fmax(2, dim * 0.03), line, LV_OPA_COVER);
}

static void update_text(hmi_widget_t *w)
{
    state_t *st = w->state;
    double clamped = clamp(st->value, st->minimumValue, st->maximumValue);
    const char *units = hmi_widget_str(w, "units", "");
    if (units[0]) lv_label_set_text_fmt(st->readout, "%.0f %s", clamped, units);
    else lv_label_set_text_fmt(st->readout, "%.0f", clamped);
    const char *label = hmi_widget_str(w, "label", "");
    lv_label_set_text(st->label, label);
    if (label[0]) {
        lv_obj_remove_flag(st->label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_align(st->label, LV_ALIGN_BOTTOM_MID, 0, 0);
        lv_obj_align_to(st->readout, st->label, LV_ALIGN_OUT_TOP_MID, 0, 0);
    } else {
        lv_obj_add_flag(st->label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_align(st->readout, LV_ALIGN_BOTTOM_MID, 0, 0);
    }
}

static void read_model(hmi_widget_t *w)
{
    state_t *st = w->state;
    st->value = hmi_widget_num(w, "value", 0);
    st->minimumValue = hmi_widget_num(w, "minimumValue", 0);
    st->maximumValue = hmi_widget_num(w, "maximumValue", 100);
    st->greenLow = hmi_widget_num(w, "greenLow", 20);
    st->greenHigh = hmi_widget_num(w, "greenHigh", 70);
    st->cautionHigh = hmi_widget_num(w, "cautionHigh", 85);
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
    st->readout = hmi_make_label(face, hmi_font_size("fontSizeSm"), 600, hmi_colour("efisText"), "");
    st->label = hmi_make_label(face, hmi_font_size("fontSizeXs"), 400, hmi_colour("mutedForeground"), "");
    lv_obj_add_event_cb(face, draw_cb, LV_EVENT_DRAW_MAIN, w);
    read_model(w);
    update_text(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "value") == 0) st->value = hmi_value_as_num(value, st->value);
    else if (strcmp(prop, "minimumValue") == 0) st->minimumValue = hmi_value_as_num(value, st->minimumValue);
    else if (strcmp(prop, "maximumValue") == 0) st->maximumValue = hmi_value_as_num(value, st->maximumValue);
    else if (strcmp(prop, "greenLow") == 0) st->greenLow = hmi_value_as_num(value, st->greenLow);
    else if (strcmp(prop, "greenHigh") == 0) st->greenHigh = hmi_value_as_num(value, st->greenHigh);
    else if (strcmp(prop, "cautionHigh") == 0) st->cautionHigh = hmi_value_as_num(value, st->cautionHigh);
    else if (strcmp(prop, "units") != 0 && strcmp(prop, "label") != 0) return;
    update_text(w);
    lv_obj_invalidate(st->face);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shenginegauge = {"ShEngineGauge", create, set_prop, destroy};
