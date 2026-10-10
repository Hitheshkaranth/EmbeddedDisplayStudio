// widgets/w_shprocessvalue.c -- kit widget ShProcessValue (Industrial, "Process value").
//
// Spec: ui/qml/Shadcn/ShProcessValue.qml -- one SCADA reading row,
//     Hot Blast Temp   [~sparkline~] [   1185 ] °C
// the label at the left (foreground 0.46 h), an optional sparkline of the
// last 32 numeric values on a dark mini-box (trend), a dark inset value box
// with the digits right-aligned in it (valueColor, semibold 0.56 h; the
// theme's warning colour beyond warnAbove / warnBelow, 0 = off), and the
// unit column at the right (muted 0.42 h; it collapses when empty).
// Geometry: unit column round(0.22 W) after a 6 px gap; value box
// max(digits + 2 x 8, round(0.26 W)) wide, inset round(0.08 H) top and
// bottom, the digits ending 8 px inside it; sparkline box round(0.18 W) with
// 6 px gaps; the label takes the rest. The columns are fixed shares of the
// width so stacked rows line their boxes up. Each text keeps the baseline of
// its nominal size in a line slot centred in the row and shrinks to fit (the
// label to 70 %, the digits and the unit to 60 %) before it elides.
//
// Children of the root, in order: label, spark box, value box, value, unit.
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

#define HISTORY 32

typedef struct {
    lv_obj_t *face, *label, *spark, *box, *value, *unit;
    hmi_value_t val;          // the value as delivered (number or string)
    double n;                 // its number, NAN when it is not one
    int decimals;
    double warnAbove, warnBelow;
    bool trend;
    char label_text[128], unit_text[48];
    char value_colour[32], box_colour[32], trend_colour[32];
    double hist[HISTORY];
    int nhist;
} state_t;

// Before live data the sparkline is a gentle rising zigzag, so a design
// shows one (the QML draws the same eight points).
static const double PLACEHOLDER[] = {0.30, 0.52, 0.40, 0.62, 0.48, 0.70, 0.58, 0.80};

// A number, or a string that is one (" 12.5"); NAN otherwise.
static double as_number(const hmi_value_t *v)
{
    if (!v) return NAN;
    if (v->kind == HMI_V_NUM) return isfinite(v->n) ? v->n : NAN;
    if (v->kind != HMI_V_STR || !v->s) return NAN;
    const char *s = v->s;
    while (*s == ' ' || *s == '\t') ++s;
    if (!*s) return NAN;
    char *end = NULL;
    double d = strtod(s, &end);
    while (end && (*end == ' ' || *end == '\t')) ++end;
    return (end && *end == '\0' && isfinite(d)) ? d : NAN;
}

// The text in the box: toFixed(decimals) for a number when decimals >= 0,
// else the value as given (a number as JavaScript's String() would print it).
static void format_value(const state_t *st, char *buf, size_t len)
{
    const hmi_value_t *v = &st->val;
    if (v->kind == HMI_V_NULL) { snprintf(buf, len, "--"); return; }
    if (st->decimals >= 0 && !isnan(st->n)) { snprintf(buf, len, "%.*f", st->decimals, st->n); return; }
    switch (v->kind) {
    case HMI_V_NUM:
        if (v->n == floor(v->n) && fabs(v->n) < 1e15) snprintf(buf, len, "%.0f", v->n);
        else snprintf(buf, len, "%.15g", v->n);
        break;
    case HMI_V_STR: snprintf(buf, len, "%s", v->s ? v->s : ""); break;
    case HMI_V_BOOL: snprintf(buf, len, "%s", v->b ? "true" : "false"); break;
    default: snprintf(buf, len, "--"); break;
    }
}

static lv_color_t colour_or(const char *hex, const char *fallback, lv_opa_t *opa)
{
    return hmi_colour_hex(hex && hex[0] == '#' ? hex : fallback, opa);
}

// Line slot metrics as the QML mirrors them (lineH, asc).
static int line_h(int px, int weight) { return lv_font_get_line_height(hmi_font(px, weight)); }
static int ascent(int px, int weight)
{
    const lv_font_t *f = hmi_font(px, weight);
    return lv_font_get_line_height(f) - f->base_line;
}

