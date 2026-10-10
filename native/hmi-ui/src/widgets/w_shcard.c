// widgets/w_shcard.c -- kit widget ShCard (Containers, "Card").
//
// Spec: ui/qml/Shadcn/ShCard.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): color, borderColor,
// borderWidth, radius, headerHeight, headerColor, gradient, opacity, visible.
// Default size 260x180. Signals: none.
//
// Style options (all off by default, so a card without them is drawn as it
// always was):
//   headerHeight > 0  a title band across the top headerHeight px: filled with
//                     headerColor ("" = the card colour lighter by
//                     HEADER_SHADE %), inside the border, with the card's top
//                     corner radius and square bottom corners, its last row a
//                     1 px divider in the border colour.
//   gradient          the fill runs from the card colour lighter by
//                     GRADIENT_SHADE % at the top to the card colour at the
//                     bottom.
// The band is a clip box (the card's first child, transparent, header-high,
// inside the border) holding the fill -- taller than the box by the radius so
// its bottom corners are cut off square -- and the divider. Children the
// design puts in the card come after it, so they draw over the band.
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"
#include "theme.h"

#define HEADER_SHADE 12.0
#define GRADIENT_SHADE 6.0

typedef struct {
    lv_obj_t *card;
    lv_obj_t *band_clip, *band, *divider;
    char colour[32], border[32], header[32];
    int border_width, radius, header_height;
    bool gradient;
} shcard_state_t;

static lv_color_t card_colour(const shcard_state_t *st, lv_opa_t *opa)
{
    if (st->colour[0]) return hmi_colour_hex(st->colour, opa);
    *opa = LV_OPA_COVER;
    return hmi_colour("card");
}

static void apply(shcard_state_t *st)
{
    lv_obj_t *card = st->card;
    lv_opa_t opa = LV_OPA_COVER;
    lv_color_t fill = card_colour(st, &opa);
    lv_obj_set_style_bg_opa(card, opa, 0);
    if (st->gradient) {
        lv_obj_set_style_bg_color(card, hmi_shade(fill, GRADIENT_SHADE), 0);
        lv_obj_set_style_bg_grad_color(card, fill, 0);
        lv_obj_set_style_bg_grad_dir(card, LV_GRAD_DIR_VER, 0);
    } else {
        lv_obj_set_style_bg_color(card, fill, 0);
        lv_obj_set_style_bg_grad_dir(card, LV_GRAD_DIR_NONE, 0);
    }

    lv_obj_set_style_radius(card, st->radius, 0);

    // Border: borderWidth px (QML border.width) in the set colour, or the
    // theme's border colour when none is set.
    lv_color_t bc = hmi_colour("border");
    lv_opa_t bopa = LV_OPA_COVER;
    int bw = st->border_width > 0 ? st->border_width : 0;
    if (st->border[0]) bc = hmi_colour_hex(st->border, &bopa);
    lv_obj_set_style_border_color(card, bc, 0);
    lv_obj_set_style_border_opa(card, bopa, 0);
    lv_obj_set_style_border_width(card, bw, 0);

    // The title band.
    int band_h = st->header_height - bw;   // inside the top border
    if (st->header_height <= 0 || band_h <= 0) {
        lv_obj_add_flag(st->band_clip, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    int inner_r = st->radius - bw > 0 ? st->radius - bw : 0;
    lv_obj_remove_flag(st->band_clip, LV_OBJ_FLAG_HIDDEN);
    // Positions are relative to the card's content box, i.e. inside the border.
    lv_obj_set_pos(st->band_clip, 0, 0);
    lv_obj_set_size(st->band_clip, LV_PCT(100), band_h);
    lv_opa_t hopa = LV_OPA_COVER;
    lv_color_t hc = st->header[0] ? hmi_colour_hex(st->header, &hopa) : hmi_shade(fill, HEADER_SHADE);
    if (!st->header[0]) hopa = opa;
    lv_obj_set_style_bg_color(st->band, hc, 0);
    lv_obj_set_style_bg_opa(st->band, hopa, 0);
    lv_obj_set_style_radius(st->band, inner_r, 0);
    lv_obj_set_pos(st->band, 0, 0);
    lv_obj_set_size(st->band, LV_PCT(100), band_h + inner_r);
    lv_obj_set_style_bg_color(st->divider, bc, 0);
    lv_obj_set_style_bg_opa(st->divider, bopa, 0);
    lv_obj_set_pos(st->divider, 0, band_h - 1);
    lv_obj_set_size(st->divider, LV_PCT(100), 1);
}

static lv_obj_t *plain(lv_obj_t *parent)
{
    lv_obj_t *o = lv_obj_create(parent);
    lv_obj_remove_style_all(o);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_CLICKABLE);
    return o;
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *card = lv_obj_create(parent);
    lv_obj_remove_style_all(card);

    shcard_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->card = card;
    // The band's clip box clips its children to itself (no OVERFLOW_VISIBLE).
    st->band_clip = plain(card);
    st->band = plain(st->band_clip);
    st->divider = plain(st->band_clip);
    lv_obj_add_flag(st->band_clip, LV_OBJ_FLAG_HIDDEN);

    snprintf(st->colour, sizeof st->colour, "%s", hmi_widget_str(w, "color", ""));
    snprintf(st->border, sizeof st->border, "%s", hmi_widget_str(w, "borderColor", ""));
    snprintf(st->header, sizeof st->header, "%s", hmi_widget_str(w, "headerColor", ""));
    st->border_width = (int)hmi_widget_num(w, "borderWidth", 1);
    st->radius = (int)hmi_widget_num(w, "radius", 10);
    st->header_height = (int)hmi_widget_num(w, "headerHeight", 0);
    st->gradient = hmi_widget_bool(w, "gradient", false);
    apply(st);

    w->state = st;
    return card;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    shcard_state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "color") == 0) {
        // An empty colour keeps the one the card has (as before).
        const char *c = hmi_value_as_str(value, "");
        if (c && *c) snprintf(st->colour, sizeof st->colour, "%s", c);
    } else if (strcmp(prop, "radius") == 0) {
        st->radius = (int)hmi_value_as_num(value, 10);
    } else if (strcmp(prop, "borderColor") == 0) {
        const char *c = hmi_value_as_str(value, "");
        if (c && *c) snprintf(st->border, sizeof st->border, "%s", c);
    } else if (strcmp(prop, "borderWidth") == 0) {
        st->border_width = (int)hmi_value_as_num(value, 1);
    } else if (strcmp(prop, "headerHeight") == 0) {
        st->header_height = (int)hmi_value_as_num(value, 0);
    } else if (strcmp(prop, "headerColor") == 0) {
        snprintf(st->header, sizeof st->header, "%s", hmi_value_as_str(value, ""));
    } else if (strcmp(prop, "gradient") == 0) {
        st->gradient = hmi_value_as_bool(value, false);
    } else {
        return;
    }
    apply(st);
}

static void destroy(hmi_widget_t *w)
{
    shcard_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_shcard = {"ShCard", create, set_prop, destroy};
