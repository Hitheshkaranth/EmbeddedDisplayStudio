// widgets/draw_util.h -- the Canvas-2D vocabulary on top of LVGL's draw API,
// for the instrument faces. Angles are degrees, clockwise, 0 at 3 o'clock
// (the Canvas painters' frame); coordinates are the widget's own, the
// helpers add the object's screen origin.
#pragma once

#include <math.h>

#include "lvgl/lvgl.h"
#include "theme.h"

typedef struct {
    lv_layer_t *layer;
    lv_area_t coords;   // the object's screen area
} hmi_draw_t;

static inline hmi_draw_t hmi_draw_begin(lv_event_t *e)
{
    hmi_draw_t d;
    d.layer = lv_event_get_layer(e);
    lv_obj_get_coords(lv_event_get_target(e), &d.coords);
    return d;
}

// ctx.arc(cx, cy, r, a0, a1) + stroke of width w (butt caps).
static inline void hmi_draw_arc(const hmi_draw_t *d, double cx, double cy, double r, double w,
                                double a0deg, double a1deg, lv_color_t color, lv_opa_t opa)
{
    if (a1deg <= a0deg || r <= 0 || w <= 0) return;
    lv_draw_arc_dsc_t dsc;
    lv_draw_arc_dsc_init(&dsc);
    dsc.center.x = (int32_t)lround(d->coords.x1 + cx);
    dsc.center.y = (int32_t)lround(d->coords.y1 + cy);
    dsc.radius = (uint16_t)lround(r + w / 2);   // LVGL's radius is the outer edge
    dsc.width = (int32_t)lround(w);
    dsc.start_angle = (lv_value_precise_t)a0deg;
    dsc.end_angle = (lv_value_precise_t)a1deg;
    dsc.color = color;
    dsc.opa = opa;
    dsc.rounded = 0;
    lv_draw_arc(d->layer, &dsc);
}

// A stroked arc whose colour runs from c0 at a0 to c1 at a1 (the Canvas
// linear gradient across the dial, approximated along the arc).
static inline void hmi_draw_arc_gradient(const hmi_draw_t *d, double cx, double cy, double r, double w,
                                         double a0deg, double a1deg, lv_color_t c0, lv_color_t c1)
{
    if (a1deg <= a0deg) return;
    int n = (int)fmax(4, fmin(48, (a1deg - a0deg) / 5));
    double step = (a1deg - a0deg) / n;
    for (int i = 0; i < n; ++i) {
        lv_color_t c = lv_color_mix(c1, c0, (lv_opa_t)(255.0 * (i + 0.5) / n));
        // overlap the joints by a hair so no background shows between segments
        hmi_draw_arc(d, cx, cy, r, w, a0deg + i * step, a0deg + (i + 1) * step + 0.6, c, LV_OPA_COVER);
    }
}

// A filled disc.
static inline void hmi_draw_disc(const hmi_draw_t *d, double cx, double cy, double r, lv_color_t color, lv_opa_t opa)
{
    lv_draw_arc_dsc_t dsc;
    lv_draw_arc_dsc_init(&dsc);
    dsc.center.x = (int32_t)lround(d->coords.x1 + cx);
    dsc.center.y = (int32_t)lround(d->coords.y1 + cy);
    dsc.radius = (uint16_t)lround(r);
    dsc.width = (int32_t)lround(r) + 1;
    dsc.start_angle = 0;
    dsc.end_angle = 360;
    dsc.color = color;
    dsc.opa = opa;
    lv_draw_arc(d->layer, &dsc);
}

// moveTo/lineTo + stroke.
static inline void hmi_draw_line(const hmi_draw_t *d, double x1, double y1, double x2, double y2,
                                 double w, lv_color_t color, lv_opa_t opa)
{
    lv_draw_line_dsc_t dsc;
    lv_draw_line_dsc_init(&dsc);
    dsc.p1.x = (lv_value_precise_t)(d->coords.x1 + x1);
    dsc.p1.y = (lv_value_precise_t)(d->coords.y1 + y1);
    dsc.p2.x = (lv_value_precise_t)(d->coords.x1 + x2);
    dsc.p2.y = (lv_value_precise_t)(d->coords.y1 + y2);
    dsc.width = (int32_t)fmax(1, lround(w));
    dsc.color = color;
    dsc.opa = opa;
    dsc.round_start = 0;
    dsc.round_end = 0;
    lv_draw_line(d->layer, &dsc);
}

