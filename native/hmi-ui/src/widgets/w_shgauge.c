// widgets/w_shgauge.c -- kit widget ShGauge (Industrial, "Gauge").
//
// Spec: ui/qml/Shadcn/ShGauge.qml: a 270-degree track (muted, round caps)
// from 135 degrees, the value arc coloured success / warning / destructive
// by the thresholds (muted when out of range), and a centred column of
// label (xs, mutedForeground), value.toFixed(1) (max(xs, 0.18 dim),
// semibold, foreground) and unit (xs, mutedForeground), 2 px apart.
#include <math.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    double value, minValue, maxValue, thresholdWarning, thresholdFault;
    lv_obj_t *face, *label, *readout, *unit;
} state_t;

static void draw_arc_round(const hmi_draw_t *d, double cx, double cy, double r, double w,
                           double a0, double a1, lv_color_t c)
{
    if (a1 <= a0) return;
    lv_draw_arc_dsc_t dsc;
    lv_draw_arc_dsc_init(&dsc);
    dsc.center.x = (int32_t)lround(d->coords.x1 + cx);
    dsc.center.y = (int32_t)lround(d->coords.y1 + cy);
    dsc.radius = (uint16_t)lround(r + w / 2);
    dsc.width = (int32_t)lround(w);
    dsc.start_angle = (lv_value_precise_t)a0;
    dsc.end_angle = (lv_value_precise_t)a1;
    dsc.color = c;
    dsc.opa = LV_OPA_COVER;
    dsc.rounded = 1;
    lv_draw_arc(d->layer, &dsc);
}

static void draw_cb(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    state_t *st = w->state;
    hmi_draw_t d = hmi_draw_begin(e);
    double W = w->width, H = w->height;
    double dim = W < H ? W : H;
    double ox = (W - dim) / 2, oy = (H - dim) / 2;   // the dim x dim item is centred
    double stroke = fmax(2, dim * 0.1);
    double r = fmax(0.1, dim / 2 - stroke / 2);
    double cx = ox + dim / 2, cy = oy + dim / 2;
    draw_arc_round(&d, cx, cy, r, stroke, 135, 135 + 270, hmi_colour("muted"));
    bool out = isnan(st->value) || st->value < st->minValue || st->value > st->maxValue;
    lv_color_t vc = out ? hmi_colour("muted")
                  : st->value >= st->thresholdFault ? hmi_colour("destructive")
                  : st->value >= st->thresholdWarning ? hmi_colour("warning") : hmi_colour("success");
    double range = st->maxValue - st->minValue;
    double clamped = fmax(st->minValue, fmin(st->maxValue, st->value));
    double sweep = range > 0 ? 270 * (clamped - st->minValue) / range : 0;
    draw_arc_round(&d, cx, cy, r, stroke, 135, 135 + sweep, vc);
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = w->width, H = w->height;
    double dim = W < H ? W : H;
    int xs = hmi_font_size("fontSizeXs");
    int vfs = (int)fmax(xs, dim * 0.18);
    int colw = (int)(dim * 0.7);
    lv_obj_t *items[3] = {st->label, st->readout, st->unit};
    int fonts[3] = {xs, vfs, xs};
    int weights[3] = {400, 600, 400};
    int total = 0;
    for (int i = 0; i < 3; ++i) {
        lv_obj_set_style_text_font(items[i], hmi_font(fonts[i], weights[i]), 0);
        lv_obj_set_width(items[i], colw);
        lv_obj_set_style_text_align(items[i], LV_TEXT_ALIGN_CENTER, 0);
        total += lv_font_get_line_height(hmi_font(fonts[i], weights[i]));
    }
    total += 2 * 2;
    int y = (int)lround(H / 2 - total / 2.0);
    int x = (int)lround(W / 2 - colw / 2.0);
    for (int i = 0; i < 3; ++i) {
        lv_obj_set_pos(items[i], x, y);
        y += lv_font_get_line_height(hmi_font(fonts[i], weights[i])) + 2;
    }
}

static void update_text(hmi_widget_t *w)
{
    state_t *st = w->state;
    lv_label_set_text(st->label, hmi_widget_str(w, "label", ""));
    lv_label_set_text(st->unit, hmi_widget_str(w, "unit", ""));
    if (isnan(st->value) || st->value < st->minValue || st->value > st->maxValue)
        lv_label_set_text(st->readout, "--");
    else
        lv_label_set_text_fmt(st->readout, "%.1f", st->value);
}

static void read_model(hmi_widget_t *w)
{
    state_t *st = w->state;
    st->value = hmi_widget_num(w, "value", 0);
    // Two spellings are in circulation: ShGauge.qml (and this port) call the
    // range minValue/maxValue, while the palette and the generated schema
    // call it minimum/maximum -- so a range set in the Designer never
    // reached the panel, the gauge silently kept 0..100, and every reading
    // outside that showed as "--". Accept either rather than pick a winner
    // and break the designs that already use the other one.
    st->minValue = hmi_widget_num(w, "minValue", hmi_widget_num(w, "minimum", 0));
    st->maxValue = hmi_widget_num(w, "maxValue", hmi_widget_num(w, "maximum", 100));
    st->thresholdWarning = hmi_widget_num(w, "thresholdWarning", 75);
    st->thresholdFault = hmi_widget_num(w, "thresholdFault", 90);
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
    st->label = hmi_make_label(face, 12, 400, hmi_colour("mutedForeground"), "");
    st->readout = hmi_make_label(face, 20, 600, hmi_colour("foreground"), "");
    st->unit = hmi_make_label(face, 12, 400, hmi_colour("mutedForeground"), "");
    lv_obj_add_event_cb(face, draw_cb, LV_EVENT_DRAW_MAIN, w);
    read_model(w);
    update_text(w);
    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "value") == 0) st->value = hmi_value_as_num(value, st->value);
    else if (strcmp(prop, "minValue") == 0 || strcmp(prop, "minimum") == 0)
        st->minValue = hmi_value_as_num(value, st->minValue);
    else if (strcmp(prop, "maxValue") == 0 || strcmp(prop, "maximum") == 0)
        st->maxValue = hmi_value_as_num(value, st->maxValue);
    else if (strcmp(prop, "thresholdWarning") == 0) st->thresholdWarning = hmi_value_as_num(value, st->thresholdWarning);
    else if (strcmp(prop, "thresholdFault") == 0) st->thresholdFault = hmi_value_as_num(value, st->thresholdFault);
    else if (strcmp(prop, "label") == 0) { lv_label_set_text(st->label, hmi_value_as_str(value, "")); return; }
    else if (strcmp(prop, "unit") == 0) { lv_label_set_text(st->unit, hmi_value_as_str(value, "")); return; }
    else return;
    update_text(w);
    lv_obj_invalidate(st->face);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shgauge = {"ShGauge", create, set_prop, destroy};
