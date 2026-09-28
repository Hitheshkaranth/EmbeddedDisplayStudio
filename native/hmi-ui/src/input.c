// input.c -- see input.h (CONTRACT 13.5). Wave 1 W5 implements.
//
// The numeric keypad (ShNumInput) and the text keyboard (ShInput) both claim
// the single modal.h slot ("keypad" / "keyboard") while open and refuse to
// open when it is taken. They build their LVGL objects on lv_layer_top() and
// delete them (releasing the slot) on OK/Cancel. See input.h for the exact
// contract of each key and outcome.
#include "input.h"

#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "compat.h"
#include "log.h"
#include "modal.h"
#include "theme.h"

#define KEY_PAD_OWNER "keypad"
#define KEYBOARD_OWNER "keyboard"

#define MAX_KEYS 16

// One open popup (keypad or keyboard): one modal slot, one at a time.
struct hmi_input_popup {
    lv_obj_t *pad;            // the editing object (keypad entry label / textarea)
    lv_obj_t *errlabel;       // the range message (keypad)
    lv_obj_t *ok_btn;         // the OK button (keypad)
    lv_obj_t *cancel_btn;     // the Cancel button (keypad)

    hmi_widget_t *w;          // the widget that opened it
    hmi_input_numeric_cb done_num;
    hmi_input_text_cb done_txt;
    void *user;
    bool is_text;             // true: keyboard, false: numeric keypad

    char entry[256];          // the entry text (keypad)
    double min, max;          // range for the numeric pad
    int decimals;             // decimals for the numeric pad

    lv_obj_t *keys[MAX_KEYS]; // keypad key buttons (label: digit/BS/C/-)
    int nkeys;
};

static struct hmi_input_popup *g_popup;

// Round half away from zero to `decimals` decimals.
static double round_half(double v, int decimals)
{
    double p = pow(10.0, (double)decimals);
    return round(v * p) / p;
}

// Parse the entry as a finite number; false when empty or not a number.
static bool parse_entry(const char *text, double *out)
{
    if (!text || !*text) return false;
    char *end = NULL;
    errno = 0;
    double v = strtod(text, &end);
    if (end == text || *end != '\0' || !isfinite(v)) return false;
    *out = v;
    return true;
}

// The shared accessor for the current entry text ("" when closed).
const char *hmi_input_entry(void)
{
    return g_popup ? g_popup->entry : "";
}

bool hmi_input_error_shown(void)
{
    return g_popup && g_popup->errlabel &&
           !lv_obj_has_flag(g_popup->errlabel, LV_OBJ_FLAG_HIDDEN);
}

bool hmi_input_is_open(void) { return g_popup != NULL; }

// Show the range message "<min>..<max>" in the destructive colour.
static void show_error(hmi_widget_t *w, double min, double max)
{
    (void)w;
    char msg[96];
    snprintf(msg, sizeof msg, "%g..%g", min, max);
    lv_label_set_text(g_popup->errlabel, msg);
    lv_obj_remove_flag(g_popup->errlabel, LV_OBJ_FLAG_HIDDEN);
}

static void hide_error(void)
{
    lv_obj_add_flag(g_popup->errlabel, LV_OBJ_FLAG_HIDDEN);
}

static void finish_popup_free(struct hmi_input_popup *p)
{
    if (p->is_text)
        hmi_modal_release(KEYBOARD_OWNER);
    else
        hmi_modal_release(KEY_PAD_OWNER);
    free(p);
}

