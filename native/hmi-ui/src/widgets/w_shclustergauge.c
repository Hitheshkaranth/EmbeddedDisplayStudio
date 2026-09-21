// widgets/w_shclustergauge.c -- kit widget ShClusterGauge (Automotive, "Cluster Gauge").
//
// Spec: ui/qml/Shadcn/ShClusterGauge.qml + faces/canvas/ClusterGaugeFace.qml
// Arc-based instrument: scale track, redline band, gradient value arc,
// tick marks + labels, optional inner dial, big centre readout.
//
// Properties: value, minimumValue, maximumValue, majorStep, redlineFrom,
//             sweep, readout, readoutUnit, caption, label, decimals,
//             showInnerDial, opacity, visible.
// Default size 240x240.
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "log.h"
#include "registry.h"
#include "theme.h"
#include "value.h"

/* ------------------------------------------------------------------ */
/*  State  —  cached from model, read by draw_cb                       */
/* ------------------------------------------------------------------ */

typedef struct {
    int   width, height;
    int   arc_r, stroke_w, tick_len, minor_tick_len, inner_r;
    int   start_angle, sweep;
    double value, minimumValue, maximumValue;
    double majorStep, redlineFrom, sweep_deg;
    int    decimals;
    double span;
    lv_color_t track_col, redline_col, accent_deep_col, accent_col, glow_col;
    lv_color_t line_col, muted_col, panel_col, tile_border_col;
    lv_color_t amber_col, text_col;
    int    n_majors;
    double majors[60];
    lv_obj_t *readout_obj, *unit_obj, *caption_obj, *label_obj;
    lv_obj_t **scale_labels;
} cluster_state_t;

/* Size-changed callback */
static void cluster_size_cb(lv_event_t *e)
{
    hmi_widget_t *w  = lv_event_get_user_data(e);
    cluster_state_t *st = w->state;
    if (!st) return;
    st->width  = (int32_t)lv_obj_get_width(lv_event_get_target(e));
    st->height = (int32_t)lv_obj_get_height(lv_event_get_target(e));
}

/* Position children after size is known */
static void cluster_position_labels(cluster_state_t *st, int d)
{
    int32_t cx = d / 2;
    int32_t cy = d / 2;

    for (int i = 0; i < st->n_majors; i++) {
        lv_obj_t *lbl = st->scale_labels[i];
        if (!lbl) continue;
        double a_deg = st->start_angle + st->sweep * (st->majors[i] - st->minimumValue) / st->span;
        double a_rad = a_deg * 3.14159265358979 / 180.0;
        int32_t label_r = (int32_t)(0.47 * d);
        int32_t lx = cx + (int32_t)(label_r * cos(a_rad)) - lv_obj_get_width(lbl);
        int32_t ly = cy + (int32_t)(label_r * sin(a_rad)) - lv_obj_get_height(lbl) / 2;
        lv_obj_set_pos(lbl, lx, ly);
        if (st->majors[i] >= st->redlineFrom)
            lv_obj_set_style_text_color(lbl, st->redline_col, 0);
        else
            lv_obj_set_style_text_color(lbl, st->line_col, 0);
    }

    lv_obj_t *ro = st->readout_obj;
    if (ro) {
        lv_obj_set_pos(ro, cx - lv_obj_get_width(ro) / 2,
                       cy - (int32_t)(0.07 * d) - lv_obj_get_height(ro) / 2);
    }
    lv_obj_t *cap = st->caption_obj;
    if (cap) {
        lv_obj_set_pos(cap, cx - lv_obj_get_width(cap) / 2,
                       cy - (int32_t)(0.07 * d) - lv_obj_get_height(ro) - 4);
    }
    lv_obj_t *unit = st->unit_obj;
    if (unit) {
        lv_obj_set_pos(unit, cx - lv_obj_get_width(unit) / 2,
                       cy - (int32_t)(0.07 * d) + lv_obj_get_height(ro) + 2);
    }
    lv_obj_t *lbl = st->label_obj;
    if (lbl) {
        lv_obj_set_pos(lbl, cx + (int32_t)(0.2 * d),
                       cy + (int32_t)(0.33 * d) - lv_obj_get_height(lbl) / 2);
    }
}

