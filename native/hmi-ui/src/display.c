// display.c -- see display.h.
#include "display.h"

#include <stdio.h>
#include <stdlib.h>

#include "log.h"
#include "lvgl/src/libs/lodepng/lodepng.h"

lv_display_t *hmi_display_drm(const char *device)
{
    lv_display_t *disp = lv_linux_drm_create();
    lv_linux_drm_set_file(disp, device, -1);
    hmi_log(HMI_LOG_INFO, "display %s %dx%d", device,
            (int)lv_display_get_horizontal_resolution(disp), (int)lv_display_get_vertical_resolution(disp));
    return disp;
}

typedef struct { uint8_t *fb; int w, h; } headless_t;

static void headless_flush(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    (void)area; (void)px_map;
    lv_display_flush_ready(disp);
}

lv_display_t *hmi_display_headless(int w, int h)
{
    headless_t *hd = calloc(1, sizeof *hd);
    hd->w = w; hd->h = h;
    hd->fb = calloc((size_t)w * h, 4);
    lv_display_t *disp = lv_display_create(w, h);
    lv_display_set_color_format(disp, LV_COLOR_FORMAT_XRGB8888);
    lv_display_set_buffers(disp, hd->fb, NULL, (uint32_t)w * h * 4, LV_DISPLAY_RENDER_MODE_DIRECT);
    lv_display_set_flush_cb(disp, headless_flush);
    lv_display_set_user_data(disp, hd);
    return disp;
}

bool hmi_display_headless_save(lv_display_t *disp, const char *path)
{
    headless_t *hd = lv_display_get_user_data(disp);
    if (!hd) return false;
    lv_timer_handler();
    lv_refr_now(disp);
    size_t n = (size_t)hd->w * hd->h;
    unsigned char *rgba = malloc(n * 4);
    for (size_t i = 0; i < n; ++i) {
        rgba[i * 4 + 0] = hd->fb[i * 4 + 2];
        rgba[i * 4 + 1] = hd->fb[i * 4 + 1];
        rgba[i * 4 + 2] = hd->fb[i * 4 + 0];
        rgba[i * 4 + 3] = 255;
    }
    unsigned char *png = NULL;
    size_t png_size = 0;
    unsigned err = lodepng_encode32(&png, &png_size, rgba, (unsigned)hd->w, (unsigned)hd->h);
    bool ok = false;
    if (!err) {
        FILE *f = fopen(path, "wb");   // LVGL's lodepng file I/O goes through lv_fs; write it ourselves
        if (f) { ok = fwrite(png, 1, png_size, f) == png_size; fclose(f); }
    }
    if (!ok) hmi_log(HMI_LOG_ERROR, "cannot write %s (%s)", path, err ? lodepng_error_text(err) : "fopen");
    free(png);
    free(rgba);
    return ok;
}
