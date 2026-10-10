// widgets/w_shannunciator.c -- kit widget ShAnnunciator (Avionics, "Annunciator").
//
// Spec: ui/qml/Shadcn/ShAnnunciator.qml -- a caption lamp: lit or unlit,
// at one of three alert levels (advisory/caution/warning).
// Style options (off by default): litColor -- the lamp's colour instead of
// the severity's (a SCADA screen's bright green); glow -- when lit, a soft
// outer glow of that colour (draw_util.h hmi_set_glow, ~8 px).
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    lv_obj_t *bg, *text;
    char text_str[128];
    char severity[16];
    char lit_colour[16];
    bool lit, glow;
} state_t;

static lv_color_t annunciator_color(const char *severity)
{
    if (strcmp(severity, "warning") == 0) return hmi_colour("efisWarning");
    if (strcmp(severity, "advisory") == 0) return hmi_colour("efisNormal");
    return hmi_colour("efisCaution");
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    lv_color_t col = annunciator_color(st->severity);
    lv_opa_t lit_opa = LV_OPA_COVER;
    if (st->lit_colour[0] == '#') {
        lv_color_t c = hmi_colour_hex(st->lit_colour, &lit_opa);
        if (lit_opa > 0) col = c;
    }

    /* Background rect */
    lv_obj_set_style_bg_color(st->bg, st->lit ? col : hmi_colour("efisPanel"), 0);
    lv_obj_set_style_bg_opa(st->bg, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(st->bg, col, 0);
    lv_obj_set_style_border_width(st->bg, 1, 0);
    lv_obj_set_style_radius(st->bg, hmi_radius("radiusSm"), 0);
    lv_obj_set_style_opa(st->bg, st->lit ? LV_OPA_COVER : (lv_opa_t)(0.35 * 255), 0);
    hmi_set_glow(st->bg, col, st->lit && st->glow ? HMI_GLOW_OPA : 0);

    /* Text */
    lv_label_set_text(st->text, st->text_str);
    lv_obj_set_style_text_font(st->text, hmi_font(hmi_font_size("fontSizeSm"), 600), 0);
    lv_obj_set_style_text_color(st->text, st->lit ? hmi_colour("efisPanel") : col, 0);
    lv_obj_set_style_opa(st->text, st->lit ? LV_OPA_COVER : (lv_opa_t)(0.75 * 255), 0);
    lv_obj_center(st->text);
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *bg = lv_obj_create(parent);
    lv_obj_remove_style_all(bg);
    lv_obj_set_size(bg, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(bg, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *text = lv_label_create(bg);
    lv_obj_remove_style_all(text);
    lv_label_set_long_mode(text, LV_LABEL_LONG_CLIP);

    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;
    st->bg = bg;
    st->text = text;

    snprintf(st->text_str, sizeof st->text_str, "%s", hmi_widget_str(w, "text", "CAPTION"));
    snprintf(st->severity, sizeof st->severity, "%s", hmi_widget_str(w, "severity", "caution"));
    st->lit = hmi_widget_bool(w, "lit", true);
    snprintf(st->lit_colour, sizeof st->lit_colour, "%s", hmi_widget_str(w, "litColor", ""));
    st->glow = hmi_widget_bool(w, "glow", false);

    layout(w);
    return bg;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "text") == 0) {
        snprintf(st->text_str, sizeof st->text_str, "%s", hmi_value_as_str(value, ""));
        layout(w);
    } else if (strcmp(prop, "severity") == 0) {
        snprintf(st->severity, sizeof st->severity, "%s", hmi_value_as_str(value, "caution"));
        layout(w);
    } else if (strcmp(prop, "lit") == 0) {
        st->lit = hmi_value_as_bool(value, st->lit);
        layout(w);
    } else if (strcmp(prop, "litColor") == 0) {
        snprintf(st->lit_colour, sizeof st->lit_colour, "%s", hmi_value_as_str(value, ""));
        layout(w);
    } else if (strcmp(prop, "glow") == 0) {
        st->glow = hmi_value_as_bool(value, false);
        layout(w);
    }
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shannunciator = {"ShAnnunciator", create, set_prop, destroy};