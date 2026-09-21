// theme.h -- the Shadcn tokens for LVGL: colours by name (Theme.qml's
// property names, both modes), fonts (the kit's Inter, by pixel size and
// weight, cached) and the kit directory (fonts/, icons/).
//
// FROZEN (Phase 3 contract). Widgets never hard-code a colour: they ask for
// the token the QML widget reads (`Theme.autoAccent` -> hmi_colour("autoAccent")).
#pragma once

#include <stdbool.h>

#include "lvgl/lvgl.h"

// Locates the kit: <kit_dir>/fonts/Inter-*.ttf and <kit_dir>/icons/*.png.
// Order: $HMI_UI_KIT, <exe>/../../../../ui/qml/Shadcn (a checkout),
// /usr/lib/hmi/qml/Shadcn (the panel). Returns the directory used.
const char *hmi_theme_init(const char *kit_dir_override, bool dark);
const char *hmi_theme_kit_dir(void);
bool hmi_theme_is_dark(void);
void hmi_theme_set_dark(bool dark);

// Colour token -> LVGL colour. Unknown token: magenta, plus one warning log.
lv_color_t hmi_colour(const char *token);
// The token's alpha (Theme tokens are opaque; "#aarrggbb" literals are not).
lv_opa_t hmi_colour_opa(const char *token);
// A literal "#rrggbb" / "#aarrggbb" / "#rgb". Unknown -> magenta, opa 255.
lv_color_t hmi_colour_hex(const char *hex, lv_opa_t *opa_out);

// Weights as Theme.qml numbers: 400 normal, 500 medium, 600 semibold, 700 bold.
// Sizes are pixel sizes as in the QML (font.pixelSize). Cached per (size, weight);
// never freed (fonts are shared by every label of that size).
const lv_font_t *hmi_font(int pixel_size, int weight);

// Theme.fontSizeXs .. fontSize3Xl and radiusSm/Md/Lg as in Theme.qml.
int hmi_font_size(const char *token);
int hmi_radius(const char *token);
