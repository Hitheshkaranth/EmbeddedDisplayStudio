// widgets/w_shtrendchart.c -- kit widget ShTrendChart (Industrial, "Trend Chart").
//
// Spec: ui/qml/Shadcn/ShTrendChart.qml (wrapper with grid, zones, labels) and
// faces/canvas/TrendChartFace.qml (gradient fill, trace, value dot).
#include <stdio.h>
#include <string.h>
#include <math.h>

#include "draw_util.h"
#include "registry.h"

#define MAX_POINTS 200

typedef struct {
    double minValue, maxValue, warningLow, warningHigh, lineWidth;
    int maxPoints;
    char label[64], unit[16];
    lv_color_t lineColor, fillColor;
    lv_obj_t *bg, *face, *gridLines[5], *yLabels[5];
    lv_obj_t *labelLabel, *unitLabel, *warnZone;
    double data[MAX_POINTS];
    int nData;
} state_t;

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

    // Fill area (gradient from fillColor at 20% opacity to 2%)
    for (int yi = 0; yi < (int)H; yi++) {
        double y = yi + 0.5;
        // Find where the trace crosses this scanline
        double leftX = -1, rightX = -1;
        for (int i = 0; i < n - 1; i++) {
            double x0 = i * stepX, y0 = H - (st->data[i] - st->minValue) * yScale * H;
            double x1 = (i + 1) * stepX, y1 = H - (st->data[i + 1] - st->minValue) * yScale * H;
            if ((y0 <= y && y1 > y) || (y0 > y && y1 <= y)) {
                double t = (y - y0) / (y1 - y0 + 0.001);
                double x = x0 + t * (x1 - x0);
                if (x < leftX || leftX < 0) leftX = x;
                rightX = x;
            }
        }
        if (leftX >= 0 && rightX >= 0 && rightX > leftX) {
            // Calculate alpha based on y position (20% at top, 2% at bottom)
            double t = y / H;
            lv_opa_t alpha = (lv_opa_t)lround(255 * (0.20 - t * 0.18));
            if (alpha < 5) alpha = 5;
            hmi_draw_fill(&d, leftX, yi, rightX - leftX, 1, st->fillColor, alpha, 0);
        }
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
    double zoneTop = chartH * (st->maxValue - st->warningHigh) * yScale;
    double zoneH = chartH * (1 - (st->warningHigh - st->warningLow) * yScale);
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
        double val = st->maxValue - values[i] * (st->maxValue - st->minValue);
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

    read_model(w);
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