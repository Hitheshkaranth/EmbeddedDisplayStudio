// widgets/w_shtrendchart.c -- kit widget ShTrendChart (Industrial, "Trend Chart").
//
// Spec: ui/qml/Shadcn/ShTrendChart.qml (wrapper with grid, zones, labels) and
// faces/canvas/TrendChartFace.qml (gradient fill, trace, value dot).
//
// `series` (default "": the single brand trace above, unchanged) switches to
// a multi-series dashboard trend: "Label|#color|level;Label|#color|level;..."
// -- a framed plot with "nice" y ticks and their labels at the left (the unit
// above them), optional `xLabels` ("12:30,13:00,...") under the x axis with
// faint vertical grid lines, and a legend at the right listing each label
// with its colour. Until live data arrives each series draws a deterministic
// gently-noisy line about its level across the plot (trend_noise(), the
// same formula as the QML's _noise()), so a design shows its picture's
// trend; the `data` binding still feeds the first series. The warning band
// is not drawn in this mode. Everything is painted by one draw callback on
// `sface`, a full-size child created hidden after the classic children.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#include "draw_util.h"
#include "registry.h"
#include "text_util.h"

#define MAX_POINTS 200
#define MAX_SERIES 8
#define MAX_XLABELS 12

typedef struct {
    char label[48];
    lv_color_t colour;
    double level;
} series_t;

typedef struct {
    double minValue, maxValue, warningLow, warningHigh, lineWidth;
    int maxPoints;
    char label[64], unit[16];
    lv_color_t lineColor, fillColor;
    lv_obj_t *bg, *face, *gridLines[5], *yLabels[5];
    lv_obj_t *labelLabel, *unitLabel, *warnZone;
    double data[MAX_POINTS];
    int nData;
    // series mode
    lv_obj_t *chartBg, *sface;
    series_t series[MAX_SERIES];
    int nSeries;
    char xLabels[MAX_XLABELS][24];
    int nXLabels;
} state_t;

// The colours a series without one takes, in order.
static const uint32_t SERIES_PALETTE[] = {0xff3b3b, 0xff9f1c, 0xffd23f, 0x3ee05a, 0x22b8ff, 0xa78bfa, 0xf472b6,
                                          0x94a3b8};

static void copy_trim(char *dst, size_t n, const char *src, size_t len)
{
    while (len && (*src == ' ' || *src == '\t')) { ++src; --len; }
    while (len && (src[len - 1] == ' ' || src[len - 1] == '\t')) --len;
    if (len >= n) len = n - 1;
    memcpy(dst, src, len);
    dst[len] = '\0';
}

// "Label|#color|level;..." -> st->series. A missing colour takes the palette's,
// a missing or non-numeric level the middle of the scale.
static void parse_series(state_t *st, const char *spec)
{
    st->nSeries = 0;
    const char *p = spec ? spec : "";
    while (*p && st->nSeries < MAX_SERIES) {
        const char *end = strchr(p, ';');
        size_t len = end ? (size_t)(end - p) : strlen(p);
        char item[160];
        copy_trim(item, sizeof item, p, len);
        if (item[0]) {
            series_t *se = &st->series[st->nSeries];
            char *f1 = strchr(item, '|');
            char *f2 = f1 ? strchr(f1 + 1, '|') : NULL;
            if (f1) *f1 = '\0';
            if (f2) *f2 = '\0';
            copy_trim(se->label, sizeof se->label, item, strlen(item));
            char col[32] = "";
            if (f1) copy_trim(col, sizeof col, f1 + 1, strlen(f1 + 1));
            se->colour = col[0] == '#' ? hmi_colour_hex(col, NULL)
                                       : lv_color_hex(SERIES_PALETTE[st->nSeries % 8]);
            se->level = NAN;
            if (f2) {
                char *e = NULL;
                double v = strtod(f2 + 1, &e);
                if (e != f2 + 1 && isfinite(v)) se->level = v;
            }
            st->nSeries++;
        }
        if (!end) break;
        p = end + 1;
    }
}

