// widgets/w_shautolevel.c -- kit widget ShAutoLevel (Automotive, "Level Bar").
//
// Spec: ui/qml/Shadcn/ShAutoLevel.qml (geometry, labels) and
// faces/canvas/AutoLevelFace.qml (the bar). The bar is painted row by
// row: every scanline of the outline -- rounded caps of radius barW/2 and
// two quadratic edges bulging left by `bulge` -- is a horizontal span
// whose colour follows the Canvas order: track, red zone, fill gradient,
// red inside the zone, the 2 px glow. Ticks and labels as the QML. The
// icon is not drawn in wave 1 (its space is left).
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    double value, minimumValue, maximumValue, redZoneSpan;
    char redZone[16];
    bool curved, showTicks;
    lv_obj_t *face, *labels[3];
} state_t;

static void draw_cb(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    state_t *st = w->state;
    hmi_draw_t d = hmi_draw_begin(e);
    double W = fmax(1, w->width), H = fmax(1, w->height);
    double span = fmax(0.0001, st->maximumValue - st->minimumValue);
    double fraction = fmax(0, fmin(1, (st->value - st->minimumValue) / span));
    double x = W * 0.55 + (W * 0.45 - W * 0.22) / 2, bw = W * 0.22;
    double top = H * 0.02, h = H * 0.78, bottom = top + h, r = bw / 2;
    double bulge = st->curved ? W * 0.18 : 0;

    lv_color_t track = hmi_colour("autoTrack"), redline = hmi_colour("autoRedline");
    lv_color_t accentDeep = hmi_colour("autoAccentDeep"), accent = hmi_colour("autoAccent");
    lv_color_t glow = hmi_colour("autoGlow"), line = hmi_colour("autoLine");
    lv_color_t zone = hmi_colour_hex("#ff2d55", NULL);   // Theme.autoRedline at 85 %

    double zoneH = fmax(0, fmin(1, st->redZoneSpan / 100)) * h;
    double zoneTop = -1, zoneBottom = -1;
    if (strcmp(st->redZone, "low") == 0) { zoneTop = bottom - zoneH; zoneBottom = bottom; }
    else if (strcmp(st->redZone, "high") == 0) { zoneTop = top; zoneBottom = top + zoneH; }
    double fillTop = bottom - h * fraction;

    // Row by row inside the outline.
    for (int yi = (int)floor(top); yi < (int)ceil(bottom); ++yi) {
        double y = yi + 0.5;
        double left, right;
        if (y < top + r) {                       // top cap: a chord of the circle
            double dy = (top + r) - y;
            if (dy >= r) continue;
            double half = sqrt(r * r - dy * dy);
            left = x + r - half; right = x + r + half;
        } else if (y > bottom - r) {             // bottom cap
            double dy = y - (bottom - r);
            if (dy >= r) continue;
            double half = sqrt(r * r - dy * dy);
            left = x + r - half; right = x + r + half;
        } else {                                 // the bulged straight part
            double s = (y - (top + r)) / fmax(1, (bottom - r) - (top + r));
            double shift = 2 * s * (1 - s) * bulge;   // the quadratic edge, control point x - bulge
            left = x - shift; right = x + bw - shift;
        }
        // colour of this row, in Canvas order
        lv_color_t c = track;
        lv_opa_t opa = LV_OPA_COVER;
        bool inZone = zoneTop >= 0 && y >= zoneTop && y <= zoneBottom;
        if (inZone) { c = zone; opa = (lv_opa_t)(0.85 * 255); }
        if (fraction > 0 && y >= fillTop) {
            double t = (bottom - y) / fmax(1, bottom - fillTop);   // 0 at bottom -> accentDeep
            c = lv_color_mix(accent, accentDeep, (lv_opa_t)(255 * fmin(1, fmax(0, t))));
            opa = LV_OPA_COVER;
            if (inZone) c = redline;
            if (y - fillTop < 2) c = glow;
        }
        if (inZone && !(fraction > 0 && y >= fillTop)) {
            // the zone is painted over the track: composite the 85 % red on the track
            hmi_draw_fill(&d, left, yi, right - left, 1, track, LV_OPA_COVER, 0);
        }
        hmi_draw_fill(&d, left, yi, right - left, 1, c, opa, 0);
    }

    // Ticks along the left edge.
    if (st->showTicks) {
        for (int i = 0; i <= 10; ++i) {
            double f = i / 10.0;
            double y = bottom - h * f;
            double t = 1 - fabs(f - 0.5) * 2;
            double edge = x - bulge * (1 - (1 - t) * (1 - t)) * 0.5;
            double len = (i % 5 == 0) ? W * 0.12 : W * 0.06;
            hmi_draw_line(&d, edge - 2, y, edge - 2 - len, y, (i % 5 == 0) ? 1.5 : 1, line, LV_OPA_COVER);
        }
    }
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    double barX = W * 0.55 + (W * 0.45 - W * 0.22) / 2, barTop = H * 0.02, barH = H * 0.78;
    double bulge = st->curved ? W * 0.18 : 0;
    int fs = hmi_px_min(W * 0.14, 7);
    int lh = lv_font_get_line_height(hmi_font(fs, 600));
    int width = (int)fmax(4, barX - bulge - W * 0.16);
    const char *keys[3] = {"topLabel", "midLabel", "bottomLabel"};
    const double fr[3] = {1.0, 0.5, 0.0};
    for (int i = 0; i < 3; ++i) {
        lv_obj_t *l = st->labels[i];
        const char *text = hmi_widget_str(w, keys[i], "");
        lv_label_set_text(l, text);
        lv_obj_set_style_text_font(l, hmi_font(fs, 600), 0);
        lv_obj_set_width(l, width);
        lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_RIGHT, 0);
        lv_obj_set_pos(l, 0, hmi_px(barTop + barH * (1 - fr[i]) - lh / 2.0));
        if (text[0]) lv_obj_remove_flag(l, LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(l, LV_OBJ_FLAG_HIDDEN);
    }
}

