// widgets/w_shtractionbar.c -- kit widget ShTractionBar (Rail, "Traction / Brake").
//
// Spec: ui/qml/Shadcn/ShTractionBar.qml (geometry, colours, labels) and the
// Designer painter designer/canvas/rail/traction_bar.py. A metro cab's T/B
// indicator: the title on top, an upper track that fills from its bottom in
// green while value > 0 (traction %), the signed percent and the mode word
// between the tracks, a lower track that fills from its top in amber while
// value < 0 (braking %), and the side labels written bottom-to-top.
//
// Geometry (W x H, default 140 x 640) -- keep in step with the QML/painter:
//   track      x = 0.38 W, width 0.50 W, radius min(0.16 tw, 12)
//   upper      top 0.075 H, height 0.36 H
//   lower      top 0.565 H, height 0.36 H
//   title      centred over the track in [0, 0.075 H)
//   percent    centred on W/2 at upperBottom + gap * 0.36
//   mode word  centred on W/2 at upperBottom + gap * 0.76
//   side label centred at x = 0.55 * trackX, rotated -90 deg on its track
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

#include "src/misc/lv_area_private.h"

typedef struct {
    double value;
    char title_text[64], powerLabel[64], brakeLabel[64], propulsionText[64], brakingText[64];
    lv_obj_t *face, *title, *percent, *mode, *power, *brake;
} state_t;

typedef struct {
    double tx, tw, th, upTop, lowTop, radius;
} geom_t;

static geom_t geometry(const hmi_widget_t *w)
{
    double W = fmax(1, w->width), H = fmax(1, w->height);
    geom_t g;
    g.tx = W * 0.38;
    g.tw = W * 0.50;
    g.th = H * 0.36;
    g.upTop = H * 0.075;
    g.lowTop = H * 0.565;
    g.radius = fmin(g.tw * 0.16, 12);
    return g;
}

static lv_color_t hex(const char *s) { return hmi_colour_hex(s, NULL); }

// A rounded rect with a vertical two-stop gradient (c0 at the top, c1 at the
// bottom), clipped to the rows [clipTop, clipBottom).
static void grad_rect(hmi_draw_t *d, double x, double y, double w, double h, int radius,
                      lv_color_t c0, lv_opa_t o0, lv_color_t c1, lv_opa_t o1,
                      double clipTop, double clipBottom)
{
    if (w <= 0 || h <= 0 || clipBottom <= clipTop) return;
    lv_area_t before = d->layer->_clip_area;
    lv_area_t want = {d->coords.x1 + (int32_t)floor(x), d->coords.y1 + (int32_t)lround(clipTop),
                      d->coords.x1 + (int32_t)ceil(x + w), d->coords.y1 + (int32_t)lround(clipBottom) - 1};
    lv_area_t clip;
    if (want.y2 < want.y1 || !lv_area_intersect(&clip, &want, &before)) return;
    d->layer->_clip_area = clip;
    lv_draw_rect_dsc_t dsc;
    lv_draw_rect_dsc_init(&dsc);
    dsc.radius = radius;
    dsc.bg_opa = LV_OPA_COVER;
    dsc.bg_grad.dir = LV_GRAD_DIR_VER;
    dsc.bg_grad.stops_count = 2;
    dsc.bg_grad.stops[0].color = c0;
    dsc.bg_grad.stops[0].opa = o0;
    dsc.bg_grad.stops[0].frac = 0;
    dsc.bg_grad.stops[1].color = c1;
    dsc.bg_grad.stops[1].opa = o1;
    dsc.bg_grad.stops[1].frac = 255;
    dsc.border_width = 0;
    lv_area_t a = {(int32_t)lround(d->coords.x1 + x), (int32_t)lround(d->coords.y1 + y),
                   (int32_t)lround(d->coords.x1 + x + w) - 1, (int32_t)lround(d->coords.y1 + y + h) - 1};
    lv_draw_rect(d->layer, &dsc, &a);
    d->layer->_clip_area = before;
}

static void track(hmi_draw_t *d, double x, double y, double w, double h, int radius,
                  lv_color_t bg, lv_color_t border)
{
    lv_draw_rect_dsc_t dsc;
    lv_draw_rect_dsc_init(&dsc);
    dsc.radius = radius;
    dsc.bg_color = bg;
    dsc.bg_opa = LV_OPA_COVER;
    dsc.border_color = border;
    dsc.border_width = 1;
    dsc.border_opa = LV_OPA_COVER;
    lv_area_t a = {(int32_t)lround(d->coords.x1 + x), (int32_t)lround(d->coords.y1 + y),
                   (int32_t)lround(d->coords.x1 + x + w) - 1, (int32_t)lround(d->coords.y1 + y + h) - 1};
    lv_draw_rect(d->layer, &dsc, &a);
}

