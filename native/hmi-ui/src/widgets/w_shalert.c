// widgets/w_shalert.c -- kit widget ShAlert (Industrial, "Alarm Indicator").
//
// Spec: ui/qml/Shadcn/ShAlert.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): title, description, variant, opacity, visible.
// Default size 260x90. Signals: none.
// Owner: W3 (wave 2).
#include <string.h>

#include "draw_util.h"
#include "registry.h"
#include "theme.h"

typedef struct {
    lv_obj_t *bg;
    lv_obj_t *title;
    lv_obj_t *description;
    char variant[16];
} shalert_state_t;

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *bg = lv_obj_create(parent);
    lv_obj_remove_style_all(bg);
    lv_obj_set_size(bg, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(bg, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(bg, lv_color_hex(0x000000), 0);
    lv_obj_set_style_bg_opa(bg, LV_OPA_TRANSP, 0);
    lv_obj_set_style_radius(bg, hmi_radius("radiusLg"), 0);

    // Border color depends on variant
    lv_obj_t *title = lv_label_create(bg);
    lv_obj_remove_style_all(title);
    lv_obj_set_style_text_font(title, hmi_font(hmi_font_size("fontSizeSm"), 500), 0);
    lv_label_set_long_mode(title, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(title, lv_pct(100));

    lv_obj_t *description = lv_label_create(bg);
    lv_obj_remove_style_all(description);
    lv_obj_set_style_text_font(description, hmi_font(hmi_font_size("fontSizeSm"), 400), 0);
    lv_label_set_long_mode(description, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(description, lv_pct(100));

    shalert_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->bg = bg;
    st->title = title;
    st->description = description;
    strncpy(st->variant, hmi_widget_str(w, "variant", "default"), sizeof(st->variant) - 1);

    // Set default text
    lv_label_set_text(title, hmi_widget_str(w, "title", ""));
    lv_label_set_text(description, hmi_widget_str(w, "description", ""));

    // Position texts with margins
    lv_obj_update_layout(bg);
    int H = (int)lv_obj_get_height(bg);
    int W = (int)lv_obj_get_width(bg);
    int margin = 16;  // Theme.spacing16
    int spacing = 4;  // Theme.spacing4

    // Calculate heights of text elements
    lv_obj_set_pos(title, margin, margin);
    lv_obj_set_pos(description, margin, margin + lv_font_get_line_height(hmi_font(hmi_font_size("fontSizeSm"), 500)) + spacing);

    // Color based on variant
    if (strcmp(st->variant, "destructive") == 0) {
        lv_obj_set_style_border_color(bg, hmi_colour("destructive"), 0);
        lv_obj_set_style_border_width(bg, 1, 0);
        lv_obj_set_style_text_color(title, hmi_colour("destructive"), 0);
        lv_obj_set_style_text_color(description, hmi_colour("destructive"), 0);
    } else {
        lv_obj_set_style_border_color(bg, hmi_colour("border"), 0);
        lv_obj_set_style_border_width(bg, 1, 0);
        lv_obj_set_style_text_color(title, hmi_colour("foreground"), 0);
        lv_obj_set_style_text_color(description, hmi_colour("mutedForeground"), 0);
    }

    w->state = st;
    return bg;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    shalert_state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "title") == 0) {
        lv_label_set_text(st->title, hmi_value_as_str(value, ""));
        lv_obj_update_layout(st->bg);
        lv_obj_set_pos(st->description, 16, 16 + lv_font_get_line_height(hmi_font(hmi_font_size("fontSizeSm"), 500)) + 4);
    } else if (strcmp(prop, "description") == 0) {
        lv_label_set_text(st->description, hmi_value_as_str(value, ""));
    } else if (strcmp(prop, "variant") == 0) {
        const char *v = hmi_value_as_str(value, "default");
        strncpy(st->variant, v, sizeof(st->variant) - 1);
        if (strcmp(v, "destructive") == 0) {
            lv_obj_set_style_border_color(st->bg, hmi_colour("destructive"), 0);
            lv_obj_set_style_text_color(st->title, hmi_colour("destructive"), 0);
            lv_obj_set_style_text_color(st->description, hmi_colour("destructive"), 0);
        } else {
            lv_obj_set_style_border_color(st->bg, hmi_colour("border"), 0);
            lv_obj_set_style_text_color(st->title, hmi_colour("foreground"), 0);
            lv_obj_set_style_text_color(st->description, hmi_colour("mutedForeground"), 0);
        }
    }
}

static void destroy(hmi_widget_t *w)
{
    shalert_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_shalert = {"ShAlert", create, set_prop, destroy};