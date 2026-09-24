// tests/test_bind.c -- the binding engine (acceptance test, part 1;
// part 2 is tests/ui/test_conformance_ui.py through a real process).
//
// Uses the engine against the engine-dashboard fixture with a recording
// apply callback: no LVGL objects are needed, the engine only computes
// property values. Every rule in bind.h has a check here.
#include <stdlib.h>

#include "bind.h"
#include "check.h"

typedef struct { char widget[64]; char prop[64]; hmi_value_t value; } rec_t;
static rec_t g_rec[256];
static size_t g_nrec;

static void apply(hmi_widget_t *w, const char *prop, const hmi_value_t *value, void *user)
{
    (void)user;
    if (g_nrec >= 256) return;
    snprintf(g_rec[g_nrec].widget, 64, "%s", w->id);
    snprintf(g_rec[g_nrec].prop, 64, "%s", prop);
    g_rec[g_nrec].value = hmi_value_copy(value);
    ++g_nrec;
}

static const hmi_value_t *last(const char *widget, const char *prop)
{
    for (size_t i = g_nrec; i > 0; --i)
        if (strcmp(g_rec[i - 1].widget, widget) == 0 && strcmp(g_rec[i - 1].prop, prop) == 0)
            return &g_rec[i - 1].value;
    return NULL;
}

static void reset(void)
{
    for (size_t i = 0; i < g_nrec; ++i) hmi_value_free(&g_rec[i].value);
    g_nrec = 0;
}

