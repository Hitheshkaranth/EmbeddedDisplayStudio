// widgets/w_shcard.c -- kit widget ShCard (Containers, "Card").
//
// Spec: ui/qml/Shadcn/ShCard.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): color, borderColor, borderWidth, radius, opacity, visible.
// Default size 260x180. Signals: none.
// Owner: W3.
#include <string.h>
#include "registry.h"
#include "theme.h"

typedef struct {
    lv_obj_t *card;
} shcard_state_t;

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    (void)w;
    lv_obj_t *card = lv_obj_create(parent);
    lv_obj_remove_style_all(card);

    shcard_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->card = card;

    // Apply color
    const char *color = hmi_widget_str(w, "color", "");
    if (color && *color) {
        lv_opa_t opa = 255;
        lv_color_t c = hmi_colour_hex(color, &opa);
        lv_obj_set_style_bg_color(card, c, 0);
        lv_obj_set_style_bg_opa(card, opa, 0);
    } else {
        lv_obj_set_style_bg_color(card, hmi_colour("card"), 0);
        lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
    }

    // Apply radius
    int radius = (int)hmi_widget_num(w, "radius", 10);
    lv_obj_set_style_radius(card, radius, 0);

    // Apply border
    const char *bc = hmi_widget_str(w, "borderColor", "");
    int bw = (int)hmi_widget_num(w, "borderWidth", 1);
    if (bc && *bc && bw > 0) {
        lv_opa_t opa = 255;
        lv_color_t c = hmi_colour_hex(bc, &opa);
        lv_obj_set_style_border_color(card, c, 0);
        lv_obj_set_style_border_opa(card, opa, 0);
        lv_obj_set_style_border_width(card, bw, 0);
    } else {
        lv_obj_set_style_border_color(card, hmi_colour("border"), 0);
        lv_obj_set_style_border_opa(card, LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(card, 1, 0);
    }

    w->state = st;
    return card;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    shcard_state_t *st = w->state;
    if (!st) return;
    lv_obj_t *card = st->card;

    if (strcmp(prop, "color") == 0) {
        const char *color = hmi_value_as_str(value, "");
        if (color && *color) {
            lv_opa_t opa = 255;
            lv_color_t c = hmi_colour_hex(color, &opa);
            lv_obj_set_style_bg_color(card, c, 0);
            lv_obj_set_style_bg_opa(card, opa, 0);
        }
    } else if (strcmp(prop, "radius") == 0) {
        lv_obj_set_style_radius(card, (int)hmi_value_as_num(value, 10), 0);
    } else if (strcmp(prop, "borderColor") == 0) {
        const char *bc = hmi_value_as_str(value, "");
        int bw = (int)hmi_widget_num(w, "borderWidth", 1);
        if (bc && *bc && bw > 0) {
            lv_opa_t opa = 255;
            lv_color_t c = hmi_colour_hex(bc, &opa);
            lv_obj_set_style_border_color(card, c, 0);
            lv_obj_set_style_border_opa(card, opa, 0);
        }
    } else if (strcmp(prop, "borderWidth") == 0) {
        int bw = (int)hmi_value_as_num(value, 1);
        lv_obj_set_style_border_width(card, bw, 0);
    }
}

static void destroy(hmi_widget_t *w)
{
    shcard_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_shcard = {"ShCard", create, set_prop, destroy};