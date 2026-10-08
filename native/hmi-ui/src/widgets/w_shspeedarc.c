// widgets/w_shspeedarc.c -- kit widget ShSpeedArc (Rail, "Speed Arc").
//
// Spec: ui/qml/Shadcn/ShSpeedArc.qml (the Canvas face and the texts, step by
// step). A metro driver-cab speedometer on a transparent background: two
// concentric neon arcs open on the lower right (240 degrees, from 6 o'clock
// clockwise over the top to about 2 o'clock), the outer one the value, the
// inner one the full track; a needle with a faint wedge behind it; the value
// and unit in the centre; an optional target tick with a callout above it.
//
// Every dimension is relative to d = min(width, height); the centre is
// (width/2, height/2) exactly as the Canvas uses cx/cy. Angles are degrees,
// clockwise, 0 at 3 o'clock.
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

#define START_ANGLE 90.0
#define SWEEP 240.0

typedef struct {
    double value, maximumValue, target;
    bool showTarget;
    int decimals;
    char unit[32], targetLabel[48], outerColor[16], innerColor[16];
    lv_obj_t *face;
    lv_obj_t *readout, *unitLabel, *callout, *calloutText;
} state_t;

static double clamp(double v, double lo, double hi) { return v < lo ? lo : v > hi ? hi : v; }
static double span_of(const state_t *st) { return fmax(0.0001, st->maximumValue); }
static double angle_of(const state_t *st, double v)
{
    return START_ANGLE + SWEEP * clamp(v, 0, st->maximumValue) / span_of(st);
}
static int decimals_of(const state_t *st) { return st->decimals < 0 ? 0 : st->decimals > 6 ? 6 : st->decimals; }

// The round-capped stroked arc the Canvas draws with lineCap "round".
static void arc_round(const hmi_draw_t *d, double cx, double cy, double r, double w,
                      double a0, double a1, lv_color_t c, lv_opa_t opa)
{
    if (a1 <= a0 || r <= 0 || w <= 0) return;
    lv_draw_arc_dsc_t dsc;
    lv_draw_arc_dsc_init(&dsc);
    dsc.center.x = (int32_t)lround(d->coords.x1 + cx);
    dsc.center.y = (int32_t)lround(d->coords.y1 + cy);
    dsc.radius = (uint16_t)lround(r + w / 2);
    dsc.width = (int32_t)lround(w);
    dsc.start_angle = (lv_value_precise_t)a0;
    dsc.end_angle = (lv_value_precise_t)a1;
    dsc.color = c;
    dsc.opa = opa;
    dsc.rounded = 1;
    lv_draw_arc(d->layer, &dsc);
}

// A neon arc: two wide translucent strokes under the solid one.
static void neon_arc(const hmi_draw_t *d, double cx, double cy, double r, double w,
                     double a0, double a1, lv_color_t c)
{
    arc_round(d, cx, cy, r, w * 3.0, a0, a1, c, (lv_opa_t)(0.10 * 255));
    arc_round(d, cx, cy, r, w * 1.9, a0, a1, c, (lv_opa_t)(0.18 * 255));
    arc_round(d, cx, cy, r, w, a0, a1, c, LV_OPA_COVER);
}

// A filled pie slice from the centre (the Canvas moveTo(cx,cy) + arc + fill).
static void wedge(const hmi_draw_t *d, double cx, double cy, double r, double a0, double a1,
                  lv_color_t c, lv_opa_t opa)
{
    hmi_draw_arc(d, cx, cy, r / 2, r, a0, a1, c, opa);
}