/* Size changed callback that positions labels */
static void cluster_position_cb(lv_event_t *e)
{
    hmi_widget_t *w  = lv_event_get_user_data(e);
    cluster_state_t *st = w->state;
    if (!st) return;
    int d = st->width < st->height ? st->width : st->height;
    if (d > 0) cluster_position_labels(st, d);
}

static double value_to_angle(cluster_state_t *st, double v)
{
    return st->start_angle + st->sweep * (v - st->minimumValue) / st->span;
}

/* ------------------------------------------------------------------ */
/*  Custom draw callback                                               */
/* ------------------------------------------------------------------ */

static void cluster_draw_cb(lv_event_t *e)
{
    hmi_widget_t *w  = lv_event_get_user_data(e);
    cluster_state_t *st = w->state;
    if (!st || st->width < 1) return;

    int d = st->width < st->height ? st->width : st->height;
    st->arc_r      = (int32_t)(0.38 * d);
    st->stroke_w   = (int32_t)(0.05 * d);
    st->tick_len   = (int32_t)(0.035 * d);
    st->minor_tick_len = (int32_t)(st->tick_len * 0.5);
    st->inner_r    = (int32_t)(0.28 * d);
    st->sweep      = (int32_t)st->sweep_deg;

    lv_area_t coords;
    lv_obj_get_coords(lv_event_get_target(e), &coords);
    lv_point_t origin = { .x = coords.x1, .y = coords.y1 };
    lv_layer_t *layer = lv_event_get_layer(e);

    int cx = origin.x + d / 2;
    int cy = origin.y + d / 2;

    double v = st->value;
    if (v < st->minimumValue) v = st->minimumValue;
    if (v > st->maximumValue) v = st->maximumValue;

    /* 1. Scale track */
    {
        lv_draw_arc_dsc_t ad; lv_draw_arc_dsc_init(&ad);
        ad.center.x = cx; ad.center.y = cy;
        ad.radius = (uint16_t)st->arc_r; ad.width = st->stroke_w;
        ad.start_angle = (lv_value_precise_t)st->start_angle;
        ad.end_angle = (lv_value_precise_t)(st->start_angle + st->sweep);
        ad.color = st->track_col; ad.opa = LV_OPA_COVER; ad.rounded = 1;
        lv_draw_arc(layer, &ad);
    }

    /* 2. Redline band */
    if (st->redlineFrom < st->maximumValue) {
        lv_draw_arc_dsc_t ad; lv_draw_arc_dsc_init(&ad);
        ad.center.x = cx; ad.center.y = cy;
        ad.radius = (uint16_t)st->arc_r; ad.width = st->stroke_w;
        ad.start_angle = (lv_value_precise_t)value_to_angle(st, st->redlineFrom);
        ad.end_angle = (lv_value_precise_t)(st->start_angle + st->sweep);
        ad.color = st->redline_col; ad.opa = LV_OPA_COVER; ad.rounded = 1;
        lv_draw_arc(layer, &ad);
    }

    /* 3. Value arc (gradient via ~24 segments) */
    {
        double val_angle = value_to_angle(st, v);
        if (val_angle > st->start_angle) {
            int segments = 24;
            double seg_a = (val_angle - st->start_angle) / segments;
            for (int i = 0; i < segments; i++) {
                double a0 = st->start_angle + i * seg_a;
                double a1 = st->start_angle + (i + 1) * seg_a;
                double t = segments > 1 ? (double)i / (segments - 1) : 0;
                lv_color_t c = lv_color_mix(st->accent_deep_col, st->accent_col, (uint8_t)(t * 255));
                lv_draw_arc_dsc_t ad; lv_draw_arc_dsc_init(&ad);
                ad.center.x = cx; ad.center.y = cy;
                ad.radius = (uint16_t)st->arc_r; ad.width = st->stroke_w;
                ad.start_angle = (lv_value_precise_t)a0;
                ad.end_angle = (lv_value_precise_t)a1;
                ad.color = c; ad.opa = LV_OPA_COVER; ad.rounded = 1;
                lv_draw_arc(layer, &ad);
            }
        }
    }

    /* 3b. Glow line */
    {
        double val_angle = value_to_angle(st, v);
        lv_draw_arc_dsc_t ad; lv_draw_arc_dsc_init(&ad);
        ad.center.x = cx; ad.center.y = cy;
        ad.radius = (uint16_t)(st->arc_r + st->stroke_w * 35 / 100);
        ad.width = 2;
        ad.start_angle = (lv_value_precise_t)st->start_angle;
        ad.end_angle = (lv_value_precise_t)val_angle;
        ad.color = st->glow_col; ad.opa = LV_OPA_COVER; ad.rounded = 0;
        lv_draw_arc(layer, &ad);
    }

    /* 3c. Redline portion of value arc */
    {
        double val_angle = value_to_angle(st, v);
        if (v > st->redlineFrom && st->redlineFrom < st->maximumValue) {
            lv_draw_arc_dsc_t ad; lv_draw_arc_dsc_init(&ad);
            ad.center.x = cx; ad.center.y = cy;
            ad.radius = (uint16_t)st->arc_r; ad.width = st->stroke_w;
            ad.start_angle = (lv_value_precise_t)value_to_angle(st, st->redlineFrom);
            ad.end_angle = (lv_value_precise_t)val_angle;
            ad.color = st->redline_col; ad.opa = LV_OPA_COVER; ad.rounded = 1;
            lv_draw_arc(layer, &ad);
        }
    }

    /* 4. Major ticks */
    for (int i = 0; i < st->n_majors; i++) {
        double mv = st->majors[i];
        double a_deg = value_to_angle(st, mv);
        double a_rad = a_deg * 3.14159265358979 / 180.0;
        int outer_r = st->arc_r + st->tick_len;
        lv_point_precise_t p1, p2;
        lv_point_precise_set(&p1, (lv_value_precise_t)(cx + outer_r * cos(a_rad)),
                                    (lv_value_precise_t)(cy + outer_r * sin(a_rad)));
        lv_point_precise_set(&p2, (lv_value_precise_t)(cx + st->arc_r * cos(a_rad)),
                                  (lv_value_precise_t)(cy + st->arc_r * sin(a_rad)));
        lv_draw_line_dsc_t ld; lv_draw_line_dsc_init(&ld);
        ld.p1 = p1; ld.p2 = p2;
        ld.color = mv >= st->redlineFrom ? st->redline_col : st->line_col;
        ld.width = 2; ld.round_end = 1;
        lv_draw_line(layer, &ld);
    }

    /* 5. Minor ticks */
    {
        int steps = (int32_t)(st->span / st->majorStep + 0.5);
        for (int s = 0; s < steps; s++) {
            double base = st->minimumValue + s * st->majorStep;
            for (int m = 1; m < 5; m++) {
                double mval = base + m * (st->majorStep / 5.0);
                if (mval > st->maximumValue + 0.0001) goto minor_done;
                double a_deg = value_to_angle(st, mval);
                double a_rad = a_deg * 3.14159265358979 / 180.0;
                int outer_r = st->arc_r + st->minor_tick_len;
                lv_point_precise_t p1, p2;
                lv_point_precise_set(&p1, (lv_value_precise_t)(cx + outer_r * cos(a_rad)),
                                          (lv_value_precise_t)(cy + outer_r * sin(a_rad)));
                lv_point_precise_set(&p2, (lv_value_precise_t)(cx + st->arc_r * cos(a_rad)),
                                         (lv_value_precise_t)(cy + st->arc_r * sin(a_rad)));
                lv_draw_line_dsc_t ld; lv_draw_line_dsc_init(&ld);
                ld.p1 = p1; ld.p2 = p2;
                ld.color = st->muted_col; ld.width = 1; ld.round_end = 1;
                lv_draw_line(layer, &ld);
            }
        minor_done:;
        }
    }

    /* 6. Inner dial */
    {
        int show = hmi_widget_bool(w, "showInnerDial", 1);
        if (show) {
            lv_draw_rect_dsc_t rd; lv_draw_rect_dsc_init(&rd);
            lv_area_t dial_area = { .x1 = cx - st->inner_r, .y1 = cy - st->inner_r,
                                    .x2 = cx + st->inner_r, .y2 = cy + st->inner_r };
            rd.bg_color = st->panel_col; rd.bg_opa = LV_OPA_COVER; rd.radius = LV_RADIUS_CIRCLE;
            lv_draw_rect(layer, &rd, &dial_area);

            lv_draw_border_dsc_t bd; lv_draw_border_dsc_init(&bd);
            bd.color = st->tile_border_col; bd.width = 1; bd.opa = LV_OPA_COVER;
            bd.side = LV_BORDER_SIDE_FULL;
            lv_draw_border(layer, &bd, &dial_area);
        }
    }
}

