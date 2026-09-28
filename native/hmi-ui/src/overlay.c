// overlay.c -- see overlay.h (CONTRACT 13.5). STUB: wave 1 W5 implements.
#include "overlay.h"

#include <stdlib.h>

struct hmi_overlay {
    int unused;
};

hmi_overlay_t *hmi_overlay_create(const hmi_project_t *project, bool has_link)
{
    (void)project; (void)has_link;
    return calloc(1, sizeof(hmi_overlay_t));
}

void hmi_overlay_destroy(hmi_overlay_t *o) { free(o); }
void hmi_overlay_link(hmi_overlay_t *o, bool online) { (void)o; (void)online; }
void hmi_overlay_tick(hmi_overlay_t *o, uint32_t now_ms, uint32_t inactive_ms)
{
    (void)o; (void)now_ms; (void)inactive_ms;
}
bool hmi_overlay_banner_visible(const hmi_overlay_t *o) { (void)o; return false; }
int hmi_overlay_backlight_percent(const hmi_overlay_t *o) { (void)o; return 100; }
bool hmi_overlay_blanked(const hmi_overlay_t *o) { (void)o; return false; }
bool hmi_overlay_wake(hmi_overlay_t *o) { (void)o; return false; }
