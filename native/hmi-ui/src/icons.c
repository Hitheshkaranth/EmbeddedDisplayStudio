// icons.c -- see icons.h.
#include "icons.h"

#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include "log.h"
#include "theme.h"

#define ICON_PX 96   // gen_icons.py's raster size

static bool icon_path(const char *name, char *buf, size_t len)
{
    if (!name || !*name || !hmi_theme_kit_dir()[0]) return false;
    snprintf(buf, len, "%s/icons/%s.png", hmi_theme_kit_dir(), name);
    return access(buf, R_OK) == 0;
}

bool hmi_icon_exists(const char *name)
{
    char path[700];
    return icon_path(name, path, sizeof path);
}

static void placeholder(lv_obj_t *icon, bool on)
{
    // ShIcon.qml: a 1 px Theme.destructive border around the empty slot.
    lv_obj_set_style_border_width(icon, on ? 1 : 0, 0);
    lv_obj_set_style_border_color(icon, hmi_colour("destructive"), 0);
    lv_obj_set_style_border_opa(icon, on ? LV_OPA_COVER : LV_OPA_TRANSP, 0);
}

void hmi_icon_set(lv_obj_t *icon, const char *name, int size, lv_color_t colour)
{
    char path[700];
    if (size < 1) size = 1;
    lv_obj_set_size(icon, size, size);
    if (!name || !*name) {
        lv_image_set_src(icon, NULL);
        placeholder(icon, false);
        lv_obj_add_flag(icon, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    lv_obj_remove_flag(icon, LV_OBJ_FLAG_HIDDEN);
    if (!icon_path(name, path, sizeof path)) {
        static int warned = 0;
        if (warned++ < 20) hmi_log(HMI_LOG_WARNING, "ShIcon: Unknown icon name '%s'", name);
        lv_image_set_src(icon, NULL);
        placeholder(icon, true);
        return;
    }
    placeholder(icon, false);
    char src[720];
    snprintf(src, sizeof src, "A:%s", path);
    lv_image_set_src(icon, src);
    lv_image_set_scale(icon, (uint32_t)(256.0 * size / ICON_PX + 0.5));
    lv_image_set_inner_align(icon, LV_IMAGE_ALIGN_CENTER);
    lv_obj_set_style_image_recolor(icon, colour, 0);
    lv_obj_set_style_image_recolor_opa(icon, LV_OPA_COVER, 0);
}

lv_obj_t *hmi_icon_create(lv_obj_t *parent, const char *name, int size, lv_color_t colour)
{
    lv_obj_t *icon = lv_image_create(parent);
    lv_obj_remove_style_all(icon);
    hmi_icon_set(icon, name, size, colour);
    return icon;
}
