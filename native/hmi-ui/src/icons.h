// icons.h -- the kit's Tabler icons for widgets (ShIcon in the QML kit).
//
// schema/gen_icons.py renders every icon of ui/qml/Shadcn/TablerIcons.js
// to <kit>/icons/<name>.png (96 px, white on transparent). A widget asks
// for an icon by the same name the QML uses (`icon: "temperature"`), at a
// pixel size, in a colour; the runtime scales and recolours the PNG.
//
// FROZEN (wave 2 contract).
#pragma once

#include <stdbool.h>

#include "lvgl/lvgl.h"

// An lv_image child of `parent`, `size` x `size`, drawn in `colour`. An
// unknown name gives the same red-bordered placeholder ShIcon.qml shows.
// Position it like any object (lv_obj_set_pos / lv_obj_align).
lv_obj_t *hmi_icon_create(lv_obj_t *parent, const char *name, int size, lv_color_t colour);
// Change an existing icon's glyph, size or colour ("" hides it).
void hmi_icon_set(lv_obj_t *icon, const char *name, int size, lv_color_t colour);
// True when <kit>/icons/<name>.png exists.
bool hmi_icon_exists(const char *name);
