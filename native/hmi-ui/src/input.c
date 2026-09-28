// input.c -- see input.h (CONTRACT 13.5). Wave 1 W5 implements.
//
// The numeric keypad (ShNumInput) and the text keyboard (ShInput) both claim
// the single modal.h slot ("keypad" / "keyboard") while open and refuse to
// open when it is taken. Each builds one tree under a full-screen scrim on
// lv_layer_top() -- the scrim keeps taps off the page underneath -- and
// closing deletes that tree and releases the slot. The on-screen buttons and
// the test hook hmi_input_press run the same code, so what the gate drives is
// what an operator touches.
#include "input.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "modal.h"
#include "theme.h"

#define KEYPAD_OWNER "keypad"
#define KEYBOARD_OWNER "keyboard"

typedef struct {
    bool is_text;             // true: keyboard, false: numeric keypad
    lv_obj_t *root;           // the scrim; deleting it frees the whole popup
    lv_obj_t *entry_label;    // keypad: shows `entry`
    lv_obj_t *error_label;    // keypad: the range message
    lv_obj_t *textarea;       // keyboard
    hmi_input_numeric_cb done_num;
    hmi_input_text_cb done_text;
    void *user;
    double min, max;
    int decimals;
    char entry[64];           // keypad entry text
} popup_t;

static popup_t *g_popup;

// Round half away from zero to `decimals`. The product is nudged by a hair
// first: 12.25 * 10 is exact, but 1.005 * 100 lands on 100.49999..., and an
// operator who typed the 5 means the half.
static double round_half_away(double v, int decimals)
{
    double scale = pow(10.0, (double)decimals);
    double s = fabs(v) * scale;
    double r = floor(s);
    if (s - r >= 0.5 - 1e-9 * (s > 1.0 ? s : 1.0)) r += 1.0;
    return copysign(r / scale, v);
}

static bool parse_entry(const char *text, double *out)
{
    if (!text || !*text) return false;
    char *end = NULL;
    double v = strtod(text, &end);
    if (end == text || *end != '\0' || !isfinite(v)) return false;
    *out = v;
    return true;
}

static void close_popup(void)
{
    popup_t *p = g_popup;
    if (!p) return;
    g_popup = NULL;
    // Deleting from inside one of its own button callbacks is safe in LVGL 9:
    // the running event chain is marked deleted and the indev is reset.
    if (p->root) lv_obj_delete(p->root);
    hmi_modal_release(p->is_text ? KEYBOARD_OWNER : KEYPAD_OWNER);
    free(p);
}