// The numeric keypad's OK: validate, then call the widget's numeric callback.
static void keypad_ok_cb(lv_event_t *e)
{
    (void)e;
    double v = 0;
    if (!parse_entry(g_popup->entry, &v) || v < g_popup->min || v > g_popup->max) {
        show_error(g_popup->w, g_popup->min, g_popup->max);
        return;   // keep the pad open
    }
    hide_error();
    double rounded = round_half(v, g_popup->decimals);
    int n = snprintf(g_popup->entry, sizeof g_popup->entry, "%.*f",
                     g_popup->decimals, rounded);
    if (n > 0 && (size_t)n < sizeof g_popup->entry) g_popup->entry[n] = '\0';
    lv_obj_delete(g_popup->pad);
    struct hmi_input_popup *p = g_popup;
    g_popup = NULL;
    finish_popup_free(p);
    if (p->done_num) p->done_num(rounded, p->user);
}

static void keypad_cancel_cb(lv_event_t *e)
{
    (void)e;
    lv_obj_delete(g_popup->pad);
    struct hmi_input_popup *p = g_popup;
    g_popup = NULL;
    finish_popup_free(p);
}

// A keypad digit/operation key on the shared row.
static void keypad_key_cb(lv_event_t *e)
{
    lv_obj_t *b = lv_event_get_target(e);
    size_t len = strlen(g_popup->entry);
    for (int i = 0; i < g_popup->nkeys; i++) {
        if (g_popup->keys[i] != b) continue;
        const char *label = "";
        lv_obj_t *t = lv_obj_get_child(b, 0);
        if (t) label = lv_label_get_text(t);
        if (!label) return;
        if (strcmp(label, "BS") == 0) {
            if (len) g_popup->entry[len - 1] = '\0';
        } else if (strcmp(label, "C") == 0) {
            g_popup->entry[0] = '\0';
        } else if (strcmp(label, "-") == 0) {
            if (g_popup->entry[0] == '-') {
                memmove(g_popup->entry, g_popup->entry + 1, strlen(g_popup->entry));
            } else if (len < (sizeof g_popup->entry) - 1) {
                memmove(g_popup->entry + 1, g_popup->entry, strlen(g_popup->entry) + 1);
                g_popup->entry[0] = '-';
            }
        } else if (strcmp(label, ".") == 0) {
            if (len < (sizeof g_popup->entry) - 1 &&
                strstr(g_popup->entry, ".") == NULL) {
                g_popup->entry[len] = '.';
                g_popup->entry[len + 1] = '\0';
            }
        } else if (label[0] >= '0' && label[0] <= '9' &&
                   len < (sizeof g_popup->entry) - 1) {
            g_popup->entry[len] = label[0];
            g_popup->entry[len + 1] = '\0';
        }
        break;
    }
    if (g_popup->pad) lv_label_set_text(g_popup->pad, g_popup->entry);
}

static lv_obj_t *make_key(lv_obj_t *row, const char *text, lv_event_cb_t cb)
{
    lv_obj_t *b = lv_button_create(row);
    lv_obj_remove_style_all(b);
    lv_obj_set_flex_grow(b, 1);
    lv_obj_set_style_radius(b, hmi_radius("md"), 0);
    lv_obj_set_style_bg_color(b, hmi_colour("secondary"), 0);
    lv_obj_t *t = lv_label_create(b);
    lv_label_set_text(t, text);
    lv_obj_center(t);
    lv_obj_add_event_cb(b, cb, LV_EVENT_CLICKED, NULL);
    return b;
}

static lv_obj_t *make_action_key(lv_obj_t *row, const char *text, lv_color_t bg,
                                 lv_event_cb_t cb)
{
    lv_obj_t *b = make_key(row, text, cb);
    lv_obj_set_style_bg_color(b, bg, 0);
    return b;
}

// A key that hmi_input_press must reach by label: register it and style it.
static lv_obj_t *register_key(const char *text, lv_event_cb_t cb, lv_obj_t *row,
                              lv_color_t bg)
{
    lv_obj_t *b = make_key(row, text, cb);
    lv_obj_set_style_bg_color(b, bg, 0);
    if (g_popup->nkeys < MAX_KEYS) g_popup->keys[g_popup->nkeys++] = b;
    return b;
}

