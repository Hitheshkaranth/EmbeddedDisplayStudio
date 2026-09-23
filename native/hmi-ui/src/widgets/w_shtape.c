// widgets/w_shtape.c -- kit widget ShTape (Avionics, "Airspeed / Altitude Tape").
//
// Spec: ui/qml/Shadcn/ShTape.qml (moving scale, fixed value box, caption).
// Default size 80x260.
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

#define MAX_TICKS 20

typedef struct {
    double value, minimumValue, maximumValue, step, span;
    char label[32], units[16];
    char side[8];
    lv_obj_t *bg, *valueBox, *valueLabel, *captionLabel;
    lv_obj_t *tickLabels[MAX_TICKS];
    lv_obj_t *tickMarks[MAX_TICKS];
    int nTicks;
} state_t;

static double clamp(double v, double lo, double hi) { return v < lo ? lo : v > hi ? hi : v; }

static void update_scale(hmi_widget_t *w)
{
    state_t *st = w->state;
    lv_obj_t *bg = st->bg;
    double W = w->width, H = w->height;

    double clamped = clamp(st->value, st->minimumValue, st->maximumValue);
    double pxPerUnit = st->span > 0 ? H / st->span : 1;
    int captionBand = (st->label[0] || st->units[0]) ? 16 : 0;

    // Scale area: full width, from top to H - captionBand
    double scaleH = H - captionBand;

    // Determine how many ticks to show
    // Model: Math.floor(span / step) + 3
    int nModel = (int)(st->span / st->step) + 3;
    if (nModel > MAX_TICKS) nModel = MAX_TICKS;

    // Ticks sit on whole steps, not on offsets from the current reading, so
    // the numbers stay round and the tape scrolls past them. Anchoring them
    // to the value instead made the scale travel with the needle, which
    // reads as a value that merely changes rather than a moving tape.
    bool leftSide = strcmp(st->side, "left") == 0;
    double firstTick = floor(clamped / st->step + 0.5)
                       - floor(st->span / st->step / 2.0) - 1;

    st->nTicks = 0;
    for (int i = 0; i < nModel; i++) {
        double tickValue = (firstTick + i) * st->step;
        int32_t y = (int32_t)(scaleH / 2.0 - (tickValue - clamped) * pxPerUnit);

        lv_obj_t *lbl = st->tickLabels[i];
        if (!lbl) {
            lbl = hmi_make_label(bg, hmi_font_size("fontSizeXs"), 400, hmi_colour("efisText"), "");
            st->tickLabels[i] = lbl;
        }
        lv_obj_t *mark = st->tickMarks[i];
        if (!mark) {
            mark = lv_obj_create(bg);
            lv_obj_remove_style_all(mark);
            lv_obj_set_size(mark, 10, 2);
            lv_obj_set_style_bg_color(mark, hmi_colour("efisLine"), 0);
            lv_obj_set_style_bg_opa(mark, LV_OPA_COVER, 0);
            st->tickMarks[i] = mark;
        }

        bool shown = tickValue >= st->minimumValue && tickValue <= st->maximumValue
                     && y >= -20 && y <= (int32_t)scaleH + 20;
        if (!shown) {
            lv_obj_add_flag(lbl, LV_OBJ_FLAG_HIDDEN);
            lv_obj_add_flag(mark, LV_OBJ_FLAG_HIDDEN);
            continue;
        }
        lv_obj_remove_flag(lbl, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(mark, LV_OBJ_FLAG_HIDDEN);

        char buf[16];
        snprintf(buf, sizeof buf, "%.0f", tickValue);
        lv_label_set_text(lbl, buf);
        // The label needs its own height: clipped to a single pixel (which
        // is what the QML delegate's height means, since QML does not clip
        // its children) nothing was ever drawn.
        lv_obj_set_width(lbl, (int32_t)W - 14);
        lv_obj_set_height(lbl, LV_SIZE_CONTENT);
        lv_obj_set_style_text_align(lbl, leftSide ? LV_TEXT_ALIGN_RIGHT : LV_TEXT_ALIGN_LEFT, 0);
        lv_obj_update_layout(lbl);
        lv_obj_set_pos(lbl, leftSide ? 0 : 14,
                       (int32_t)lround(y - lv_obj_get_height(lbl) / 2.0));
        lv_obj_set_pos(mark, leftSide ? (int32_t)W - 10 : 0, y - 1);

        st->nTicks++;
    }
    // Ticks are created after the box, so they would otherwise draw over it.
    lv_obj_move_foreground(st->valueBox);

    // Value box: centered vertically in scale area, full width
    lv_obj_set_pos(st->valueBox, 0, (int32_t)(scaleH / 2.0 - 13));
    lv_obj_set_width(st->valueBox, (int32_t)W);
    lv_obj_set_height(st->valueBox, 26);

    // Value label inside box
    char valBuf[16];
    snprintf(valBuf, sizeof valBuf, "%.0f", clamped);
    lv_label_set_text(st->valueLabel, valBuf);

    // Caption (label + units) at bottom
    char captionText[64];
    if (st->units[0])
        snprintf(captionText, sizeof captionText, "%s %s", st->label, st->units);
    else
        snprintf(captionText, sizeof captionText, "%s", st->label);
    lv_label_set_text(st->captionLabel, captionText);
    if (st->label[0] || st->units[0])
        lv_obj_remove_flag(st->captionLabel, LV_OBJ_FLAG_HIDDEN);
    else
        lv_obj_add_flag(st->captionLabel, LV_OBJ_FLAG_HIDDEN);
}

static void read_model(hmi_widget_t *w)
{
    state_t *st = w->state;
    st->value = hmi_widget_num(w, "value", 0);
    st->minimumValue = hmi_widget_num(w, "minimumValue", 0);
    st->maximumValue = hmi_widget_num(w, "maximumValue", 200);
    st->step = hmi_widget_num(w, "step", 10);
    st->span = hmi_widget_num(w, "span", 60);
    snprintf(st->label, sizeof st->label, "%s", hmi_widget_str(w, "label", ""));
    snprintf(st->units, sizeof st->units, "%s", hmi_widget_str(w, "units", ""));
    snprintf(st->side, sizeof st->side, "%s", hmi_widget_str(w, "side", "left"));
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    // Background with opacity
    lv_obj_t *bg = lv_obj_create(parent);
    lv_obj_remove_style_all(bg);
    lv_obj_set_size(bg, (int32_t)w->width, (int32_t)w->height);
    lv_obj_set_style_bg_color(bg, hmi_colour("efisPanel"), 0);
    lv_obj_set_style_bg_opa(bg, (lv_opa_t)(0.85 * 255), 0);
    lv_obj_remove_flag(bg, LV_OBJ_FLAG_SCROLLABLE);

    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;
    st->bg = bg;
    for (int i = 0; i < MAX_TICKS; i++) {
        st->tickLabels[i] = NULL;
        st->tickMarks[i] = NULL;
    }

    // Value box
    st->valueBox = lv_obj_create(bg);
    lv_obj_remove_style_all(st->valueBox);
    lv_obj_set_style_bg_color(st->valueBox, hmi_colour("efisPanel"), 0);
    lv_obj_set_style_bg_opa(st->valueBox, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(st->valueBox, hmi_colour("efisLine"), 0);
    lv_obj_set_style_border_width(st->valueBox, 1, 0);

    st->valueLabel = hmi_make_label(st->valueBox, hmi_font_size("fontSizeLg"), 600,
                                      hmi_colour("efisText"), "");

    // Caption label at bottom
    st->captionLabel = hmi_make_label(bg, hmi_font_size("fontSizeXs"), 400,
                                        hmi_colour("mutedForeground"), "");
    lv_obj_align(st->captionLabel, LV_ALIGN_BOTTOM_MID, 0, -2);

    read_model(w);
    update_scale(w);
    return bg;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "value") == 0) st->value = hmi_value_as_num(value, st->value);
    else if (strcmp(prop, "minimumValue") == 0) st->minimumValue = hmi_value_as_num(value, st->minimumValue);
    else if (strcmp(prop, "maximumValue") == 0) st->maximumValue = hmi_value_as_num(value, st->maximumValue);
    else if (strcmp(prop, "step") == 0) st->step = hmi_value_as_num(value, st->step);
    else if (strcmp(prop, "span") == 0) st->span = hmi_value_as_num(value, st->span);
    else if (strcmp(prop, "label") == 0) snprintf(st->label, sizeof st->label, "%s", hmi_value_as_str(value, st->label));
    else if (strcmp(prop, "units") == 0) snprintf(st->units, sizeof st->units, "%s", hmi_value_as_str(value, st->units));
    else if (strcmp(prop, "side") == 0) snprintf(st->side, sizeof st->side, "%s", hmi_value_as_str(value, st->side));
    else return;
    update_scale(w);
}

static void destroy(hmi_widget_t *w)
{
    state_t *st = w->state;
    if (!st) return;
    for (int i = 0; i < MAX_TICKS; i++) {
        if (st->tickLabels[i]) lv_obj_del(st->tickLabels[i]);
        if (st->tickMarks[i]) lv_obj_del(st->tickMarks[i]);
    }
    if (st->valueBox) lv_obj_del(st->valueBox);
    if (st->captionLabel) lv_obj_del(st->captionLabel);
    lv_free(st);
}

const hmi_widget_ops_t hmi_widget_shtape = {"ShTape", create, set_prop, destroy};