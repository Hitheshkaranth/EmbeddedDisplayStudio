// tests/test_widgets.c -- widget behaviour that a still render cannot show:
// what a tap does. Widgets are built headless from a one-widget project, the
// way `hmi-ui --render-widget` builds them.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "check.h"
#include "compat.h"
#include "display.h"
#include "model.h"
#include "registry.h"
#include "theme.h"
#include "src/libs/gif/lv_gif_private.h"

static hmi_project_t *one_widget(const char *type, const char *props_json)
{
    char path[512], err[256];
    FILE *f = hmi_tmpfile(path, sizeof path);
    if (!f) return NULL;
    fprintf(f, "{\"name\":\"t\",\"screen\":{\"width\":320,\"height\":120,\"theme\":\"dark\"},"
               "\"pages\":[{\"id\":\"main\",\"widgets\":[{\"type\":\"%s\",\"id\":\"sample\","
               "\"geometry\":{\"x\":0,\"y\":0,\"width\":160,\"height\":40},\"properties\":%s}]}]}",
            type, props_json);
    fclose(f);
    hmi_project_t *p = hmi_project_load(path, err, sizeof err);
    hmi_remove(path);
    if (!p) fprintf(stderr, "load: %s\n", err);
    return p;
}

static hmi_widget_t *build(hmi_project_t *p)
{
    hmi_widget_t *w = p->pages[0]->widgets[0];
    const hmi_widget_ops_t *ops = hmi_registry_find(w->type);
    w->native = ops->create(w, lv_screen_active());
    hmi_widget_apply_common(w);
    lv_obj_update_layout(lv_screen_active());
    return w;
}

// The knob is the track's only child; its x says which side it is on.
static int32_t knob_x(hmi_widget_t *w)
{
    lv_obj_t *row = lv_obj_get_child(w->native, 0);
    lv_obj_t *track = lv_obj_get_child(row, 0);
    lv_obj_update_layout(lv_screen_active());
    return lv_obj_get_x(lv_obj_get_child(track, 0));
}

static void test_toggle_starts_checked(void)
{
    hmi_project_t *p = one_widget("ShToggle", "{\"checked\":true}");
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    CHECK(knob_x(w) > 2);                  // on the right, like the QML
    lv_obj_delete(w->native);
    hmi_project_free(p);
}

static void test_toggle_tap_flips_it(void)
{
    hmi_project_t *p = one_widget("ShToggle", "{\"checked\":false}");
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    CHECK(knob_x(w) == 2);
    lv_obj_send_event(w->native, LV_EVENT_CLICKED, NULL);
    CHECK(knob_x(w) > 2);
    lv_obj_send_event(w->native, LV_EVENT_CLICKED, NULL);
    CHECK(knob_x(w) == 2);
    lv_obj_delete(w->native);
    hmi_project_free(p);
}

// -- ShAnimatedImage -----------------------------------------------------------
// root -> [clip -> gif, placeholder]
static lv_obj_t *anim_gif(hmi_widget_t *w) { return lv_obj_get_child(lv_obj_get_child(w->native, 0), 0); }
static lv_obj_t *anim_placeholder(hmi_widget_t *w) { return lv_obj_get_child(w->native, 1); }

static void anim_set(hmi_widget_t *w, const char *prop, hmi_value_t v)
{
    hmi_registry_find(w->type)->set_prop(w, prop, &v);
    hmi_value_free(&v);
}

static void anim_free(hmi_project_t *p, hmi_widget_t *w)
{
    hmi_registry_find(w->type)->destroy(w);
    lv_obj_delete(w->native);
    hmi_project_free(p);
}

// The first pixel of the frame on show: 'r' red, 'b' blue, '?' neither.
static char anim_frame(hmi_widget_t *w)
{
    lv_gif_t *g = (lv_gif_t *)anim_gif(w);
    if (!g->gif || !g->imgdsc.data) return '?';
    const uint8_t *px = g->imgdsc.data;            // ARGB8888: B, G, R, A
    if (px[2] > 150 && px[0] < 100) return 'r';
    if (px[0] > 150 && px[2] < 100) return 'b';
    return '?';
}

static void anim_advance(uint32_t ms)
{
    lv_tick_inc(ms);
    lv_timer_handler();
}

