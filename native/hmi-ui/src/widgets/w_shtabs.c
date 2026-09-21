// widgets/w_shtabs.c -- kit widget ShTabs (Navigation, "Tab Container").
//
// Spec: ui/qml/Shadcn/ShTabs.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): tabs, currentIndex, opacity, visible.
// Default size 360x240. Signals: none.
// Owner: W3 (wave 2).
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"
#include "theme.h"

#define MAX_TABS 20

typedef struct {
    lv_obj_t *bg;
    lv_obj_t *tabBar;
    lv_obj_t *tabBg[MAX_TABS];
    lv_obj_t *tabText[MAX_TABS];
    char tabs[MAX_TABS][64];
    int n_tabs;
    int current_index;
} shtabs_state_t;

static void update_tabs(shtabs_state_t *st)
{
    for (int i = 0; i < st->n_tabs; i++) {
        if (i == st->current_index) {
            lv_obj_set_style_bg_color(st->tabBg[i], hmi_colour("background"), 0);
            lv_obj_set_style_bg_opa(st->tabBg[i], LV_OPA_COVER, 0);
            lv_obj_set_style_text_color(st->tabText[i], hmi_colour("foreground"), 0);
        } else {
            lv_obj_set_style_bg_color(st->tabBg[i], lv_color_hex(0x000000), 0);
            lv_obj_set_style_bg_opa(st->tabBg[i], LV_OPA_TRANSP, 0);
            lv_obj_set_style_text_color(st->tabText[i], hmi_colour("mutedForeground"), 0);
        }
    }
}

