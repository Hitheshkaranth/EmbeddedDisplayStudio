// widgets/w_shlabel.c -- kit widget ShLabel (Shadcn, "Label").
//
// Spec: ui/qml/Shadcn/ShLabel.qml (the QML component is the drawing and
// behaviour specification). Extends QtQuick Text. Properties: text, fontSize,
// bold, color, horizontalAlignment, verticalAlignment, wrapMode, opacity, visible.
// Default size varies. Signals: none.
// Owner: W3.
#include <string.h>
#include "registry.h"
#include "theme.h"

typedef struct {
    lv_obj_t *label;
    lv_text_align_t align;
    int font_size;
    int font_weight;
} shlabel_state_t;

static lv_text_align_t shlabel_parse_align(const char *s)
{
    if (strstr(s, "AlignRight")) return LV_TEXT_ALIGN_RIGHT;
    if (strstr(s, "AlignHCenter") || strstr(s, "Center")) return LV_TEXT_ALIGN_CENTER;
    return LV_TEXT_ALIGN_LEFT;
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *label = lv_label_create(parent);
    lv_obj_remove_style_all(label);
    lv_obj_set_style_bg_opa(label, LV_OPA_TRANSP, 0);

    shlabel_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->label = label;
    st->align = LV_TEXT_ALIGN_LEFT;
    st->font_size = 14;
    st->font_weight = 500;

    lv_label_set_text(label, hmi_widget_str(w, "text", ""));

    int fs = (int)hmi_widget_num(w, "fontSize", 14);
    bool bold = hmi_widget_bool(w, "bold", false);
    int weight = bold ? 700 : 500;  // ShLabel default weight is Medium (500)
    lv_obj_set_style_text_font(label, hmi_font(fs, weight), 0);
    lv_obj_set_style_text_color(label, hmi_colour("foreground"), 0);

    st->align = shlabel_parse_align(hmi_widget_str(w, "horizontalAlignment", "Text.AlignLeft"));
    lv_obj_set_style_text_align(label, st->align, 0);

    st->font_size = fs;
    st->font_weight = weight;

    w->state = st;
    return label;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    shlabel_state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "text") == 0) {
        lv_label_set_text(st->label, hmi_value_as_str(value, ""));
    } else if (strcmp(prop, "fontSize") == 0) {
        int fs = (int)hmi_value_as_num(value, 14);
        lv_obj_set_style_text_font(st->label, hmi_font(fs, st->font_weight), 0);
        st->font_size = fs;
    } else if (strcmp(prop, "bold") == 0) {
        bool b = hmi_value_as_bool(value, false);
        int weight = b ? 700 : 500;
        lv_obj_set_style_text_font(st->label, hmi_font(st->font_size, weight), 0);
        st->font_weight = weight;
    } else if (strcmp(prop, "color") == 0) {
        const char *color = hmi_value_as_str(value, "");
        if (color && *color) {
            lv_opa_t opa = 255;
            lv_color_t c = hmi_colour_hex(color, &opa);
            lv_obj_set_style_text_color(st->label, c, 0);
        }
    } else if (strcmp(prop, "horizontalAlignment") == 0) {
        const char *s = hmi_value_as_str(value, "Text.AlignLeft");
        st->align = shlabel_parse_align(s);
        lv_obj_set_style_text_align(st->label, st->align, 0);
    }
}

static void destroy(hmi_widget_t *w)
{
    shlabel_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_shlabel = {"ShLabel", create, set_prop, destroy};