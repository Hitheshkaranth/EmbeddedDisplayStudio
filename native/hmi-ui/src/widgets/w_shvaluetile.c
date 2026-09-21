// widgets/w_shvaluetile.c -- kit widget ShValueTile (Industrial, "Value Tile").
// Spec: ui/qml/Shadcn/ShValueTile.qml on ShCard: card (Theme.card,
// radiusXl, 1 px border), content inset 16; a Column (spacing 8) with a
// row of the label (sm medium, mutedForeground) and a badge (pill, 20 px,
// xs semibold, state text upper-cased, variant by state) at the right,
// then the value (xxxl semibold, foreground) with the unit (sm, muted)
// 4 px after it, bottoms aligned.
#include <ctype.h>
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    char state[16];
    lv_obj_t *face, *label, *badge, *badgeText, *value, *unit;
} state_t;

static void badge_colours(const char *state, lv_color_t *bg, lv_color_t *fg)
{
    if (strcmp(state, "ok") == 0) { *bg = hmi_colour("success"); *fg = hmi_colour("successForeground"); }
    else if (strcmp(state, "warn") == 0) { *bg = hmi_colour("warning"); *fg = hmi_colour("warningForeground"); }
    else if (strcmp(state, "fault") == 0) { *bg = hmi_colour("destructive"); *fg = hmi_colour("destructiveForeground"); }
    else { *bg = hmi_colour("secondary"); *fg = hmi_colour("secondaryForeground"); }
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width);
    const int inset = 16, spacing = 8;
    char upper[16];
    size_t n = strlen(st->state);
    for (size_t i = 0; i < n && i < sizeof upper - 1; ++i) upper[i] = (char)toupper((unsigned char)st->state[i]);
    upper[n < sizeof upper - 1 ? n : sizeof upper - 1] = '\0';
    lv_label_set_text(st->badgeText, upper);
    lv_color_t bg, fg;
    badge_colours(st->state, &bg, &fg);
    lv_obj_set_style_bg_color(st->badge, bg, 0);
    lv_obj_set_style_text_color(st->badgeText, fg, 0);
    lv_obj_update_layout(st->badgeText);
    int badgeW = lv_obj_get_width(st->badgeText) + 20;
    lv_obj_set_size(st->badge, badgeW, 20);
    lv_obj_set_pos(st->badge, (int)W - inset - badgeW, inset);
    lv_obj_center(st->badgeText);

    lv_label_set_text(st->label, hmi_widget_str(w, "label", ""));
    lv_obj_set_width(st->label, (int)fmax(10, W - 2 * inset - badgeW));
    lv_obj_set_pos(st->label, inset, inset + (20 - lv_font_get_line_height(hmi_font(14, 500))) / 2);

    int rowY = inset + 20 + spacing;
    lv_label_set_text(st->value, hmi_widget_str(w, "value", "--"));
    lv_label_set_text(st->unit, hmi_widget_str(w, "unit", ""));
    lv_obj_update_layout(st->value);
    int valueW = lv_obj_get_width(st->value);
    int valueH = lv_font_get_line_height(hmi_font(30, 600));
    int unitH = lv_font_get_line_height(hmi_font(14, 400));
    lv_obj_set_pos(st->value, inset, rowY);
    lv_obj_set_pos(st->unit, inset + valueW + 4, rowY + valueH - unitH - 4);
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *face = lv_obj_create(parent);
    lv_obj_remove_style_all(face);
    lv_obj_set_size(face, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(face, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(face, hmi_colour("card"), 0);
    lv_obj_set_style_bg_opa(face, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(face, hmi_colour("border"), 0);
    lv_obj_set_style_border_width(face, 1, 0);
    lv_obj_set_style_radius(face, hmi_radius("radiusXl"), 0);
    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;
    st->face = face;
    st->label = hmi_make_label(face, hmi_font_size("fontSizeSm"), 500, hmi_colour("mutedForeground"), "");
    st->badge = lv_obj_create(face);
    lv_obj_remove_style_all(st->badge);
    lv_obj_set_style_radius(st->badge, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(st->badge, LV_OPA_COVER, 0);
    st->badgeText = hmi_make_label(st->badge, hmi_font_size("fontSizeXs"), 600, hmi_colour("foreground"), "");
    st->value = hmi_make_label(face, hmi_font_size("fontSizeXxxl"), 600, hmi_colour("foreground"), "");
    st->unit = hmi_make_label(face, hmi_font_size("fontSizeSm"), 400, hmi_colour("mutedForeground"), "");
    snprintf(st->state, sizeof st->state, "%s", hmi_widget_str(w, "state", "idle"));
    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "state") == 0) { snprintf(st->state, sizeof st->state, "%s", hmi_value_as_str(value, st->state)); layout(w); }
    else if (strcmp(prop, "value") == 0) {
        layout(w);
        if (value->kind == HMI_V_NUM) lv_label_set_text(st->value, hmi_value_debug(value));
        else lv_label_set_text(st->value, hmi_value_as_str(value, "--"));
        lv_obj_update_layout(st->value);
        lv_obj_set_pos(st->unit, 16 + lv_obj_get_width(st->value) + 4, lv_obj_get_y(st->unit));
    }
    else if (strcmp(prop, "label") == 0) { layout(w); lv_label_set_text(st->label, hmi_value_as_str(value, "")); }
    else if (strcmp(prop, "unit") == 0) { layout(w); lv_label_set_text(st->unit, hmi_value_as_str(value, "")); }
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shvaluetile = {"ShValueTile", create, set_prop, destroy};
