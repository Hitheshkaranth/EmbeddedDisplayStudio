// widgets/w_shselect.c -- kit widget ShSelect (Industrial, "Dropdown").
//
// Spec: ui/qml/Shadcn/ShSelect.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): currentIndex, placeholder, label, options, enabled, opacity, visible.
// Default size 200x56. Signals: activated.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"
#include "theme.h"

typedef struct {
    lv_obj_t *label;
    lv_obj_t *dropdown;
    lv_obj_t *indicator;
    int current_index;
    char options[256];
    char placeholder[64];
    char last_text[128];
    int n_options;
} shselect_state_t;

static void dropdown_event_cb(lv_event_t *e)
{
    hmi_widget_t *widget = (hmi_widget_t *)lv_event_get_user_data(e);
    if (!widget) return;
    shselect_state_t *st = widget->state;
    if (!st) return;
    int idx = (int)lv_dropdown_get_selected(st->dropdown);
    st->current_index = idx;
    hmi_value_t val = hmi_value_num((double)idx);
    hmi_widget_emit(widget, "activated", &val);
    hmi_value_free(&val);
}

static void update_dropdown_text(shselect_state_t *st)
{
    if (st->current_index >= 0 && st->current_index < st->n_options) {
        // Extract the option at the current index
        char text[256];
        char *copy = strdup(st->options);
        char *token = strtok(copy, ",");
        int i = 0;
        while (token && i < st->current_index) {
            token = strtok(NULL, ",");
            i++;
        }
        if (token) {
            // Trim whitespace
            while (*token == ' ') token++;
            char *end = token + strlen(token) - 1;
            while (end > token && *end == ' ') { *end = '\0'; end--; }
            strncpy(st->last_text, token, sizeof(st->last_text) - 1);
        } else {
            strncpy(st->last_text, st->placeholder, sizeof(st->last_text) - 1);
        }
        free(copy);
    } else {
        strncpy(st->last_text, st->placeholder, sizeof(st->last_text) - 1);
    }
    lv_dropdown_set_selected(st->dropdown, st->current_index >= 0 ? st->current_index : 0);
    lv_label_set_text(st->indicator, st->current_index >= 0 && st->current_index < st->n_options ? "\u25BC" : "\u25BC");
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *bg = lv_obj_create(parent);
    lv_obj_remove_style_all(bg);
    lv_obj_set_size(bg, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(bg, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(bg, lv_color_hex(0x000000), 0);
    lv_obj_set_style_bg_opa(bg, LV_OPA_TRANSP, 0);

    // Column layout with 4px spacing
    lv_obj_set_flex_flow(bg, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_all(bg, 0, 0);
    lv_obj_set_style_pad_gap(bg, 4, 0);
    lv_obj_set_size(bg, lv_pct(100), lv_pct(100));

    // Optional label (xs)
    lv_obj_t *label = hmi_make_label(bg, hmi_font_size("fontSizeXs"), 400, hmi_colour("foreground"), "");
    lv_obj_set_flex_grow(label, 0);

    // Dropdown container
    lv_obj_t *dropdown = lv_dropdown_create(bg);
    lv_obj_remove_style_all(dropdown);
    lv_obj_set_style_bg_color(dropdown, hmi_colour("background"), 0);
    lv_obj_set_style_bg_opa(dropdown, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(dropdown, hmi_radius("radiusMd"), 0);
    lv_obj_set_style_border_color(dropdown, hmi_colour("input"), 0);
    lv_obj_set_style_border_width(dropdown, 1, 0);
    lv_obj_set_style_pad_all(dropdown, 0, 0);
    lv_obj_set_style_pad_gap(dropdown, 0, 0);
    lv_obj_set_width(dropdown, lv_pct(100));
    lv_obj_set_height(dropdown, 36);

    // Text color for content item
    lv_obj_set_style_text_color(dropdown, hmi_colour("foreground"), LV_PART_MAIN);
    lv_obj_set_style_text_font(dropdown, hmi_font(hmi_font_size("fontSizeSm"), 400), LV_PART_MAIN);
    lv_obj_set_style_pad_left(dropdown, hmi_font_size("fontSizeXs") * 3, LV_PART_MAIN);
    lv_obj_set_style_pad_right(dropdown, 30, LV_PART_MAIN);

    // Indicator arrow
    lv_obj_t *indicator = lv_label_create(dropdown);
    lv_obj_remove_style_all(indicator);
    lv_obj_set_style_text_font(indicator, hmi_font(10, 400), 0);
    lv_obj_set_style_text_color(indicator, hmi_colour("mutedForeground"), 0);
    lv_label_set_text(indicator, "\u25BC");
    lv_obj_align(indicator, LV_ALIGN_RIGHT_MID, -10, 0);

    shselect_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->label = label;
    st->dropdown = dropdown;
    st->indicator = indicator;
    st->current_index = (int)hmi_widget_num(w, "currentIndex", 0);
    strncpy(st->placeholder, hmi_widget_str(w, "placeholder", "Select..."), sizeof(st->placeholder) - 1);
    strncpy(st->options, hmi_widget_str(w, "options", ""), sizeof(st->options) - 1);

    // Parse options and set dropdown menu
    int n_opts = 0;
    char *copy = strdup(st->options);
    char *token = strtok(copy, ",");
    char menu_str[512] = "";
    while (token) {
        // Trim whitespace
        while (*token == ' ') token++;
        char *end = token + strlen(token) - 1;
        while (end > token && *end == ' ') { *end = '\0'; end--; }
        if (strlen(token) > 0) {
            if (n_opts > 0) strncat(menu_str, "\n", sizeof(menu_str) - strlen(menu_str) - 1);
            strncat(menu_str, token, sizeof(menu_str) - strlen(menu_str) - 1);
            n_opts++;
        }
        token = strtok(NULL, ",");
    }
    free(copy);
    st->n_options = n_opts;

    if (n_opts > 0) {
        lv_dropdown_set_options(dropdown, menu_str);
    } else {
        lv_dropdown_set_options(dropdown, st->placeholder);
    }

    lv_dropdown_set_selected(dropdown, st->current_index >= 0 && st->current_index < n_opts ? st->current_index : 0);

    // Update label visibility
    const char *lbl = hmi_widget_str(w, "label", "");
    lv_label_set_text(st->label, lbl);
    if (lbl[0] == '\0') {
        lv_obj_add_flag(label, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_clear_flag(label, LV_OBJ_FLAG_HIDDEN);
    }

    update_dropdown_text(st);

    lv_obj_add_event_cb(dropdown, dropdown_event_cb, LV_EVENT_VALUE_CHANGED, w);

    w->state = st;
    return bg;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    shselect_state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "currentIndex") == 0) {
        int idx = (int)hmi_value_as_num(value, st->current_index);
        if (idx >= 0 && idx < st->n_options) {
            st->current_index = idx;
            lv_dropdown_set_selected(st->dropdown, idx);
        }
    } else if (strcmp(prop, "placeholder") == 0) {
        strncpy(st->placeholder, hmi_value_as_str(value, "Select..."), sizeof(st->placeholder) - 1);
    } else if (strcmp(prop, "label") == 0) {
        const char *lbl = hmi_value_as_str(value, "");
        lv_label_set_text(st->label, lbl);
        if (lbl[0] == '\0') {
            lv_obj_add_flag(st->label, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_clear_flag(st->label, LV_OBJ_FLAG_HIDDEN);
        }
    } else if (strcmp(prop, "options") == 0) {
        // Options as a comma-separated string
        strncpy(st->options, hmi_value_as_str(value, ""), sizeof(st->options) - 1);
        // Re-parse options
        int n_opts = 0;
        char *copy = strdup(st->options);
        char *token = strtok(copy, ",");
        char menu_str[512] = "";
        while (token) {
            while (*token == ' ') token++;
            char *end = token + strlen(token) - 1;
            while (end > token && *end == ' ') { *end = '\0'; end--; }
            if (strlen(token) > 0) {
                if (n_opts > 0) strncat(menu_str, "\n", sizeof(menu_str) - strlen(menu_str) - 1);
                strncat(menu_str, token, sizeof(menu_str) - strlen(menu_str) - 1);
                n_opts++;
            }
            token = strtok(NULL, ",");
        }
        free(copy);
        st->n_options = n_opts;
        if (n_opts > 0) {
            lv_dropdown_set_options(st->dropdown, menu_str);
        } else {
            lv_dropdown_set_options(st->dropdown, st->placeholder);
        }
        // Update current index
        if (st->current_index >= n_opts) {
            st->current_index = 0;
        }
        lv_dropdown_set_selected(st->dropdown, st->current_index >= 0 ? st->current_index : 0);
    }
}

static void destroy(hmi_widget_t *w)
{
    shselect_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_shselect = {"ShSelect", create, set_prop, destroy};