static void tab_click_cb(lv_event_t *e)
{
    hmi_widget_t *widget = (hmi_widget_t *)lv_event_get_user_data(e);
    if (!widget) return;
    shtabs_state_t *st = widget->state;
    if (!st) return;
    lv_obj_t *clicked = lv_event_get_target(e);
    for (int i = 0; i < st->n_tabs; i++) {
        if (st->tabBg[i] == clicked) {
            st->current_index = i;
            update_tabs(st);
            hmi_value_t val = hmi_value_num((double)i);
            hmi_widget_emit(widget, "tabChanged", &val);
            hmi_value_free(&val);
            return;
        }
    }
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *bg = lv_obj_create(parent);
    lv_obj_remove_style_all(bg);
    lv_obj_set_size(bg, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(bg, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(bg, lv_color_hex(0x000000), 0);
    lv_obj_set_style_bg_opa(bg, LV_OPA_TRANSP, 0);

    shtabs_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->bg = bg;

    // Parse tabs (comma-separated)
    const char *tabs_str = hmi_widget_str(w, "tabs", "");
    char *copy = strdup(tabs_str);
    char *token = strtok(copy, ",");
    st->current_index = (int)hmi_widget_num(w, "currentIndex", 0);
    st->n_tabs = 0;

    while (token && st->n_tabs < MAX_TABS) {
        while (*token == ' ') token++;
        char *end = token + strlen(token) - 1;
        while (end > token && *end == ' ') { *end = '\0'; end--; }
        strncpy(st->tabs[st->n_tabs], token, sizeof(st->tabs[0]) - 1);
        st->n_tabs++;
        token = strtok(NULL, ",");
    }
    free(copy);

    // Tab bar: Rectangle { anchors.left/right: parent; top: parent.top; height: 36; radius: radiusLg; color: muted }
    lv_obj_t *tabBar = lv_obj_create(bg);
    lv_obj_remove_style_all(tabBar);
    lv_obj_set_size(tabBar, lv_pct(100), 36);
    lv_obj_set_style_radius(tabBar, hmi_radius("radiusLg"), 0);
    lv_obj_set_style_bg_color(tabBar, hmi_colour("muted"), 0);
    lv_obj_set_style_bg_opa(tabBar, LV_OPA_COVER, 0);
    // Disable flex on tab bar - we'll position children manually
    lv_obj_set_layout(tabBar, LV_LAYOUT_NONE);

    // Position tab bar at top-left of bg, full width
    lv_obj_set_pos(tabBar, 0, 0);

    st->tabBar = tabBar;

    // Create tab items
    int tabBarW = (int)w->width;
    int margin = 4;  // spacing4
    int innerW = tabBarW - 2 * margin;  // spacing8
    int tabW = st->n_tabs > 0 ? innerW / st->n_tabs : 0;
    int tabH = 36 - 2 * margin;

    for (int i = 0; i < st->n_tabs; i++) {
        lv_obj_t *tabBg = lv_obj_create(tabBar);
        lv_obj_remove_style_all(tabBg);
        lv_obj_set_style_radius(tabBg, hmi_radius("radiusMd"), 0);
        lv_obj_set_style_bg_color(tabBg, lv_color_hex(0x000000), 0);
        lv_obj_set_style_bg_opa(tabBg, LV_OPA_TRANSP, 0);
        lv_obj_set_size(tabBg, tabW, tabH);
        lv_obj_set_pos(tabBg, margin + i * tabW, margin);

        lv_obj_t *tabText = lv_label_create(tabBg);
        lv_obj_remove_style_all(tabText);
        lv_obj_set_style_text_font(tabText, hmi_font(hmi_font_size("fontSizeSm"), 500), 0);
        lv_obj_set_style_text_color(tabText, hmi_colour("mutedForeground"), 0);
        lv_obj_set_style_text_align(tabText, LV_TEXT_ALIGN_CENTER, 0);
        lv_label_set_text(tabText, st->tabs[i]);
        lv_obj_set_size(tabText, tabW - 8, LV_SIZE_CONTENT);   // one line, centred in the pill
        lv_obj_center(tabText);

        st->tabBg[i] = tabBg;
        st->tabText[i] = tabText;

        lv_obj_add_event_cb(tabBg, tab_click_cb, LV_EVENT_CLICKED, w);
        lv_obj_add_flag(tabBg, LV_OBJ_FLAG_CLICKABLE);
    }

    // Highlight active tab
    if (st->current_index >= 0 && st->current_index < st->n_tabs) {
        lv_obj_set_style_bg_color(st->tabBg[st->current_index], hmi_colour("background"), 0);
        lv_obj_set_style_bg_opa(st->tabBg[st->current_index], LV_OPA_COVER, 0);
        lv_obj_set_style_text_color(st->tabText[st->current_index], hmi_colour("foreground"), 0);
    }

    w->state = st;
    return bg;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    shtabs_state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "currentIndex") == 0) {
        int idx = (int)hmi_value_as_num(value, st->current_index);
        if (idx >= 0 && idx < st->n_tabs) {
            st->current_index = idx;
            update_tabs(st);
        }
    } else if (strcmp(prop, "tabs") == 0) {
        const char *tabs_str = hmi_value_as_str(value, "");
        char *copy = strdup(tabs_str);
        char *token = strtok(copy, ",");
        st->n_tabs = 0;
        while (token && st->n_tabs < MAX_TABS) {
            while (*token == ' ') token++;
            char *end = token + strlen(token) - 1;
            while (end > token && *end == ' ') { *end = '\0'; end--; }
            strncpy(st->tabs[st->n_tabs], token, sizeof(st->tabs[0]) - 1);
            st->n_tabs++;
            token = strtok(NULL, ",");
        }
        free(copy);

        // Recreate tab widgets
        lv_obj_clean(st->tabBar);
        int tabBarW = (int)w->width;
        int margin = 4;
        int innerW = tabBarW - 2 * margin;
        int tabW = st->n_tabs > 0 ? innerW / st->n_tabs : 0;
        int tabH = 36 - 2 * margin;

        for (int i = 0; i < st->n_tabs; i++) {
            lv_obj_t *tabBg = lv_obj_create(st->tabBar);
            lv_obj_remove_style_all(tabBg);
            lv_obj_set_style_radius(tabBg, hmi_radius("radiusMd"), 0);
            lv_obj_set_style_bg_color(tabBg, lv_color_hex(0x000000), 0);
            lv_obj_set_style_bg_opa(tabBg, LV_OPA_TRANSP, 0);
            lv_obj_set_size(tabBg, tabW, tabH);
            lv_obj_set_pos(tabBg, margin + i * tabW, margin);

            lv_obj_t *tabText = lv_label_create(tabBg);
            lv_obj_remove_style_all(tabText);
            lv_obj_set_style_text_font(tabText, hmi_font(hmi_font_size("fontSizeSm"), 500), 0);
            lv_obj_set_style_text_color(tabText, hmi_colour("mutedForeground"), 0);
            lv_obj_set_style_text_align(tabText, LV_TEXT_ALIGN_CENTER, 0);
            lv_label_set_text(tabText, st->tabs[i]);
            lv_obj_set_size(tabText, tabW - 8, LV_SIZE_CONTENT);   // one line, centred in the pill
            lv_obj_center(tabText);

            st->tabBg[i] = tabBg;
            st->tabText[i] = tabText;

            lv_obj_add_event_cb(tabBg, tab_click_cb, LV_EVENT_CLICKED, w);
            lv_obj_add_flag(tabBg, LV_OBJ_FLAG_CLICKABLE);
        }

        if (st->current_index >= st->n_tabs) {
            st->current_index = 0;
        }
        update_tabs(st);
    }
}

static void destroy(hmi_widget_t *w)
{
    shtabs_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_shtabs = {"ShTabs", create, set_prop, destroy};