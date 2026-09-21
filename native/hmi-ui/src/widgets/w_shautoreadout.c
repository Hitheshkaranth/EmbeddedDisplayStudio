// widgets/w_shautoreadout.c -- kit widget ShAutoReadout (Automotive, "Readout").
// Spec: ui/qml/Shadcn/ShAutoReadout.qml: an icon slot on the `iconSide`
// (round(0.6 h) + round(0.15 h) wide; the icon itself is wave 2), and a
// block vertically centred in the rest: the caption (label, muted 0.2 h)
// above the reading -- value.toFixed(decimals) (autoText semibold 0.5 h,
// right-aligned unless the icon is left) with the unit after it (muted
// 0.28 h). warnBelow / warnAbove turn the number autoRed.
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "icons.h"
#include "registry.h"

typedef struct {
    double value, warnBelow, warnAbove;
    int decimals;
    lv_obj_t *face, *caption, *number, *unit, *icon;
} state_t;

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    bool warns = (st->warnBelow != 0 && st->value < st->warnBelow) || (st->warnAbove != 0 && st->value > st->warnAbove);
    const char *icon = hmi_widget_str(w, "icon", "");
    bool iconLeft = strcmp(hmi_widget_str(w, "iconSide", "right"), "left") == 0;
    int iconSlot = icon[0] ? (int)(round(H * 0.6) + round(H * 0.15)) : 0;
    int glyph = (int)round(H * 0.6);
    hmi_icon_set(st->icon, icon, glyph, warns ? hmi_colour("autoRed") : hmi_colour("autoLine"));
    lv_obj_set_pos(st->icon, iconLeft ? 0 : (int)W - glyph, (int)round(H / 2 - glyph / 2.0));
    int blockX = iconLeft ? iconSlot : 0;
    int blockW = (int)fmax(1, W - iconSlot);

    const char *label = hmi_widget_str(w, "label", "");
    int capFs = hmi_px_min(H * 0.2, 7), numFs = hmi_px_min(H * 0.5, 8), unitFs = hmi_px_min(H * 0.28, 7);
    lv_label_set_text(st->caption, label);
    lv_obj_set_style_text_font(st->caption, hmi_font(capFs, 400), 0);
    int capH = label[0] ? lv_font_get_line_height(hmi_font(capFs, 400)) : 0;
    if (label[0]) lv_obj_remove_flag(st->caption, LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(st->caption, LV_OBJ_FLAG_HIDDEN);

    lv_label_set_text_fmt(st->number, "%.*f", st->decimals, st->value);
    lv_obj_set_style_text_font(st->number, hmi_font(numFs, 600), 0);
    lv_obj_set_style_text_color(st->number, warns ? hmi_colour("autoRed") : hmi_colour("autoText"), 0);
    const char *unit = hmi_widget_str(w, "unit", "");
    lv_label_set_text(st->unit, unit);
    lv_obj_set_style_text_font(st->unit, hmi_font(unitFs, 400), 0);
    if (unit[0]) lv_obj_remove_flag(st->unit, LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(st->unit, LV_OBJ_FLAG_HIDDEN);
    lv_obj_update_layout(st->unit);
    int unitW = unit[0] ? lv_obj_get_width(st->unit) : 0;
    int numH = lv_font_get_line_height(hmi_font(numFs, 600));
    int unitH = lv_font_get_line_height(hmi_font(unitFs, 400));
    int blockH = capH + numH;
    int top = (int)round(H / 2 - blockH / 2.0);
    lv_obj_set_pos(st->caption, blockX, top);
    int numW = (int)fmax(10, blockW - unitW - 3);
    lv_obj_set_width(st->number, numW);
    lv_obj_set_style_text_align(st->number, iconLeft ? LV_TEXT_ALIGN_LEFT : LV_TEXT_ALIGN_RIGHT, 0);
    lv_obj_set_pos(st->number, blockX, top + capH);
    // unit on the number's baseline (approximate: bottoms aligned, 1 px up)
    lv_obj_set_pos(st->unit, blockX + numW + 3, top + capH + (numH - unitH) - 1);
}

static void read_model(hmi_widget_t *w)
{
    state_t *st = w->state;
    st->value = hmi_widget_num(w, "value", 0);
    st->decimals = (int)hmi_widget_num(w, "decimals", 0);
    st->warnBelow = hmi_widget_num(w, "warnBelow", 0);
    st->warnAbove = hmi_widget_num(w, "warnAbove", 0);
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *face = lv_obj_create(parent);
    lv_obj_remove_style_all(face);
    lv_obj_set_size(face, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(face, LV_OBJ_FLAG_SCROLLABLE);
    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;
    st->face = face;
    st->caption = hmi_make_label(face, 12, 400, hmi_colour("autoMuted"), "");
    st->number = hmi_make_label(face, 20, 600, hmi_colour("autoText"), "");
    st->unit = hmi_make_label(face, 12, 400, hmi_colour("autoMuted"), "");
    st->icon = hmi_icon_create(face, "", 16, hmi_colour("autoLine"));
    read_model(w);
    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "value") == 0) st->value = hmi_value_as_num(value, st->value);
    else if (strcmp(prop, "decimals") == 0) st->decimals = (int)hmi_value_as_num(value, st->decimals);
    else if (strcmp(prop, "warnBelow") == 0) st->warnBelow = hmi_value_as_num(value, st->warnBelow);
    else if (strcmp(prop, "warnAbove") == 0) st->warnAbove = hmi_value_as_num(value, st->warnAbove);
    else if (strcmp(prop, "unit") == 0) { lv_label_set_text(st->unit, hmi_value_as_str(value, "")); }
    else if (strcmp(prop, "label") != 0 && strcmp(prop, "icon") != 0 && strcmp(prop, "iconSide") != 0) return;
    layout(w);
    if (strcmp(prop, "unit") == 0) {   // a bound unit is not in the model: re-apply it after layout
        lv_label_set_text(st->unit, hmi_value_as_str(value, ""));
        if (hmi_value_as_str(value, "")[0]) lv_obj_remove_flag(st->unit, LV_OBJ_FLAG_HIDDEN);
    }
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shautoreadout = {"ShAutoReadout", create, set_prop, destroy};
