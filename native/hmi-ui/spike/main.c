/* native/hmi-ui/spike/main.c -- feasibility spike for the Qt-free runtime.
 *
 * Draws a cluster-style arc gauge and a readout with LVGL 9:
 *   hmi-ui-spike drm [/dev/dri/cardN]     on the panel, straight to DRM/KMS
 *   hmi-ui-spike png out.png [WxH]        headless, into a PNG (QC / previews)
 * The value sweeps so a live display visibly animates; drm mode exits after
 * 8 s and reports the frame rate. Proves: display ownership without Weston
 * or Qt, software rendering speed, the TTF font path (Inter from the kit,
 * HMI_UI_FONT=<ttf>), and a headless render path for pixel comparison
 * against the QML kit.
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "lvgl/lvgl.h"
#include "lvgl/src/libs/lodepng/lodepng.h"

static uint32_t now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)(ts.tv_sec * 1000 + ts.tv_nsec / 1000000);
}

/* Headless display: LVGL renders into our buffer; flush is a no-op. */
static uint8_t *g_fb;
static void headless_flush(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    (void)area; (void)px_map;
    lv_display_flush_ready(disp);
}

static lv_obj_t *build_scene(int w, int h, const char *font_path)
{
    lv_obj_t *scr = lv_screen_active();
    lv_obj_set_style_bg_color(scr, lv_color_hex(0x101418), 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);

    int d = w < h ? w : h;
    lv_obj_t *arc = lv_arc_create(scr);
    lv_obj_set_size(arc, (int)(d * 0.9), (int)(d * 0.9));
    lv_obj_center(arc);
    lv_arc_set_rotation(arc, 150);
    lv_arc_set_bg_angles(arc, 0, 240);
    lv_arc_set_range(arc, 0, 8000);
    lv_arc_set_value(arc, 3200);
    lv_obj_remove_style(arc, NULL, LV_PART_KNOB);
    lv_obj_remove_flag(arc, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_arc_width(arc, (int)(d * 0.05), LV_PART_MAIN);
    lv_obj_set_style_arc_width(arc, (int)(d * 0.05), LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(arc, lv_color_hex(0x1a222e), LV_PART_MAIN);
    lv_obj_set_style_arc_color(arc, lv_color_hex(0x22a8ff), LV_PART_INDICATOR);
    lv_obj_set_style_arc_rounded(arc, false, LV_PART_MAIN);
    lv_obj_set_style_arc_rounded(arc, false, LV_PART_INDICATOR);

    lv_obj_t *readout = lv_label_create(scr);
    lv_label_set_text(readout, "3200");
    lv_obj_set_style_text_color(readout, lv_color_hex(0xffffff), 0);
    lv_font_t *big = font_path ? lv_tiny_ttf_create_file(font_path, (int)(d * 0.28)) : NULL;
    lv_obj_set_style_text_font(readout, big ? big : LV_FONT_DEFAULT, 0);
    lv_obj_align(readout, LV_ALIGN_CENTER, 0, -(int)(d * 0.07));

    lv_obj_t *unit = lv_label_create(scr);
    lv_label_set_text(unit, "RPM");
    lv_obj_set_style_text_color(unit, lv_color_hex(0x8a97a8), 0);
    lv_font_t *small = font_path ? lv_tiny_ttf_create_file(font_path, (int)(d * 0.08)) : NULL;
    lv_obj_set_style_text_font(unit, small ? small : LV_FONT_DEFAULT, 0);
    lv_obj_align_to(unit, readout, LV_ALIGN_OUT_BOTTOM_MID, 0, 2);
    return arc;
}

int main(int argc, char **argv)
{
    const char *mode = argc > 1 ? argv[1] : "png";
    /* LVGL's file layer addresses drives by letter (lv_conf.h: STDIO on 'A'). */
    static char font_buf[512];
    const char *font = getenv("HMI_UI_FONT");
    if (font && font[1] != ':') {
        snprintf(font_buf, sizeof font_buf, "A:%s", font);
        font = font_buf;
    }

    lv_init();
    lv_tick_set_cb(now_ms);

    lv_display_t *disp;
    int w = 1024, h = 768;
    if (strcmp(mode, "drm") == 0) {
        disp = lv_linux_drm_create();
        lv_linux_drm_set_file(disp, argc > 2 ? argv[2] : "/dev/dri/card1", -1);
        w = lv_display_get_horizontal_resolution(disp);
        h = lv_display_get_vertical_resolution(disp);
        fprintf(stderr, "drm display %dx%d\n", w, h);
    } else {
        if (argc > 3)
            sscanf(argv[3], "%dx%d", &w, &h);
        disp = lv_display_create(w, h);
        g_fb = malloc((size_t)w * h * 4);
        lv_display_set_color_format(disp, LV_COLOR_FORMAT_XRGB8888);
        lv_display_set_buffers(disp, g_fb, NULL, (uint32_t)w * h * 4, LV_DISPLAY_RENDER_MODE_DIRECT);
        lv_display_set_flush_cb(disp, headless_flush);
    }

    lv_obj_t *arc = build_scene(w, h, font);

    uint32_t t0 = now_ms();
    uint32_t frames = 0;
    if (strcmp(mode, "drm") == 0) {
        while (now_ms() - t0 < 8000) {
            uint32_t t = now_ms() - t0;
            lv_arc_set_value(arc, 3200 + (int)(3000.0 * (0.5 - 0.5 * cos(t / 800.0))));
            lv_timer_handler();
            ++frames;
            usleep(5000);
        }
        uint32_t dt = now_ms() - t0;
        fprintf(stderr, "%u frames in %u ms (%.1f fps)\n", frames, dt, frames * 1000.0 / dt);
    } else {
        lv_timer_handler();
        lv_refr_now(disp);
        uint8_t *rgba = malloc((size_t)w * h * 4);     /* XRGB8888 -> RGBA */
        for (size_t i = 0; i < (size_t)w * h; ++i) {
            rgba[i * 4 + 0] = g_fb[i * 4 + 2];
            rgba[i * 4 + 1] = g_fb[i * 4 + 1];
            rgba[i * 4 + 2] = g_fb[i * 4 + 0];
            rgba[i * 4 + 3] = 255;
        }
        const char *out = argc > 2 ? argv[2] : "spike.png";
        /* Encode in memory: LVGL's lodepng routes file I/O through lv_fs. */
        unsigned char *png = NULL;
        size_t png_size = 0;
        unsigned err = lodepng_encode32(&png, &png_size, rgba, (unsigned)w, (unsigned)h);
        if (!err) {
            FILE *f = fopen(out, "wb");
            if (f) {
                fwrite(png, 1, png_size, f);
                fclose(f);
            } else {
                err = 79;
            }
        }
        fprintf(stderr, "%s: %s\n", out, err ? lodepng_error_text(err) : "written");
        free(png);
        free(rgba);
    }
    return 0;
}