static void parse_xlabels(state_t *st, const char *spec)
{
    st->nXLabels = 0;
    const char *p = spec ? spec : "";
    if (!*p) return;
    while (st->nXLabels < MAX_XLABELS) {
        const char *end = strchr(p, ',');
        size_t len = end ? (size_t)(end - p) : strlen(p);
        copy_trim(st->xLabels[st->nXLabels], sizeof st->xLabels[0], p, len);
        st->nXLabels++;
        if (!end) break;
        p = end + 1;
    }
}

// A deterministic value in -1..1 for point i of series s: a hash of the two
// (uint32 arithmetic; the QML does the same with Math.imul) blended with a
// slow sine, so each series wanders gently about its level.
static double trend_noise(int s, int i, int n)
{
    uint32_t h = (uint32_t)i * 374761393u + (uint32_t)(s + 1) * 668265263u;
    h = (h ^ (h >> 13)) * 1274126177u;
    h ^= h >> 16;
    double r = h / 4294967295.0 * 2.0 - 1.0;
    double t = n > 1 ? (double)i / (n - 1) : 0;
    return 0.62 * r + 0.38 * sin(2 * M_PI * (1.3 + 0.37 * s) * t + 1.7 * s);
}

// A "nice" tick step (1, 2, 2.5, 5 x 10^k) giving at most max_ticks intervals.
static double nice_step(double range, int max_ticks)
{
    if (range <= 0 || max_ticks < 1) return 1;
    double raw = range / max_ticks;
    double mag = pow(10, floor(log10(raw)));
    const double steps[] = {1, 2, 2.5, 5, 10};
    for (int i = 0; i < 5; ++i)
        if (steps[i] * mag >= raw - 1e-9 * mag) return steps[i] * mag;
    return 10 * mag;
}

// A tick's text, thousands grouped with a comma as dashboards print them
// ("1,400"); decimals as the step needs.
static void format_tick(char *buf, size_t n, double v, double step)
{
    if (fabs(v) < step * 1e-6) v = 0;
    int dec = step >= 1 ? 0 : (int)ceil(-log10(step) - 1e-9);
    if (dec > 4) dec = 4;
    char raw[48];
    snprintf(raw, sizeof raw, "%.*f", dec, v);
    char *dot = strchr(raw, '.');
    size_t intLen = dot ? (size_t)(dot - raw) : strlen(raw);
    size_t start = raw[0] == '-' ? 1 : 0;
    size_t o = 0;
    for (size_t i = 0; i < intLen && o + 2 < n; ++i) {
        buf[o++] = raw[i];
        size_t left = intLen - 1 - i;
        if (i >= start && left > 0 && left % 3 == 0) buf[o++] = ',';
    }
    if (dot) for (const char *q = dot; *q && o + 1 < n; ++q) buf[o++] = *q;
    buf[o] = '\0';
}

static void draw_text(const hmi_draw_t *d, const char *text, int px, int weight, lv_color_t colour, lv_opa_t opa,
                      int x, int y, int w, lv_text_align_t align)
{
    lv_draw_label_dsc_t dsc;
    lv_draw_label_dsc_init(&dsc);
    dsc.font = hmi_font(px, weight);
    dsc.color = colour;
    dsc.opa = opa;
    dsc.text = text;
    dsc.text_local = 1;
    dsc.align = align;
    lv_area_t a = {d->coords.x1 + x, d->coords.y1 + y, d->coords.x1 + x + w - 1,
                   d->coords.y1 + y + hmi_text_line_h(px, weight) - 1};
    lv_draw_label(d->layer, &dsc, &a);
}

