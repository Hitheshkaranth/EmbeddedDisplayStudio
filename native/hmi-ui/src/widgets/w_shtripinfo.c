// widgets/w_shtripinfo.c -- kit widget ShTripInfo (Automotive, "Trip Info").
// Spec: ui/qml/Shadcn/ShTripInfo.qml: a tile (autoTileBg at 60 %, 1 px
// autoTileBorder, radius round(0.08 h)), the title top-left (muted,
// 0.15 h), then up to two rows of height round(0.3 h): label left
// (autoLine 0.16 h), value right-aligned (autoText semibold 0.2 h), unit
// after it (muted 0.14 h), a 1 px separator above the second row.
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    lv_obj_t *face, *title;
    lv_obj_t *label[2], *value[2], *unit[2], *sep;
    char text[7][64];   // title, l1, v1, u1, l2, v2, u2
} state_t;

static const char *keys[7] = {"title", "row1Label", "row1Value", "row1Unit", "row2Label", "row2Value", "row2Unit"};

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    int pad = (int)round(H * 0.1);
    int titleFs = hmi_px_min(H * 0.15, 7), labelFs = hmi_px_min(H * 0.16, 7);
    int valueFs = hmi_px_min(H * 0.2, 7), unitFs = hmi_px_min(H * 0.14, 7);
    int rowH = (int)round(H * 0.3);

    lv_label_set_text(st->title, st->text[0]);
    lv_obj_set_style_text_font(st->title, hmi_font(titleFs, 400), 0);
    bool titleVisible = st->text[0][0] != '\0';
    lv_obj_set_pos(st->title, pad, pad + 1);
    if (titleVisible) lv_obj_remove_flag(st->title, LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(st->title, LV_OBJ_FLAG_HIDDEN);
    int titleH = titleVisible ? lv_font_get_line_height(hmi_font(titleFs, 400)) : 0;
    int y = titleVisible ? pad + titleH + (int)round(H * 0.04) : pad;
    int rowW = (int)(W - 2 * pad);
    lv_obj_add_flag(st->sep, LV_OBJ_FLAG_HIDDEN);
    for (int r = 0; r < 2; ++r) {
        const char *l = st->text[1 + r * 3], *v = st->text[2 + r * 3], *u = st->text[3 + r * 3];
        bool visible = l[0] || v[0];
        lv_obj_t *objs[3] = {st->label[r], st->value[r], st->unit[r]};
        for (int i = 0; i < 3; ++i) {
            if (visible) lv_obj_remove_flag(objs[i], LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(objs[i], LV_OBJ_FLAG_HIDDEN);
        }
        if (!visible) continue;
        if (r == 1) {   // separator above the second row
            lv_obj_set_size(st->sep, rowW, 1);
            lv_obj_set_pos(st->sep, pad, y);
            lv_obj_remove_flag(st->sep, LV_OBJ_FLAG_HIDDEN);
        }
        lv_label_set_text(st->label[r], l);
        lv_obj_set_style_text_font(st->label[r], hmi_font(labelFs, 400), 0);
        lv_obj_set_pos(st->label[r], pad, y + rowH / 2 - lv_font_get_line_height(hmi_font(labelFs, 400)) / 2 + 1);
        lv_label_set_text(st->unit[r], u);
        lv_obj_set_style_text_font(st->unit[r], hmi_font(unitFs, 400), 0);
        lv_obj_update_layout(st->unit[r]);
        int unitW = u[0] ? lv_obj_get_width(st->unit[r]) : 0;
        int labelW = lv_obj_get_width(st->label[r]);
        if (u[0]) lv_obj_remove_flag(st->unit[r], LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(st->unit[r], LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text(st->value[r], v);
        lv_obj_set_style_text_font(st->value[r], hmi_font(valueFs, 600), 0);
        int valueW = (int)fmax(10, rowW - labelW - unitW - 12);
        lv_obj_set_width(st->value[r], valueW);
        lv_obj_set_style_text_align(st->value[r], LV_TEXT_ALIGN_RIGHT, 0);
        int valueH = lv_font_get_line_height(hmi_font(valueFs, 600));
        int valueRight = pad + rowW - (u[0] ? unitW + 4 : 0);
        lv_obj_set_pos(st->value[r], valueRight - valueW, y + rowH / 2 - valueH / 2 + 1);
        // unit on the value's baseline: approximate by aligning bottoms
        int unitH = lv_font_get_line_height(hmi_font(unitFs, 400));
        lv_obj_set_pos(st->unit[r], pad + rowW - unitW, y + rowH / 2 - valueH / 2 + (valueH - unitH));
        y += rowH;
    }
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *face = lv_obj_create(parent);
    lv_obj_remove_style_all(face);
    lv_obj_set_size(face, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(face, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(face, hmi_colour("autoTileBg"), 0);
    lv_obj_set_style_bg_opa(face, (lv_opa_t)(0.6 * 255), 0);
    lv_obj_set_style_border_color(face, hmi_colour("autoTileBorder"), 0);
    lv_obj_set_style_border_width(face, 1, 0);
    lv_obj_set_style_radius(face, (int)round(fmax(1, w->height) * 0.08), 0);
    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;
    st->face = face;
    st->title = hmi_make_label(face, 12, 400, hmi_colour("autoMuted"), "");
    st->sep = lv_obj_create(face);
    lv_obj_remove_style_all(st->sep);
    lv_obj_set_style_bg_color(st->sep, hmi_colour("autoTileBorder"), 0);
    lv_obj_set_style_bg_opa(st->sep, LV_OPA_COVER, 0);
    for (int r = 0; r < 2; ++r) {
        st->label[r] = hmi_make_label(face, 12, 400, hmi_colour("autoLine"), "");
        st->value[r] = hmi_make_label(face, 12, 600, hmi_colour("autoText"), "");
        st->unit[r] = hmi_make_label(face, 12, 400, hmi_colour("autoMuted"), "");
    }
    for (int i = 0; i < 7; ++i)
        snprintf(st->text[i], sizeof st->text[i], "%s", hmi_widget_str(w, keys[i], ""));
    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    for (int i = 0; i < 7; ++i) {
        if (strcmp(prop, keys[i]) == 0) {
            if (value->kind == HMI_V_NUM) snprintf(st->text[i], sizeof st->text[i], "%s", hmi_value_debug(value));
            else snprintf(st->text[i], sizeof st->text[i], "%s", hmi_value_as_str(value, ""));
            layout(w);
            return;
        }
    }
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shtripinfo = {"ShTripInfo", create, set_prop, destroy};