// Build the whole keypad on lv_layer_top.
static void build_keypad(void)
{
    lv_obj_t *root = lv_obj_create(lv_layer_top());
    lv_obj_remove_style_all(root);
    lv_obj_set_size(root, lv_pct(100), LV_SIZE_CONTENT);
    lv_obj_align(root, LV_ALIGN_BOTTOM_MID, 0, -64);
    lv_obj_set_flex_flow(root, LV_FLEX_FLOW_COLUMN);

    // The editing line.
    lv_obj_t *entry = lv_obj_create(root);
    lv_obj_remove_style_all(entry);
    lv_obj_set_size(entry, lv_pct(100), 44);
    lv_obj_set_style_border_color(entry, hmi_colour("input"), 0);
    lv_obj_set_style_border_width(entry, 1, 0);
    lv_obj_t *lbl = lv_label_create(entry);
    lv_label_set_text(lbl, g_popup->entry);
    lv_obj_set_style_text_font(lbl, hmi_font(hmi_font_size("fontSizeMd"), 500), 0);
    lv_label_set_long_mode(lbl, LV_LABEL_LONG_SCROLL);
    g_popup->pad = lbl;   // the entry label: edited by the keys, read on OK

    // The hidden range message.
    g_popup->errlabel = lv_label_create(root);
    lv_obj_remove_style_all(g_popup->errlabel);
    lv_label_set_text(g_popup->errlabel, "");
    lv_obj_set_style_text_color(g_popup->errlabel, hmi_colour("destructive"), 0);
    lv_obj_add_flag(g_popup->errlabel, LV_OBJ_FLAG_HIDDEN);

// Keypad rows: 1-2-3, 4-5-6, 7-8-9, .-0-BS.
    static const char *keys[4][3] = {{"1", "2", "3"}, {"4", "5", "6"}, {"7", "8", "9"},
                                       {".", "0", "BS"}};
    for (int r = 0; r < 4; r++) {
        lv_obj_t *row = lv_obj_create(root);
        lv_obj_remove_style_all(row);
        lv_obj_set_size(row, lv_pct(100), 40);
        lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
        for (int c = 0; c < 3; c++)
            register_key(keys[r][c], keypad_key_cb, row, hmi_colour("secondary"));
    }

    // Bottom control row: C, "-", CANCEL, OK.
    lv_obj_t *row5 = lv_obj_create(root);
    lv_obj_remove_style_all(row5);
    lv_obj_set_size(row5, lv_pct(100), 44);
    lv_obj_set_flex_flow(row5, LV_FLEX_FLOW_ROW);
register_key("C", keypad_key_cb, row5, hmi_colour("secondary"));
    register_key("-", keypad_key_cb, row5, hmi_colour("secondary"));
    lv_obj_t *cancel = make_action_key(row5, "CANCEL", hmi_colour("secondary"), keypad_cancel_cb);
    g_popup->cancel_btn = cancel;
    g_popup->ok_btn = make_action_key(row5, "OK", hmi_colour("brand"), keypad_ok_cb);
}

bool hmi_input_open_numeric(hmi_widget_t *w, double value, double min, double max, int decimals,
                            hmi_input_numeric_cb done, void *user)
{
    if (g_popup) return false;   // one popup at a time
    if (!hmi_modal_claim(KEY_PAD_OWNER)) return false;
    struct hmi_input_popup *p = calloc(1, sizeof *p);
    if (!p) { hmi_modal_release(KEY_PAD_OWNER); return false; }
    p->w = w;
    p->done_num = done;
    p->user = user;
    p->min = min;
    p->max = max;
    p->decimals = decimals;
    int n = snprintf(p->entry, sizeof p->entry, "%.*f", decimals, value);
    if (n > 0 && (size_t)n < sizeof p->entry) p->entry[n] = '\0';
    g_popup = p;
    build_keypad();
    return g_popup->pad != NULL;
}

// -- text keyboard --------------------------------------------------------------

