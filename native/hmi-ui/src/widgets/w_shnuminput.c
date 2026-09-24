// widgets/w_shnuminput.c -- kit widget ShNumInput (Industrial, "Numeric Input").
//
// Spec: ui/qml/Shadcn/ShNumInput.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): value, minValue, maxValue, step, unit, label, enabled, decimalPlaces, opacity, visible.
// Default size 240x64. Signals: valueChanged.
#include <stdio.h>
#include <string.h>
#include <math.h>

#include "draw_util.h"
#include "registry.h"
#include "theme.h"

typedef struct {
    lv_obj_t *label;
    lv_obj_t *minusBtn;
    lv_obj_t *valueDisplay;
    lv_obj_t *valueText;
    lv_obj_t *unitText;
    lv_obj_t *plusBtn;
    double value, minValue, maxValue, step;
    int decimalPlaces;
    char unit[16];
} shnuminput_state_t;

static void btn_click_cb(lv_event_t *e)
{
    hmi_widget_t *widget = (hmi_widget_t *)lv_event_get_user_data(e);
    if (!widget) return;
    shnuminput_state_t *st = widget->state;
    if (!st) return;
    lv_obj_t *clicked = lv_event_get_target(e);
    if (clicked == st->minusBtn) {
        st->value = fmax(st->minValue, fmin(st->maxValue, st->value - (st->step > 0 ? st->step : 1)));
    } else {
        st->value = fmax(st->minValue, fmin(st->maxValue, st->value + (st->step > 0 ? st->step : 1)));
    }
    // Format and display value
    char txt[64];
    snprintf(txt, sizeof txt, "%.*f", st->decimalPlaces, st->value);
    lv_label_set_text(st->valueText, txt);
    // Emit valueChanged signal
    hmi_value_t val = hmi_value_num(st->value);
    hmi_widget_emit(widget, "valueChanged", &val);
    hmi_value_free(&val);
}

static void update_value_text(shnuminput_state_t *st)
{
    char txt[64];
    snprintf(txt, sizeof txt, "%.*f", st->decimalPlaces, st->value);
    lv_label_set_text(st->valueText, txt);
}

