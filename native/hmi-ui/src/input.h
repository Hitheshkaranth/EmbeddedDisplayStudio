// input.h -- CONTRACT 13.5 operator input: numeric keypad and text keyboard
// on lv_layer_top(). FROZEN (wave 1, W5).
//
// Both claim the modal.h slot (owner "keypad" / "keyboard") and refuse to
// open (return false) when it is taken. They close -- deleting their LVGL
// objects and releasing the slot -- on OK (when accepted) or Cancel.
//
// Keypad: keys "0".."9", ".", "-", "BS" (backspace), "C" (clear), "OK",
// "CANCEL". The entry starts as the value formatted with `decimals`
// ("%.*f"). "-" toggles a leading minus; "." is ignored when one is present.
// OK parses the entry: not a number, or outside [min, max], keeps the pad
// open and shows "<min>..<max>" (both "%g") in hmi_colour("destructive");
// otherwise the value is rounded half away from zero to `decimals`
// (12.25 at 1 decimal is 12.3), the pad closes, and
// done(value, user) is called exactly once. Cancel closes without calling.
//
// Keyboard: an lv_textarea with the text plus an lv_keyboard (text mode);
// the keyboard's OK (LV_EVENT_READY) or hmi_input_press("OK") calls
// done(text, user) and closes; Cancel (LV_EVENT_CANCEL / "CANCEL") closes.
//
// The widgets (w_shnuminput.c, w_shinput.c):
//   ShNumInput: LV_EVENT_CLICKED on the widget's root object (w->native)
//     opens the keypad with (value, minValue, maxValue, decimalPlaces) --
//     not when "enabled" is false. The -/+ buttons keep their own behaviour
//     and do not open it. On OK the widget shows the value and emits
//     "valueChanged" with it (HMI_V_NUM).
//   ShInput: LV_EVENT_CLICKED on w->native opens the keyboard with its text
//     -- not when "readOnly" is true or "enabled" false. On OK the widget
//     shows the text and emits "accepted" with it (HMI_V_STR).
#pragma once

#include <stdbool.h>

#include "model.h"

typedef void (*hmi_input_numeric_cb)(double value, void *user);
typedef void (*hmi_input_text_cb)(const char *text, void *user);

bool hmi_input_open_numeric(hmi_widget_t *w, double value, double min, double max, int decimals,
                            hmi_input_numeric_cb done, void *user);
bool hmi_input_open_text(hmi_widget_t *w, const char *text, hmi_input_text_cb done, void *user);
bool hmi_input_is_open(void);

// Test hooks (the on-screen buttons call the same code).
bool hmi_input_press(const char *key);     // false when no pad/keyboard is open or unknown key
const char *hmi_input_entry(void);          // current entry text; "" when closed
bool hmi_input_set_text(const char *text);  // keyboard only: replace the text
bool hmi_input_error_shown(void);           // keypad: the range message is visible