static void read_model(hmi_widget_t *w)
{
    state_t *st = w->state;
    st->value = hmi_widget_num(w, "value", 55);
    st->minimumValue = hmi_widget_num(w, "minimumValue", 0);
    st->maximumValue = hmi_widget_num(w, "maximumValue", 100);
    st->redZoneSpan = hmi_widget_num(w, "redZoneSpan", 12);
    snprintf(st->redZone, sizeof st->redZone, "%s", hmi_widget_str(w, "redZone", "low"));
    st->curved = hmi_widget_bool(w, "curved", true);
    st->showTicks = hmi_widget_bool(w, "showTicks", true);
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
    for (int i = 0; i < 3; ++i)
        st->labels[i] = hmi_make_label(face, 12, 600, hmi_colour("autoLine"), "");
    lv_obj_add_event_cb(face, draw_cb, LV_EVENT_DRAW_MAIN, w);
    read_model(w);
    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "value") == 0) st->value = hmi_value_as_num(value, st->value);
    else if (strcmp(prop, "minimumValue") == 0) st->minimumValue = hmi_value_as_num(value, st->minimumValue);
    else if (strcmp(prop, "maximumValue") == 0) st->maximumValue = hmi_value_as_num(value, st->maximumValue);
    else if (strcmp(prop, "redZoneSpan") == 0) st->redZoneSpan = hmi_value_as_num(value, st->redZoneSpan);
    else if (strcmp(prop, "redZone") == 0) snprintf(st->redZone, sizeof st->redZone, "%s", hmi_value_as_str(value, st->redZone));
    else if (strcmp(prop, "curved") == 0) { st->curved = hmi_value_as_bool(value, st->curved); layout(w); }
    else if (strcmp(prop, "showTicks") == 0) st->showTicks = hmi_value_as_bool(value, st->showTicks);
    else if (strcmp(prop, "topLabel") == 0 || strcmp(prop, "midLabel") == 0 || strcmp(prop, "bottomLabel") == 0) {
        int i = prop[0] == 't' ? 0 : prop[0] == 'm' ? 1 : 2;
        const char *s = hmi_value_as_str(value, "");
        lv_label_set_text(st->labels[i], s);
        if (s[0]) lv_obj_remove_flag(st->labels[i], LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(st->labels[i], LV_OBJ_FLAG_HIDDEN);
        return;
    } else return;
    lv_obj_invalidate(st->face);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shautolevel = {"ShAutoLevel", create, set_prop, destroy};
