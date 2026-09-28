// input.c -- see input.h (CONTRACT 13.5). STUB: wave 1 W5 implements.
#include "input.h"

bool hmi_input_open_numeric(hmi_widget_t *w, double value, double min, double max, int decimals,
                            hmi_input_numeric_cb done, void *user)
{
    (void)w; (void)value; (void)min; (void)max; (void)decimals; (void)done; (void)user;
    return false;
}

bool hmi_input_open_text(hmi_widget_t *w, const char *text, hmi_input_text_cb done, void *user)
{
    (void)w; (void)text; (void)done; (void)user;
    return false;
}

bool hmi_input_is_open(void) { return false; }
bool hmi_input_press(const char *key) { (void)key; return false; }
const char *hmi_input_entry(void) { return ""; }
bool hmi_input_set_text(const char *text) { (void)text; return false; }
bool hmi_input_error_shown(void) { return false; }
