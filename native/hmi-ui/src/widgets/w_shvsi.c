// widgets/w_shvsi.c -- kit widget ShVSI (Avionics, "Vertical Speed").
//
// Spec: ui/qml/Shadcn/ShVSI.qml (scale, needle, units).
// Default size 70x220.
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    double value, range;
    char units[8];
    lv_obj_t *bg, *needle, *unitLabel;
    lv_obj_t *ticks[5], *tickLabels[5];
} state_t;

static double clamp(double v, double lo, double hi) { return v < lo ? lo : v > hi ? hi : v; }

static void update_scale(hmi_widget_t *w)
{
    state_t *st = w->state;
    lv_obj_t *bg = st->bg;
    double W = w->width, H = w->height;
    double range = st->range;

    // Scale area: full width, bottom 16px reserved for units
    double scaleH = H - 16;

    // 5 ticks: range, range/2, 0, -range/2, -range
    const double tickValues[] = {1, 0.5, 0, -0.5, -1};
    for (int i = 0; i < 5; i++) {
        // y = scale.y + scale.height / 2 - (tick / range) * (scale.height / 2 - 12)
        // tick value = range * tickValues[i]
        // y = scaleH / 2 - (range * tickValues[i] / range) * (scaleH / 2 - 12)
        // y = scaleH / 2 - tickValues[i] * (scaleH / 2 - 12)
        double tv = tickValues[i];
        int32_t y = (int32_t)(scaleH / 2.0 - tv * (scaleH / 2.0 - 12));

        if (!st->ticks[i]) {
            st->ticks[i] = lv_obj_create(bg);
            lv_obj_remove_style_all(st->ticks[i]);
            lv_obj_set_style_bg_color(st->ticks[i], hmi_colour("efisLine"), 0);
            lv_obj_set_style_bg_opa(st->ticks[i], LV_OPA_COVER, 0);
        }
        lv_obj_set_pos(st->ticks[i], 4, y);
        lv_obj_set_height(st->ticks[i], 1);

        // Tick width: 14 for abs(tick)==range (i=0, i=4), 8 otherwise
        int tickW = (i == 0 || i == 4) ? 14 : 8;
        lv_obj_set_width(st->ticks[i], tickW);

        // Zero line height: 2, others: 1
        if (i == 2) {
            lv_obj_set_height(st->ticks[i], 2);
        }

        // Label: only for ±2000 (i=0, i=4), show "2" or "-2"
        if (!st->tickLabels[i]) {
            st->tickLabels[i] = hmi_make_label(bg, hmi_font_size("fontSizeXs"), 400,
                                                 hmi_colour("efisText"), "");
            lv_obj_set_pos(st->tickLabels[i], 20, y - 6);
        }
        if (i == 0) {
            lv_label_set_text(st->tickLabels[i], "2");
            lv_obj_remove_flag(st->tickLabels[i], LV_OBJ_FLAG_HIDDEN);
        } else if (i == 4) {
            lv_label_set_text(st->tickLabels[i], "-2");
            lv_obj_remove_flag(st->tickLabels[i], LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_add_flag(st->tickLabels[i], LV_OBJ_FLAG_HIDDEN);
        }
    }

    // Needle: width = parent.width - 26, height = 3
    // x = 22, y = scale.y + scale.height / 2 - (value / range) * (scale.height / 2 - 12) - 1
    double clamped = clamp(st->value, -range, range);
    int32_t ny = (int32_t)(scaleH / 2.0 - (clamped / range) * (scaleH / 2.0 - 12) - 1);
    lv_obj_set_pos(st->needle, 22, ny);
    lv_obj_set_width(st->needle, (int32_t)(W - 26));
    lv_obj_set_height(st->needle, 3);

    // Needle color: caution if |value| >= range, normal otherwise
    lv_color_t needleColor = (fabs(clamped) >= range) ? hmi_colour("efisCaution") : hmi_colour("efisNormal");
    lv_obj_set_style_bg_color(st->needle, needleColor, 0);
    lv_obj_set_style_bg_opa(st->needle, LV_OPA_COVER, 0);

    // Unit label
    lv_label_set_text(st->unitLabel, st->units);
    if (st->units[0])
        lv_obj_remove_flag(st->unitLabel, LV_OBJ_FLAG_HIDDEN);
    else
        lv_obj_add_flag(st->unitLabel, LV_OBJ_FLAG_HIDDEN);
}

static void read_model(hmi_widget_t *w)
{
    state_t *st = w->state;
    st->value = hmi_widget_num(w, "value", 0);
    st->range = hmi_widget_num(w, "range", 2000);
    snprintf(st->units, sizeof st->units, "%s", hmi_widget_str(w, "units", "FPM"));
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    // Background with border
    lv_obj_t *bg = lv_obj_create(parent);
    lv_obj_remove_style_all(bg);
    lv_obj_set_size(bg, (int32_t)w->width, (int32_t)w->height);
    lv_obj_set_style_bg_color(bg, hmi_colour("efisPanel"), 0);
    lv_obj_set_style_bg_opa(bg, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(bg, hmi_colour("border"), 0);
    lv_obj_set_style_border_width(bg, 1, 0);
    lv_obj_set_style_radius(bg, hmi_radius("radiusSm"), 0);
    lv_obj_remove_flag(bg, LV_OBJ_FLAG_SCROLLABLE);

    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;
    st->bg = bg;
    for (int i = 0; i < 5; i++) {
        st->ticks[i] = NULL;
        st->tickLabels[i] = NULL;
    }

    // Needle
    st->needle = lv_obj_create(bg);
    lv_obj_remove_style_all(st->needle);
    lv_obj_set_style_bg_color(st->needle, hmi_colour("efisNormal"), 0);
    lv_obj_set_style_bg_opa(st->needle, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(st->needle, 0, 0);

    // Unit label at bottom center
    st->unitLabel = hmi_make_label(bg, hmi_font_size("fontSizeXs"), 400, hmi_colour("mutedForeground"), "FPM");
    lv_obj_align(st->unitLabel, LV_ALIGN_BOTTOM_MID, 0, -2);

    read_model(w);
    update_scale(w);
    return bg;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "value") == 0) st->value = hmi_value_as_num(value, st->value);
    else if (strcmp(prop, "range") == 0) st->range = hmi_value_as_num(value, st->range);
    else if (strcmp(prop, "units") == 0) snprintf(st->units, sizeof st->units, "%s", hmi_value_as_str(value, st->units));
    else return;
    update_scale(w);
}

static void destroy(hmi_widget_t *w)
{
    state_t *st = w->state;
    if (!st) return;
    for (int i = 0; i < 5; i++) {
        if (st->ticks[i]) lv_obj_del(st->ticks[i]);
        if (st->tickLabels[i]) lv_obj_del(st->tickLabels[i]);
    }
    if (st->needle) lv_obj_del(st->needle);
    if (st->unitLabel) lv_obj_del(st->unitLabel);
    lv_free(st);
}

const hmi_widget_ops_t hmi_widget_shvsi = {"ShVSI", create, set_prop, destroy};