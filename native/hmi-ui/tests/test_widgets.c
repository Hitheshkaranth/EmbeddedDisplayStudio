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

int main(void)
{
    lv_init();
    hmi_kit_register_all();
    hmi_theme_init(HMI_REPO_ROOT "/ui/qml/Shadcn", true);
    hmi_display_headless(320, 120);
    test_toggle_starts_checked();
    test_toggle_tap_flips_it();
    return check_summary("test_widgets");
}