static void draw_cb(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    state_t *st = w->state;
    hmi_draw_t d = hmi_draw_begin(e);
    double W = w->width, H = w->height;
    double cx = W / 2, cy = H / 2;
    double dim = fmax(1, W < H ? W : H);
    lv_color_t outer = hmi_colour_hex(st->outerColor, NULL);
    lv_color_t inner = hmi_colour_hex(st->innerColor, NULL);
    lv_color_t white = lv_color_hex(0xffffff);

    double outerR = 0.40 * dim, outerW = 0.034 * dim;
    double innerR = 0.335 * dim, innerW = 0.024 * dim;
    double a0 = START_ANGLE, a1 = START_ANGLE + SWEEP;
    double av = angle_of(st, st->value);

    // 1. wedge behind the needle: the whole swept sector, brighter towards the needle
    double wedgeR = innerR - innerW / 2;
    wedge(&d, cx, cy, wedgeR, a0, av, outer, (lv_opa_t)(0.06 * 255));
    wedge(&d, cx, cy, wedgeR, fmax(a0, av - 40), av, outer, (lv_opa_t)(0.07 * 255));
    wedge(&d, cx, cy, wedgeR, fmax(a0, av - 14), av, outer, (lv_opa_t)(0.08 * 255));

    // 2. inner arc: the full track, purple
    neon_arc(&d, cx, cy, innerR, innerW, a0, a1, inner);

    // 3. outer arc: a faint track, then the value
    arc_round(&d, cx, cy, outerR, outerW, a0, a1, outer, (lv_opa_t)(0.14 * 255));
    if (av > a0) neon_arc(&d, cx, cy, outerR, outerW, a0, av, outer);

    // 4. needle, from 0.2 d out across both arcs
    double ar = av * M_PI / 180;
    double r0 = 0.20 * dim, r1 = outerR + outerW / 2 + 0.01 * dim;
    double nx0 = cx + r0 * cos(ar), ny0 = cy + r0 * sin(ar);
    double nx1 = cx + r1 * cos(ar), ny1 = cy + r1 * sin(ar);
    hmi_draw_line(&d, nx0, ny0, nx1, ny1, 0.026 * dim, outer, (lv_opa_t)(0.25 * 255));
    hmi_draw_line(&d, nx0, ny0, nx1, ny1, 0.011 * dim, outer, LV_OPA_COVER);

    // 5. target tick across the outer arc
    if (st->showTarget) {
        double at = angle_of(st, st->target) * M_PI / 180;
        double t0 = outerR - outerW / 2 - 0.022 * dim, t1 = outerR + outerW / 2 + 0.022 * dim;
        hmi_draw_line(&d, cx + t0 * cos(at), cy + t0 * sin(at), cx + t1 * cos(at), cy + t1 * sin(at),
                      0.010 * dim, white, LV_OPA_COVER);
    }
}