static void test_animated_image_missing_file_draws_placeholder(void)
{
    hmi_project_t *p = one_widget("ShAnimatedImage", "{\"source\":\"assets/no_such_truck.gif\"}");
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    CHECK(!lv_gif_is_loaded(anim_gif(w)));
    CHECK(lv_obj_has_flag(anim_gif(w), LV_OBJ_FLAG_HIDDEN));
    CHECK(!lv_obj_has_flag(anim_placeholder(w), LV_OBJ_FLAG_HIDDEN));
    lv_refr_now(NULL);                             // draws without crashing
    // Bindings reaching a widget with nothing loaded are harmless.
    anim_set(w, "playing", hmi_value_bool(false));
    anim_set(w, "playing", hmi_value_bool(true));
    anim_set(w, "speed", hmi_value_num(250));
    anim_set(w, "fillMode", hmi_value_str("Image.Stretch"));
    anim_advance(500);
    // A file that is not a GIF is a placeholder too.
    anim_set(w, "source", hmi_value_str(HMI_REPO_ROOT "/ui/qml/Shadcn/qmldir"));
    CHECK(!lv_gif_is_loaded(anim_gif(w)));
    CHECK(!lv_obj_has_flag(anim_placeholder(w), LV_OBJ_FLAG_HIDDEN));
    lv_refr_now(NULL);
    anim_free(p, w);
}

static void test_animated_image_plays_pauses_and_scales_speed(void)
{
    hmi_project_t *p = one_widget("ShAnimatedImage",
        "{\"source\":\"" HMI_REPO_ROOT "/tests/fixtures/animated/two_frames.gif\","
        "\"fillMode\":\"Image.PreserveAspectCrop\"}");
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    CHECK(lv_gif_is_loaded(anim_gif(w)));
    CHECK(!lv_obj_has_flag(anim_gif(w), LV_OBJ_FLAG_HIDDEN));
    CHECK(lv_obj_has_flag(anim_placeholder(w), LV_OBJ_FLAG_HIDDEN));
    CHECK(lv_image_get_inner_align(anim_gif(w)) == LV_IMAGE_ALIGN_COVER);
    CHECK(anim_frame(w) == 'r');                   // frame 1 shows at once
    anim_advance(150);                             // frames are 100 ms
    CHECK(anim_frame(w) == 'b');
    lv_refr_now(NULL);

    anim_set(w, "playing", hmi_value_bool(false)); // holds the frame
    anim_advance(150);
    anim_advance(150);
    CHECK(anim_frame(w) == 'b');
    anim_set(w, "playing", hmi_value_bool(true));
    anim_advance(150);
    CHECK(anim_frame(w) == 'r');                   // loops

    anim_set(w, "speed", hmi_value_num(50));       // 100 ms frames last 200 ms
    anim_advance(150);
    CHECK(anim_frame(w) == 'r');
    anim_advance(100);
    CHECK(anim_frame(w) == 'b');

    anim_set(w, "fillMode", hmi_value_str("Image.Stretch"));
    CHECK(lv_image_get_inner_align(anim_gif(w)) == LV_IMAGE_ALIGN_STRETCH);

    anim_set(w, "source", hmi_value_str("assets/gone.gif"));   // the file went away
    CHECK(!lv_gif_is_loaded(anim_gif(w)));
    CHECK(!lv_obj_has_flag(anim_placeholder(w), LV_OBJ_FLAG_HIDDEN));
    anim_advance(300);
    lv_refr_now(NULL);
    anim_free(p, w);
}

// The page can be torn down before destroy() runs; the frame timer goes too.
static void test_animated_image_deleted_before_destroy(void)
{
    hmi_project_t *p = one_widget("ShAnimatedImage",
        "{\"source\":\"" HMI_REPO_ROOT "/tests/fixtures/animated/two_frames.gif\"}");
    CHECK(p != NULL);
    if (!p) return;
    hmi_widget_t *w = build(p);
    lv_obj_delete(w->native);
    anim_advance(300);                             // no timer left on a dead object
    hmi_registry_find(w->type)->destroy(w);
    CHECK(w->state == NULL);
    hmi_project_free(p);
}

int main(void)
{
    lv_init();
    hmi_kit_register_all();
    hmi_theme_init(HMI_REPO_ROOT "/ui/qml/Shadcn", true);
    hmi_display_headless(320, 120);
    test_toggle_starts_checked();
    test_toggle_tap_flips_it();
    test_animated_image_missing_file_draws_placeholder();
    test_animated_image_plays_pauses_and_scales_speed();
    test_animated_image_deleted_before_destroy();
    return check_summary("test_widgets");
}