// fillRect.
static inline void hmi_draw_fill(const hmi_draw_t *d, double x, double y, double w, double h,
                                 lv_color_t color, lv_opa_t opa, int radius)
{
    if (w <= 0 || h <= 0) return;
    lv_draw_rect_dsc_t dsc;
    lv_draw_rect_dsc_init(&dsc);
    dsc.bg_color = color;
    dsc.bg_opa = opa;
    dsc.radius = radius;
    dsc.border_width = 0;
    lv_area_t a = {(int32_t)lround(d->coords.x1 + x), (int32_t)lround(d->coords.y1 + y),
                   (int32_t)lround(d->coords.x1 + x + w) - 1, (int32_t)lround(d->coords.y1 + y + h) - 1};
    lv_draw_rect(d->layer, &dsc, &a);
}

// A label child styled the kit's way. Weight 400/500/600/700.
static inline lv_obj_t *hmi_make_label(lv_obj_t *parent, int px, int weight, lv_color_t color, const char *text)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_remove_style_all(l);
    lv_obj_set_style_text_font(l, hmi_font(px, weight), 0);
    lv_obj_set_style_text_color(l, color, 0);
    lv_label_set_long_mode(l, LV_LABEL_LONG_CLIP);
    lv_label_set_text(l, text ? text : "");
    return l;
}

// A colour "lighter by pct %" (pct > 0: each channel moves pct % of the way
// to white) or "darker by -pct %" (pct < 0: each channel loses that share).
// Theme.shade() in ui/qml/Shadcn/Theme.qml is the same formula, so the
// kit's gradients, header bands and bevels match on both sides.
static inline lv_color_t hmi_shade(lv_color_t c, double pct)
{
    double k = pct / 100.0;
    if (k > 1) k = 1;
    if (k < -1) k = -1;
    double ch[3] = {c.red, c.green, c.blue};
    for (int i = 0; i < 3; ++i) {
        double v = k >= 0 ? ch[i] + (255.0 - ch[i]) * k : ch[i] * (1.0 + k);
        ch[i] = v < 0 ? 0 : v > 255 ? 255 : v;
    }
    return lv_color_make((uint8_t)lround(ch[0]), (uint8_t)lround(ch[1]), (uint8_t)lround(ch[2]));
}

// The kit's soft outer glow (ShButton glowColor, ShAnnunciator glow): an
// LVGL shadow with no offset, blurred over HMI_GLOW_BLUR px so it fades out
// about HMI_GLOW_BLUR / 2 px beyond the edge. ShGlow.qml draws the same
// fall-off as stacked rounded rings. opa 0 removes it.
#define HMI_GLOW_BLUR 16
#define HMI_GLOW_SPREAD 2
#define HMI_GLOW_OPA 255
static inline void hmi_set_glow(lv_obj_t *o, lv_color_t colour, lv_opa_t opa)
{
    if (opa == 0) {
        lv_obj_set_style_shadow_width(o, 0, 0);
        lv_obj_set_style_shadow_opa(o, LV_OPA_TRANSP, 0);
        return;
    }
    lv_obj_set_style_shadow_width(o, HMI_GLOW_BLUR, 0);
    lv_obj_set_style_shadow_spread(o, HMI_GLOW_SPREAD, 0);
    lv_obj_set_style_shadow_offset_x(o, 0, 0);
    lv_obj_set_style_shadow_offset_y(o, 0, 0);
    lv_obj_set_style_shadow_color(o, colour, 0);
    lv_obj_set_style_shadow_opa(o, opa, 0);
}

static inline int hmi_px(double v) { return (int)lround(v); }
static inline int hmi_px_min(double v, int floor_px) { int p = hmi_px(v); return p < floor_px ? floor_px : p; }