int main(void)
{
    // Thresholds.
    char op[3]; double n;
    CHECK(hmi_bind_parse_threshold("> 6.5", op, &n) && strcmp(op, ">") == 0 && n == 6.5);
    CHECK(hmi_bind_parse_threshold(">=100", op, &n) && strcmp(op, ">=") == 0 && n == 100);
    CHECK(hmi_bind_parse_threshold("< -3", op, &n) && strcmp(op, "<") == 0 && n == -3);
    CHECK(!hmi_bind_parse_threshold("", op, &n));
    CHECK(!hmi_bind_parse_threshold("hot", op, &n));
    CHECK(hmi_bind_threshold_trips(7, ">", 6.5));
    CHECK(!hmi_bind_threshold_trips(6.5, ">", 6.5));
    CHECK(hmi_bind_threshold_trips(6.5, ">=", 6.5));
    CHECK(hmi_bind_threshold_trips(1, "<", 2) && hmi_bind_threshold_trips(2, "<=", 2));
    CHECK(hmi_bind_threshold_trips(2, "==", 2) && hmi_bind_threshold_trips(3, "!=", 2));

    char err[256];
    hmi_project_t *p = hmi_project_load(HMI_REPO_ROOT "/tests/ui/fixtures/engine-dashboard/project.edsui", err, sizeof err);
    CHECK(p != NULL);
    if (!p) return check_summary("test_bind");
    hmi_bind_t *b = hmi_bind_create(apply, NULL);

    // Rule 1/2: registering the page applies fallbacks (0 for numeric) and
    // derives the unit from the binding.
    hmi_bind_page(b, p->pages[0]);
    const hmi_value_t *v = last("rpmGauge", "value");
    CHECK(v && v->kind == HMI_V_NUM && v->n == 0);
    // ShClusterGauge has no unit property; ShAutoReadout does (avgFuel binds with unit "l/100km").
    v = last("avgFuel", "unit");
    CHECK(v && strcmp(hmi_value_as_str(v, ""), "l/100km") == 0);
    // ShNumDisplay: thresholds "< 20"/"< 10" style are not on odoDisplay, but
    // batteryBar (ShSegmentBar) has "< 20": no threshold_properties entry for
    // that type, so nothing derived; ShStatDot binds `state` without
    // thresholds: it receives the raw tag as its state.

    // Rule 1: a frame updates the bound property (scaled/offset when set).
    reset();
    hmi_value_t rpm = hmi_value_num(3.2);
    hmi_bind_on_tag(b, "eng.rpm", &rpm);
    v = last("rpmGauge", "value");
    CHECK(v && v->kind == HMI_V_NUM);
    CHECK_NEAR(v ? v->n : -1, 3.2, 1e-9);
    // An unrelated tag touches nothing.
    reset();
    hmi_value_t x = hmi_value_num(1);
    hmi_bind_on_tag(b, "not.bound", &x);
    CHECK(g_nrec == 0);

    // Rule 3: thresholds on a state_properties type. Build a widget in place:
    // a ShStatDot whose `state` binding carries warning "> 50" / critical "> 90".
    {
        hmi_widget_t *dot = NULL;
        for (size_t i = 0; i < p->pages[0]->nwidgets; ++i)
            if (strcmp(p->pages[0]->widgets[i]->id, "statusDot") == 0) dot = p->pages[0]->widgets[i];
        CHECK(dot && dot->nbindings == 1);
        if (dot) {
            free(dot->bindings[0].warning); dot->bindings[0].warning = strdup("> 50");
            free(dot->bindings[0].critical); dot->bindings[0].critical = strdup("> 90");
            hmi_bind_page(b, p->pages[0]);
            reset();
            hmi_value_t lo = hmi_value_num(10), mid = hmi_value_num(60), hi = hmi_value_num(95);
            hmi_bind_on_tag(b, "eng.status_ok", &lo);
            CHECK_EQ_STR(hmi_value_as_str(last("statusDot", "state"), "?"), "ok");
            hmi_bind_on_tag(b, "eng.status_ok", &mid);
            CHECK_EQ_STR(hmi_value_as_str(last("statusDot", "state"), "?"), "warn");
            hmi_bind_on_tag(b, "eng.status_ok", &hi);
            CHECK_EQ_STR(hmi_value_as_str(last("statusDot", "state"), "?"), "fault");
        }
    }
    // Rule 3b: threshold_properties. ShNumDisplay odoDisplay with warning "< 20"
    // must receive warningLow = 20 at page registration.
    {
        hmi_widget_t *odo = NULL;
        for (size_t i = 0; i < p->pages[0]->nwidgets; ++i)
            if (strcmp(p->pages[0]->widgets[i]->id, "odoDisplay") == 0) odo = p->pages[0]->widgets[i];
        CHECK(odo && odo->nbindings == 1);
        if (odo) {
            free(odo->bindings[0].warning); odo->bindings[0].warning = strdup("< 20");
            free(odo->bindings[0].critical); odo->bindings[0].critical = strdup(">= 900000");
            reset();
            hmi_bind_page(b, p->pages[0]);
            v = last("odoDisplay", "warningLow");
            CHECK(v && v->kind == HMI_V_NUM && v->n == 20);
            v = last("odoDisplay", "faultHigh");
            CHECK(v && v->kind == HMI_V_NUM && v->n == 900000);
            v = last("odoDisplay", "unit");
            CHECK_EQ_STR(hmi_value_as_str(v, "?"), "km");
        }
    }

    // Rule 7: ShTripInfo value -> row1Value string with one decimal.
    reset();
    hmi_value_t dist = hmi_value_num(352.37);
    hmi_bind_on_tag(b, "trip.a_dist", &dist);
    v = last("tripInfoA", "row1Value");
    CHECK(v && v->kind == HMI_V_STR);
    CHECK_EQ_STR(hmi_value_as_str(v, ""), "352.4");

    // Rule 1: a str-typed property (not "value", unscaled, unformatted) reads
    // "" before its tag arrives: ShTripInfo.row1Value is such a property when
    // bound directly.
    reset();
    hmi_bind_page(b, p->pages[0]);
    v = last("avgFuel", "value");
    CHECK(v && v->kind == HMI_V_NUM && v->n == 0);
    // Rule 1 (format): multiplier/offset/format applied.
    {
        hmi_widget_t *fuel = NULL;
        for (size_t i = 0; i < p->pages[0]->nwidgets; ++i)
            if (strcmp(p->pages[0]->widgets[i]->id, "avgFuel") == 0) fuel = p->pages[0]->widgets[i];
        if (fuel) {
            fuel->bindings[0].multiplier = 2.0; fuel->bindings[0].offset = 0.5;
            hmi_bind_page(b, p->pages[0]);
            reset();
            hmi_value_t raw = hmi_value_num(3.0);
            hmi_bind_on_tag(b, "avg.fuel_l100", &raw);
            v = last("avgFuel", "value");
            CHECK_NEAR(hmi_value_as_num(v, -1), 6.5, 1e-9);
            free(fuel->bindings[0].format); fuel->bindings[0].format = strdup("%1 L");
            hmi_bind_page(b, p->pages[0]);
            reset();
            hmi_bind_on_tag(b, "avg.fuel_l100", &raw);
            v = last("avgFuel", "value");
            CHECK_EQ_STR(hmi_value_as_str(v, "?"), "6.5 L");
        }
    }

    // Rule 6: sim tags never deliver.
    reset();
    hmi_value_t sim = hmi_value_num(5);
    hmi_bind_on_tag(b, "sim.car.rpm", &sim);
    CHECK(g_nrec == 0);

    hmi_bind_destroy(b);
    hmi_project_free(p);
    reset();
    return check_summary("test_bind");
}
