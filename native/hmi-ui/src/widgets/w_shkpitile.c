// widgets/w_shkpitile.c -- kit widget ShKpiTile (Industrial, "KPI tile").
//
// Spec: ui/qml/Shadcn/ShKpiTile.qml -- one tile of a plant dashboard's KPI
// strip:
//     [icon]  Production Rate
//             3,015 tpd
//             Target 3,200 tpd                 94 %
//     [=================================------]
// a rounded tile (tileColor, "" = Theme.card; 1 px Theme.border), an
// optional kit icon at the left (mutedForeground), the title (foreground,
// medium), the value (valueColor, "" = Theme.foreground, bold) with the unit
// beside it on the same baseline (regular, ~72 % of the value), the subtitle
// under them (mutedForeground), and a thin rounded progress bar along the
// bottom (barColor, "" = Theme.success, on Theme.muted) for progress 0..100;
// a negative progress hides it. progressText sits right-aligned just above
// the bar's right end. `value` is a number or a string ("3,015"); decimals
// >= 0 formats a number with toFixed, -1 shows it as given.
//
// Geometry (shared with the QML): padX clamp(round(0.05 W), 6, 14), padY
// clamp(round(0.10 H), 4, 12); bar clamp(round(0.06 H), 3, 8) tall, padY
// above the bottom, with a gap of clamp(round(0.04 H), 2, 6) over it; the
// icon clamp(round(min(0.62 content, 0.20 W)), 12, 56) at padX, centred in
// the content height; the text column after it (gap max(8, round(0.06 W))).
// Fonts: title clamp(round(0.145 H), 8, 18), value clamp(round(0.27 H), 10,
// 40), unit round(0.72 value), subtitle clamp(round(0.125 H), 8, 15), all
// scaled down together when their lines do not fit the content height; the
// lines share the spare height evenly between and around them.
//
// Children of the root, in order: tile background, icon, title, value, unit, subtitle,
// progressText, track (-> fill).
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "draw_util.h"
#include "icons.h"
#include "registry.h"
#include "text_util.h"

typedef struct {
    lv_obj_t *root, *bg, *icon, *title, *value, *unit, *sub, *ptext, *track, *fill;
    hmi_value_t val;
    double progress;
    int decimals;
    char icon_name[64], title_text[96], unit_text[32], sub_text[96], ptext_text[32];
    char value_colour[32], bar_colour[32], tile_colour[32];
} state_t;

static int clampi(double v, int lo, int hi)
{
    int r = (int)lround(v);
    return r < lo ? lo : r > hi ? hi : r;
}

static double as_number(const hmi_value_t *v)
{
    if (!v) return NAN;
    if (v->kind == HMI_V_NUM) return isfinite(v->n) ? v->n : NAN;
    if (v->kind != HMI_V_STR || !v->s) return NAN;
    const char *s = v->s;
    while (*s == ' ') ++s;
    if (!*s) return NAN;
    char *end = NULL;
    double d = strtod(s, &end);
    while (end && *end == ' ') ++end;
    return (end && *end == '\0' && isfinite(d)) ? d : NAN;
}

