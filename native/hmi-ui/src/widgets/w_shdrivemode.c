// widgets/w_shdrivemode.c -- kit widget ShDriveMode (Automotive, "Drive Mode").
//
// Spec: ui/qml/Shadcn/ShDriveMode.qml -- a caption over the current mode
// name, flanked by chevrons that step through the mode list.
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "icons.h"
#include "registry.h"

typedef struct {
    lv_obj_t *caption, *leftChevron, *rightChevron, *modeText, *leftTap, *rightTap;
    char caption_text[64];
    char modes[256];
    char current_mode[64];
    int current_index;
    int mode_count;
} state_t;

static void mode_tap_cb(lv_event_t *e, hmi_widget_t *w, int delta)
{
    state_t *st = w->state;
    if (!st || st->mode_count == 0) return;
    st->current_index = ((st->current_index + delta) % st->mode_count + st->mode_count) % st->mode_count;
    lv_label_set_text(st->modeText, st->current_mode);
    hmi_value_t v = hmi_value_num((double)st->current_index);
    hmi_widget_emit(w, "activated", &v);
    hmi_value_free(&v);
}

static void left_tap_cb(lv_event_t *e)
{
    hmi_widget_t *w = (hmi_widget_t *)lv_event_get_user_data(e);
    mode_tap_cb(e, w, -1);
}

static void right_tap_cb(lv_event_t *e)
{
    hmi_widget_t *w = (hmi_widget_t *)lv_event_get_user_data(e);
    mode_tap_cb(e, w, 1);
}

static void update_current_mode(hmi_widget_t *w)
{
    state_t *st = w->state;
    // modes: a comma-separated string; trim each entry, drop empties.
    char copy[256];
    snprintf(copy, sizeof copy, "%s", st->modes);
    char *names[32];
    int count = 0;
    char *save = NULL;
    for (char *tok = strtok_r(copy, ",", &save); tok && count < 32; tok = strtok_r(NULL, ",", &save)) {
        while (*tok == ' ') ++tok;
        size_t len = strlen(tok);
        while (len > 0 && tok[len - 1] == ' ') tok[--len] = '\0';
        if (len) names[count++] = tok;
    }
    st->mode_count = count;
    if (count == 0 || st->current_index < 0 || st->current_index >= count)
        st->current_mode[0] = '\0';
    else
        snprintf(st->current_mode, sizeof st->current_mode, "%s", names[st->current_index]);
    lv_label_set_text(st->modeText, st->current_mode);
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);

    lv_label_set_text(st->caption, st->caption_text);
    lv_obj_set_style_text_font(st->caption, hmi_font(hmi_px_min(H * 0.24, 8), 500), 0);
    lv_obj_set_style_text_color(st->caption, hmi_colour("autoMuted"), 0);
    lv_obj_align(st->caption, LV_ALIGN_TOP_MID, 0, (int)round(H * 0.04));
    if (st->caption_text[0]) lv_obj_remove_flag(st->caption, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(st->caption, LV_OBJ_FLAG_HIDDEN);

    // Row at the bottom (margin 0.02 h), centred: [slot] gap [text] gap [slot]
    int slotW = (int)round(H * 0.9), slotH = (int)round(H * 0.62), gap = (int)round(H * 0.2);
    int chevron = (int)round(H * 0.36);
    lv_obj_set_style_text_font(st->modeText, hmi_font(hmi_px_min(H * 0.34, 8), 600), 0);
    lv_obj_set_style_text_color(st->modeText, hmi_colour("autoAmber"), 0);
    lv_obj_update_layout(st->modeText);
    int textW = lv_obj_get_width(st->modeText), textH = lv_obj_get_height(st->modeText);
    int rowW = slotW + gap + textW + gap + slotW;
    int rowX = (int)round(W / 2 - rowW / 2.0);
    int rowBottom = (int)round(H - H * 0.02);
    int rowTop = rowBottom - slotH;
    lv_obj_set_size(st->leftTap, slotW, slotH);
    lv_obj_set_pos(st->leftTap, rowX, rowTop);
    hmi_icon_set(st->leftChevron, "chevron-left", chevron, hmi_colour("autoLine"));
    lv_obj_set_pos(st->leftChevron, rowX + slotW / 2 - chevron / 2, rowTop + slotH / 2 - chevron / 2);
    lv_obj_set_pos(st->modeText, rowX + slotW + gap, rowTop + slotH / 2 - textH / 2);
    int rightX = rowX + slotW + gap + textW + gap;
    lv_obj_set_size(st->rightTap, slotW, slotH);
    lv_obj_set_pos(st->rightTap, rightX, rowTop);
    hmi_icon_set(st->rightChevron, "chevron-right", chevron, hmi_colour("autoLine"));
    lv_obj_set_pos(st->rightChevron, rightX + slotW / 2 - chevron / 2, rowTop + slotH / 2 - chevron / 2);
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *root = lv_obj_create(parent);
    lv_obj_remove_style_all(root);
    lv_obj_set_size(root, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(root, LV_OBJ_FLAG_SCROLLABLE);

    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;

    /* Caption */
    st->caption = lv_label_create(root);
    lv_obj_remove_style_all(st->caption);
    lv_label_set_long_mode(st->caption, LV_LABEL_LONG_CLIP);

    /* Left chevron */
    st->leftChevron = hmi_icon_create(root, "chevron-left", 16, hmi_colour("autoLine"));

    /* Left tap area */
    st->leftTap = lv_obj_create(root);
    lv_obj_remove_style_all(st->leftTap);
    lv_obj_remove_flag(st->leftTap, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(st->leftTap, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_bg_opa(st->leftTap, LV_OPA_TRANSP, 0);
    lv_obj_add_event_cb(st->leftTap, left_tap_cb, LV_EVENT_CLICKED, w);

    /* Mode text */
    st->modeText = lv_label_create(root);
    lv_obj_remove_style_all(st->modeText);
    lv_label_set_long_mode(st->modeText, LV_LABEL_LONG_CLIP);

    /* Right chevron */
    st->rightChevron = hmi_icon_create(root, "chevron-right", 16, hmi_colour("autoLine"));

    /* Right tap area */
    st->rightTap = lv_obj_create(root);
    lv_obj_remove_style_all(st->rightTap);
    lv_obj_remove_flag(st->rightTap, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(st->rightTap, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_bg_opa(st->rightTap, LV_OPA_TRANSP, 0);
    lv_obj_add_event_cb(st->rightTap, right_tap_cb, LV_EVENT_CLICKED, w);

    snprintf(st->caption_text, sizeof st->caption_text, "%s", hmi_widget_str(w, "label", "Drive mode"));
    snprintf(st->modes, sizeof st->modes, "%s", hmi_widget_str(w, "modes", "ECO,COMFORT,SPORT"));
    st->current_index = (int)hmi_widget_num(w, "currentIndex", 2);

    update_current_mode(w);
    layout(w);
    return root;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "label") == 0) {
        snprintf(st->caption_text, sizeof st->caption_text, "%s", hmi_value_as_str(value, ""));
        layout(w);
    } else if (strcmp(prop, "modes") == 0) {
        snprintf(st->modes, sizeof st->modes, "%s", hmi_value_as_str(value, ""));
        update_current_mode(w);
        layout(w);
    } else if (strcmp(prop, "currentIndex") == 0) {
        st->current_index = (int)hmi_value_as_num(value, st->current_index);
        update_current_mode(w);
        layout(w);
    }
    /* enabled/opacity/visible handled by runtime */
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shdrivemode = {"ShDriveMode", create, set_prop, destroy};