static void update_texts(hmi_widget_t *w)
{
    state_t *st = w->state;
    int dp = decimals_of(st);
    lv_label_set_text_fmt(st->readout, "%.*f", dp, clamp(st->value, 0, st->maximumValue));
    lv_label_set_text(st->unitLabel, st->unit);
    lv_obj_set_style_text_color(st->unitLabel, hmi_colour_hex(st->outerColor, NULL), 0);

    // "<targetLabel>: <target> <unit in lower case>", e.g. "TARGET: 60 km/h"
    char unit[32];
    size_t i = 0;
    for (; st->unit[i] && i < sizeof unit - 1; ++i)
        unit[i] = (char)((st->unit[i] >= 'A' && st->unit[i] <= 'Z') ? st->unit[i] + 32 : st->unit[i]);
    unit[i] = 0;
    char num[32], text[128];
    snprintf(num, sizeof num, "%.*f", dp, clamp(st->target, 0, st->maximumValue));
    snprintf(text, sizeof text, "%s%s%s%s%s", st->targetLabel, st->targetLabel[0] ? ": " : "",
             num, unit[0] ? " " : "", unit);
    lv_label_set_text(st->calloutText, text);
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = w->width, H = w->height;
    double cx = W / 2, cy = H / 2;
    double dim = fmax(1, W < H ? W : H);

    // centre readout and unit; a long readout ("100.0") takes a smaller face
    // so it stays inside the inner arc (about 0.58 d wide)
    size_t chars = strlen(lv_label_get_text(st->readout));
    double fs = fmin(0.226 * dim, 0.58 * dim / (fmax(1, chars) * 0.62));
    lv_obj_set_style_text_font(st->readout, hmi_font(hmi_px_min(fs, 8), 700), 0);
    lv_obj_align(st->readout, LV_ALIGN_CENTER, 0, -hmi_px(0.045 * dim));
    lv_obj_set_style_text_font(st->unitLabel, hmi_font(hmi_px_min(0.071 * dim, 7), 500), 0);
    lv_obj_align_to(st->unitLabel, st->readout, LV_ALIGN_OUT_BOTTOM_MID, 0, -hmi_px(0.03 * dim));

    // target callout: a dark rounded box over the tick. On the upper part of
    // the dial (sin < -0.35) it sits centred above the tick; elsewhere it is
    // pushed outwards from the tick's outer end, clear of the readout.
    // Either way it is kept inside the widget.
    if (!st->showTarget) {
        lv_obj_add_flag(st->callout, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_remove_flag(st->callout, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_text_font(st->calloutText, hmi_font(hmi_px_min(0.048 * dim, 7), 500), 0);
        lv_obj_set_style_radius(st->callout, hmi_px(0.018 * dim), 0);
        lv_obj_set_style_pad_hor(st->callout, hmi_px(0.026 * dim), 0);
        lv_obj_set_style_pad_ver(st->callout, hmi_px(0.012 * dim), 0);
        lv_obj_update_layout(st->callout);
        double bw = lv_obj_get_width(st->callout), bh = lv_obj_get_height(st->callout);
        double outerR = 0.40 * dim, outerW = 0.034 * dim;
        double at = angle_of(st, st->target) * M_PI / 180;
        double tr = outerR + outerW / 2 + 0.022 * dim;            // the tick's outer end
        double gap = 0.014 * dim, bx, by;
        if (sin(at) < -0.35) {
            bx = cx + outerR * cos(at) - bw / 2;
            by = cy + tr * sin(at) - gap - bh;
        } else {
            bx = cx + tr * cos(at) + cos(at) * (bw / 2 + gap) - bw / 2;
            by = cy + tr * sin(at) + sin(at) * (bh / 2 + gap) - bh / 2;
        }
        bx = clamp(bx, 0, fmax(0, W - bw));
        by = clamp(by, 0, fmax(0, H - bh));
        // Never over the readout: the box steps up or down (whichever is
        // nearer) out of the band the number and unit occupy.
        double half = lv_obj_get_width(st->readout) / 2.0 + gap;
        double zoneTop = cy - 0.15 * dim, zoneBottom = cy + 0.15 * dim;
        if (bx < cx + half && bx + bw > cx - half && by < zoneBottom && by + bh > zoneTop) {
            double up = zoneTop - bh, down = zoneBottom;
            by = clamp(fabs(by - up) <= fabs(by - down) ? up : down, 0, fmax(0, H - bh));
        }
        lv_obj_set_pos(st->callout, hmi_px(bx), hmi_px(by));
    }
    lv_obj_invalidate(st->face);
}

static void copy_str(char *dst, size_t len, const char *src)
{
    if (src == dst) return;   // the default handed back: already in place
    snprintf(dst, len, "%s", src ? src : "");
}

static void read_model(hmi_widget_t *w)
{
    state_t *st = w->state;
    st->value = hmi_widget_num(w, "value", 55);
    st->maximumValue = hmi_widget_num(w, "maximumValue", 100);
    st->target = hmi_widget_num(w, "target", 60);
    st->showTarget = hmi_widget_bool(w, "showTarget", true);
    st->decimals = (int)hmi_widget_num(w, "decimals", 0);
    copy_str(st->unit, sizeof st->unit, hmi_widget_str(w, "unit", "KM/H"));
    copy_str(st->targetLabel, sizeof st->targetLabel, hmi_widget_str(w, "targetLabel", "TARGET"));
    copy_str(st->outerColor, sizeof st->outerColor, hmi_widget_str(w, "outerColor", "#22d3ee"));
    copy_str(st->innerColor, sizeof st->innerColor, hmi_widget_str(w, "innerColor", "#a855f7"));
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
    st->readout = hmi_make_label(face, 32, 700, lv_color_hex(0xffffff), "");
    st->unitLabel = hmi_make_label(face, 14, 500, lv_color_hex(0x22d3ee), "");

    lv_obj_t *box = lv_obj_create(face);
    lv_obj_remove_style_all(box);
    lv_obj_remove_flag(box, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(box, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_style_bg_color(box, lv_color_hex(0x1c1c22), 0);
    lv_obj_set_style_bg_opa(box, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(box, lv_color_hex(0x3a3a44), 0);
    lv_obj_set_style_border_opa(box, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(box, 1, 0);
    st->callout = box;
    st->calloutText = hmi_make_label(box, 14, 500, lv_color_hex(0xffffff), "");

    lv_obj_add_event_cb(face, draw_cb, LV_EVENT_DRAW_MAIN, w);
    read_model(w);
    update_texts(w);
    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    // Bound props arrive with the value: keep our copy from the argument.
    if (strcmp(prop, "value") == 0) st->value = hmi_value_as_num(value, st->value);
    else if (strcmp(prop, "maximumValue") == 0) st->maximumValue = hmi_value_as_num(value, st->maximumValue);
    else if (strcmp(prop, "target") == 0) st->target = hmi_value_as_num(value, st->target);
    else if (strcmp(prop, "showTarget") == 0) st->showTarget = hmi_value_as_bool(value, st->showTarget);
    else if (strcmp(prop, "decimals") == 0) st->decimals = (int)hmi_value_as_num(value, st->decimals);
    else if (strcmp(prop, "unit") == 0) copy_str(st->unit, sizeof st->unit, hmi_value_as_str(value, st->unit));
    else if (strcmp(prop, "targetLabel") == 0)
        copy_str(st->targetLabel, sizeof st->targetLabel, hmi_value_as_str(value, st->targetLabel));
    else if (strcmp(prop, "outerColor") == 0)
        copy_str(st->outerColor, sizeof st->outerColor, hmi_value_as_str(value, st->outerColor));
    else if (strcmp(prop, "innerColor") == 0)
        copy_str(st->innerColor, sizeof st->innerColor, hmi_value_as_str(value, st->innerColor));
    else return;
    update_texts(w);
    layout(w);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shspeedarc = {"ShSpeedArc", create, set_prop, destroy};
