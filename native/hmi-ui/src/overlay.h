// overlay.h -- CONTRACT 13.5 link-lost banner and screen idle (dim / off).
// FROZEN (wave 1, W5).
//
// Link: created with has_link=false (headless renders) the overlay never
// shows a banner. With a link, the banner (lv_layer_top, full width, top,
// hmi_colour("destructive") background, text exactly
// "No connection to controller - values may be stale") shows when
// hmi_overlay_link(false) follows an online period, or when no
// hmi_overlay_link(true) arrived within 5000 ms of the first tick; it hides
// on hmi_overlay_link(true).
//
// Idle: from the project's idle_dim_s / idle_dim_pct / idle_off_s (0 = never).
// hmi_overlay_tick gets the milliseconds since the last touch (the runtime
// passes lv_display_get_inactive_time). inactive >= off (when set): backlight
// 0 and a black full-screen object on lv_layer_top that swallows the touch
// that wakes it; else inactive >= dim (when set): backlight dim_pct; else 100.
// The backlight is written only when the level changes: the first directory
// in $HMI_BACKLIGHT_DIR or /sys/class/backlight/, file "brightness" =
// round(max_brightness * pct / 100) (max read once). No backlight directory:
// only the black overlay; hmi_overlay_backlight_percent still reports the
// level it would have set.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "model.h"

typedef struct hmi_overlay hmi_overlay_t;

hmi_overlay_t *hmi_overlay_create(const hmi_project_t *project, bool has_link);
void hmi_overlay_destroy(hmi_overlay_t *o);   // removes its objects; NULL is fine

void hmi_overlay_link(hmi_overlay_t *o, bool online);
// now_ms: monotonic ms (lv_tick_get); inactive_ms: since the last touch.
void hmi_overlay_tick(hmi_overlay_t *o, uint32_t now_ms, uint32_t inactive_ms);

// Test hooks.
bool hmi_overlay_banner_visible(const hmi_overlay_t *o);
int hmi_overlay_backlight_percent(const hmi_overlay_t *o);   // 100 until idle changes it
bool hmi_overlay_blanked(const hmi_overlay_t *o);
// Simulate the touch that wakes an off screen: unblanks, backlight 100, and
// returns true when the screen was blanked (the touch was swallowed).
bool hmi_overlay_wake(hmi_overlay_t *o);