static int text_w(const char *text, int px, int weight)
{
    return lv_text_get_width(text, (uint32_t)strlen(text), hmi_font(px, weight), 0);
}

// The largest size <= px (down to `floor` x px, at least 8) at which `text`
// fits `width` (QML: fontSizeMode HorizontalFit + minimumPixelSize).
static int fit_px(const char *text, int px, int weight, int width, double floor)
{
    int floor_px = (int)fmax(8, round(px * floor));
    for (int p = px; p > floor_px; --p)
        if (text_w(text, p, weight) <= width) return p;
    return floor_px;
}

// One line of text, `width` wide, on the baseline of the nominal size in a
// slot centred in the row of height H; it shrinks to `floor` x px and then
// elides.
static void place_line(lv_obj_t *label, const char *text, int px, int weight, double floor, int x, int width,
                       double H, lv_color_t colour, lv_text_align_t align)
{
    int p = fit_px(text, px, weight, width, floor);
    int top = (int)round((H - line_h(px, weight)) / 2);
    lv_obj_set_style_text_font(label, hmi_font(p, weight), 0);
    lv_obj_set_style_text_color(label, colour, 0);
    lv_obj_set_style_text_align(label, align, 0);
    lv_label_set_long_mode(label, LV_LABEL_LONG_DOT);
    // Size first: the label elides against its width when the text is set.
    lv_obj_set_size(label, width, line_h(p, weight));
    lv_label_set_text(label, text);
    lv_obj_set_pos(label, x, top + ascent(px, weight) - ascent(p, weight));
}

