// widgets/w_rectangle.c -- kit widget Rectangle (Basic, "Rectangle").
//
// Spec: ui/qml/Shadcn/Rectangle.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): color, borderColor, borderWidth, radius, opacity, visible.
// Default size 140x90. Signals: none.
#include <string.h>

#include "registry.h"
#include "theme.h"

typedef struct {
    lv_obj_t *rect;
} rectangle_state_t;

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *rect = lv_obj_create(parent);
    lv_obj_remove_style_all(rect);

    rectangle_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->rect = rect;

    // Apply color
    const char *color = hmi_widget_str(w, "color", "");
    if (color && *color) {
        lv_opa_t opa = 255;
        lv_color_t c = hmi_colour_hex(color, &opa);
        lv_obj_set_style_bg_color(rect, c, 0);
        lv_obj_set_style_bg_opa(rect, opa, 0);
    } else {
        lv_obj_set_style_bg_opa(rect, LV_OPA_TRANSP, 0);
    }

    // Apply radius
    int radius = (int)hmi_widget_num(w, "radius", 6);
    lv_obj_set_style_radius(rect, radius, 0);

    // Apply border
    const char *border_color = hmi_widget_str(w, "borderColor", "");
    int border_width = (int)hmi_widget_num(w, "borderWidth", 0);
    if (border_color && *border_color && border_width > 0) {
        lv_opa_t opa = 255;
        lv_color_t c = hmi_colour_hex(border_color, &opa);
        lv_obj_set_style_border_color(rect, c, 0);
        lv_obj_set_style_border_opa(rect, opa, 0);
        lv_obj_set_style_border_width(rect, border_width, 0);
    } else {
        lv_obj_set_style_border_width(rect, 0, 0);
    }

    w->state = st;
    return rect;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    rectangle_state_t *st = w->state;
    if (!st) return;
    lv_obj_t *rect = st->rect;

    if (strcmp(prop, "color") == 0) {
        const char *color = hmi_value_as_str(value, "");
        if (color && *color) {
            lv_opa_t opa = 255;
            lv_color_t c = hmi_colour_hex(color, &opa);
            lv_obj_set_style_bg_color(rect, c, 0);
            lv_obj_set_style_bg_opa(rect, opa, 0);
        } else {
            lv_obj_set_style_bg_opa(rect, LV_OPA_TRANSP, 0);
        }
    } else if (strcmp(prop, "radius") == 0) {
        lv_obj_set_style_radius(rect, (int)hmi_value_as_num(value, 6), 0);
    } else if (strcmp(prop, "borderColor") == 0) {
        const char *border_color = hmi_value_as_str(value, "");
        int bw = (int)hmi_widget_num(w, "borderWidth", 0);
        if (border_color && *border_color && bw > 0) {
            lv_opa_t opa = 255;
            lv_color_t c = hmi_colour_hex(border_color, &opa);
            lv_obj_set_style_border_color(rect, c, 0);
            lv_obj_set_style_border_opa(rect, opa, 0);
        } else {
            lv_obj_set_style_border_width(rect, 0, 0);
        }
    } else if (strcmp(prop, "borderWidth") == 0) {
        int bw = (int)hmi_value_as_num(value, 0);
        if (bw > 0) {
            const char *bc = hmi_widget_str(w, "borderColor", "");
            if (bc && *bc) {
                lv_opa_t opa = 255;
                lv_color_t c = hmi_colour_hex(bc, &opa);
                lv_obj_set_style_border_color(rect, c, 0);
                lv_obj_set_style_border_opa(rect, opa, 0);
            }
            lv_obj_set_style_border_width(rect, bw, 0);
        } else {
            lv_obj_set_style_border_width(rect, 0, 0);
        }
    }
}

static void destroy(hmi_widget_t *w)
{
    rectangle_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_rectangle = {"Rectangle", create, set_prop, destroy};