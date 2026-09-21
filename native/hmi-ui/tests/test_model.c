// tests/test_model.c -- the .edsui loader against the engine-dashboard fixture.
#include "check.h"
#include "model.h"
#include "gen/kit_schema.h"

int main(void)
{
    char err[256];
    hmi_project_t *p = hmi_project_load(HMI_REPO_ROOT "/tests/ui/fixtures/engine-dashboard/project.edsui", err, sizeof err);
    CHECK(p != NULL);
    if (!p) { fprintf(stderr, "%s\n", err); return check_summary("test_model"); }
    CHECK_EQ_STR(p->name, "engine-dashboard");
    CHECK(p->width == 1024 && p->height == 768);
    CHECK_EQ_STR(p->theme, "dark");
    CHECK_EQ_STR(p->background, "#101418");
    CHECK(p->npages == 1);
    hmi_page_t *page = p->pages[0];
    CHECK(page->nwidgets == 15);
    CHECK(hmi_page_widget_count(page) == 15);

    hmi_widget_t *gauge = page->widgets[0];
    CHECK_EQ_STR(gauge->type, "ShClusterGauge");
    CHECK_EQ_STR(gauge->id, "rpmGauge");
    CHECK(gauge->x == 260 && gauge->y == 30 && gauge->width == 520 && gauge->height == 520);
    CHECK_NEAR(hmi_value_as_num(hmi_widget_prop(gauge, "value"), -1), 3.5, 1e-9);
    CHECK_EQ_STR(hmi_value_as_str(hmi_widget_prop(gauge, "readout"), ""), "3200");
    CHECK(hmi_value_as_bool(hmi_widget_prop(gauge, "showInnerDial"), false));
    CHECK(hmi_widget_prop(gauge, "nonexistent") == NULL);
    const hmi_binding_t *b = hmi_widget_binding(gauge, "value");
    CHECK(b != NULL);
    if (b) {
        CHECK_EQ_STR(b->tag, "eng.rpm");
        CHECK_EQ_STR(b->unit, "RPM");
        CHECK_EQ_STR(b->warning, "> 6.5");
        CHECK_EQ_STR(b->critical, "> 7.5");
        CHECK_NEAR(b->multiplier, 1.0, 1e-9);
        CHECK_NEAR(b->offset, 0.0, 1e-9);
        CHECK_EQ_STR(b->format, "");
    }

    // Buttons carry actions.
    hmi_widget_t *start = NULL;
    for (size_t i = 0; i < page->nwidgets; ++i)
        if (strcmp(page->widgets[i]->id, "btnStart") == 0) start = page->widgets[i];
    CHECK(start != NULL);
    if (start) {
        CHECK(start->nactions == 1);
        CHECK_EQ_STR(start->actions[0].signal, "clicked");
        CHECK_EQ_STR(start->actions[0].kind, "write");
        CHECK_EQ_STR(start->actions[0].tag, "do.engine_start");
        CHECK(start->actions[0].value.kind == HMI_V_BOOL && start->actions[0].value.b);
        CHECK_EQ_STR(hmi_value_as_str(hmi_widget_prop(start, "text"), ""), "START");
    }

    // Every type in the fixture is in the kit schema.
    for (size_t i = 0; i < page->nwidgets; ++i)
        CHECK(hmi_kit_find(page->widgets[i]->type) != NULL);
    CHECK(hmi_kit_type_count == 46);
    CHECK(hmi_theme_colour("autoAccent", true) != NULL);
    CHECK_EQ_STR(hmi_theme_colour("autoAccent", true), "#22a8ff");
    CHECK_EQ_STR(hmi_theme_colour("background", false), "#ffffff");
    CHECK(hmi_theme_colour("nope", true) == NULL);

    hmi_project_free(p);

    // Failure paths.
    CHECK(hmi_project_load("/nonexistent/project.edsui", err, sizeof err) == NULL);
    CHECK(strstr(err, "cannot open") != NULL);

    // Values.
    hmi_value_t s = hmi_value_str("12.5");
    CHECK_NEAR(hmi_value_as_num(&s, 0), 12.5, 1e-9);
    CHECK(hmi_value_as_bool(&s, true) == true);   // not a bool word -> default
    hmi_value_t c = hmi_value_copy(&s);
    CHECK(hmi_value_equal(&s, &c));
    hmi_value_free(&s); hmi_value_free(&c);
    CHECK(s.kind == HMI_V_NULL);
    return check_summary("test_model");
}
