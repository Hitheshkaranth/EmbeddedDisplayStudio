// tests/test_overlay.c -- CONTRACT 13.5 link-lost banner and screen idle.
// Wave 1 gate for W5 (FROZEN).
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

#include "check.h"
#include "overlay.h"
#include "rt_harness.h"

static const char *IDLE_DESIGN =
    "{\"version\":1,\"name\":\"ov\",\"screen\":{\"width\":800,\"height\":480,"
    " \"idle\":{\"dimAfterS\":10,\"dimPercent\":40,\"offAfterS\":30}},\"pages\":[{\"id\":\"main\",\"widgets\":[]}]}";
static const char *PLAIN_DESIGN =
    "{\"version\":1,\"name\":\"ov\",\"screen\":{\"width\":800,\"height\":480},\"pages\":[{\"id\":\"main\",\"widgets\":[]}]}";

static bool top_has_label(const char *text)
{
    lv_obj_t *top = lv_layer_top();
    for (uint32_t i = 0; i < lv_obj_get_child_count(top); i++) {
        lv_obj_t *o = lv_obj_get_child(top, (int32_t)i);
        if (lv_obj_has_flag(o, LV_OBJ_FLAG_HIDDEN)) continue;
        for (uint32_t k = 0; k < lv_obj_get_child_count(o); k++) {
            lv_obj_t *c = lv_obj_get_child(o, (int32_t)k);
            if (lv_obj_check_type(c, &lv_label_class) && strcmp(lv_label_get_text(c), text) == 0) return true;
        }
    }
    return false;
}

static long read_int(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) return -1;
    long v = -1;
    if (fscanf(f, "%ld", &v) != 1) v = -1;
    fclose(f);
    return v;
}

static void test_banner(void)
{
    hmi_project_t *p = rt_load_json(PLAIN_DESIGN);
    hmi_overlay_t *o = hmi_overlay_create(p, true);
    hmi_overlay_tick(o, 1000, 0);                  // first tick starts the 5 s grace
    CHECK(!hmi_overlay_banner_visible(o));
    hmi_overlay_tick(o, 5900, 0);
    CHECK(!hmi_overlay_banner_visible(o));
    hmi_overlay_tick(o, 6100, 0);                  // never came online within 5 s
    CHECK(hmi_overlay_banner_visible(o));
    CHECK(top_has_label("No connection to controller - values may be stale"));
    hmi_overlay_link(o, true);
    CHECK(!hmi_overlay_banner_visible(o));
    CHECK(!top_has_label("No connection to controller - values may be stale"));
    hmi_overlay_link(o, false);                    // lost after being online
    CHECK(hmi_overlay_banner_visible(o));
    hmi_overlay_link(o, true);
    CHECK(!hmi_overlay_banner_visible(o));
    hmi_overlay_destroy(o);
    CHECK(lv_obj_get_child_count(lv_layer_top()) == 0);   // cleans up after itself

    // no link object: never a banner
    o = hmi_overlay_create(p, false);
    hmi_overlay_tick(o, 1000, 0);
    hmi_overlay_tick(o, 60000, 0);
    hmi_overlay_link(o, false);
    CHECK(!hmi_overlay_banner_visible(o));
    hmi_overlay_destroy(o);
    hmi_project_free(p);
}

static void test_idle(void)
{
    char dir[] = "/tmp/hmi-bl-XXXXXX";
    CHECK(mkdtemp(dir) != NULL);
    char sub[600], bright[700], maxb[700];
    snprintf(sub, sizeof sub, "%s/panel0", dir);
    mkdir(sub, 0755);
    snprintf(bright, sizeof bright, "%s/brightness", sub);
    snprintf(maxb, sizeof maxb, "%s/max_brightness", sub);
    FILE *f = fopen(maxb, "w"); fputs("200\n", f); fclose(f);
    f = fopen(bright, "w"); fputs("200\n", f); fclose(f);
    setenv("HMI_BACKLIGHT_DIR", dir, 1);

    hmi_project_t *p = rt_load_json(IDLE_DESIGN);
    CHECK(p && p->idle_dim_s == 10 && p->idle_dim_pct == 40 && p->idle_off_s == 30);
    hmi_overlay_t *o = hmi_overlay_create(p, false);
    CHECK(hmi_overlay_backlight_percent(o) == 100);
    hmi_overlay_tick(o, 1000, 9000);
    CHECK(hmi_overlay_backlight_percent(o) == 100);
    hmi_overlay_tick(o, 2000, 10000);
    CHECK(hmi_overlay_backlight_percent(o) == 40);
    CHECK(read_int(bright) == 80);                 // 200 * 40 %
    CHECK(!hmi_overlay_blanked(o));
    hmi_overlay_tick(o, 3000, 30000);
    CHECK(hmi_overlay_backlight_percent(o) == 0);
    CHECK(read_int(bright) == 0);
    CHECK(hmi_overlay_blanked(o));
    CHECK(lv_obj_get_child_count(lv_layer_top()) > 0);
    CHECK(hmi_overlay_wake(o));                    // the waking touch is swallowed
    CHECK(!hmi_overlay_blanked(o));
    CHECK(hmi_overlay_backlight_percent(o) == 100);
    CHECK(read_int(bright) == 200);
    CHECK(!hmi_overlay_wake(o));                   // not blanked: not swallowed
    hmi_overlay_tick(o, 4000, 20);                 // activity: stays bright
    CHECK(hmi_overlay_backlight_percent(o) == 100);
    // the file is written only when the level changes
    f = fopen(bright, "w"); fputs("123\n", f); fclose(f);
    hmi_overlay_tick(o, 5000, 50);
    CHECK(read_int(bright) == 123);
    hmi_overlay_destroy(o);
    hmi_project_free(p);

    // idle off: nothing ever dims
    p = rt_load_json(PLAIN_DESIGN);
    o = hmi_overlay_create(p, false);
    hmi_overlay_tick(o, 1000, 10u * 3600u * 1000u);
    CHECK(hmi_overlay_backlight_percent(o) == 100 && !hmi_overlay_blanked(o));
    hmi_overlay_destroy(o);
    hmi_project_free(p);

    // no backlight directory: the overlay alone
    setenv("HMI_BACKLIGHT_DIR", "/nonexistent-hmi-backlight", 1);
    p = rt_load_json(IDLE_DESIGN);
    o = hmi_overlay_create(p, false);
    hmi_overlay_tick(o, 1000, 31000);
    CHECK(hmi_overlay_blanked(o) && hmi_overlay_backlight_percent(o) == 0);
    hmi_overlay_destroy(o);
    hmi_project_free(p);
    unsetenv("HMI_BACKLIGHT_DIR");
    remove(bright); remove(maxb); rmdir(sub); rmdir(dir);
}

int main(void)
{
    rt_lvgl_once();
    lv_tick_set_cb(rt_now_ms);
    test_banner();
    test_idle();
    return check_summary("test_overlay");
}