static lv_obj_t *make_scrim(void)
{
    lv_obj_t *scrim = lv_obj_create(lv_layer_top());
    lv_obj_remove_style_all(scrim);
    lv_obj_set_size(scrim, lv_pct(100), lv_pct(100));
    lv_obj_set_style_bg_color(scrim, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(scrim, LV_OPA_50, 0);
    lv_obj_add_flag(scrim, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_remove_flag(scrim, LV_OBJ_FLAG_SCROLLABLE);
    return scrim;
}

// -- numeric keypad -------------------------------------------------------------

static void keypad_show_entry(void)
{
    lv_label_set_text(g_popup->entry_label, g_popup->entry);
}

static void keypad_ok(void)
{
    double v = 0;
    if (!parse_entry(g_popup->entry, &v) || v < g_popup->min || v > g_popup->max) {
        char msg[80];
        snprintf(msg, sizeof msg, "%g..%g", g_popup->min, g_popup->max);
        lv_label_set_text(g_popup->error_label, msg);
        lv_obj_remove_flag(g_popup->error_label, LV_OBJ_FLAG_HIDDEN);
        return;   // the pad stays open
    }
    double value = round_half_away(v, g_popup->decimals);
    hmi_input_numeric_cb done = g_popup->done_num;
    void *user = g_popup->user;
    close_popup();   // before the callback: it may open the next popup
    if (done) done(value, user);
}

// One keypad key; false for a key the keypad does not have.
static bool keypad_key(const char *key)
{
    char *e = g_popup->entry;
    size_t len = strlen(e);
    if (strcmp(key, "OK") == 0) { keypad_ok(); return true; }
    if (strcmp(key, "CANCEL") == 0) { close_popup(); return true; }
    if (strcmp(key, "BS") == 0) {
        if (len) e[len - 1] = '\0';
    } else if (strcmp(key, "C") == 0) {
        e[0] = '\0';
    } else if (strcmp(key, "-") == 0) {
        if (e[0] == '-') memmove(e, e + 1, len);
        else if (len + 1 < sizeof g_popup->entry) { memmove(e + 1, e, len + 1); e[0] = '-'; }
    } else if (strcmp(key, ".") == 0) {
        if (!strchr(e, '.') && len + 1 < sizeof g_popup->entry) { e[len] = '.'; e[len + 1] = '\0'; }
    } else if (key[0] >= '0' && key[0] <= '9' && key[1] == '\0') {
        if (len + 1 < sizeof g_popup->entry) { e[len] = key[0]; e[len + 1] = '\0'; }
    } else {
        return false;
    }
    lv_obj_add_flag(g_popup->error_label, LV_OBJ_FLAG_HIDDEN);   // the range hint was for the old entry
    keypad_show_entry();
    return true;
}

static void keypad_button_cb(lv_event_t *e)
{
    // The key name is the static string passed as user data.
    if (g_popup && !g_popup->is_text) keypad_key((const char *)lv_event_get_user_data(e));
}

static void make_key(lv_obj_t *grid, const char *key, const char *caption, const char *bg,
                     const char *fg, int col, int row, int span)
{
    lv_obj_t *b = lv_button_create(grid);
    lv_obj_remove_style_all(b);
    lv_obj_set_grid_cell(b, LV_GRID_ALIGN_STRETCH, col, span, LV_GRID_ALIGN_STRETCH, row, 1);
    lv_obj_set_style_radius(b, hmi_radius("radiusMd"), 0);
    lv_obj_set_style_bg_color(b, hmi_colour(bg), 0);
    lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_opa(b, LV_OPA_70, LV_STATE_PRESSED);
    lv_obj_set_style_border_color(b, hmi_colour("border"), 0);
    lv_obj_set_style_border_width(b, 1, 0);
    lv_obj_t *t = lv_label_create(b);
    lv_obj_set_style_text_font(t, hmi_font(hmi_font_size("fontSizeLg"), 500), 0);
    lv_obj_set_style_text_color(t, hmi_colour(fg), 0);
    lv_label_set_text(t, caption);
    lv_obj_center(t);
    lv_obj_add_event_cb(b, keypad_button_cb, LV_EVENT_CLICKED, (void *)key);
}

static void build_keypad(void)
{
    popup_t *p = g_popup;
    p->root = make_scrim();

    lv_obj_t *card = lv_obj_create(p->root);
    lv_obj_remove_style_all(card);
    lv_obj_set_size(card, 300, LV_SIZE_CONTENT);
    lv_obj_center(card);
    lv_obj_remove_flag(card, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(card, hmi_colour("card"), 0);
    lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(card, hmi_colour("border"), 0);
    lv_obj_set_style_border_width(card, 1, 0);
    lv_obj_set_style_radius(card, hmi_radius("radiusLg"), 0);
    lv_obj_set_style_pad_all(card, 12, 0);
    lv_obj_set_style_pad_row(card, 8, 0);
    lv_obj_set_flex_flow(card, LV_FLEX_FLOW_COLUMN);

    lv_obj_t *box = lv_obj_create(card);
    lv_obj_remove_style_all(box);
    lv_obj_set_size(box, lv_pct(100), 48);
    lv_obj_remove_flag(box, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(box, hmi_colour("background"), 0);
    lv_obj_set_style_bg_opa(box, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(box, hmi_colour("input"), 0);
    lv_obj_set_style_border_width(box, 1, 0);
    lv_obj_set_style_radius(box, hmi_radius("radiusMd"), 0);
    p->entry_label = lv_label_create(box);
    lv_obj_set_style_text_font(p->entry_label, hmi_font(hmi_font_size("fontSizeXl"), 600), 0);
    lv_obj_set_style_text_color(p->entry_label, hmi_colour("foreground"), 0);
    lv_obj_align(p->entry_label, LV_ALIGN_RIGHT_MID, -12, 0);
    keypad_show_entry();

    p->error_label = lv_label_create(card);
    lv_obj_set_style_text_font(p->error_label, hmi_font(hmi_font_size("fontSizeSm"), 500), 0);
    lv_obj_set_style_text_color(p->error_label, hmi_colour("destructive"), 0);
    lv_label_set_text(p->error_label, "");
    lv_obj_add_flag(p->error_label, LV_OBJ_FLAG_HIDDEN);

    static const int32_t cols[] = {LV_GRID_FR(1), LV_GRID_FR(1), LV_GRID_FR(1), LV_GRID_FR(1),
                                   LV_GRID_TEMPLATE_LAST};
    static const int32_t rows[] = {52, 52, 52, 52, 52, LV_GRID_TEMPLATE_LAST};
    lv_obj_t *grid = lv_obj_create(card);
    lv_obj_remove_style_all(grid);
    lv_obj_set_size(grid, lv_pct(100), LV_SIZE_CONTENT);
    lv_obj_remove_flag(grid, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_pad_row(grid, 6, 0);
    lv_obj_set_style_pad_column(grid, 6, 0);
    lv_obj_set_grid_dsc_array(grid, cols, rows);

    static const char *digits[3][3] = {{"7", "8", "9"}, {"4", "5", "6"}, {"1", "2", "3"}};
    for (int r = 0; r < 3; r++)
        for (int c = 0; c < 3; c++)
            make_key(grid, digits[r][c], digits[r][c], "secondary", "secondaryForeground", c, r, 1);
    // Inter has no FontAwesome glyphs, so the backspace key is spelled out.
    make_key(grid, "BS", "Del", "muted", "foreground", 3, 0, 1);
    make_key(grid, "C", "C", "muted", "foreground", 3, 1, 1);
    make_key(grid, "-", "+/-", "muted", "foreground", 3, 2, 1);
    make_key(grid, "0", "0", "secondary", "secondaryForeground", 0, 3, 2);
    make_key(grid, ".", ".", "secondary", "secondaryForeground", 2, 3, 1);
    make_key(grid, "CANCEL", "Cancel", "muted", "foreground", 0, 4, 2);
    make_key(grid, "OK", "OK", "primary", "primaryForeground", 2, 4, 2);
}

bool hmi_input_open_numeric(hmi_widget_t *w, double value, double min, double max, int decimals,
                            hmi_input_numeric_cb done, void *user)
{
    (void)w;
    if (g_popup || !hmi_modal_claim(KEYPAD_OWNER)) return false;
    popup_t *p = calloc(1, sizeof *p);
    if (!p) { hmi_modal_release(KEYPAD_OWNER); return false; }
    if (decimals < 0) decimals = 0;
    if (decimals > 12) decimals = 12;
    p->done_num = done;
    p->user = user;
    p->min = min;
    p->max = max;
    p->decimals = decimals;
    snprintf(p->entry, sizeof p->entry, "%.*f", decimals, value);
    g_popup = p;
    build_keypad();
    return true;
}

// -- text keyboard --------------------------------------------------------------

static void keyboard_ok(void)
{
    char text[256];
    snprintf(text, sizeof text, "%s", lv_textarea_get_text(g_popup->textarea));
    hmi_input_text_cb done = g_popup->done_text;
    void *user = g_popup->user;
    close_popup();
    if (done) done(text, user);
}

static void keyboard_event_cb(lv_event_t *e)
{
    if (!g_popup || !g_popup->is_text) return;
    lv_event_code_t code = lv_event_get_code(e);
    if (code == LV_EVENT_READY) keyboard_ok();
    else if (code == LV_EVENT_CANCEL) close_popup();
}

bool hmi_input_open_text(hmi_widget_t *w, const char *text, hmi_input_text_cb done, void *user)
{
    (void)w;
    if (g_popup || !hmi_modal_claim(KEYBOARD_OWNER)) return false;
    popup_t *p = calloc(1, sizeof *p);
    if (!p) { hmi_modal_release(KEYBOARD_OWNER); return false; }
    p->is_text = true;
    p->done_text = done;
    p->user = user;
    g_popup = p;
    p->root = make_scrim();

    lv_obj_t *ta = lv_textarea_create(p->root);
    lv_textarea_set_one_line(ta, true);
    lv_textarea_set_max_length(ta, 255);
    lv_obj_set_width(ta, lv_pct(90));
    lv_obj_align(ta, LV_ALIGN_TOP_MID, 0, 16);
    lv_obj_set_style_text_font(ta, hmi_font(hmi_font_size("fontSizeLg"), 400), 0);
    // The kit's input look, not LVGL's default light theme.
    lv_obj_set_style_bg_color(ta, hmi_colour("background"), 0);
    lv_obj_set_style_bg_opa(ta, LV_OPA_COVER, 0);
    lv_obj_set_style_text_color(ta, hmi_colour("foreground"), 0);
    lv_obj_set_style_border_color(ta, hmi_colour("input"), 0);
    lv_obj_set_style_border_color(ta, hmi_colour("primary"), LV_STATE_FOCUSED);
    lv_obj_set_style_border_width(ta, 1, 0);
    lv_obj_set_style_radius(ta, hmi_radius("radiusMd"), 0);
    lv_obj_set_style_bg_color(ta, hmi_colour("foreground"), LV_PART_CURSOR | LV_STATE_FOCUSED);
    lv_obj_set_style_border_color(ta, hmi_colour("foreground"), LV_PART_CURSOR | LV_STATE_FOCUSED);
    lv_textarea_set_text(ta, text ? text : "");
    lv_obj_add_state(ta, LV_STATE_FOCUSED);   // show the cursor
    p->textarea = ta;

    lv_obj_t *kb = lv_keyboard_create(p->root);
    lv_keyboard_set_mode(kb, LV_KEYBOARD_MODE_TEXT_LOWER);
    lv_keyboard_set_textarea(kb, ta);
    // Kit colours; the key captions keep LVGL's font, which carries the
    // backspace/enter/arrow symbols Inter does not have.
    lv_obj_set_style_bg_color(kb, hmi_colour("card"), 0);
    lv_obj_set_style_bg_opa(kb, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(kb, hmi_colour("border"), 0);
    lv_obj_set_style_border_width(kb, 1, 0);
    lv_obj_set_style_border_side(kb, LV_BORDER_SIDE_TOP, 0);
    lv_obj_set_style_bg_color(kb, hmi_colour("secondary"), LV_PART_ITEMS);
    lv_obj_set_style_text_color(kb, hmi_colour("foreground"), LV_PART_ITEMS);
    lv_obj_set_style_radius(kb, hmi_radius("radiusMd"), LV_PART_ITEMS);
    lv_obj_set_style_border_width(kb, 0, LV_PART_ITEMS);
    lv_obj_set_style_shadow_width(kb, 0, LV_PART_ITEMS);
    lv_obj_set_style_bg_color(kb, hmi_colour("muted"), LV_PART_ITEMS | LV_STATE_CHECKED);
    lv_obj_set_style_text_color(kb, hmi_colour("foreground"), LV_PART_ITEMS | LV_STATE_CHECKED);
    lv_obj_set_style_bg_color(kb, hmi_colour("primary"), LV_PART_ITEMS | LV_STATE_PRESSED);
    lv_obj_add_event_cb(kb, keyboard_event_cb, LV_EVENT_READY, NULL);
    lv_obj_add_event_cb(kb, keyboard_event_cb, LV_EVENT_CANCEL, NULL);
    return true;
}

// -- shared ---------------------------------------------------------------------

bool hmi_input_is_open(void) { return g_popup != NULL; }

bool hmi_input_press(const char *key)
{
    if (!g_popup || !key) return false;
    if (!g_popup->is_text) return keypad_key(key);
    if (strcmp(key, "OK") == 0) { keyboard_ok(); return true; }
    if (strcmp(key, "CANCEL") == 0) { close_popup(); return true; }
    return false;
}

const char *hmi_input_entry(void)
{
    if (!g_popup) return "";
    if (g_popup->is_text) return lv_textarea_get_text(g_popup->textarea);
    return g_popup->entry;
}

bool hmi_input_set_text(const char *text)
{
    if (!g_popup || !g_popup->is_text) return false;
    lv_textarea_set_text(g_popup->textarea, text ? text : "");
    return true;
}

bool hmi_input_error_shown(void)
{
    return g_popup && !g_popup->is_text && g_popup->error_label &&
           !lv_obj_has_flag(g_popup->error_label, LV_OBJ_FLAG_HIDDEN);
}
