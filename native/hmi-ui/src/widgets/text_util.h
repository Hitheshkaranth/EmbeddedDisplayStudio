// widgets/text_util.h -- one line of kit text placed the way the QML kit
// places it: on the baseline of its nominal size in a line slot, shrinking
// to a floor before it elides. Shared by the dashboard widgets (ShKpiTile,
// ShStatusRow, the ShAlarmTable table and the ShTrendChart series view);
// their QML twins mirror the metrics (Inter hhea 1984/-494 of 2048,
// truncated like LVGL's tiny_ttf: lineH = floor(px * 2478 / 2048),
// ascent = lineH - floor(px * 494 / 2048)).
#pragma once

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "value.h"

static inline int hmi_text_line_h(int px, int weight) { return lv_font_get_line_height(hmi_font(px, weight)); }

static inline int hmi_text_ascent(int px, int weight)
{
    const lv_font_t *f = hmi_font(px, weight);
    return lv_font_get_line_height(f) - f->base_line;
}

static inline int hmi_text_w(const char *text, int px, int weight)
{
    return lv_text_get_width(text, (uint32_t)strlen(text), hmi_font(px, weight), 0);
}

// The largest size <= px (down to floor x px, at least 8) at which `text`
// fits `width` (QML: fontSizeMode HorizontalFit + minimumPixelSize).
static inline int hmi_text_fit_px(const char *text, int px, int weight, int width, double floor_k)
{
    int floor_px = (int)fmax(8, round(px * floor_k));
    if (floor_px > px) floor_px = px;
    for (int p = px; p > floor_px; --p)
        if (hmi_text_w(text, p, weight) <= width) return p;
    return floor_px;
}

// `label` shows `text` in a slot `width` wide whose nominal line (size px)
// starts at y `top`; the text shrinks to floor_k x px to fit, then elides,
// and keeps the nominal size's baseline. Returns the size used.
static inline int hmi_text_place(lv_obj_t *label, const char *text, int px, int weight, double floor_k, int x,
                                 int top, int width, lv_color_t colour, lv_opa_t opa, lv_text_align_t align)
{
    if (width < 1) width = 1;
    int p = hmi_text_fit_px(text, px, weight, width, floor_k);
    lv_obj_set_style_text_font(label, hmi_font(p, weight), 0);
    lv_obj_set_style_text_color(label, colour, 0);
    lv_obj_set_style_text_opa(label, opa, 0);
    lv_obj_set_style_text_align(label, align, 0);
    lv_label_set_long_mode(label, LV_LABEL_LONG_DOT);
    // Size first: the label elides against its width when the text is set.
    lv_obj_set_size(label, width, hmi_text_line_h(p, weight));
    lv_label_set_text(label, text);
    lv_obj_set_pos(label, x, top + hmi_text_ascent(px, weight) - hmi_text_ascent(p, weight));
    lv_obj_remove_flag(label, LV_OBJ_FLAG_HIDDEN);
    return p;
}

// A property's text: a string as is, a number as JavaScript's String()
// prints it ("3", "3.2"), anything else `def`.
static inline const char *hmi_text_of(const hmi_value_t *v, char *buf, size_t len, const char *def)
{
    if (v && v->kind == HMI_V_STR) return v->s ? v->s : "";
    if (v && v->kind == HMI_V_NUM) {
        if (v->n == floor(v->n) && fabs(v->n) < 1e15) snprintf(buf, len, "%.0f", v->n);
        else snprintf(buf, len, "%.15g", v->n);
        return buf;
    }
    return def;
}

// A colour property: "#rrggbb" / "#aarrggbb", or the theme token `token`
// when it is empty or not a colour literal.
static inline lv_color_t hmi_colour_or_token(const char *hex, const char *token, lv_opa_t *opa)
{
    if (hex && hex[0] == '#') return hmi_colour_hex(hex, opa);
    if (opa) *opa = LV_OPA_COVER;
    return hmi_colour(token);
}

// A dark or a light ink for text on `fill` (relative luminance > 0.5 -> dark).
static inline lv_color_t hmi_ink_on(lv_color_t fill)
{
    double l = (0.2126 * fill.red + 0.7152 * fill.green + 0.0722 * fill.blue) / 255.0;
    return l > 0.55 ? lv_color_hex(0x0b0f14) : lv_color_hex(0xffffff);
}
