// tests/test_series.c -- bind.h rule 4 for a scalar tag: a trend chart bound
// to an ordinary numeric tag draws that tag's recent samples. Before this
// the binder only forwarded list-valued tags, so such a chart stayed empty.
#include <stdio.h>
#include <stdlib.h>

#include "bind.h"
#include "check.h"

static const char *DESIGN =
    "{\"version\":1,\"name\":\"series\",\"screen\":{\"width\":800,\"height\":480},"
    "\"pages\":[{\"id\":\"main\",\"name\":\"Main\",\"widgets\":["
    "{\"type\":\"ShTrendChart\",\"id\":\"trend\",\"geometry\":{\"x\":0,\"y\":0,\"width\":400,\"height\":200},"
    "\"properties\":{\"maxPoints\":3},"
    "\"bindings\":{\"data\":{\"tag\":\"eng.egt\",\"multiplier\":2.0,\"offset\":1.0}}}]}]}";

static hmi_value_t g_data;
static int g_applied;
static size_t g_asked;

static void apply(hmi_widget_t *w, const char *prop, const hmi_value_t *value, void *user)
{
    (void)w; (void)user;
    if (strcmp(prop, "data") != 0) return;
    hmi_value_free(&g_data);
    g_data = hmi_value_copy(value);
    ++g_applied;
}

// Stands in for hmi_tags_history: five samples 10..14, the last `count`.
static hmi_value_t history(const char *tag, size_t count, void *user)
{
    (void)user;
    hmi_value_t out = hmi_value_null();
    out.kind = HMI_V_LIST;
    g_asked = count;
    if (strcmp(tag, "eng.egt") != 0) return out;
    if (count > 5) count = 5;
    out.items = calloc(count, sizeof(hmi_value_t));
    out.count = count;
    for (size_t i = 0; i < count; i++) out.items[i] = hmi_value_num(10.0 + (5 - count) + i);
    return out;
}

int main(void)
{
    char path[] = "/tmp/hmi-series-XXXXXX";
    int fd = mkstemp(path);
    CHECK(fd >= 0);
    FILE *f = fdopen(fd, "w");
    fputs(DESIGN, f);
    fclose(f);

    char err[256];
    hmi_project_t *p = hmi_project_load(path, err, sizeof err);
    remove(path);
    CHECK(p != NULL);
    if (!p) return check_summary("test_series");

    // No history source: a scalar sample is not a series.
    hmi_bind_t *b = hmi_bind_create(apply, NULL);
    hmi_bind_page(b, p->pages[0]);
    g_applied = 0;
    hmi_value_t egt = hmi_value_num(14.0);
    hmi_bind_on_tag(b, "eng.egt", &egt);
    CHECK(g_applied == 0);

    // With one: the last maxPoints samples, oldest first, scaled.
    hmi_bind_set_history(b, history, NULL);
    hmi_bind_on_tag(b, "eng.egt", &egt);
    CHECK(g_applied == 1);
    CHECK(g_asked == 3);
    CHECK(g_data.kind == HMI_V_LIST && g_data.count == 3);
    if (g_data.count == 3) {
        CHECK_NEAR(g_data.items[0].n, 12.0 * 2 + 1, 1e-9);
        CHECK_NEAR(g_data.items[2].n, 14.0 * 2 + 1, 1e-9);
    }

    // A list-valued tag still passes through unchanged.
    hmi_value_t list = hmi_value_null();
    list.kind = HMI_V_LIST;
    list.items = calloc(2, sizeof(hmi_value_t));
    list.count = 2;
    list.items[0] = hmi_value_num(1);
    list.items[1] = hmi_value_num(2);
    hmi_bind_on_tag(b, "eng.egt", &list);
    CHECK(g_data.count == 2 && g_data.items[1].n == 2);
    hmi_value_free(&list);

    hmi_value_free(&g_data);
    hmi_bind_destroy(b);
    hmi_project_free(p);
    return check_summary("test_series");
}