static void draw_cb(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    state_t *st = w->state;
    hmi_draw_t d = hmi_draw_begin(e);
    geom_t g = geometry(w);
    int r = (int)lround(g.radius);
    double power = fmax(0, fmin(100, st->value)) / 100.0;
    double brake = fmax(0, fmin(100, -st->value)) / 100.0;
    // the fill sits inside the 1 px border
    double ix = g.tx + 1, iw = g.tw - 2, ir = fmax(0, g.radius - 1);

    // Upper track: traction, filled from the bottom.
    track(&d, g.tx, g.upTop, g.tw, g.th, r, hex("#0f1a12"), hex("#1f3a26"));
    double upBottom = g.upTop + g.th;
    if (power > 0) {
        double fillTop = upBottom - 1 - (g.th - 2) * power;
        // the gradient spans the filled part: deep green at its top, bright at the bottom
        double gy = fmax(g.upTop + 1, fillTop - ir);
        grad_rect(&d, ix, gy, iw, upBottom - 1 - gy, (int)lround(ir),
                  hex("#166534"), LV_OPA_COVER, hex("#4ade80"), LV_OPA_COVER, fillTop, upBottom - 1);
        // the level mark, where the track is straight (in the round ends the fill edge reads alone)
        double ly = fillTop - 1.5;
        if (ly >= g.upTop + ir && ly + 3 <= upBottom - ir)
            hmi_draw_fill(&d, ix, ly, iw, 3, hex("#bef264"), LV_OPA_COVER, 0);
    }

    // Lower track: braking, filled from the top; a faint hint when idle.
    track(&d, g.tx, g.lowTop, g.tw, g.th, r, hex("#1a140a"), hex("#3a2a10"));
    double lowBottom = g.lowTop + g.th;
    if (brake > 0) {
        double fillBottom = g.lowTop + 1 + (g.th - 2) * brake;
        double gb = fmin(lowBottom - 1, fillBottom + ir);
        grad_rect(&d, ix, g.lowTop + 1, iw, gb - g.lowTop - 1, (int)lround(ir),
                  hex("#f59e0b"), LV_OPA_COVER, hex("#92400e"), LV_OPA_COVER, g.lowTop + 1, fillBottom);
        // the level mark, where the track is straight (in the round ends the fill edge reads alone)
        double ly = fillBottom - 1.5;
        if (ly >= g.lowTop + ir && ly + 3 <= lowBottom - ir)
            hmi_draw_fill(&d, ix, ly, iw, 3, hex("#fcd34d"), LV_OPA_COVER, 0);
    } else {
        grad_rect(&d, ix, g.lowTop + 1, iw, g.th - 2, (int)lround(ir),
                  hex("#f59e0b"), (lv_opa_t)lround(255 * 0.16), hex("#92400e"), (lv_opa_t)lround(255 * 0.03),
                  g.lowTop + 1, lowBottom - 1);
    }
}

static void place_centered(lv_obj_t *l, double cx, double cy)
{
    lv_obj_update_layout(l);
    int lw = lv_obj_get_width(l), lh = lv_obj_get_height(l);
    lv_obj_set_pos(l, hmi_px(cx - lw / 2.0), hmi_px(cy - lh / 2.0));
}

static void place_vertical(lv_obj_t *l, double cx, double cy)
{
    lv_obj_update_layout(l);
    int lw = lv_obj_get_width(l), lh = lv_obj_get_height(l);
    lv_obj_set_style_transform_pivot_x(l, lw / 2, 0);
    lv_obj_set_style_transform_pivot_y(l, lh / 2, 0);
    lv_obj_set_style_transform_rotation(l, -900, 0);
    lv_obj_set_pos(l, hmi_px(cx - lw / 2.0), hmi_px(cy - lh / 2.0));
}