static void keyboard_ready_cb(lv_event_t *e)
{
    (void)e;
    const char *t = lv_textarea_get_text(g_popup->pad);
    char dup[256];
    snprintf(dup, sizeof dup, "%s", t ? t : "");
    lv_obj_delete(g_popup->pad);
    struct hmi_input_popup *p = g_popup;
    g_popup = NULL;
    hmi_input_text_cb done_txt = p->done_txt;
    void *user = p->user;
    finish_popup_free(p);
    if (done_txt) done_txt(dup, user);
}

static void keyboard_cancel_cb(lv_event_t *e)
{
    (void)e;
    lv_obj_delete(g_popup->pad);
    struct hmi_input_popup *p = g_popup;
    g_popup = NULL;
    finish_popup_free(p);
}

// Open the text keyboard; returns false when the slot is taken.
bool hmi_input_open_text(hmi_widget_t *w, const char *text, hmi_input_text_cb done, void *user)
{
    if (g_popup) return false;
    if (!hmi_modal_claim(KEYBOARD_OWNER)) return false;
    struct hmi_input_popup *p = calloc(1, sizeof *p);
    if (!p) { hmi_modal_release(KEYBOARD_OWNER); return false; }
    p->w = w;
    p->done_txt = done;
    p->user = user;
    p->is_text = true;
    snprintf(p->entry, sizeof p->entry, "%s", text ? text : "");

    lv_obj_t *area = lv_textarea_create(lv_layer_top());
    lv_obj_remove_style_all(area);
    lv_obj_set_size(area, lv_pct(100), 44);
    lv_textarea_set_text(area, p->entry);
    lv_textarea_set_one_line(area, true);

    lv_obj_t *kb = lv_keyboard_create(lv_layer_top());
    lv_keyboard_set_mode(kb, LV_KEYBOARD_MODE_TEXT_LOWER);
    lv_keyboard_set_textarea(kb, area);
    lv_obj_add_event_cb(kb, keyboard_ready_cb, LV_EVENT_READY, NULL);
    lv_obj_add_event_cb(kb, keyboard_cancel_cb, LV_EVENT_CANCEL, NULL);

    g_popup = p;
    g_popup->pad = area;   // the editing object: the textarea
    return g_popup->pad != NULL;
}

// The on-screen buttons (and the widget's ready/cancel) call the same code.
bool hmi_input_press(const char *key)
{
    if (!g_popup) return false;
    if (g_popup->is_text) {
        if (strcmp(key, "OK") == 0) {
            lv_obj_send_event(g_popup->pad, LV_EVENT_READY, NULL);
            return true;
        }
        if (strcmp(key, "CANCEL") == 0) {
            lv_obj_send_event(g_popup->pad, LV_EVENT_CANCEL, NULL);
            return true;
        }
        return false;
    }
    if (strcmp(key, "OK") == 0) {
        lv_obj_send_event(g_popup->ok_btn, LV_EVENT_CLICKED, NULL);
        return true;
    }
    if (strcmp(key, "CANCEL") == 0) {
        lv_obj_send_event(g_popup->cancel_btn, LV_EVENT_CLICKED, NULL);
        return true;
    }
    // Drive the key button whose label matches `key` (digit/BS/C/-).
    for (int i = 0; i < g_popup->nkeys; i++) {
        const char *label = "";
        lv_obj_t *t = lv_obj_get_child(g_popup->keys[i], 0);
        if (t) label = lv_label_get_text(t);
        if (label && strcmp(label, key) == 0) {
            lv_obj_send_event(g_popup->keys[i], LV_EVENT_CLICKED, NULL);
            return true;
        }
    }
    return false;
}

// Replace the keyboard's text; not supported by the keypad.
bool hmi_input_set_text(const char *text)
{
    if (!g_popup || !g_popup->is_text) return false;
    lv_textarea_set_text(g_popup->pad, text ? text : "");
    return true;
}