// widgets/w_shicontile.c -- kit widget ShIconTile (Automotive, "Icon Tile").
//
// Spec: ui/qml/Shadcn/ShIconTile.qml -- a rounded tile with a line icon and
// a caption under it. ``active`` gives the accent border and glow; pressing
// fires ``clicked()``.
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "icons.h"
#include "registry.h"

typedef struct {
    lv_obj_t *glow, *tile, *icon, *label;
    char icon_name[64];
    char label_text[64];
    bool active;
} state_t;

static void shicontile_clicked_cb(lv_event_t *e)
{
    hmi_widget_t *w = (hmi_widget_t *)lv_event_get_user_data(e);
    if (w) hmi_widget_emit(w, "clicked", NULL);
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    int tileH = (int)round(H * 0.72);
    int radius = (int)round(W * 0.18);
    int iconSz = (int)round(W * 0.42);
    int margin = 4;

    /* Glow: tile-size + 8 */
    int gw = (int)W + 2 * margin, gh = tileH + 2 * margin;
    lv_obj_set_size(st->glow, gw, gh);
    lv_obj_set_style_radius(st->glow, radius + 4, 0);
    lv_obj_set_style_bg_color(st->glow, hmi_colour("autoAccent"), 0);
    lv_obj_set_style_bg_opa(st->glow, st->active ? (lv_opa_t)(0.20 * 255) : 0, 0);
    lv_obj_set_pos(st->glow, -margin, -margin);
    if (st->active) lv_obj_remove_flag(st->glow, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(st->glow, LV_OBJ_FLAG_HIDDEN);

    /* Tile */
    lv_obj_set_size(st->tile, (int32_t)W, tileH);
    lv_obj_set_style_radius(st->tile, radius, 0);
    lv_obj_set_style_bg_color(st->tile, hmi_colour("autoTileBg"), 0);
    lv_obj_set_style_bg_opa(st->tile, LV_OPA_COVER, 0);
    if (st->active) {
        lv_obj_set_style_border_color(st->tile, hmi_colour("autoAccent"), 0);
        lv_obj_set_style_border_width(st->tile, 2, 0);
    } else {
        lv_obj_set_style_border_color(st->tile, hmi_colour("autoTileBorder"), 0);
        lv_obj_set_style_border_width(st->tile, 1, 0);
    }
    lv_obj_set_pos(st->tile, 0, 0);

    /* Icon */
    hmi_icon_set(st->icon, st->icon_name, iconSz, hmi_colour("autoText"));
    lv_obj_set_pos(st->icon, (int)W / 2 - iconSz / 2, tileH / 2 - iconSz / 2);

    /* Label */
    lv_label_set_text(st->label, st->label_text);
    int labelFs = hmi_px_min(H * 0.14, 8);
    lv_obj_set_style_text_font(st->label, hmi_font(labelFs, 500), 0);
    lv_obj_set_style_text_color(st->label, hmi_colour("autoText"), 0);
    lv_obj_set_style_text_align(st->label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_pos(st->label, 0, tileH + (int)round(H * 0.04));
    lv_obj_set_width(st->label, (int32_t)W);

    if (st->label_text[0]) lv_obj_remove_flag(st->label, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(st->label, LV_OBJ_FLAG_HIDDEN);
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *root = lv_obj_create(parent);
    lv_obj_remove_style_all(root);
    lv_obj_set_size(root, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(root, LV_OBJ_FLAG_SCROLLABLE);

    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;

    st->glow = lv_obj_create(root);
    lv_obj_remove_style_all(st->glow);
    lv_obj_remove_flag(st->glow, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(st->glow, LV_OBJ_FLAG_HIDDEN);

    st->tile = lv_obj_create(root);
    lv_obj_remove_style_all(st->tile);
    lv_obj_remove_flag(st->tile, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(st->tile, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(st->tile, shicontile_clicked_cb, LV_EVENT_CLICKED, w);

    st->icon = hmi_icon_create(root, "", 16, hmi_colour("autoText"));

    st->label = lv_label_create(root);
    lv_obj_remove_style_all(st->label);
    lv_label_set_long_mode(st->label, LV_LABEL_LONG_CLIP);

    snprintf(st->icon_name, sizeof st->icon_name, "%s", hmi_widget_str(w, "icon", "phone"));
    snprintf(st->label_text, sizeof st->label_text, "%s", hmi_widget_str(w, "label", "BT"));
    st->active = hmi_widget_bool(w, "active", false);

    layout(w);
    return root;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "icon") == 0) {
        snprintf(st->icon_name, sizeof st->icon_name, "%s", hmi_value_as_str(value, ""));
        layout(w);
    } else if (strcmp(prop, "label") == 0) {
        snprintf(st->label_text, sizeof st->label_text, "%s", hmi_value_as_str(value, ""));
        layout(w);
    } else if (strcmp(prop, "active") == 0) {
        st->active = hmi_value_as_bool(value, st->active);
        layout(w);
    }
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shicontile = {"ShIconTile", create, set_prop, destroy};