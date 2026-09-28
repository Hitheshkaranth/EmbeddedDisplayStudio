// modal.h -- CONTRACT 13.5 "one popup at a time": the confirmation dialog
// (actions.c), the numeric keypad and the keyboard (input.c) all claim this
// single slot before they open and release it when they close.
#pragma once

#include <stdbool.h>

// Claim the slot for `owner` (any non-NULL tag, e.g. "confirm", "keypad").
// false when another owner holds it.
bool hmi_modal_claim(const char *owner);
// Release it; only the holder's release counts.
void hmi_modal_release(const char *owner);
// The current holder, or NULL.
const char *hmi_modal_owner(void);
