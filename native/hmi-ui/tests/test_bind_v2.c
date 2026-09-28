// tests/test_bind_v2.c -- CONTRACT 13.2 binding options in the binding engine:
// decimals, expression bindings, rules. Wave 1 gate for W2 (FROZEN).
// Same recording-apply approach as test_bind.c: no LVGL objects.
#include <stdlib.h>

#include "bind.h"
#include "check.h"
#include "compat.h"

typedef struct { char widget[64]; char prop[64]; hmi_value_t value; } rec_t;
static rec_t g_rec[512];
static size_t g_nrec;

static void apply(hmi_widget_t *w, const char *prop, const hmi_value_t *value, void *user)
{
    (void)user;
    if (g_nrec >= 512) return;
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

static const char *DESIGN =
    "{\"version\":1,\"name\":\"b2\",\"screen\":{\"width\":800,\"height\":480},\"pages\":[{\"id\":\"main\",\"widgets\":["
    // decimals into a str-typed property
    "{\"type\":\"ShValueTile\",\"id\":\"tile\",\"geometry\":{\"x\":0,\"y\":0,\"width\":200,\"height\":100},"
    " \"properties\":{\"title\":\"T\"},"
    " \"bindings\":{\"value\":{\"tag\":\"e.t\",\"decimals\":1}}},"
    // decimals through a format
    "{\"type\":\"Text\",\"id\":\"txt\",\"geometry\":{\"x\":0,\"y\":100,\"width\":200,\"height\":30},"
    " \"bindings\":{\"text\":{\"tag\":\"e.d\",\"format\":\"%1 km\",\"decimals\":2}}},"
    // decimals 0 with scaling
    "{\"type\":\"Text\",\"id\":\"txt0\",\"geometry\":{\"x\":0,\"y\":140,\"width\":200,\"height\":30},"
    " \"bindings\":{\"text\":{\"tag\":\"e.d\",\"format\":\"%1\",\"decimals\":0,\"multiplier\":10}}},"
    // numeric expression with scaling, no tag
    "{\"type\":\"ShGauge\",\"id\":\"g\",\"geometry\":{\"x\":200,\"y\":0,\"width\":200,\"height\":200},"
    " \"bindings\":{\"value\":{\"tag\":\"\",\"expr\":\"e.a + e.b\",\"multiplier\":2}}},"
    // string-valued expression
    "{\"type\":\"Text\",\"id\":\"state\",\"geometry\":{\"x\":200,\"y\":200,\"width\":200,\"height\":30},"
    " \"bindings\":{\"text\":{\"tag\":\"\",\"expr\":\"e.run ? \\\"RUN\\\" : \\\"STOP\\\"\"}}},"
    // visibility from an expression
    "{\"type\":\"Rectangle\",\"id\":\"box\",\"geometry\":{\"x\":400,\"y\":0,\"width\":50,\"height\":50},"
    " \"bindings\":{\"visible\":{\"tag\":\"\",\"expr\":\"e.p > 50\"}}},"
    // rules, first match per property wins, else the declared value
    "{\"type\":\"ShValueTile\",\"id\":\"rt\",\"geometry\":{\"x\":400,\"y\":100,\"width\":200,\"height\":100},"
    " \"properties\":{\"title\":\"Normal\"},"
    " \"bindings\":{\"value\":{\"tag\":\"e.p\",\"rules\":["
    "   {\"if\":\"> 80\",\"prop\":\"title\",\"value\":\"HOT\"},"
    "   {\"if\":\"> 50\",\"prop\":\"title\",\"value\":\"WARM\"},"
    "   {\"if\":\">= 50\",\"prop\":\"state\",\"value\":\"warn\"}]}}},"
    // a state type keeps its bound value AND derives its state from thresholds
    // (qml_generator._derived: state only when the binding has thresholds)
    "{\"type\":\"ShValueTile\",\"id\":\"vt\",\"geometry\":{\"x\":600,\"y\":0,\"width\":200,\"height\":100},"
    " \"bindings\":{\"value\":{\"tag\":\"e.v\",\"warning\":\"> 5\",\"critical\":\"> 9\"}}}"
    "]}]}";

static void on(hmi_bind_t *b, const char *tag, double v)
{
    hmi_value_t x = hmi_value_num(v);
    hmi_bind_on_tag(b, tag, &x);
}

int main(void)
{
    char path[512], err[256];
    FILE *f = hmi_tmpfile(path, sizeof path);
    fputs(DESIGN, f);
    fclose(f);
    hmi_project_t *p = hmi_project_load(path, err, sizeof err);
    hmi_remove(path);
    CHECK(p != NULL);
    if (!p) return check_summary("test_bind_v2");
    // the model carries the 13.2 fields (skeleton)
    CHECK(p->pages[0]->widgets[0]->bindings[0].decimals == 1);
    CHECK_EQ_STR(p->pages[0]->widgets[3]->bindings[0].expr, "e.a + e.b");
    CHECK(p->pages[0]->widgets[6]->bindings[0].nrules == 3);

    hmi_bind_t *b = hmi_bind_create(apply, NULL);
    hmi_bind_page(b, p->pages[0]);

    // decimals
    reset();
    on(b, "e.t", 12.345);
    const hmi_value_t *v = last("tile", "value");
    CHECK(v && v->kind == HMI_V_STR);
    CHECK_EQ_STR(v ? hmi_value_as_str(v, "") : "", "12.3");
    on(b, "e.d", 3.14159);
    CHECK_EQ_STR(hmi_value_as_str(last("txt", "text"), ""), "3.14 km");
    CHECK_EQ_STR(hmi_value_as_str(last("txt0", "text"), ""), "31");

    // expression: both tags needed; one missing -> null -> fallback 0
    reset();
    on(b, "e.a", 1);
    v = last("g", "value");
    CHECK(v && v->kind == HMI_V_NUM && v->n == 0);
    on(b, "e.b", 2);
    v = last("g", "value");
    CHECK(v && v->kind == HMI_V_NUM);
    CHECK_NEAR(v ? v->n : -1, 6, 1e-9);          // (1 + 2) * 2
    on(b, "e.a", 10);
    CHECK_NEAR(last("g", "value") ? last("g", "value")->n : -1, 24, 1e-9);

    // string result
    hmi_value_t t = hmi_value_bool(true);
    hmi_bind_on_tag(b, "e.run", &t);
    CHECK_EQ_STR(hmi_value_as_str(last("state", "text"), ""), "RUN");
    t = hmi_value_bool(false);
    hmi_bind_on_tag(b, "e.run", &t);
    CHECK_EQ_STR(hmi_value_as_str(last("state", "text"), ""), "STOP");

    // visibility + rules on e.p
    reset();
    on(b, "e.p", 90);
    CHECK(last("box", "visible") && hmi_value_as_bool(last("box", "visible"), false));
    CHECK_EQ_STR(hmi_value_as_str(last("rt", "title"), ""), "HOT");
    CHECK_EQ_STR(hmi_value_as_str(last("rt", "state"), ""), "warn");
    on(b, "e.p", 60);
    CHECK_EQ_STR(hmi_value_as_str(last("rt", "title"), ""), "WARM");
    on(b, "e.p", 10);
    CHECK(last("box", "visible") && !hmi_value_as_bool(last("box", "visible"), true));
    CHECK_EQ_STR(hmi_value_as_str(last("rt", "title"), ""), "Normal");     // declared value
    CHECK_EQ_STR(hmi_value_as_str(last("rt", "state"), ""), "idle");       // kit default

    // the classic path is untouched: tile still gets its value
    CHECK(last("rt", "value") != NULL);

    // state types: value delivered, state derived only with thresholds
    reset();
    on(b, "e.v", 7);
    CHECK(last("vt", "value") != NULL);
    CHECK_EQ_STR(hmi_value_as_str(last("vt", "state"), ""), "warn");
    on(b, "e.v", 10);
    CHECK_EQ_STR(hmi_value_as_str(last("vt", "state"), ""), "fault");
    reset();
    on(b, "e.t", 1.0);                         // "tile" has no thresholds
    CHECK(last("tile", "state") == NULL);      // no derived state

    reset();
    hmi_bind_destroy(b);
    hmi_project_free(p);
    return check_summary("test_bind_v2");
}
