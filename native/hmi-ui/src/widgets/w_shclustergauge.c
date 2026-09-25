// widgets/w_shclustergauge.c -- kit widget ShClusterGauge (Automotive, "Cluster Gauge").
//
// Spec: ui/qml/Shadcn/ShClusterGauge.qml (texts, layout) and
// ui/qml/Shadcn/faces/canvas/ClusterGaugeFace.qml (the face, step by step).
// Every dimension is relative to d = min(width, height); the centre is
// (width/2, height/2) exactly as the Canvas uses cx/cy.
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

#define MAX_MAJORS 60

typedef struct {
    double value, minimumValue, maximumValue, majorStep, redlineFrom, sweep;
    bool showInnerDial;
    int decimals;
    lv_obj_t *face;
    lv_obj_t *readout, *unit, *caption, *label;
    lv_obj_t *scale[MAX_MAJORS];
    int nscale;
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
    double span = fmax(0.0001, st->maximumValue - st->minimumValue);
    double clamped = clamp(st->value, st->minimumValue, st->maximumValue);
    double startAngle = 90 + (360 - st->sweep) / 2;
    double arcR = 0.38 * dim, strokeW = 0.05 * dim;
    lv_color_t track = hmi_colour("autoTrack"), redline = hmi_colour("autoRedline");
    lv_color_t accentDeep = hmi_colour("autoAccentDeep"), accent = hmi_colour("autoAccent");
    lv_color_t glow = hmi_colour("autoGlow"), line = hmi_colour("autoLine"), muted = hmi_colour("autoMuted");

    // 1. track
    hmi_draw_arc(&d, cx, cy, arcR, strokeW, startAngle, startAngle + st->sweep, track, LV_OPA_COVER);
    // 2. redline band
    if (st->redlineFrom < st->maximumValue) {
        double a = startAngle + st->sweep * (st->redlineFrom - st->minimumValue) / span;
        hmi_draw_arc(&d, cx, cy, arcR, strokeW, a, startAngle + st->sweep, redline, LV_OPA_COVER);
    }
    // 3. value arc (gradient accentDeep -> accent) + glow + redline portion
    double valueAngle = startAngle + st->sweep * (clamped - st->minimumValue) / span;
    hmi_draw_arc_gradient(&d, cx, cy, arcR, strokeW, startAngle, valueAngle, accentDeep, accent);
    hmi_draw_arc(&d, cx, cy, arcR + strokeW * 0.35, 2, startAngle, valueAngle, glow, LV_OPA_COVER);
    if (clamped > st->redlineFrom && st->redlineFrom < st->maximumValue) {
        double a = startAngle + st->sweep * (st->redlineFrom - st->minimumValue) / span;
        hmi_draw_arc(&d, cx, cy, arcR, strokeW, a, valueAngle, redline, LV_OPA_COVER);
    }
    // 4. major ticks
    double tickLen = 0.035 * dim;
    // A majorStep far too small for the span (a typo in the design) would
    // draw millions of lines per frame; past 10x the label cap, draw no ticks.
    bool ticks = st->majorStep > 0 && span / st->majorStep <= MAX_MAJORS * 10;
    for (double mv = st->minimumValue; ticks && mv <= st->maximumValue + 0.0001; mv += st->majorStep) {
        double a = (startAngle + st->sweep * (mv - st->minimumValue) / span) * M_PI / 180;
        hmi_draw_line(&d, cx + (arcR + tickLen) * cos(a), cy + (arcR + tickLen) * sin(a),
                      cx + arcR * cos(a), cy + arcR * sin(a), 2,
                      mv >= st->redlineFrom ? redline : line, LV_OPA_COVER);
        if (st->majorStep <= 0) break;
    }
    // 5. minor ticks
    double minorLen = tickLen * 0.5;
    int steps = ticks ? (int)lround(span / st->majorStep) : 0;
    for (int s = 0; s < steps; ++s) {
        double base = st->minimumValue + s * st->majorStep;
        for (int m = 1; m < 5; ++m) {
            double mval = base + m * (st->majorStep / 5);
            if (mval > st->maximumValue + 0.0001) break;
            double a = (startAngle + st->sweep * (mval - st->minimumValue) / span) * M_PI / 180;
            hmi_draw_line(&d, cx + (arcR + minorLen) * cos(a), cy + (arcR + minorLen) * sin(a),
                          cx + arcR * cos(a), cy + arcR * sin(a), 1.2, muted, LV_OPA_COVER);
        }
    }
    // 6. inner dial: panel disc, a faint tint, a 1.5 px ring
    if (st->showInnerDial) {
        double innerR = 0.28 * dim;
        hmi_draw_disc(&d, cx, cy, innerR, hmi_colour("autoPanel"), LV_OPA_COVER);
        hmi_draw_disc(&d, cx, cy, innerR * 0.6, hmi_colour_hex("#0a4f8a", NULL), (lv_opa_t)(0.20 * 255 * 0.5));
        hmi_draw_arc(&d, cx, cy, innerR - 0.75, 1.5, 0, 360, hmi_colour("autoTileBorder"), LV_OPA_COVER);
    }
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = w->width, H = w->height;
    double dim = fmax(1, W < H ? W : H);
    double span = fmax(0.0001, st->maximumValue - st->minimumValue);
    double startAngle = 90 + (360 - st->sweep) / 2;
    lv_color_t line = hmi_colour("autoLine"), redline = hmi_colour("autoRedline");
    // scale numbers at radius 0.47 d, centred on the angle
    int fs = hmi_px_min(0.068 * dim, 7);
    double step = fmax(0.0001, st->majorStep);
    int i = 0;
    for (double v = st->minimumValue; v <= st->maximumValue + 0.0001 && i < MAX_MAJORS; v += step, ++i) {
        lv_obj_t *l = st->scale[i];
        if (!l) l = st->scale[i] = hmi_make_label(st->face, fs, 500, line, "");
        char buf[16];
        snprintf(buf, sizeof buf, "%.0f", v);
        lv_label_set_text(l, buf);
        lv_obj_set_style_text_font(l, hmi_font(fs, 500), 0);
        lv_obj_set_style_text_color(l, v >= st->redlineFrom ? redline : line, 0);
        double a = (startAngle + st->sweep * (v - st->minimumValue) / span) * M_PI / 180;
        lv_obj_align(l, LV_ALIGN_CENTER, hmi_px(0.47 * dim * cos(a)), hmi_px(0.47 * dim * sin(a)));
        lv_obj_remove_flag(l, LV_OBJ_FLAG_HIDDEN);
    }
    st->nscale = i;
    for (; i < MAX_MAJORS; ++i)
        if (st->scale[i]) lv_obj_add_flag(st->scale[i], LV_OBJ_FLAG_HIDDEN);

    lv_obj_set_style_text_font(st->readout, hmi_font(hmi_px(0.28 * dim), 600), 0);
    lv_obj_align(st->readout, LV_ALIGN_CENTER, 0, -hmi_px(0.07 * dim));
    lv_obj_set_style_text_font(st->unit, hmi_font(hmi_px(0.08 * dim), 400), 0);
    lv_obj_align_to(st->unit, st->readout, LV_ALIGN_OUT_BOTTOM_MID, 0, 2);
    lv_obj_set_style_text_font(st->caption, hmi_font(hmi_px(0.07 * dim), 500), 0);
    lv_obj_align_to(st->caption, st->readout, LV_ALIGN_OUT_TOP_MID, 0, -4);
    int lfs = hmi_px_min(0.045 * dim, 7);
    lv_obj_set_style_text_font(st->label, hmi_font(lfs, 400), 0);
    int lh = lv_font_get_line_height(hmi_font(lfs, 400));
    lv_obj_set_pos(st->label, hmi_px(W / 2 + 0.2 * dim), hmi_px(H / 2 + 0.33 * dim - lh / 2.0));
}