/* ------------------------------------------------------------------ */
/*  LVGL object tree: face + labels                                    */
/* ------------------------------------------------------------------ */

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *face = lv_obj_create(parent);
    lv_obj_remove_style_all(face);
    lv_obj_set_style_bg_opa(face, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(face, 0, 0);
    lv_obj_remove_flag(face, LV_OBJ_FLAG_SCROLLABLE);

    cluster_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->minimumValue = 0; st->maximumValue = 8;
    st->majorStep    = 1; st->redlineFrom  = 7;
    st->sweep_deg    = 240; st->decimals = 0;
    st->span         = st->maximumValue - st->minimumValue;
    st->start_angle  = 90 + (360 - 240) / 2; /* = 210 */

    st->track_col      = hmi_colour("autoTrack");
    st->redline_col    = hmi_colour("autoRedline");
    st->accent_deep_col = hmi_colour("autoAccentDeep");
    st->accent_col     = hmi_colour("autoAccent");
    st->glow_col       = hmi_colour("autoGlow");
    st->line_col       = hmi_colour("autoLine");
    st->muted_col      = hmi_colour("autoMuted");
    st->panel_col      = hmi_colour("autoPanel");
    st->tile_border_col = hmi_colour("autoTileBorder");
    st->amber_col      = hmi_colour("autoAmber");
    st->text_col       = hmi_colour("autoText");

    w->state = st;

    lv_obj_add_event_cb(face, cluster_size_cb,  LV_EVENT_SIZE_CHANGED, w);
    lv_obj_add_event_cb(face, cluster_position_cb, LV_EVENT_SIZE_CHANGED, w);
    lv_obj_add_event_cb(face, cluster_draw_cb,   LV_EVENT_DRAW_MAIN, w);

    /* Scale numbers */
    st->n_majors = 0;
    for (double mv = st->minimumValue; mv <= st->maximumValue + 0.0001 && st->n_majors < 60; mv += st->majorStep)
        st->majors[st->n_majors++] = mv;

    st->scale_labels = (lv_obj_t **)lv_malloc_zeroed(st->n_majors * sizeof(lv_obj_t *));
    for (int i = 0; i < st->n_majors; i++) {
        lv_obj_t *lbl = lv_label_create(face);
        char buf[16];
        snprintf(buf, sizeof buf, "%d", (int)st->majors[i]);
        lv_label_set_text(lbl, buf);
        int fs = (int)(0.068 * 240); if (fs < 7) fs = 7;
        lv_obj_set_style_text_font(lbl, hmi_font(fs, 500), 0);
        lv_obj_set_style_text_color(lbl, st->line_col, 0);
        lv_label_set_long_mode(lbl, LV_LABEL_LONG_CLIP);
        st->scale_labels[i] = lbl;
    }

    lv_obj_t *readout = lv_label_create(face);
    lv_label_set_text(readout, "4");
    lv_obj_set_style_text_font(readout, hmi_font(67, 600), 0);
    lv_obj_set_style_text_color(readout, st->text_col, 0);
    lv_label_set_long_mode(readout, LV_LABEL_LONG_CLIP);

    lv_obj_t *unit = lv_label_create(face);
    lv_label_set_text(unit, "km/h");
    lv_obj_set_style_text_font(unit, hmi_font(19, 400), 0);
    lv_obj_set_style_text_color(unit, st->muted_col, 0);
    lv_label_set_long_mode(unit, LV_LABEL_LONG_CLIP);

    lv_obj_t *cap = lv_label_create(face);
    lv_label_set_text(cap, "");
    lv_obj_set_style_text_font(cap, hmi_font(17, 500), 0);
    lv_obj_set_style_text_color(cap, st->amber_col, 0);
    lv_label_set_long_mode(cap, LV_LABEL_LONG_CLIP);
    lv_obj_add_flag(cap, LV_OBJ_FLAG_HIDDEN);

    lv_obj_t *lbl = lv_label_create(face);
    lv_label_set_text(lbl, "x1000 RPM");
    lv_obj_set_style_text_font(lbl, hmi_font(11, 500), 0);
    lv_obj_set_style_text_color(lbl, st->muted_col, 0);
    lv_label_set_long_mode(lbl, LV_LABEL_LONG_CLIP);

    st->readout_obj = readout;
    st->unit_obj    = unit;
    st->caption_obj = cap;
    st->label_obj   = lbl;

    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    cluster_state_t *st = w->state;
    if (!st) return;
    lv_obj_t *face = (lv_obj_t *)w->native;
    int d = st->width < st->height ? st->width : st->height;

    if (strcmp(prop, "value") == 0) {
        st->value = hmi_value_as_num(value, 0);
        const char *readout = hmi_widget_str(w, "readout", "");
        if (readout[0] != '\0')
            lv_label_set_text(st->readout_obj, readout);
        else {
            char buf[32];
            snprintf(buf, sizeof buf, "%.*f", st->decimals, st->value);
            lv_label_set_text(st->readout_obj, buf);
        }
        lv_obj_invalidate(face);
    }
    else if (strcmp(prop, "readout") == 0) {
        lv_label_set_text(st->readout_obj, hmi_value_as_str(value, ""));
    }
    else if (strcmp(prop, "readoutUnit") == 0) {
        lv_label_set_text(st->unit_obj, hmi_value_as_str(value, ""));
    }
    else if (strcmp(prop, "caption") == 0) {
        const char *s = hmi_value_as_str(value, "");
        lv_label_set_text(st->caption_obj, s);
        if (s[0] != '\0') lv_obj_remove_flag(st->caption_obj, LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(st->caption_obj, LV_OBJ_FLAG_HIDDEN);
        if (d > 0) cluster_position_labels(st, d);
    }
    else if (strcmp(prop, "label") == 0) {
        const char *s = hmi_widget_str(w, "label", "");
        lv_label_set_text(st->label_obj, s);
        if (d > 0) cluster_position_labels(st, d);
    }
    else if (strcmp(prop, "minimumValue") == 0) {
        st->minimumValue = hmi_value_as_num(value, 0);
        st->span = st->maximumValue - st->minimumValue;
        lv_obj_invalidate(face);
    }
    else if (strcmp(prop, "maximumValue") == 0) {
        st->maximumValue = hmi_value_as_num(value, 8);
        st->span = st->maximumValue - st->minimumValue;
        lv_obj_invalidate(face);
    }
    else if (strcmp(prop, "majorStep") == 0) {
        st->majorStep = hmi_value_as_num(value, 1);
        st->n_majors = 0;
        for (double mv = st->minimumValue; mv <= st->maximumValue + 0.0001 && st->n_majors < 60; mv += st->majorStep)
            st->majors[st->n_majors++] = mv;
        for (int i = 0; i < st->n_majors; i++) {
            if (st->scale_labels[i]) {
                char buf[16];
                snprintf(buf, sizeof buf, "%d", (int)st->majors[i]);
                lv_label_set_text(st->scale_labels[i], buf);
            }
        }
        lv_obj_invalidate(face);
    }
    else if (strcmp(prop, "redlineFrom") == 0) {
        st->redlineFrom = hmi_value_as_num(value, 7);
        lv_obj_invalidate(face);
    }
    else if (strcmp(prop, "sweep") == 0) {
        st->sweep_deg = hmi_value_as_num(value, 240);
        st->start_angle = 90 + (360 - (int32_t)st->sweep_deg) / 2;
        lv_obj_invalidate(face);
    }
    else if (strcmp(prop, "decimals") == 0) {
        st->decimals = (int32_t)hmi_value_as_num(value, 0);
        const char *readout = hmi_widget_str(w, "readout", "");
        if (readout[0] == '\0') {
            char buf[32];
            snprintf(buf, sizeof buf, "%.*f", st->decimals, st->value);
            lv_label_set_text(st->readout_obj, buf);
        }
    }
    else if (strcmp(prop, "showInnerDial") == 0) {
        lv_obj_invalidate(face);
    }
}

const hmi_widget_ops_t hmi_widget_shclustergauge = {
    "ShClusterGauge", create, set_prop, NULL
};