static void style_box(lv_obj_t *o, const state_t *st)
{
    lv_opa_t opa = LV_OPA_COVER;
    lv_obj_set_style_bg_color(o, colour_or(st->box_colour, "#0a0d0b", &opa), 0);
    lv_obj_set_style_bg_opa(o, opa, 0);
    lv_obj_set_style_border_color(o, lv_color_hex(0x3a3f45), 0);
    lv_obj_set_style_border_width(o, 1, 0);
    lv_obj_set_style_radius(o, 3, 0);
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    int Wi = (int)round(W);
    int valuePx = (int)fmax(9, fmin(18, round(H * 0.56)));
    int labelPx = (int)fmax(8, fmin(15, round(H * 0.46)));
    int unitPx = (int)fmax(8, fmin(14, round(H * 0.42)));
    int inset = (int)fmax(1, round(H * 0.08));
    int boxH = (int)fmax(6, (int)round(H) - 2 * inset);
    bool hasUnit = st->unit_text[0] != '\0';
    int unitW = hasUnit ? (int)round(W * 0.22) : 0;
    int unitGap = hasUnit ? 6 : 0;

    char text[96];
    format_value(st, text, sizeof text);
    int digitsW = text_w(text, valuePx, 600);
    int boxW = (int)fmin(fmax(digitsW + 16, round(W * 0.26)), fmax(16, Wi - unitW - unitGap));
    int boxX = Wi - unitW - unitGap - boxW;
    int sparkW = st->trend ? (int)round(W * 0.18) : 0;
    int sparkX = boxX - 6 - sparkW;
    int labelW = (int)fmax(0, (st->trend ? sparkX : boxX) - 6);

    lv_obj_set_size(st->face, (int32_t)W, (int32_t)H);

    // label
    if (labelW > 0) {
        place_line(st->label, st->label_text, labelPx, 400, 0.7, 0, labelW, H, hmi_colour("foreground"),
                   LV_TEXT_ALIGN_LEFT);
        lv_obj_remove_flag(st->label, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(st->label, LV_OBJ_FLAG_HIDDEN);
    }

    // sparkline box
    if (st->trend) {
        style_box(st->spark, st);
        lv_obj_set_pos(st->spark, sparkX, inset);
        lv_obj_set_size(st->spark, sparkW, boxH);
        lv_obj_remove_flag(st->spark, LV_OBJ_FLAG_HIDDEN);
        lv_obj_invalidate(st->spark);
    } else {
        lv_obj_add_flag(st->spark, LV_OBJ_FLAG_HIDDEN);
    }

    // value box and digits
    style_box(st->box, st);
    lv_obj_set_pos(st->box, boxX, inset);
    lv_obj_set_size(st->box, boxW, boxH);
    bool warns = !isnan(st->n) && ((st->warnAbove != 0 && st->n > st->warnAbove)
                                   || (st->warnBelow != 0 && st->n < st->warnBelow));
    lv_color_t vc = warns ? hmi_colour("warning") : colour_or(st->value_colour, "#3ee05a", NULL);
    // The digits end 8 px inside the box; their slot starts 4 px in, so a
    // value the box was sized for never meets the slot's edge and elides.
    place_line(st->value, text, valuePx, 600, 0.6, boxX + 4, (int)fmax(1, boxW - 12), H, vc,
               LV_TEXT_ALIGN_RIGHT);

    // unit column
    if (hasUnit) {
        place_line(st->unit, st->unit_text, unitPx, 400, 0.6, boxX + boxW + unitGap, (int)fmax(1, unitW), H,
                   hmi_colour("mutedForeground"), LV_TEXT_ALIGN_LEFT);
        lv_obj_remove_flag(st->unit, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(st->unit, LV_OBJ_FLAG_HIDDEN);
    }
}

// The sparkline over its mini-box: the history normalised to the plot (one
// point is a flat line), or the placeholder zigzag before any live data.
static void draw_spark_cb(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    state_t *st = w->state;
    if (!st || !st->trend) return;
    hmi_draw_t d = hmi_draw_begin(e);
    double bw = lv_area_get_width(&d.coords), bh = lv_area_get_height(&d.coords);
    double ys[HISTORY + 1];
    int n = 0;
    if (st->nhist == 0) {
        n = (int)(sizeof PLACEHOLDER / sizeof PLACEHOLDER[0]);
        memcpy(ys, PLACEHOLDER, sizeof PLACEHOLDER);
    } else {
        double lo = st->hist[0], hi = st->hist[0];
        for (int i = 1; i < st->nhist; ++i) { lo = fmin(lo, st->hist[i]); hi = fmax(hi, st->hist[i]); }
        for (int i = 0; i < st->nhist; ++i) ys[n++] = hi - lo > 1e-9 ? (st->hist[i] - lo) / (hi - lo) : 0.5;
        if (n == 1) ys[n++] = ys[0];
    }
    double padX = 4, padY = fmax(3, round(bh * 0.16));
    double pw = bw - 2 * padX, ph = bh - 2 * padY;
    if (pw <= 0 || ph <= 0) return;
    lv_opa_t opa = LV_OPA_COVER;
    lv_color_t c = colour_or(st->trend_colour, "#f5a524", &opa);
    lv_draw_line_dsc_t dsc;
    lv_draw_line_dsc_init(&dsc);
    dsc.width = 2;
    dsc.color = c;
    dsc.opa = opa;
    dsc.round_start = 1;
    dsc.round_end = 1;
    for (int i = 1; i < n; ++i) {
        dsc.p1.x = (lv_value_precise_t)(d.coords.x1 + padX + pw * (i - 1) / (n - 1));
        dsc.p1.y = (lv_value_precise_t)(d.coords.y1 + padY + ph * (1 - ys[i - 1]));
        dsc.p2.x = (lv_value_precise_t)(d.coords.x1 + padX + pw * i / (n - 1));
        dsc.p2.y = (lv_value_precise_t)(d.coords.y1 + padY + ph * (1 - ys[i]));
        lv_draw_line(d.layer, &dsc);
    }
}

static void set_value(state_t *st, const hmi_value_t *v)
{
    hmi_value_free(&st->val);
    st->val = v ? hmi_value_copy(v) : hmi_value_num(0);
    st->n = as_number(&st->val);
}

static void copy_str(char *dst, size_t n, const hmi_value_t *v, const char *def)
{
    if (v && v->kind == HMI_V_NUM) snprintf(dst, n, "%s", hmi_value_debug(v));
    else snprintf(dst, n, "%s", hmi_value_as_str(v, def));
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
    st->val = hmi_value_null();
    st->label = hmi_make_label(face, 14, 400, hmi_colour("foreground"), "");
    st->spark = lv_obj_create(face);
    lv_obj_remove_style_all(st->spark);
    lv_obj_remove_flag(st->spark, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(st->spark, draw_spark_cb, LV_EVENT_DRAW_MAIN_END, w);
    st->box = lv_obj_create(face);
    lv_obj_remove_style_all(st->box);
    lv_obj_remove_flag(st->box, LV_OBJ_FLAG_SCROLLABLE);
    st->value = hmi_make_label(face, 17, 600, lv_color_hex(0x3ee05a), "");
    st->unit = hmi_make_label(face, 13, 400, hmi_colour("mutedForeground"), "");

    // The value the page was built with is not history; later updates are.
    set_value(st, hmi_widget_get(w, "value"));
    st->decimals = (int)hmi_widget_num(w, "decimals", -1);
    st->warnAbove = hmi_widget_num(w, "warnAbove", 0);
    st->warnBelow = hmi_widget_num(w, "warnBelow", 0);
    st->trend = hmi_widget_bool(w, "trend", false);
    snprintf(st->label_text, sizeof st->label_text, "%s", hmi_widget_str(w, "label", "Value"));
    snprintf(st->unit_text, sizeof st->unit_text, "%s", hmi_widget_str(w, "unit", ""));
    snprintf(st->value_colour, sizeof st->value_colour, "%s", hmi_widget_str(w, "valueColor", "#3ee05a"));
    snprintf(st->box_colour, sizeof st->box_colour, "%s", hmi_widget_str(w, "boxColor", "#0a0d0b"));
    snprintf(st->trend_colour, sizeof st->trend_colour, "%s", hmi_widget_str(w, "trendColor", "#f5a524"));
    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "value") == 0) {
        // The runtime re-pushes the model's own value right after create();
        // that is the design value, not history (the QML's onValueChanged
        // does not fire for it either).
        bool design = value == hmi_widget_get(w, "value");
        set_value(st, value);
        if (!design && !isnan(st->n)) {
            if (st->nhist == HISTORY) {
                memmove(st->hist, st->hist + 1, (HISTORY - 1) * sizeof st->hist[0]);
                --st->nhist;
            }
            st->hist[st->nhist++] = st->n;
        }
    } else if (strcmp(prop, "decimals") == 0) st->decimals = (int)hmi_value_as_num(value, st->decimals);
    else if (strcmp(prop, "warnAbove") == 0) st->warnAbove = hmi_value_as_num(value, st->warnAbove);
    else if (strcmp(prop, "warnBelow") == 0) st->warnBelow = hmi_value_as_num(value, st->warnBelow);
    else if (strcmp(prop, "trend") == 0) st->trend = hmi_value_as_bool(value, st->trend);
    else if (strcmp(prop, "label") == 0) copy_str(st->label_text, sizeof st->label_text, value, "");
    else if (strcmp(prop, "unit") == 0) copy_str(st->unit_text, sizeof st->unit_text, value, "");
    else if (strcmp(prop, "valueColor") == 0)
        snprintf(st->value_colour, sizeof st->value_colour, "%s", hmi_value_as_str(value, ""));
    else if (strcmp(prop, "boxColor") == 0)
        snprintf(st->box_colour, sizeof st->box_colour, "%s", hmi_value_as_str(value, ""));
    else if (strcmp(prop, "trendColor") == 0)
        snprintf(st->trend_colour, sizeof st->trend_colour, "%s", hmi_value_as_str(value, ""));
    else
        return;
    layout(w);
}

static void destroy(hmi_widget_t *w)
{
    state_t *st = w->state;
    if (!st) return;
    hmi_value_free(&st->val);
    lv_free(st);
    w->state = NULL;
}

const hmi_widget_ops_t hmi_widget_shprocessvalue = {"ShProcessValue", create, set_prop, destroy};
