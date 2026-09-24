// widgets/w_text.c -- kit widget Text (Basic, "Text").
//
// Spec: ui/qml/Shadcn/Text.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): text, fontSize, bold, color, horizontalAlignment, verticalAlignment, wrapMode, opacity, visible.
// Default size 140x32. Signals: none.
#include <string.h>

#include "registry.h"
#include "theme.h"

typedef struct {
    lv_obj_t *label;
    lv_text_align_t align;
    int font_size;
    int font_weight;
} text_state_t;

static lv_text_align_t parse_align(const char *s)
{
    if (strstr(s, "AlignRight")) return LV_TEXT_ALIGN_RIGHT;
    if (strstr(s, "AlignHCenter") || strstr(s, "Center")) return LV_TEXT_ALIGN_CENTER;
    return LV_TEXT_ALIGN_LEFT;
}

static lv_label_long_mode_t parse_wrap(const char *s)
{
    if (strcmp(s, "Text.NoWrap") == 0) return LV_LABEL_LONG_CLIP;
    if (strcmp(s, "Text.WordWrap") == 0) return LV_LABEL_LONG_WRAP;
    if (strcmp(s, "Text.Wrap") == 0) return LV_LABEL_LONG_WRAP;
    if (strcmp(s, "Text.WrapAnywhere") == 0) return LV_LABEL_LONG_WRAP;
    return LV_LABEL_LONG_CLIP;
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *label = lv_label_create(parent);
    lv_obj_remove_style_all(label);
    lv_obj_set_style_bg_opa(label, LV_OPA_TRANSP, 0);
    // Prevent LVGL from setting any default text padding
    lv_obj_set_style_pad_left(label, 0, 0);
    lv_obj_set_style_pad_right(label, 0, 0);
    lv_obj_set_style_pad_top(label, 0, 0);
    lv_obj_set_style_pad_bottom(label, 0, 0);

    text_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->label = label;
    st->align = LV_TEXT_ALIGN_LEFT;
    st->font_size = 14;
    st->font_weight = 400;

    // Apply all properties from the model
    const char *text = hmi_widget_str(w, "text", "");
    lv_label_set_text(label, text);

    int fs = (int)hmi_widget_num(w, "fontSize", 14);
    bool bold = hmi_widget_bool(w, "bold", false);
    int weight = bold ? 700 : 400;
    lv_obj_set_style_text_font(label, hmi_font(fs, weight), 0);
    
    st->font_size = fs;
    st->font_weight = weight;

    const char *color = hmi_widget_str(w, "color", "");
    if (color && *color) {
        lv_opa_t opa = 255;
        lv_color_t c = hmi_colour_hex(color, &opa);
        lv_obj_set_style_text_color(label, c, 0);
        lv_obj_set_style_text_opa(label, opa, 0);
    }

    const char *halign = hmi_widget_str(w, "horizontalAlignment", "Text.AlignLeft");
    st->align = parse_align(halign);
    lv_obj_set_style_text_align(label, st->align, 0);

    const char *valign = hmi_widget_str(w, "verticalAlignment", "");
    (void)valign;

    const char *wrap = hmi_widget_str(w, "wrapMode", "Text.NoWrap");
    lv_label_set_long_mode(label, parse_wrap(wrap));

    w->state = st;
    return label;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    text_state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "text") == 0) {
        lv_label_set_text(st->label, hmi_value_as_str(value, ""));
    } else if (strcmp(prop, "fontSize") == 0) {
        int fs = (int)hmi_value_as_num(value, 14);
        int weight = st->font_weight;
        lv_obj_set_style_text_font(st->label, hmi_font(fs, weight), 0);
        st->font_size = fs;
    } else if (strcmp(prop, "bold") == 0) {
        bool b = hmi_value_as_bool(value, false);
        int weight = b ? 700 : 400;
        lv_obj_set_style_text_font(st->label, hmi_font(st->font_size, weight), 0);
        st->font_weight = weight;
    } else if (strcmp(prop, "color") == 0) {
        const char *color = hmi_value_as_str(value, "");
        if (color && *color) {
            lv_opa_t opa = 255;
            lv_color_t c = hmi_colour_hex(color, &opa);
            lv_obj_set_style_text_color(st->label, c, 0);
            lv_obj_set_style_text_opa(st->label, opa, 0);
        }
    } else if (strcmp(prop, "horizontalAlignment") == 0) {
        const char *s = hmi_value_as_str(value, "Text.AlignLeft");
        st->align = parse_align(s);
        lv_obj_set_style_text_align(st->label, st->align, 0);
    } else if (strcmp(prop, "wrapMode") == 0) {
        const char *s = hmi_value_as_str(value, "Text.NoWrap");
        lv_label_set_long_mode(st->label, parse_wrap(s));
    }
}

static void destroy(hmi_widget_t *w)
{
    text_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_text = {"Text", create, set_prop, destroy};