static void update_readout(hmi_widget_t *w)
{
    state_t *st = w->state;
    const char *readout = hmi_widget_str(w, "readout", "");
    if (readout[0]) {
        lv_label_set_text(st->readout, readout);
    } else {
        double clamped = clamp(st->value, st->minimumValue, st->maximumValue);
        lv_label_set_text_fmt(st->readout, "%.*f", st->decimals, clamped);
    }
    const char *cap = hmi_widget_str(w, "caption", "");
    lv_label_set_text(st->caption, cap);
    if (cap[0]) lv_obj_remove_flag(st->caption, LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(st->caption, LV_OBJ_FLAG_HIDDEN);
    lv_label_set_text(st->unit, hmi_widget_str(w, "readoutUnit", ""));
    const char *lbl = hmi_widget_str(w, "label", "");
    lv_label_set_text(st->label, lbl);
    if (lbl[0]) lv_obj_remove_flag(st->label, LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(st->label, LV_OBJ_FLAG_HIDDEN);
}

static void read_model(hmi_widget_t *w)
{
    state_t *st = w->state;
    st->value = hmi_widget_num(w, "value", 0);
    st->minimumValue = hmi_widget_num(w, "minimumValue", 0);
    st->maximumValue = hmi_widget_num(w, "maximumValue", 8);
    st->majorStep = hmi_widget_num(w, "majorStep", 1);
    st->redlineFrom = hmi_widget_num(w, "redlineFrom", 7);
    st->sweep = hmi_widget_num(w, "sweep", 240);
    st->showInnerDial = hmi_widget_bool(w, "showInnerDial", true);
    st->decimals = (int)hmi_widget_num(w, "decimals", 0);
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
    st->readout = hmi_make_label(face, 16, 600, hmi_colour("autoText"), "");
    st->unit = hmi_make_label(face, 12, 400, hmi_colour("autoMuted"), "");
    st->caption = hmi_make_label(face, 12, 500, hmi_colour("autoAmber"), "");
    st->label = hmi_make_label(face, 10, 400, hmi_colour("autoMuted"), "");
    lv_obj_add_event_cb(face, draw_cb, LV_EVENT_DRAW_MAIN, w);
    read_model(w);
    update_readout(w);
    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    (void)value;
    // The model already holds the new value for declared props; bound
    // props arrive here with the value: keep our copy from the argument.
    if (strcmp(prop, "value") == 0) st->value = hmi_value_as_num(value, st->value);
    else if (strcmp(prop, "minimumValue") == 0) st->minimumValue = hmi_value_as_num(value, st->minimumValue);
    else if (strcmp(prop, "maximumValue") == 0) st->maximumValue = hmi_value_as_num(value, st->maximumValue);
    else if (strcmp(prop, "majorStep") == 0) st->majorStep = hmi_value_as_num(value, st->majorStep);
    else if (strcmp(prop, "redlineFrom") == 0) st->redlineFrom = hmi_value_as_num(value, st->redlineFrom);
    else if (strcmp(prop, "sweep") == 0) st->sweep = hmi_value_as_num(value, st->sweep);
    else if (strcmp(prop, "showInnerDial") == 0) st->showInnerDial = hmi_value_as_bool(value, st->showInnerDial);
    else if (strcmp(prop, "decimals") == 0) st->decimals = (int)hmi_value_as_num(value, st->decimals);
    else if (strcmp(prop, "readout") == 0 || strcmp(prop, "readoutUnit") == 0 ||
             strcmp(prop, "caption") == 0 || strcmp(prop, "label") == 0) {
        // text props: read back through the model (bound text arrives as the value)
        if (strcmp(prop, "readout") == 0) {
            const char *s = hmi_value_as_str(value, "");
            if (s[0]) lv_label_set_text(st->readout, s);
            else lv_label_set_text_fmt(st->readout, "%.*f", st->decimals, clamp(st->value, st->minimumValue, st->maximumValue));
        } else if (strcmp(prop, "readoutUnit") == 0) lv_label_set_text(st->unit, hmi_value_as_str(value, ""));
        else if (strcmp(prop, "caption") == 0) {
            const char *s = hmi_value_as_str(value, "");
            lv_label_set_text(st->caption, s);
            if (s[0]) lv_obj_remove_flag(st->caption, LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(st->caption, LV_OBJ_FLAG_HIDDEN);
        } else {
            const char *s = hmi_value_as_str(value, "");
            lv_label_set_text(st->label, s);
            if (s[0]) lv_obj_remove_flag(st->label, LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(st->label, LV_OBJ_FLAG_HIDDEN);
        }
        layout(w);
        return;
    } else return;
    if (strcmp(prop, "value") == 0 || strcmp(prop, "decimals") == 0) {
        if (!hmi_widget_str(w, "readout", "")[0])
            lv_label_set_text_fmt(st->readout, "%.*f", st->decimals, clamp(st->value, st->minimumValue, st->maximumValue));
    }
    layout(w);
    lv_obj_invalidate(st->face);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shclustergauge = {"ShClusterGauge", create, set_prop, destroy};