static lv_obj_t *create_outline_button(lv_obj_t *parent)
{
    lv_obj_t *btn = lv_button_create(parent);
    lv_obj_remove_style_all(btn);
    lv_obj_set_size(btn, 40, 40);
    lv_obj_set_style_radius(btn, hmi_radius("md"), 0);
    lv_obj_set_style_bg_opa(btn, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_color(btn, hmi_colour("border"), 0);
    lv_obj_set_style_border_width(btn, 1, 0);

    lv_obj_t *lbl = lv_label_create(btn);
    lv_obj_remove_style_all(lbl);
    lv_obj_set_style_text_font(lbl, hmi_font(14, 500), 0);
    lv_obj_set_style_text_color(lbl, hmi_colour("foreground"), 0);
    lv_obj_set_style_text_align(lbl, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_center(lbl);

    return btn;
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *bg = lv_obj_create(parent);
    lv_obj_remove_style_all(bg);
    lv_obj_set_size(bg, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(bg, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(bg, lv_color_hex(0x000000), 0);
    lv_obj_set_style_bg_opa(bg, LV_OPA_TRANSP, 0);

    // Column layout with 4px spacing
    lv_obj_set_flex_flow(bg, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_all(bg, 0, 0);
    lv_obj_set_style_pad_gap(bg, 4, 0);
    lv_obj_set_size(bg, lv_pct(100), lv_pct(100));

    // Optional label
    lv_obj_t *label = hmi_make_label(bg, hmi_font_size("fontSizeXs"), 400, hmi_colour("foreground"), "");

    // Row: [-] value [+] 
    lv_obj_t *row = lv_obj_create(bg);
    lv_obj_remove_style_all(row);
    lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_size(row, lv_pct(100), 40);
    lv_obj_set_style_pad_gap(row, 4, 0);

    // Minus button
    lv_obj_t *minusBtn = create_outline_button(row);
    lv_obj_t *minusLbl = lv_obj_get_child(minusBtn, 0);
    lv_label_set_text(minusLbl, "\u2212");

    // Value display (rectangle with text input feel)
    lv_obj_t *valueDisplay = lv_obj_create(row);
    lv_obj_remove_style_all(valueDisplay);
    lv_obj_set_flex_grow(valueDisplay, 1);
    lv_obj_set_size(valueDisplay, 0, 40);
    lv_obj_set_style_radius(valueDisplay, hmi_radius("radiusMd"), 0);
    lv_obj_set_style_bg_color(valueDisplay, hmi_colour("background"), 0);
    lv_obj_set_style_bg_opa(valueDisplay, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(valueDisplay, hmi_colour("input"), 0);
    lv_obj_set_style_border_width(valueDisplay, 1, 0);

    // Value text (center, sm semibold)
    lv_obj_t *valueText = lv_label_create(valueDisplay);
    lv_obj_remove_style_all(valueText);
    lv_obj_set_style_text_font(valueText, hmi_font(hmi_font_size("fontSizeSm"), 600), 0);
    lv_obj_set_style_text_color(valueText, hmi_colour("foreground"), 0);
    lv_obj_set_style_text_align(valueText, LV_TEXT_ALIGN_CENTER, 0);

    // Unit text (xs, mutedForeground, right side)
    lv_obj_t *unitText = lv_label_create(valueDisplay);
    lv_obj_remove_style_all(unitText);
    lv_obj_set_style_text_font(unitText, hmi_font(hmi_font_size("fontSizeXs"), 400), 0);
    lv_obj_set_style_text_color(unitText, hmi_colour("mutedForeground"), 0);

    // Plus button
    lv_obj_t *plusBtn = create_outline_button(row);
    lv_obj_t *plusLbl = lv_obj_get_child(plusBtn, 0);
    lv_label_set_text(plusLbl, "+");

    shnuminput_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->label = label;
    st->minusBtn = minusBtn;
    st->valueDisplay = valueDisplay;
    st->valueText = valueText;
    st->unitText = unitText;
    st->plusBtn = plusBtn;
    st->value = hmi_widget_num(w, "value", 0);
    st->minValue = hmi_widget_num(w, "minValue", 0);
    st->maxValue = hmi_widget_num(w, "maxValue", 1000);
    st->step = hmi_widget_num(w, "step", 1);
    st->decimalPlaces = (int)hmi_widget_num(w, "decimalPlaces", 0);
    strncpy(st->unit, hmi_widget_str(w, "unit", ""), sizeof(st->unit) - 1);

    // Set label visibility
    const char *lbl = hmi_widget_str(w, "label", "");
    lv_label_set_text(st->label, lbl);
    if (lbl[0] == '\0') {
        lv_obj_add_flag(label, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_clear_flag(label, LV_OBJ_FLAG_HIDDEN);
    }

    update_value_text(st);

    // Set unit visibility
    if (st->unit[0] != '\0') {
        lv_obj_clear_flag(unitText, LV_OBJ_FLAG_HIDDEN);
        // Position unit text on the right side of value display
        lv_obj_align(unitText, LV_ALIGN_RIGHT_MID, -8, 0);
    } else {
        lv_obj_add_flag(unitText, LV_OBJ_FLAG_HIDDEN);
    }

    // Position value text centered
    lv_obj_align(valueText, LV_ALIGN_LEFT_MID, 8, 0);

    // Click handlers
    lv_obj_add_event_cb(minusBtn, btn_click_cb, LV_EVENT_CLICKED, w);
    lv_obj_add_event_cb(plusBtn, btn_click_cb, LV_EVENT_CLICKED, w);

    w->state = st;
    return bg;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    shnuminput_state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "value") == 0) {
        st->value = hmi_value_as_num(value, st->value);
        st->value = fmax(st->minValue, fmin(st->maxValue, st->value));
        update_value_text(st);
    } else if (strcmp(prop, "minValue") == 0) {
        st->minValue = hmi_value_as_num(value, st->minValue);
    } else if (strcmp(prop, "maxValue") == 0) {
        st->maxValue = hmi_value_as_num(value, st->maxValue);
    } else if (strcmp(prop, "step") == 0) {
        st->step = hmi_value_as_num(value, st->step);
    } else if (strcmp(prop, "unit") == 0) {
        strncpy(st->unit, hmi_value_as_str(value, ""), sizeof(st->unit) - 1);
        if (st->unit[0] != '\0') {
            lv_obj_clear_flag(st->unitText, LV_OBJ_FLAG_HIDDEN);
            lv_obj_align(st->unitText, LV_ALIGN_RIGHT_MID, -8, 0);
        } else {
            lv_obj_add_flag(st->unitText, LV_OBJ_FLAG_HIDDEN);
        }
    } else if (strcmp(prop, "label") == 0) {
        const char *lbl = hmi_value_as_str(value, "");
        lv_label_set_text(st->label, lbl);
        if (lbl[0] == '\0') {
            lv_obj_add_flag(st->label, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_clear_flag(st->label, LV_OBJ_FLAG_HIDDEN);
        }
    } else if (strcmp(prop, "decimalPlaces") == 0) {
        st->decimalPlaces = (int)hmi_value_as_num(value, st->decimalPlaces);
        update_value_text(st);
    }
}

static void destroy(hmi_widget_t *w)
{
    shnuminput_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_shnuminput = {"ShNumInput", create, set_prop, destroy};