// The series view (see the header). Every measure is a share of the size.
static void draw_series_cb(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    state_t *st = w->state;
    if (!st || st->nSeries == 0) return;
    hmi_draw_t d = hmi_draw_begin(e);
    double W = fmax(1, w->width), H = fmax(1, w->height);
    int tickPx = (int)fmax(8, fmin(12, lround(H * 0.055)));
    int legendPx = (int)fmax(8, fmin(13, lround(H * 0.065)));
    int tickLH = hmi_text_line_h(tickPx, 400);
    lv_color_t muted = hmi_colour("mutedForeground"), grid = hmi_colour("border");

    int top = 0;
    if (st->label[0]) {
        int lpx = hmi_font_size("fontSizeXs");
        draw_text(&d, st->label, lpx, 500, muted, LV_OPA_COVER, 0, 0, (int)W, LV_TEXT_ALIGN_LEFT);
        top += hmi_text_line_h(lpx, 500) + 4;
    }
    if (st->unit[0]) {
        draw_text(&d, st->unit, tickPx, 400, muted, LV_OPA_COVER, 0, top, (int)W / 3, LV_TEXT_ALIGN_LEFT);
        top += tickLH + 2;
    }
    top += tickLH / 2;   // room for the top tick's label
    int bottom = (int)H - (st->nXLabels > 0 ? tickLH + 4 : tickLH / 2) - 1;

    // legend
    int swatch = (int)fmax(8, lround(legendPx * 1.25));
    int legendW = 0;
    for (int s = 0; s < st->nSeries; ++s) {
        int tw = hmi_text_w(st->series[s].label, legendPx, 400);
        if (tw > legendW) legendW = tw;
    }
    legendW += swatch + 8 + 10;
    if (legendW > W * 0.45) legendW = 0;

    double lo = st->minValue, hi = st->maxValue > st->minValue ? st->maxValue : st->minValue + 1;
    int plotH0 = bottom - top;
    int maxTicks = (int)fmax(2, fmin(10, plotH0 / (tickLH * 1.6)));
    double step = nice_step(hi - lo, maxTicks);
    double first = ceil(lo / step - 1e-9) * step;
    int yLW = 0;
    char buf[48];
    for (double v = first; v <= hi + step * 1e-6; v += step) {
        format_tick(buf, sizeof buf, v, step);
        int tw = hmi_text_w(buf, tickPx, 400);
        if (tw > yLW) yLW = tw;
    }
    int x0 = yLW + 6;
    int x1 = (int)W - legendW - 6;
    if (st->nXLabels > 0 && legendW == 0) {
        int half = hmi_text_w(st->xLabels[st->nXLabels - 1], tickPx, 400) / 2 + 1;
        if ((int)W - half < x1) x1 = (int)W - half;
    }
    if (x1 - x0 < 10 || bottom - top < 10) return;
    double pw = x1 - x0, ph = bottom - top;

    // plot frame and grid
    hmi_draw_fill(&d, x0, top, pw, ph, hmi_colour("background"), LV_OPA_COVER, 0);
    for (double v = first; v <= hi + step * 1e-6; v += step) {
        double y = bottom - (v - lo) / (hi - lo) * ph;
        int yi = (int)lround(y);
        if (yi > top && yi < bottom) hmi_draw_fill(&d, x0, yi, pw, 1, grid, (lv_opa_t)150, 0);
        format_tick(buf, sizeof buf, v, step);
        draw_text(&d, buf, tickPx, 400, muted, LV_OPA_COVER, 0, yi - tickLH / 2, yLW, LV_TEXT_ALIGN_RIGHT);
    }
    for (int i = 0; i < st->nXLabels; ++i) {
        double x = st->nXLabels > 1 ? x0 + pw * i / (st->nXLabels - 1) : x0;
        int xi = (int)lround(x);
        if (xi > x0 && xi < x1) hmi_draw_fill(&d, xi, top, 1, ph, grid, (lv_opa_t)90, 0);
        int tw = hmi_text_w(st->xLabels[i], tickPx, 400);
        int tx = xi - tw / 2;
        if (tx < 0) tx = 0;
        if (tx + tw > (int)W) tx = (int)W - tw;
        draw_text(&d, st->xLabels[i], tickPx, 400, muted, LV_OPA_COVER, tx, bottom + 4, tw + 2, LV_TEXT_ALIGN_LEFT);
    }
    lv_color_t axis = hmi_shade(grid, 45);
    hmi_draw_fill(&d, x0, top, 1, ph + 1, axis, LV_OPA_COVER, 0);
    hmi_draw_fill(&d, x0, bottom, pw, 1, axis, LV_OPA_COVER, 0);

    // the lines
    double lw = st->lineWidth > 0 ? st->lineWidth : 2;
    int n = (int)fmax(8, fmin(160, lround(pw / 5)));
    for (int s = 0; s < st->nSeries; ++s) {
        const series_t *se = &st->series[s];
        bool live = s == 0 && st->nData >= 2;
        int count = live ? (st->nData > st->maxPoints ? st->maxPoints : st->nData) : n;
        double level = isnan(se->level) ? (lo + hi) / 2 : se->level;
        double px = 0, py = 0;
        for (int i = 0; i < count; ++i) {
            double v, x;
            if (live) {
                int span = st->maxPoints - 1 > 0 ? st->maxPoints - 1 : 1;
                v = st->data[st->nData - count + i];
                x = x0 + pw * i / span;
            } else {
                v = level + (hi - lo) * 0.016 * trend_noise(s, i, n);
                x = x0 + pw * i / (n - 1);
            }
            double y = bottom - (v - lo) / (hi - lo) * ph;
            if (y < top) y = top;
            if (y > bottom) y = bottom;
            if (i > 0) hmi_draw_line(&d, px, py, x, y, lw, se->colour, LV_OPA_COVER);
            px = x;
            py = y;
        }
    }

    // legend entries
    if (legendW > 0) {
        int lx = x1 + 10;
        int lh = hmi_text_line_h(legendPx, 400);
        int rowH = (int)fmin(lround(lh * 2.1), ph / fmax(1, st->nSeries));
        for (int s = 0; s < st->nSeries; ++s) {
            int cy = top + rowH * s + rowH / 2;
            hmi_draw_fill(&d, lx, cy - 2, swatch, 4, st->series[s].colour, LV_OPA_COVER, 1);
            draw_text(&d, st->series[s].label, legendPx, 400, hmi_colour("foreground"), LV_OPA_COVER,
                      lx + swatch + 8, cy - lh / 2, legendW - swatch - 8, LV_TEXT_ALIGN_LEFT);
        }
    }
}

