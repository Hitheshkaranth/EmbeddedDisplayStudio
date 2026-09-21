// display.h -- where the pixels go: DRM/KMS on the panel, or a memory
// buffer that can be written as PNG (QC, Studio previews, tests).
#pragma once

#include <stdbool.h>

#include "lvgl/lvgl.h"

// /dev/dri/cardN via LVGL's DRM driver; the display's native mode.
lv_display_t *hmi_display_drm(const char *device);
// A w x h XRGB8888 buffer; nothing is shown anywhere.
lv_display_t *hmi_display_headless(int w, int h);
// Render everything pending and write the headless buffer as PNG.
bool hmi_display_headless_save(lv_display_t *disp, const char *path);
