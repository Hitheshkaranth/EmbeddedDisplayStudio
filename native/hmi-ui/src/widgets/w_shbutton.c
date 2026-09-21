// widgets/w_shbutton.c -- kit widget ShButton (Basic, "Button").
//
// Spec: ui/qml/Shadcn/ShButton.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): text, variant, size, enabled, backgroundColor, textColor, borderColor, borderWidth, cornerRadius, opacity, visible.
// Default size 120x40. Signals: clicked.
// Owner: W3.
#include <string.h>
#include "registry.h"
#include "theme.h"

typedef struct {
    lv_obj_t *bg;
    lv_obj_t *label;
    char variant[16];
} shbutton_state_t;

static void apply_variant_colors(shbutton_state_t *st, const char *variant)
{
    lv_color_t bg_color, text_color;
    lv_opa_t text_opa = 255;

    if (strcmp(variant, "default") == 0) {
        bg_color = hmi_colour("primary");
        text_color = hmi_colour("primaryForeground");
    } else if (strcmp(variant, "secondary") == 0) {
        bg_color = hmi_colour("secondary");
        text_color = hmi_colour("secondaryForeground");
    } else if (strcmp(variant, "destructive") == 0) {
        bg_color = hmi_colour("destructive");
        text_color = hmi_colour("destructiveForeground");
    } else if (strcmp(variant, "outline") == 0) {
        bg_color = lv_color_hex(0x000000); // will be transparent below
        lv_obj_set_style_bg_opa(st->bg, LV_OPA_TRANSP, 0);
        lv_obj_set_style_border_color(st->bg, hmi_colour("border"), 0);
        lv_obj_set_style_border_width(st->bg, 1, 0);
        text_color = hmi_colour("foreground");
    } else if (strcmp(variant, "ghost") == 0) {
        lv_obj_set_style_bg_opa(st->bg, LV_OPA_TRANSP, 0);
        text_color = hmi_colour("foreground");
    } else {
        bg_color = hmi_colour("primary");
        text_color = hmi_colour("primaryForeground");
    }

    if (strcmp(variant, "outline") != 0 && strcmp(variant, "ghost") != 0) {
        lv_obj_set_style_bg_opa(st->bg, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(st->bg, bg_color, 0);
    } else {
        lv_obj_set_style_bg_color(st->bg, bg_color, 0);
    }

    lv_obj_set_style_text_color(st->label, text_color, 0);
}

static void shbutton_clicked_cb(lv_event_t *e)
{
    hmi_widget_t *widget = (hmi_widget_t *)lv_event_get_user_data(e);
    if (widget) hmi_widget_emit(widget, "clicked", NULL);
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *bg = lv_obj_create(parent);
    lv_obj_remove_style_all(bg);
    lv_obj_set_style_radius(bg, hmi_radius("md"), 0);
    lv_obj_set_style_bg_opa(bg, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(bg, lv_color_hex(0x000000), 0);

    lv_obj_t *label = lv_label_create(bg);
    lv_obj_remove_style_all(label);
    lv_label_set_text(label, hmi_widget_str(w, "text", ""));
    lv_obj_set_style_text_font(label, hmi_font(14, 500), 0);
    lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_bg_opa(label, LV_OPA_TRANSP, 0);

    // Center the label inside the button
    lv_obj_set_flex_flow(bg, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(bg, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_all(bg, 8, 0);

    shbutton_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->bg = bg;
    st->label = label;
    strncpy(st->variant, hmi_widget_str(w, "variant", "default"), sizeof(st->variant) - 1);

    apply_variant_colors(st, st->variant);

    // Click signal
    lv_obj_add_event_cb(bg, shbutton_clicked_cb, LV_EVENT_CLICKED, w);

    w->state = st;
    return bg;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    shbutton_state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "text") == 0) {
        lv_label_set_text(st->label, hmi_value_as_str(value, ""));
    } else if (strcmp(prop, "variant") == 0) {
        const char *v = hmi_value_as_str(value, "default");
        strncpy(st->variant, v, sizeof(st->variant) - 1);
        apply_variant_colors(st, st->variant);
    }
}

static void destroy(hmi_widget_t *w)
{
    shbutton_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_shbutton = {"ShButton", create, set_prop, destroy};