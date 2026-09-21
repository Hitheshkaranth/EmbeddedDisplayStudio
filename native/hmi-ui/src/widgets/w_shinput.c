// widgets/w_shinput.c -- kit widget ShInput (Basic, "Input Field").
//
// Spec: ui/qml/Shadcn/ShInput.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): placeholderText, text, enabled, readOnly, opacity, visible.
// Default size 180x40. Signals: none.
// Owner: W3 (wave 2).
#include <string.h>

#include "draw_util.h"
#include "registry.h"
#include "theme.h"

typedef struct {
    lv_obj_t *bg;
    lv_obj_t *text;
    lv_obj_t *placeholder;
    char placeholder_text[256];
    bool has_text;
} shinput_state_t;

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *bg = lv_obj_create(parent);
    lv_obj_remove_style_all(bg);
    lv_obj_set_size(bg, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(bg, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(bg, lv_color_hex(0x000000), 0);
    lv_obj_set_style_bg_opa(bg, LV_OPA_TRANSP, 0);
    lv_obj_set_style_radius(bg, hmi_radius("radiusMd"), 0);
    lv_obj_set_style_border_color(bg, hmi_colour("input"), 0);
    lv_obj_set_style_border_width(bg, 1, 0);

    // Text label (actual text) - positioned with margins and vertically centered
    lv_obj_t *text = lv_label_create(bg);
    lv_obj_remove_style_all(text);
    lv_obj_set_style_text_font(text, hmi_font(hmi_font_size("fontSizeSm"), 400), 0);
    lv_obj_set_style_text_color(text, hmi_colour("foreground"), 0);
    lv_label_set_long_mode(text, LV_LABEL_LONG_CLIP);

    // Placeholder label - same positioning
    lv_obj_t *placeholder = lv_label_create(bg);
    lv_obj_remove_style_all(placeholder);
    lv_obj_set_style_text_font(placeholder, hmi_font(hmi_font_size("fontSizeSm"), 400), 0);
    lv_obj_set_style_text_color(placeholder, hmi_colour("mutedForeground"), 0);
    lv_label_set_long_mode(placeholder, LV_LABEL_LONG_CLIP);

    shinput_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->bg = bg;
    st->text = text;
    st->placeholder = placeholder;
    strncpy(st->placeholder_text, hmi_widget_str(w, "placeholderText", ""), sizeof(st->placeholder_text) - 1);
    st->has_text = false;

    const char *txt = hmi_widget_str(w, "text", "");
    lv_label_set_text(text, txt);
    if (txt[0] != '\0') {
        st->has_text = true;
        lv_obj_add_flag(placeholder, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_clear_flag(placeholder, LV_OBJ_FLAG_HIDDEN);
    }

    // Position text/placeholder: leftMargin=12, verticalCenter
    lv_obj_update_layout(bg);
    int W = (int)lv_obj_get_width(bg);
    int H = (int)lv_obj_get_height(bg);
    int margin = 12; // Theme.spacing12
    lv_obj_set_pos(text, margin, (H - lv_font_get_line_height(hmi_font(hmi_font_size("fontSizeSm"), 400))) / 2);
    lv_obj_set_width(text, W - 2 * margin);

    lv_obj_set_pos(placeholder, margin, (H - lv_font_get_line_height(hmi_font(hmi_font_size("fontSizeSm"), 400))) / 2);
    lv_obj_set_width(placeholder, W - 2 * margin);

    w->state = st;
    return bg;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    shinput_state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "text") == 0) {
        const char *txt = hmi_value_as_str(value, "");
        lv_label_set_text(st->text, txt);
        if (txt[0] != '\0') {
            st->has_text = true;
            lv_obj_add_flag(st->placeholder, LV_OBJ_FLAG_HIDDEN);
        } else {
            st->has_text = false;
            lv_obj_clear_flag(st->placeholder, LV_OBJ_FLAG_HIDDEN);
        }
    } else if (strcmp(prop, "placeholderText") == 0) {
        strncpy(st->placeholder_text, hmi_value_as_str(value, ""), sizeof(st->placeholder_text) - 1);
        lv_label_set_text(st->placeholder, st->placeholder_text);
    }
}

static void destroy(hmi_widget_t *w)
{
    shinput_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_shinput = {"ShInput", create, set_prop, destroy};