static void format_value(const state_t *st, char *buf, size_t len)
{
    double n = as_number(&st->val);
    if (st->val.kind == HMI_V_NULL) { snprintf(buf, len, "--"); return; }
    if (st->decimals >= 0 && !isnan(n)) { snprintf(buf, len, "%.*f", st->decimals, n); return; }
    char tmp[64];
    snprintf(buf, len, "%s", hmi_text_of(&st->val, tmp, sizeof tmp, "--"));
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    int Wi = (int)lround(W), Hi = (int)lround(H);
    lv_opa_t opa;

    lv_obj_set_size(st->root, Wi, Hi);
    lv_obj_set_size(st->bg, Wi, Hi);
    lv_color_t tile = hmi_colour_or_token(st->tile_colour, "card", &opa);
    lv_obj_set_style_bg_color(st->bg, tile, 0);
    lv_obj_set_style_bg_opa(st->bg, opa, 0);
    lv_obj_set_style_border_color(st->bg, hmi_colour("border"), 0);
    lv_obj_set_style_border_width(st->bg, 1, 0);
    lv_obj_set_style_radius(st->bg, hmi_radius("radiusSm"), 0);

    int padX = clampi(W * 0.05, 6, 14), padY = clampi(H * 0.10, 4, 12);
    bool bar = st->progress >= 0;
    int barH = clampi(H * 0.06, 3, 8);
    int barY = Hi - padY - barH;
    int top = padY;
    int bottom = bar ? barY - clampi(H * 0.04, 2, 6) : Hi - padY;
    int contentH = bottom - top > 1 ? bottom - top : 1;

    // icon
    bool hasIcon = st->icon_name[0] != '\0';
    int iconSz = hasIcon ? clampi(fmin(contentH * 0.62, W * 0.20), 12, 56) : 0;
    if (hasIcon) {
        hmi_icon_set(st->icon, st->icon_name, iconSz, hmi_colour("mutedForeground"));
        lv_obj_set_pos(st->icon, padX, top + (contentH - iconSz) / 2);
    } else {
        lv_obj_add_flag(st->icon, LV_OBJ_FLAG_HIDDEN);
    }
    int textX = hasIcon ? padX + iconSz + (int)fmax(8, lround(W * 0.06)) : padX;
    int textW = Wi - padX - textX > 1 ? Wi - padX - textX : 1;

    // fonts, scaled down together until the lines fit
    bool hasTitle = st->title_text[0] != '\0', hasSub = st->sub_text[0] != '\0';
    int titlePx = clampi(H * 0.145, 8, 18), valuePx = clampi(H * 0.27, 10, 40), subPx = clampi(H * 0.125, 8, 15);
    for (int guard = 0; guard < 40; ++guard) {
        int stack = (hasTitle ? hmi_text_line_h(titlePx, 500) : 0) + hmi_text_line_h(valuePx, 700)
                  + (hasSub ? hmi_text_line_h(subPx, 400) : 0);
        if (stack <= contentH || (titlePx <= 8 && valuePx <= 10 && subPx <= 8)) break;
        if (valuePx > 10) --valuePx;
        if (guard % 2 == 0 && titlePx > 8) --titlePx;
        if (guard % 2 == 0 && subPx > 8) --subPx;
    }
    int unitPx = (int)fmax(8, lround(valuePx * 0.72));
    int lines = 1 + (hasTitle ? 1 : 0) + (hasSub ? 1 : 0);
    int stack = (hasTitle ? hmi_text_line_h(titlePx, 500) : 0) + hmi_text_line_h(valuePx, 700)
              + (hasSub ? hmi_text_line_h(subPx, 400) : 0);
    double gap = fmax(0, (contentH - stack) / (double)(lines + 1));
    double y = top + gap;

    if (hasTitle) {
        hmi_text_place(st->title, st->title_text, titlePx, 500, 0.75, textX, (int)lround(y), textW,
                       hmi_colour("foreground"), LV_OPA_COVER, LV_TEXT_ALIGN_LEFT);
        y += hmi_text_line_h(titlePx, 500) + gap;
    } else {
        lv_obj_add_flag(st->title, LV_OBJ_FLAG_HIDDEN);
    }

    // value + unit on one baseline; the value shrinks first, then elides
    char text[96];
    format_value(st, text, sizeof text);
    bool hasUnit = st->unit_text[0] != '\0';
    int unitGap = hasUnit ? (int)fmax(3, lround(valuePx * 0.22)) : 0;
    int unitW = hasUnit ? hmi_text_w(st->unit_text, unitPx, 400) + 1 : 0;
    if (unitW > textW / 2) unitW = textW / 2;
    int valueSlot = textW - unitGap - unitW;
    if (valueSlot < 1) valueSlot = 1;
    lv_color_t vc = hmi_colour_or_token(st->value_colour, "foreground", &opa);
    int vTop = (int)lround(y);
    int vp = hmi_text_place(st->value, text, valuePx, 700, 0.6, textX, vTop, valueSlot, vc, opa, LV_TEXT_ALIGN_LEFT);
    int vw = hmi_text_w(text, vp, 700);
    if (vw > valueSlot) vw = valueSlot;
    lv_obj_set_width(st->value, vw + 1);
    if (hasUnit) {
        // the unit's baseline is the value's nominal one
        int uTop = vTop + hmi_text_ascent(valuePx, 700) - hmi_text_ascent(unitPx, 400);
        hmi_text_place(st->unit, st->unit_text, unitPx, 400, 0.75, textX + vw + unitGap, uTop, unitW, vc, opa,
                       LV_TEXT_ALIGN_LEFT);
    } else {
        lv_obj_add_flag(st->unit, LV_OBJ_FLAG_HIDDEN);
    }
    y += hmi_text_line_h(valuePx, 700) + gap;

    // subtitle and progress text share the last line (above the bar)
    bool hasPText = st->ptext_text[0] != '\0';
    int ptW = hasPText ? hmi_text_w(st->ptext_text, subPx, 500) + 2 : 0;
    int subTop = hasSub ? (int)lround(y) : bottom - hmi_text_line_h(subPx, 400);
    if (hasSub) {
        int sw = textW - (hasPText ? ptW + 6 : 0);
        hmi_text_place(st->sub, st->sub_text, subPx, 400, 0.75, textX, subTop, sw > 1 ? sw : 1,
                       hmi_colour("mutedForeground"), LV_OPA_COVER, LV_TEXT_ALIGN_LEFT);
    } else {
        lv_obj_add_flag(st->sub, LV_OBJ_FLAG_HIDDEN);
    }
    if (hasPText) {
        if (ptW > Wi - 2 * padX) ptW = Wi - 2 * padX;
        hmi_text_place(st->ptext, st->ptext_text, subPx, 500, 0.75, Wi - padX - ptW, subTop, ptW,
                       hmi_colour("foreground"), LV_OPA_COVER, LV_TEXT_ALIGN_RIGHT);
    } else {
        lv_obj_add_flag(st->ptext, LV_OBJ_FLAG_HIDDEN);
    }

    // progress bar
    if (bar) {
        int trackW = Wi - 2 * padX > 1 ? Wi - 2 * padX : 1;
        lv_obj_set_pos(st->track, padX, barY);
        lv_obj_set_size(st->track, trackW, barH);
        lv_obj_set_style_radius(st->track, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_bg_color(st->track, hmi_colour("muted"), 0);
        lv_obj_set_style_bg_opa(st->track, LV_OPA_COVER, 0);
        double p = st->progress > 100 ? 100 : st->progress;
        int fw = (int)lround(trackW * p / 100.0);
        lv_color_t bc = hmi_colour_or_token(st->bar_colour, "success", &opa);
        lv_obj_set_pos(st->fill, 0, 0);
        lv_obj_set_size(st->fill, fw, barH);
        lv_obj_set_style_radius(st->fill, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_bg_color(st->fill, bc, 0);
        lv_obj_set_style_bg_opa(st->fill, opa, 0);
        if (fw > 0) lv_obj_remove_flag(st->fill, LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(st->fill, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(st->track, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(st->track, LV_OBJ_FLAG_HIDDEN);
    }
}

static lv_obj_t *plain(lv_obj_t *parent)
{
    lv_obj_t *o = lv_obj_create(parent);
    lv_obj_remove_style_all(o);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_CLICKABLE);
    return o;
}

static void copy_text(char *dst, size_t n, const hmi_value_t *v)
{
    char tmp[64];
    snprintf(dst, n, "%s", hmi_text_of(v, tmp, sizeof tmp, ""));
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *root = plain(parent);
    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;
    st->root = root;
    st->bg = plain(root);   // the tile itself; a border on root would offset the children
    st->icon = hmi_icon_create(root, "", 16, hmi_colour("mutedForeground"));
    st->title = hmi_make_label(root, 14, 500, hmi_colour("foreground"), "");
    st->value = hmi_make_label(root, 26, 700, hmi_colour("foreground"), "");
    st->unit = hmi_make_label(root, 18, 400, hmi_colour("foreground"), "");
    st->sub = hmi_make_label(root, 12, 400, hmi_colour("mutedForeground"), "");
    st->ptext = hmi_make_label(root, 12, 500, hmi_colour("foreground"), "");
    st->track = plain(root);
    st->fill = plain(st->track);

    st->val = hmi_value_copy(hmi_widget_get(w, "value"));
    st->decimals = (int)hmi_widget_num(w, "decimals", -1);
    st->progress = hmi_widget_num(w, "progress", -1);
    copy_text(st->icon_name, sizeof st->icon_name, hmi_widget_get(w, "icon"));
    copy_text(st->title_text, sizeof st->title_text, hmi_widget_get(w, "title"));
    copy_text(st->unit_text, sizeof st->unit_text, hmi_widget_get(w, "unit"));
    copy_text(st->sub_text, sizeof st->sub_text, hmi_widget_get(w, "subtitle"));
    copy_text(st->ptext_text, sizeof st->ptext_text, hmi_widget_get(w, "progressText"));
    copy_text(st->value_colour, sizeof st->value_colour, hmi_widget_get(w, "valueColor"));
    copy_text(st->bar_colour, sizeof st->bar_colour, hmi_widget_get(w, "barColor"));
    copy_text(st->tile_colour, sizeof st->tile_colour, hmi_widget_get(w, "tileColor"));
    layout(w);
    return root;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "value") == 0) {
        hmi_value_free(&st->val);
        st->val = value ? hmi_value_copy(value) : hmi_value_null();
    } else if (strcmp(prop, "decimals") == 0) st->decimals = (int)hmi_value_as_num(value, st->decimals);
    else if (strcmp(prop, "progress") == 0) st->progress = hmi_value_as_num(value, st->progress);
    else if (strcmp(prop, "icon") == 0) copy_text(st->icon_name, sizeof st->icon_name, value);
    else if (strcmp(prop, "title") == 0) copy_text(st->title_text, sizeof st->title_text, value);
    else if (strcmp(prop, "unit") == 0) copy_text(st->unit_text, sizeof st->unit_text, value);
    else if (strcmp(prop, "subtitle") == 0) copy_text(st->sub_text, sizeof st->sub_text, value);
    else if (strcmp(prop, "progressText") == 0) copy_text(st->ptext_text, sizeof st->ptext_text, value);
    else if (strcmp(prop, "valueColor") == 0) copy_text(st->value_colour, sizeof st->value_colour, value);
    else if (strcmp(prop, "barColor") == 0) copy_text(st->bar_colour, sizeof st->bar_colour, value);
    else if (strcmp(prop, "tileColor") == 0) copy_text(st->tile_colour, sizeof st->tile_colour, value);
    else return;
    layout(w);
}

static void destroy(hmi_widget_t *w)
{
    state_t *st = w->state;
    if (!st) return;
    hmi_value_free(&st->val);
    lv_free(st);
    w->state = NULL;
}

const hmi_widget_ops_t hmi_widget_shkpitile = {"ShKpiTile", create, set_prop, destroy};