static void update_readout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width);
    geom_t g = geometry(w);
    long pct = lround(fmin(100, fabs(st->value)));
    char buf[24];
    const char *word;
    lv_color_t c;
    if (pct > 0 && st->value > 0) {
        snprintf(buf, sizeof buf, "+%ld%%", pct);
        c = hex("#4ade80");
        word = st->propulsionText;
    } else if (pct > 0) {
        snprintf(buf, sizeof buf, "-%ld%%", pct);
        c = hex("#f59e0b");
        word = st->brakingText;
    } else {
        snprintf(buf, sizeof buf, "0%%");
        c = hex("#a1a1aa");
        word = "Coast";
    }
    double upBottom = g.upTop + g.th, gap = g.lowTop - upBottom;
    lv_label_set_text(st->percent, buf);
    lv_obj_set_style_text_color(st->percent, c, 0);
    lv_label_set_text(st->mode, word);
    place_centered(st->percent, W / 2, upBottom + gap * 0.36);
    place_centered(st->mode, W / 2, upBottom + gap * 0.76);
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    geom_t g = geometry(w);
    lv_obj_set_size(st->face, (int32_t)W, (int32_t)H);
    lv_obj_set_style_text_font(st->title, hmi_font(hmi_px_min(fmin(W * 0.21, H * 0.047), 8), 600), 0);
    lv_obj_set_style_text_font(st->percent, hmi_font(hmi_px_min(fmin(W * 0.26, H * 0.056), 10), 700), 0);
    lv_obj_set_style_text_font(st->mode, hmi_font(hmi_px_min(fmin(W * 0.13, H * 0.028), 7), 500), 0);
    int side = hmi_px_min(fmin(W * 0.115, H * 0.025), 7);
    lv_obj_set_style_text_font(st->power, hmi_font(side, 600), 0);
    lv_obj_set_style_text_font(st->brake, hmi_font(side, 600), 0);

    lv_label_set_text(st->title, st->title_text);
    lv_label_set_text(st->power, st->powerLabel);
    lv_label_set_text(st->brake, st->brakeLabel);
    place_centered(st->title, g.tx + g.tw / 2, g.upTop / 2);
    double sideX = g.tx * 0.55;
    place_vertical(st->power, sideX, g.upTop + g.th / 2);
    place_vertical(st->brake, sideX, g.lowTop + g.th / 2);
    update_readout(w);
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
    st->value = hmi_widget_num(w, "value", 30);
    snprintf(st->title_text, sizeof st->title_text, "%s", hmi_widget_str(w, "title", "T/B"));
    snprintf(st->powerLabel, sizeof st->powerLabel, "%s", hmi_widget_str(w, "powerLabel", "POWER"));
    snprintf(st->brakeLabel, sizeof st->brakeLabel, "%s", hmi_widget_str(w, "brakeLabel", "BRAKING"));
    snprintf(st->propulsionText, sizeof st->propulsionText, "%s", hmi_widget_str(w, "propulsionText", "Propulsion"));
    snprintf(st->brakingText, sizeof st->brakingText, "%s", hmi_widget_str(w, "brakingText", "Braking"));
    st->title = hmi_make_label(face, 30, 600, hex("#d4d4d8"), "");
    st->percent = hmi_make_label(face, 36, 700, hex("#4ade80"), "");
    st->mode = hmi_make_label(face, 18, 500, hex("#d4d4d8"), "");
    st->power = hmi_make_label(face, 16, 600, hex("#4ade80"), "");
    st->brake = hmi_make_label(face, 16, 600, hex("#f59e0b"), "");
    lv_obj_set_style_text_letter_space(st->power, 1, 0);
    lv_obj_set_style_text_letter_space(st->brake, 1, 0);
    lv_obj_add_event_cb(face, draw_cb, LV_EVENT_DRAW_MAIN, w);
    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "value") == 0) {
        st->value = hmi_value_as_num(value, st->value);
        update_readout(w);
    } else {
        char *dst = NULL;
        bool relayout = true;
        if (strcmp(prop, "title") == 0) dst = st->title_text;
        else if (strcmp(prop, "powerLabel") == 0) dst = st->powerLabel;
        else if (strcmp(prop, "brakeLabel") == 0) dst = st->brakeLabel;
        else if (strcmp(prop, "propulsionText") == 0) { dst = st->propulsionText; relayout = false; }
        else if (strcmp(prop, "brakingText") == 0) { dst = st->brakingText; relayout = false; }
        if (!dst) return;
        snprintf(dst, 64, "%s", hmi_value_as_str(value, ""));
        if (relayout) layout(w); else update_readout(w);
    }
    lv_obj_invalidate(st->face);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); w->state = NULL; }

const hmi_widget_ops_t hmi_widget_shtractionbar = {"ShTractionBar", create, set_prop, destroy};