// Shows the series view or the classic one.
static void apply_mode(hmi_widget_t *w)
{
    state_t *st = w->state;
    bool series = st->nSeries > 0;
    lv_obj_t *classic[] = {st->chartBg, st->face, st->warnZone, st->unitLabel, st->labelLabel};
    if (series) {
        for (size_t i = 0; i < sizeof classic / sizeof classic[0]; ++i) lv_obj_add_flag(classic[i], LV_OBJ_FLAG_HIDDEN);
        for (int i = 0; i < 5; i++) {
            if (st->gridLines[i]) lv_obj_add_flag(st->gridLines[i], LV_OBJ_FLAG_HIDDEN);
            if (st->yLabels[i]) lv_obj_add_flag(st->yLabels[i], LV_OBJ_FLAG_HIDDEN);
        }
        lv_obj_set_size(st->sface, (int32_t)w->width, (int32_t)w->height);
        lv_obj_remove_flag(st->sface, LV_OBJ_FLAG_HIDDEN);
        lv_obj_invalidate(st->sface);
    } else {
        lv_obj_add_flag(st->sface, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(st->chartBg, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(st->face, LV_OBJ_FLAG_HIDDEN);
        for (int i = 0; i < 5; i++) {
            if (st->gridLines[i]) lv_obj_remove_flag(st->gridLines[i], LV_OBJ_FLAG_HIDDEN);
            if (st->yLabels[i]) lv_obj_remove_flag(st->yLabels[i], LV_OBJ_FLAG_HIDDEN);
        }
    }
}

static void draw_trace_cb(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    state_t *st = w->state;
    hmi_draw_t d = hmi_draw_begin(e);
    double W = w->width, H = w->height;

    if (st->nData < 2) return;

    int n = st->nData > st->maxPoints ? st->maxPoints : st->nData;
    double stepX = W / (st->maxPoints - 1 > 0 ? st->maxPoints - 1 : 1);
    double yScale = 1.0 / (st->maxValue - st->minValue > 0 ? st->maxValue - st->minValue : 1);

    // Fill under the trace: a vertical gradient over the whole plot, fillColor
    // at 20% opacity at the top to 2% at the bottom (the canvas face's
    // createLinearGradient). Drawn as COL-wide columns from the trace down to
    // the baseline; each column's gradient starts at the plot gradient's
    // opacity for its own top, so the columns read as one fill. O(W) draws.
    const double COL = 2.0;
    double xEnd = (n - 1) * stepX;
    lv_draw_rect_dsc_t fill;
    lv_draw_rect_dsc_init(&fill);
    fill.bg_opa = LV_OPA_COVER;
    fill.border_width = 0;
    fill.bg_grad.dir = LV_GRAD_DIR_VER;
    fill.bg_grad.stops_count = 2;
    fill.bg_grad.stops[0].color = st->fillColor;
    fill.bg_grad.stops[0].frac = 0;
    fill.bg_grad.stops[1].color = st->fillColor;
    fill.bg_grad.stops[1].opa = (lv_opa_t)lround(255 * 0.02);
    fill.bg_grad.stops[1].frac = 255;
    for (double cx = 0; cx < xEnd; cx += COL) {
        double mid = fmin(cx + COL * 0.5, xEnd);
        int i = (int)(mid / stepX);
        if (i > n - 2) i = n - 2;
        double t = (mid - i * stepX) / stepX;
        double v = st->data[i] + t * (st->data[i + 1] - st->data[i]);
        double top = H - (v - st->minValue) * yScale * H;
        if (top < 0) top = 0;
        if (top >= H) continue;
        fill.bg_grad.stops[0].opa = (lv_opa_t)lround(255 * (0.20 - 0.18 * top / H));
        lv_area_t a = {(int32_t)lround(d.coords.x1 + cx), (int32_t)lround(d.coords.y1 + top),
                       (int32_t)lround(d.coords.x1 + fmin(cx + COL, xEnd)) - 1,
                       (int32_t)lround(d.coords.y1 + H) - 1};
        if (a.x2 < a.x1 || a.y2 < a.y1) continue;
        lv_draw_rect(d.layer, &fill, &a);
    }

    // Line trace
    for (int i = 0; i < n; i++) {
        double x = i * stepX;
        double y = H - (st->data[i] - st->minValue) * yScale * H;
        if (i > 0) {
            double px = (i - 1) * stepX;
            double py = H - (st->data[i - 1] - st->minValue) * yScale * H;
            hmi_draw_line(&d, px, py, x, y, st->lineWidth, st->lineColor, LV_OPA_COVER);
        }
    }

    // Current value dot
    int lastI = n - 1;
    double lx = lastI * stepX;
    double ly = H - (st->data[lastI] - st->minValue) * yScale * H;
    hmi_draw_disc(&d, lx, ly, 4, st->fillColor, LV_OPA_COVER);
    hmi_draw_disc(&d, lx, ly, 3, hmi_colour("background"), LV_OPA_COVER);
}

static void update_grid(hmi_widget_t *w)
{
    state_t *st = w->state;
    if (st->nSeries > 0) {
        apply_mode(w);
        return;
    }
    lv_obj_t *bg = st->bg;
    double W = w->width, H = w->height;
    (void)bg;

    // Chart area height = H - (label ? 18 : 0)
    double chartH = H - (st->label[0] ? 18 : 0);

    // Grid lines (5 horizontal lines at y = 0, 1/4, 2/4, 3/4, 1 of chartH)
    for (int i = 0; i < 5; i++) {
        lv_obj_t *g = st->gridLines[i];
        if (!g) {
            g = lv_obj_create(bg);
            lv_obj_remove_style_all(g);
            lv_obj_set_size(g, (int32_t)W, 1);
            lv_obj_set_style_bg_color(g, hmi_colour("border"), 0);
            lv_obj_set_style_bg_opa(g, (lv_opa_t)(0.5 * 255), 0);
            st->gridLines[i] = g;
        }
        lv_obj_set_pos(g, 0, (int32_t)((i / 4.0) * chartH));
        lv_obj_set_width(g, (int32_t)W);
    }

    // Warning zone: rectangle at the height of the warning region
    double yScale = 1.0 / (st->maxValue - st->minValue > 0 ? st->maxValue - st->minValue : 1);
    // The band spans warningLow..warningHigh, clipped to the scale: its
    // height is that span's share of the chart (it was 1 - share, which
    // drew most of the chart amber and ran past its bottom edge).
    double bandHigh = st->warningHigh < st->maxValue ? st->warningHigh : st->maxValue;
    double bandLow = st->warningLow > st->minValue ? st->warningLow : st->minValue;
    double zoneTop = chartH * (st->maxValue - bandHigh) * yScale;
    double zoneH = chartH * (bandHigh - bandLow) * yScale;
    if (zoneH > 0 && zoneTop >= 0 && zoneTop < chartH) {
        lv_obj_set_pos(st->warnZone, 0, (int32_t)zoneTop);
        lv_obj_set_size(st->warnZone, (int32_t)W, (int32_t)zoneH);
        lv_obj_remove_flag(st->warnZone, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(st->warnZone, LV_OBJ_FLAG_HIDDEN);
    }

    // Y-axis labels at left edge
    const double values[] = {1.0, 0.75, 0.5, 0.25, 0.0};
    for (int i = 0; i < 5; i++) {
        lv_obj_t *lbl = st->yLabels[i];
        if (!lbl) {
            lbl = hmi_make_label(bg, 9, 400, hmi_colour("mutedForeground"), "");
            lv_obj_set_width(lbl, 30);
            lv_obj_set_style_text_align(lbl, LV_TEXT_ALIGN_RIGHT, 0);
            st->yLabels[i] = lbl;
        }
        // Top grid line is the maximum, bottom the minimum.
        double val = st->minValue + values[i] * (st->maxValue - st->minValue);
        char buf[24];
        snprintf(buf, sizeof buf, "%.0f", val);
        lv_label_set_text(lbl, buf);
        lv_obj_set_pos(lbl, 2, (int32_t)((i / 4.0) * chartH * 2 - chartH / 2 + chartH * 0.75 - (i == 0 ? 0 : i == 4 ? 0 : 0)));
        // Actually: position at (parent.height / 4) * (3 - index * 2)
        // i=0: 3/4 * chartH, i=1: 1/4 * chartH, i=2: -1/4 (invalid), ...
        // Let me recalculate: the QML says (parent.height / 4) * (3 - index * 2)
        // i=0: 3/4*H, i=1: 1/4*H, i=2: -1/4*H (use 0?), i=3: -3/4*H (use 0?), i=4: -5/4*H
        // That doesn't look right. Let me just position them at the grid line positions.
        lv_obj_set_pos(lbl, 2, (int32_t)((i / 4.0) * chartH) - 6);
    }

    // Unit label at bottom right of chart area
    lv_label_set_text(st->unitLabel, st->unit);
    if (st->unit[0])
        lv_obj_remove_flag(st->unitLabel, LV_OBJ_FLAG_HIDDEN);
    else
        lv_obj_add_flag(st->unitLabel, LV_OBJ_FLAG_HIDDEN);

    // Label at top
    lv_label_set_text(st->labelLabel, st->label);
    if (st->label[0])
        lv_obj_remove_flag(st->labelLabel, LV_OBJ_FLAG_HIDDEN);
    else
        lv_obj_add_flag(st->labelLabel, LV_OBJ_FLAG_HIDDEN);
}

static void read_model(hmi_widget_t *w)
{
    state_t *st = w->state;
    st->minValue = hmi_widget_num(w, "minValue", 0);
    st->maxValue = hmi_widget_num(w, "maxValue", 100);
    st->warningLow = hmi_widget_num(w, "warningLow", 20);
    st->warningHigh = hmi_widget_num(w, "warningHigh", 80);
    st->maxPoints = (int)hmi_widget_num(w, "maxPoints", 100);
    st->lineWidth = hmi_widget_num(w, "lineWidth", 2);
    snprintf(st->label, sizeof st->label, "%s", hmi_widget_str(w, "label", ""));
    snprintf(st->unit, sizeof st->unit, "%s", hmi_widget_str(w, "unit", ""));
    // lineColor and fillColor come from binding, default to Theme.brand
    st->lineColor = hmi_colour("brand");
    st->fillColor = hmi_colour("brand");
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *bg = lv_obj_create(parent);
    lv_obj_remove_style_all(bg);
    lv_obj_set_size(bg, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(bg, LV_OBJ_FLAG_SCROLLABLE);

    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;
    st->bg = bg;
    st->nData = 0;

    // Label at top (hidden if empty)
    st->labelLabel = hmi_make_label(bg, hmi_font_size("fontSizeXs"), 500, hmi_colour("mutedForeground"), "");
    lv_obj_set_style_text_font(st->labelLabel, hmi_font(hmi_font_size("fontSizeXs"), 500), 0);
    lv_obj_align(st->labelLabel, LV_ALIGN_TOP_MID, 0, 2);
    lv_obj_add_flag(st->labelLabel, LV_OBJ_FLAG_HIDDEN);

    // Chart area background
    lv_obj_t *chartBg = lv_obj_create(bg);
    st->chartBg = chartBg;
    lv_obj_remove_style_all(chartBg);
    lv_obj_set_size(chartBg, (int32_t)w->width, (int32_t)(w->height - 18));
    lv_obj_set_pos(chartBg, 0, st->label[0] ? 18 : 0);
    lv_obj_set_style_bg_color(chartBg, hmi_colour("background"), 0);
    lv_obj_set_style_bg_opa(chartBg, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(chartBg, hmi_colour("border"), 0);
    lv_obj_set_style_border_width(chartBg, 1, 0);
    lv_obj_set_style_radius(chartBg, hmi_radius("radiusSm"), 0);

    // Warning zone
    st->warnZone = lv_obj_create(bg);
    lv_obj_remove_style_all(st->warnZone);
    lv_obj_set_style_bg_color(st->warnZone, hmi_colour("warning"), 0);
    lv_obj_set_style_bg_opa(st->warnZone, (lv_opa_t)(0.08 * 255), 0);
    lv_obj_set_style_radius(st->warnZone, 0, 0);
    lv_obj_add_flag(st->warnZone, LV_OBJ_FLAG_HIDDEN);

    // Grid lines
    for (int i = 0; i < 5; i++)
        st->gridLines[i] = NULL;

    // Y-axis labels
    for (int i = 0; i < 5; i++)
        st->yLabels[i] = NULL;

    // Unit label at bottom right of chart
    st->unitLabel = hmi_make_label(bg, 9, 400, hmi_colour("mutedForeground"), "");
    lv_obj_align(st->unitLabel, LV_ALIGN_BOTTOM_RIGHT, -4, -4);
    lv_obj_add_flag(st->unitLabel, LV_OBJ_FLAG_HIDDEN);

    // Trace canvas
    lv_obj_t *face = lv_obj_create(bg);
    lv_obj_remove_style_all(face);
    lv_obj_set_size(face, (int32_t)w->width, (int32_t)(w->height - (st->label[0] ? 18 : 0)));
    lv_obj_set_pos(face, 2, st->label[0] ? 20 : 2);
    lv_obj_remove_flag(face, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_opa(face, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(face, 0, 0);
    lv_obj_add_event_cb(face, draw_trace_cb, LV_EVENT_DRAW_MAIN, w);
    st->face = face;

    // Series view: created hidden, drawn only when `series` is set.
    st->sface = lv_obj_create(bg);
    lv_obj_remove_style_all(st->sface);
    lv_obj_remove_flag(st->sface, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(st->sface, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(st->sface, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_event_cb(st->sface, draw_series_cb, LV_EVENT_DRAW_MAIN, w);

    read_model(w);
    parse_series(st, hmi_widget_str(w, "series", ""));
    parse_xlabels(st, hmi_widget_str(w, "xLabels", ""));
    update_grid(w);
    return bg;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "minValue") == 0) st->minValue = hmi_value_as_num(value, st->minValue);
    else if (strcmp(prop, "maxValue") == 0) st->maxValue = hmi_value_as_num(value, st->maxValue);
    else if (strcmp(prop, "warningLow") == 0) st->warningLow = hmi_value_as_num(value, st->warningLow);
    else if (strcmp(prop, "warningHigh") == 0) st->warningHigh = hmi_value_as_num(value, st->warningHigh);
    else if (strcmp(prop, "maxPoints") == 0) st->maxPoints = (int)hmi_value_as_num(value, st->maxPoints);
    else if (strcmp(prop, "lineWidth") == 0) st->lineWidth = hmi_value_as_num(value, st->lineWidth);
    else if (strcmp(prop, "label") == 0) snprintf(st->label, sizeof st->label, "%s", hmi_value_as_str(value, st->label));
    else if (strcmp(prop, "unit") == 0) snprintf(st->unit, sizeof st->unit, "%s", hmi_value_as_str(value, st->unit));
    else if (strcmp(prop, "lineColor") == 0 || strcmp(prop, "fillColor") == 0) {
        /* colors come from binding - for now use default */
    }
    else if (strcmp(prop, "series") == 0) {
        bool was = st->nSeries > 0;
        parse_series(st, hmi_value_as_str(value, ""));
        if (was && st->nSeries == 0) apply_mode(w);   // back to the classic view
    }
    else if (strcmp(prop, "xLabels") == 0) parse_xlabels(st, hmi_value_as_str(value, ""));
    else if (strcmp(prop, "data") == 0) {
        // data arrives as HMI_V_LIST of HMI_V_NUM
        if (value->kind == HMI_V_LIST && value->items) {
            st->nData = 0;
            for (size_t i = 0; i < value->count && st->nData < MAX_POINTS; i++) {
                st->data[st->nData++] = value->items[i].n;
            }
        }
    }
    else return;
    update_grid(w);
    lv_obj_invalidate(st->face);
    if (st->nSeries > 0) lv_obj_invalidate(st->sface);
}

static void destroy(hmi_widget_t *w)
{
    state_t *st = w->state;
    if (!st) return;
    for (int i = 0; i < 5; i++) {
        if (st->gridLines[i]) lv_obj_del(st->gridLines[i]);
        if (st->yLabels[i]) lv_obj_del(st->yLabels[i]);
    }
    if (st->warnZone) lv_obj_del(st->warnZone);
    if (st->unitLabel) lv_obj_del(st->unitLabel);
    if (st->labelLabel) lv_obj_del(st->labelLabel);
    lv_free(st);
}

const hmi_widget_ops_t hmi_widget_shtrendchart = {"ShTrendChart", create, set_prop, destroy};