// theme.c -- see theme.h.
#include "theme.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "compat.h"
#include "gen/kit_schema.h"
#include "log.h"

static char g_kit_dir[512];
static bool g_dark = true;

static bool has_fonts(const char *dir)
{
    char path[600];
    snprintf(path, sizeof path, "%s/fonts/Inter-Regular.ttf", dir);
    return hmi_path_exists(path);
}

const char *hmi_theme_init(const char *override, bool dark)
{
    g_dark = dark;
    g_kit_dir[0] = '\0';
    const char *env = getenv("HMI_UI_KIT");
    // /usr/lib/hmi/kit is where provisioning puts fonts/ and icons/ on a panel;
    // /usr/lib/hmi/qml/Shadcn is where a panel provisioned for the Qt loader had them.
    const char *candidates[5] = {override, env, NULL, "/usr/lib/hmi/kit", "/usr/lib/hmi/qml/Shadcn"};
    char from_exe[600] = "";
    char exe[512];
    if (hmi_exe_dir(exe, sizeof exe)) {
        // walk up from the binary's directory looking for ui/qml/Shadcn/fonts (a checkout)
        for (;;) {
            snprintf(from_exe, sizeof from_exe, "%s/ui/qml/Shadcn", exe);
            if (has_fonts(from_exe)) break;
            from_exe[0] = '\0';
            char *p = strrchr(exe, '/');
            if (!p || p == exe) break;
            *p = '\0';
        }
    }
    candidates[2] = from_exe[0] ? from_exe : NULL;
    for (int i = 0; i < 5; ++i) {
        if (candidates[i] && *candidates[i] && has_fonts(candidates[i])) {
            snprintf(g_kit_dir, sizeof g_kit_dir, "%s", candidates[i]);
            break;
        }
    }
    if (!g_kit_dir[0])
        hmi_log(HMI_LOG_WARNING, "kit not found (no Inter fonts): text uses the built-in font");
    return g_kit_dir;
}

const char *hmi_theme_kit_dir(void) { return g_kit_dir; }
bool hmi_theme_is_dark(void) { return g_dark; }
void hmi_theme_set_dark(bool dark) { g_dark = dark; }

lv_color_t hmi_colour_hex(const char *hex, lv_opa_t *opa_out)
{
    lv_opa_t opa = LV_OPA_COVER;
    unsigned r = 255, g = 0, b = 255;
    if (hex && hex[0] == '#') {
        size_t len = strlen(hex + 1);
        unsigned v = (unsigned)strtoul(hex + 1, NULL, 16);
        if (len == 6) { r = (v >> 16) & 255; g = (v >> 8) & 255; b = v & 255; }
        else if (len == 8) { opa = (v >> 24) & 255; r = (v >> 16) & 255; g = (v >> 8) & 255; b = v & 255; }
        else if (len == 3) { r = ((v >> 8) & 15) * 17; g = ((v >> 4) & 15) * 17; b = (v & 15) * 17; }
    }
    if (opa_out) *opa_out = opa;
    return lv_color_make((uint8_t)r, (uint8_t)g, (uint8_t)b);
}

lv_color_t hmi_colour(const char *token)
{
    const char *hex = hmi_theme_colour(token, g_dark);
    if (!hex) {
        static int warned = 0;
        if (warned++ < 20)
            hmi_log(HMI_LOG_WARNING, "unknown theme colour '%s'", token);
        return lv_color_make(255, 0, 255);
    }
    return hmi_colour_hex(hex, NULL);
}

lv_opa_t hmi_colour_opa(const char *token)
{
    const char *hex = hmi_theme_colour(token, g_dark);
    lv_opa_t opa = LV_OPA_COVER;
    if (hex) hmi_colour_hex(hex, &opa);
    return opa;
}

typedef struct { int size; int weight; const lv_font_t *font; } font_entry_t;
static font_entry_t g_fonts[128];
static int g_nfonts;

const lv_font_t *hmi_font(int pixel_size, int weight)
{
    if (pixel_size < 4) pixel_size = 4;
    weight = weight >= 700 ? 700 : weight >= 600 ? 600 : weight >= 500 ? 500 : 400;
    for (int i = 0; i < g_nfonts; ++i)
        if (g_fonts[i].size == pixel_size && g_fonts[i].weight == weight)
            return g_fonts[i].font;
    const lv_font_t *font = LV_FONT_DEFAULT;
    if (g_kit_dir[0]) {
        const char *file = weight == 700 ? "Inter-Bold.ttf" : weight == 600 ? "Inter-SemiBold.ttf"
                         : weight == 500 ? "Inter-Medium.ttf" : "Inter-Regular.ttf";
        char path[700];
        snprintf(path, sizeof path, "A:%s/fonts/%s", g_kit_dir, file);
        lv_font_t *f = lv_tiny_ttf_create_file(path, pixel_size);
        if (f) font = f;
        else hmi_log(HMI_LOG_WARNING, "cannot load font %s", path);
    }
    if (g_nfonts < (int)(sizeof g_fonts / sizeof g_fonts[0]))
        g_fonts[g_nfonts++] = (font_entry_t){pixel_size, weight, font};
    return font;
}

int hmi_font_size(const char *token)
{
    static const struct { const char *t; int px; } sizes[] = {
        {"fontSizeXs", 12}, {"fontSizeSm", 14}, {"fontSizeBase", 16}, {"fontSizeLg", 18},
        {"fontSizeXl", 20}, {"fontSizeXxl", 24}, {"fontSizeXxxl", 30}};
    for (size_t i = 0; i < sizeof sizes / sizeof sizes[0]; ++i)
        if (strcmp(sizes[i].t, token) == 0) return sizes[i].px;
    return 16;
}

int hmi_radius(const char *token)
{
    static const struct { const char *t; int px; } radii[] = {
        {"radiusSm", 4}, {"radiusMd", 12}, {"radiusLg", 16}, {"radiusXl", 20}, {"radiusFull", 9999}};
    for (size_t i = 0; i < sizeof radii / sizeof radii[0]; ++i)
        if (strcmp(radii[i].t, token) == 0) return radii[i].px;
    return 4;
}
