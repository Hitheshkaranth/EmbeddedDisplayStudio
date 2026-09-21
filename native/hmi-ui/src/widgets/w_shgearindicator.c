// widgets/w_shgearindicator.c -- kit widget ShGearIndicator (Automotive, "Gear Indicator").
//
// Spec: ui/qml/Shadcn/ShGearIndicator.qml -- a row of gears (P R N D) with
// the engaged gear large and bright, others dimmed.  modeNumber > 0 shows
// a lighter digit after the engaged gear.
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    char gear_label[32][32];
    lv_obj_t *gear_obj[32];
    lv_obj_t *num_obj[32];
    char gears[256];
    char gear[32];
    int modeNumber;
    bool showAll;
    int count;
} state_t;

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    int spacing = (int)round(H * 0.12);
    int activeFs = hmi_px_min(H * 0.62, 8);
    int dimFs = hmi_px_min(H * 0.4, 7);
    int modeNumFs = hmi_px_min(H * 0.45, 8);
    int modeNumMargin = (int)round(H * 0.02);

    /* Parse gear list */
    char gears_copy[256];
    snprintf(gears_copy, sizeof gears_copy, "%s", st->gears);
    st->count = 0;
    char *saveptr = NULL;
    char *tok = strtok_r(gears_copy, ",", &saveptr);
    while (tok && st->count < 32) {
        while (*tok == ' ') tok++;
        int len = (int)strlen(tok);
        while (len > 0 && tok[len - 1] == ' ') { tok[len - 1] = '\0'; len--; }
        if (len > 0) {
            snprintf(st->gear_label[st->count], sizeof(st->gear_label[0]), "%s", tok);
            st->count++;
        }
        tok = strtok_r(NULL, ",", &saveptr);
    }

    bool gearIsKnown = st->gear[0] != '\0';
    // Check if gear is a letter (not a number)
    if (gearIsKnown) {
        for (int i = 0; st->gear[i]; i++) {
            if (st->gear[i] >= '0' && st->gear[i] <= '9') {
                gearIsKnown = false;
                break;
            }
        }
    }

    if (!st->showAll) {
        // Only show engaged gear
        st->count = gearIsKnown ? 1 : 0;
        if (gearIsKnown) {
            snprintf(st->gear_label[0], sizeof(st->gear_label[0]), "%s", st->gear);
        }
    } else if (gearIsKnown) {
        // Check if gear is in the list, if not append it
        bool found = false;
        for (int i = 0; i < st->count; i++) {
            if (strcmp(st->gear_label[i], st->gear) == 0) { found = true; break; }
        }
        if (!found && st->count < 31) {
            snprintf(st->gear_label[st->count], sizeof(st->gear_label[0]), "%s", st->gear);
            st->count++;
        }
    }

    /* Position: a Row at the bottom (margin 0.12 h), centred, spacing 0.12 h;
       each entry is the gear glyph followed (1 px) by the mode number when
       current; everything bottom-aligned as the QML anchors it. */
    int bottom = (int)H - (int)round(H * 0.12);
    int widths[32];
    int total = 0;
    for (int i = 0; i < st->count; i++) {
        bool current = strcmp(st->gear_label[i], st->gear) == 0;
        lv_label_set_text(st->gear_obj[i], st->gear_label[i]);
        lv_obj_set_style_text_font(st->gear_obj[i], hmi_font(current ? activeFs : dimFs, current ? 600 : 500), 0);
        lv_obj_set_style_text_color(st->gear_obj[i], current ? hmi_colour("autoText") : hmi_colour("autoMuted"), 0);
        lv_obj_remove_flag(st->gear_obj[i], LV_OBJ_FLAG_HIDDEN);
        lv_obj_update_layout(st->gear_obj[i]);
        widths[i] = lv_obj_get_width(st->gear_obj[i]);
        if (current && st->modeNumber > 0) {
            lv_label_set_text_fmt(st->num_obj[i], "%d", st->modeNumber);
            lv_obj_set_style_text_font(st->num_obj[i], hmi_font(modeNumFs, 400), 0);
            lv_obj_set_style_text_color(st->num_obj[i], hmi_colour("autoLine"), 0);
            lv_obj_remove_flag(st->num_obj[i], LV_OBJ_FLAG_HIDDEN);
            lv_obj_update_layout(st->num_obj[i]);
            widths[i] += 1 + lv_obj_get_width(st->num_obj[i]);
        } else {
            lv_obj_add_flag(st->num_obj[i], LV_OBJ_FLAG_HIDDEN);
        }
        total += widths[i] + (i ? spacing : 0);
    }
    for (int i = st->count; i < 32; i++) {
        if (st->gear_obj[i]) lv_obj_add_flag(st->gear_obj[i], LV_OBJ_FLAG_HIDDEN);
        if (st->num_obj[i]) lv_obj_add_flag(st->num_obj[i], LV_OBJ_FLAG_HIDDEN);
    }
    int x = (int)round(W / 2 - total / 2.0);
    for (int i = 0; i < st->count; i++) {
        bool current = strcmp(st->gear_label[i], st->gear) == 0;
        int gh = lv_obj_get_height(st->gear_obj[i]);
        lv_obj_set_pos(st->gear_obj[i], x, bottom - gh);
        int gw = lv_obj_get_width(st->gear_obj[i]);
        if (current && st->modeNumber > 0) {
            int nh = lv_obj_get_height(st->num_obj[i]);
            lv_obj_set_pos(st->num_obj[i], x + gw + 1, bottom - modeNumMargin - nh);
        }
        x += widths[i] + spacing;
    }
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *root = lv_obj_create(parent);
    lv_obj_remove_style_all(root);
    lv_obj_set_size(root, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(root, LV_OBJ_FLAG_SCROLLABLE);

    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;

    snprintf(st->gears, sizeof st->gears, "%s", hmi_widget_str(w, "gears", "P,R,N,D"));
    snprintf(st->gear, sizeof st->gear, "%s", hmi_widget_str(w, "gear", "D"));
    st->modeNumber = (int)hmi_widget_num(w, "modeNumber", 4);
    st->showAll = hmi_widget_bool(w, "showAll", true);

    /* Create gear label objects */
    for (int i = 0; i < 32; i++) {
        st->gear_obj[i] = lv_label_create(root);
        lv_obj_remove_style_all(st->gear_obj[i]);
        lv_label_set_long_mode(st->gear_obj[i], LV_LABEL_LONG_CLIP);
        st->num_obj[i] = lv_label_create(root);
        lv_obj_remove_style_all(st->num_obj[i]);
        lv_label_set_long_mode(st->num_obj[i], LV_LABEL_LONG_CLIP);
        lv_obj_add_flag(st->num_obj[i], LV_OBJ_FLAG_HIDDEN);
    }

    layout(w);
    return root;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "gears") == 0) {
        snprintf(st->gears, sizeof st->gears, "%s", hmi_value_as_str(value, ""));
        layout(w);
    } else if (strcmp(prop, "gear") == 0) {
        snprintf(st->gear, sizeof st->gear, "%s", hmi_value_as_str(value, ""));
        layout(w);
    } else if (strcmp(prop, "modeNumber") == 0) {
        st->modeNumber = (int)hmi_value_as_num(value, st->modeNumber);
        layout(w);
    } else if (strcmp(prop, "showAll") == 0) {
        st->showAll = hmi_value_as_bool(value, st->showAll);
        layout(w);
    }
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shgearindicator = {"ShGearIndicator", create, set_prop, destroy};