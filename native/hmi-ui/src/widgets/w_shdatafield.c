// widgets/w_shdatafield.c -- kit widget ShDataField (Avionics, "Data Field").
//
// Spec: ui/qml/Shadcn/ShDataField.qml -- a labelled readout with severity
// colors for the value. stacked=true: label above value; stacked=false:
// label beside value.
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    lv_obj_t *labelEl, *valueEl, *unitEl;
    char label_text[64];
    char value_text[64];
    char units_text[32];
    char severity[16];
    bool stacked;
} state_t;

static lv_color_t value_color_for(const char *severity)
{
    if (strcmp(severity, "warning") == 0) return hmi_colour("efisWarning");
    if (strcmp(severity, "caution") == 0) return hmi_colour("efisCaution");
    return hmi_colour("efisText");
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width);
    int spacing4 = 4;
    const int spacing8 = 8;
    int labelFs = hmi_font_size("fontSizeXs");
    int valueFs = st->stacked ? hmi_font_size("fontSizeXl") : hmi_font_size("fontSizeBase");
    int unitFs = hmi_font_size("fontSizeXs");

    /* Label */
    lv_label_set_text(st->labelEl, st->label_text);
    lv_obj_set_style_text_font(st->labelEl, hmi_font(labelFs, 500), 0);
    lv_obj_set_style_text_color(st->labelEl, hmi_colour("mutedForeground"), 0);
    lv_obj_set_style_text_align(st->labelEl, LV_TEXT_ALIGN_LEFT, 0);

    /* Value */
    lv_label_set_text(st->valueEl, st->value_text);
    lv_obj_set_style_text_font(st->valueEl, hmi_font(valueFs, 600), 0);
    lv_obj_set_style_text_color(st->valueEl, value_color_for(st->severity), 0);
    lv_obj_set_style_text_align(st->valueEl, LV_TEXT_ALIGN_LEFT, 0);

    /* Unit */
    lv_label_set_text(st->unitEl, st->units_text);
    lv_obj_set_style_text_font(st->unitEl, hmi_font(unitFs, 400), 0);
    lv_obj_set_style_text_color(st->unitEl, hmi_colour("mutedForeground"), 0);
    lv_obj_set_style_text_align(st->unitEl, LV_TEXT_ALIGN_LEFT, 0);
    if (st->units_text[0]) {
        lv_obj_remove_flag(st->unitEl, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(st->unitEl, LV_OBJ_FLAG_HIDDEN);
    }

    /* Update layout to get sizes */
    lv_obj_update_layout(st->labelEl);
    lv_obj_update_layout(st->valueEl);
    lv_obj_update_layout(st->unitEl);

    int labelW = lv_obj_get_width(st->labelEl);
    int valueW = lv_obj_get_width(st->valueEl);
    int unitW = st->units_text[0] ? lv_obj_get_width(st->unitEl) : 0;
    int valueH = lv_obj_get_height(st->valueEl);
    if (valueH <= 0) valueH = hmi_font(valueFs, 600)->line_height;

    if (st->stacked) {
        /* Label on top, value below with spacing */
        int labelH = lv_obj_get_height(st->labelEl);
        if (labelH <= 0) labelH = hmi_font(labelFs, 500)->line_height;

        lv_obj_set_pos(st->labelEl, 0, 0);
        lv_obj_set_width(st->labelEl, (int32_t)W);
        lv_obj_set_height(st->labelEl, labelH);

        lv_obj_set_pos(st->valueEl, 0, labelH + 2);   // content width: the unit follows it

        if (st->units_text[0]) {
            lv_obj_set_pos(st->unitEl, valueW + spacing4, labelH + 2);
            /* Align bottom with value */
            lv_obj_set_pos(st->unitEl, valueW + spacing4, labelH + 2 + valueH - hmi_font(unitFs, 400)->line_height - 3);
        }
    } else {
        /* Label on left, value+unit on right */
        int maxLabelW = (int)(W * 0.5);
        lv_obj_set_width(st->labelEl, (int32_t)maxLabelW);
        lv_obj_update_layout(st->labelEl);
        labelW = lv_obj_get_width(st->labelEl);

        lv_obj_set_pos(st->labelEl, 0, 0);

        lv_obj_set_pos(st->valueEl, labelW + spacing8, 0);

        if (st->units_text[0]) {
            lv_obj_set_pos(st->unitEl, labelW + spacing8 + valueW + spacing4, 3);
        }
    }

    if (st->label_text[0]) lv_obj_remove_flag(st->labelEl, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(st->labelEl, LV_OBJ_FLAG_HIDDEN);
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *root = lv_obj_create(parent);
    lv_obj_remove_style_all(root);
    lv_obj_set_size(root, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(root, LV_OBJ_FLAG_SCROLLABLE);

    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;

    st->labelEl = lv_label_create(root);
    lv_obj_remove_style_all(st->labelEl);
    lv_label_set_long_mode(st->labelEl, LV_LABEL_LONG_CLIP);

    st->valueEl = lv_label_create(root);
    lv_obj_remove_style_all(st->valueEl);
    lv_label_set_long_mode(st->valueEl, LV_LABEL_LONG_CLIP);

    st->unitEl = lv_label_create(root);
    lv_obj_remove_style_all(st->unitEl);
    lv_label_set_long_mode(st->unitEl, LV_LABEL_LONG_CLIP);

    snprintf(st->label_text, sizeof st->label_text, "%s", hmi_widget_str(w, "label", "LABEL"));
    snprintf(st->value_text, sizeof st->value_text, "%s", hmi_widget_str(w, "value", "---"));
    snprintf(st->units_text, sizeof st->units_text, "%s", hmi_widget_str(w, "units", ""));
    snprintf(st->severity, sizeof st->severity, "%s", hmi_widget_str(w, "severity", "advisory"));
    st->stacked = hmi_widget_bool(w, "stacked", true);

    layout(w);
    return root;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "label") == 0) {
        snprintf(st->label_text, sizeof st->label_text, "%s", hmi_value_as_str(value, ""));
        layout(w);
    } else if (strcmp(prop, "value") == 0) {
        if (value->kind == HMI_V_NUM) snprintf(st->value_text, sizeof st->value_text, "%s", hmi_value_debug(value));
        else snprintf(st->value_text, sizeof st->value_text, "%s", hmi_value_as_str(value, "---"));
        layout(w);
    } else if (strcmp(prop, "units") == 0) {
        snprintf(st->units_text, sizeof st->units_text, "%s", hmi_value_as_str(value, ""));
        layout(w);
    } else if (strcmp(prop, "severity") == 0) {
        snprintf(st->severity, sizeof st->severity, "%s", hmi_value_as_str(value, "advisory"));
        lv_obj_set_style_text_color(st->valueEl, value_color_for(st->severity), 0);
    } else if (strcmp(prop, "stacked") == 0) {
        st->stacked = hmi_value_as_bool(value, st->stacked);
        layout(w);
    }
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shdatafield = {"ShDataField", create, set_prop, destroy};