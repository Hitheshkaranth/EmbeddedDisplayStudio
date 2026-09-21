// tests/test_alarms.c -- the alarm engine against the rules in alarms.h;
// mirrors native/hmi-gui/tests/tst_alarms.cpp case for case, plus the
// per-tag delivery the hmi-ui runtime uses.
#include "alarms.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "check.h"
#ifdef _WIN32
#include <direct.h>
#else
#include <sys/stat.h>
#endif

// A deterministic clock: tick() advances one second.
static char g_now[24] = "2025-01-01T00:00:00";
static int g_tick;
static const char *fake_now(void *user) { (void)user; return g_now; }
static void tick(void) { g_tick = (g_tick + 1) % 60; snprintf(g_now, sizeof g_now, "2025-01-01T00:00:%02d", g_tick); }
static void tick_to(int s) { g_tick = s % 60; snprintf(g_now, sizeof g_now, "2025-01-01T00:00:%02d", g_tick); }

static int g_changes;
static void on_changed(void *user) { (void)user; ++g_changes; }

static hmi_alarms_t *engine(const char *json)
{
    hmi_alarms_t *a = hmi_alarms_create_from_json(json);
    hmi_alarms_set_clock(a, fake_now, NULL);
    hmi_alarms_set_callback(a, on_changed, NULL);
    return a;
}

// One tag, one number.
static bool feed(hmi_alarms_t *a, const char *tag, double v)
{
    hmi_value_t val = hmi_value_num(v);
    const char *tags[1] = {tag};
    return hmi_alarms_evaluate(a, tags, &val, 1);
}

static bool feed_null(hmi_alarms_t *a, const char *tag)
{
    hmi_value_t val = hmi_value_null();
    const char *tags[1] = {tag};
    return hmi_alarms_evaluate(a, tags, &val, 1);
}

static size_t count(const hmi_alarms_t *a) { size_t n; hmi_alarms_active(a, &n); return n; }

#define POT_WARN "[{\"tag\":\"ai.pot\",\"label\":\"Input Voltage\",\"unit\":\"V\",\"warning\":{\"op\":\">\",\"value\":2.0}}]"
#define POT_BOTH "[{\"tag\":\"ai.pot\",\"label\":\"Input Voltage\",\"unit\":\"V\",\"critical\":{\"op\":\">\",\"value\":4.0},\"warning\":{\"op\":\">\",\"value\":2.0}}]"

static void test_empty(void)
{
    hmi_alarms_t *a = engine("[]");
    CHECK(hmi_alarms_tag_count(a) == 0);
    CHECK(count(a) == 0);
    CHECK(!feed(a, "ai.pot", 99));
    hmi_alarms_destroy(a);
    a = engine(NULL);
    CHECK(hmi_alarms_tag_count(a) == 0);
    hmi_alarms_destroy(a);
    a = engine("not json");
    CHECK(hmi_alarms_tag_count(a) == 0);
    hmi_alarms_destroy(a);
}

// The six operators and an unknown one, through the engine.
static void test_ops(void)
{
    struct { const char *op; double fires, holds; } cases[] = {
        {">", 5, 3}, {">=", 3, 2}, {"<", 2, 3}, {"<=", 3, 4}, {"==", 3, 4}, {"!=", 4, 3}};
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; ++i) {
        char json[160];
        snprintf(json, sizeof json, "[{\"tag\":\"t\",\"warning\":{\"op\":\"%s\",\"value\":3}}]", cases[i].op);
        hmi_alarms_t *a = engine(json);
        CHECK(feed(a, "t", cases[i].fires));
        CHECK(count(a) == 1);
        CHECK(feed(a, "t", cases[i].holds));
        CHECK(count(a) == 0);
        hmi_alarms_destroy(a);
    }
    hmi_alarms_t *a = engine("[{\"tag\":\"t\",\"warning\":{\"op\":\"~\",\"value\":3}}]");
    CHECK(!feed(a, "t", 100));
    CHECK(count(a) == 0);
    hmi_alarms_destroy(a);
}

static void test_critical_wins(void)
{
    hmi_alarms_t *a = engine(POT_BOTH);
    CHECK(feed(a, "ai.pot", 5.0));
    size_t n;
    const hmi_alarm_t *act = hmi_alarms_active(a, &n);
    CHECK(n == 1);
    CHECK_EQ_STR(act[0].severity, "critical");
    CHECK_EQ_STR(act[0].label, "Input Voltage");
    CHECK_EQ_STR(act[0].message, "Input Voltage 5V");
    hmi_alarms_destroy(a);
}

static void test_warning_only(void)
{
    hmi_alarms_t *a = engine(POT_BOTH);
    CHECK(feed(a, "ai.pot", 3.0));
    size_t n;
    const hmi_alarm_t *act = hmi_alarms_active(a, &n);
    CHECK(n == 1);
    CHECK_EQ_STR(act[0].severity, "warning");
    hmi_alarms_destroy(a);
}

static void test_null_clears(void)
{
    hmi_alarms_t *a = engine(POT_WARN);
    CHECK(feed(a, "ai.pot", 3.0));
    CHECK(count(a) == 1);
    CHECK(feed_null(a, "ai.pot"));       // a failed read clears
    CHECK(count(a) == 0);
    hmi_alarms_destroy(a);
}

static void test_json_null_inactive(void)
{
    // "< 10" must not fire on a null (it is not 0).
    hmi_alarms_t *a = engine("[{\"tag\":\"ai.pot\",\"label\":\"Pot\",\"warning\":{\"op\":\"<\",\"value\":10}}]");
    CHECK(!feed_null(a, "ai.pot"));
    CHECK(count(a) == 0);
    hmi_alarms_destroy(a);
}

static void test_threshold_must_be_numeric(void)
{
    hmi_alarms_t *a = engine("[{\"tag\":\"a\",\"warning\":{\"op\":\">\",\"value\":true}},"
                             "{\"tag\":\"b\",\"warning\":{\"op\":\">\",\"value\":\"0\"}},"
                             "{\"tag\":\"c\",\"warning\":{\"op\":\">\",\"value\":0}}]");
    const char *tags[3] = {"a", "b", "c"};
    hmi_value_t vals[3] = {hmi_value_num(5), hmi_value_num(5), hmi_value_num(5)};
    CHECK(hmi_alarms_evaluate(a, tags, vals, 3));
    size_t n;
    const hmi_alarm_t *act = hmi_alarms_active(a, &n);
    CHECK(n == 1);
    CHECK_EQ_STR(act[0].tag, "c");
    hmi_alarms_destroy(a);
}

static void test_same_second_ties(void)
{
    hmi_alarms_t *a = engine("[{\"tag\":\"x\",\"warning\":{\"op\":\">\",\"value\":0}},"
                             "{\"tag\":\"y\",\"warning\":{\"op\":\">\",\"value\":0}},"
                             "{\"tag\":\"z\",\"warning\":{\"op\":\">\",\"value\":0}}]");
    const char *tags1[2] = {"z", "x"};
    hmi_value_t v1[2] = {hmi_value_num(1), hmi_value_num(1)};
    CHECK(hmi_alarms_evaluate(a, tags1, v1, 2));    // frame order irrelevant: definition order
    CHECK(feed(a, "y", 1));
    size_t n;
    const hmi_alarm_t *act = hmi_alarms_active(a, &n);
    CHECK(n == 3);
    CHECK_EQ_STR(act[0].tag, "x");
    CHECK_EQ_STR(act[1].tag, "z");
    CHECK_EQ_STR(act[2].tag, "y");
    hmi_alarms_destroy(a);
}

// Per-tag delivery: a tag absent from the call keeps its last value.
static void test_partial_delivery_keeps_values(void)
{
    hmi_alarms_t *a = engine("[{\"tag\":\"x\",\"warning\":{\"op\":\">\",\"value\":0}},"
                             "{\"tag\":\"y\",\"warning\":{\"op\":\">\",\"value\":0}}]");
    CHECK(feed(a, "x", 1));
    CHECK(count(a) == 1);
    CHECK(feed(a, "y", 1));
    CHECK(count(a) == 2);                 // x stays active although not in this call
    CHECK(!feed(a, "y", 2));              // still firing: no change
    CHECK(count(a) == 2);
    CHECK(feed(a, "x", 0));
    CHECK(count(a) == 1);
    hmi_alarms_destroy(a);
}

static void test_persistence(void)
{
    hmi_alarms_t *a = engine(POT_WARN);
    tick();
    CHECK(feed(a, "ai.pot", 3.0));
    size_t n;
    const hmi_alarm_t *act = hmi_alarms_active(a, &n);
    CHECK(n == 1);
    CHECK_EQ_STR(act[0].timestamp, "2025-01-01T00:00:01");
    CHECK(!act[0].acknowledged);
    g_changes = 0;
    CHECK(hmi_alarms_acknowledge(a, "ai.pot"));
    CHECK(g_changes == 1);
    tick();
    CHECK(!feed(a, "ai.pot", 3.0));
    CHECK(g_changes == 1);
    act = hmi_alarms_active(a, &n);
    CHECK(n == 1);
    CHECK_EQ_STR(act[0].timestamp, "2025-01-01T00:00:01");
    CHECK(act[0].acknowledged);
    hmi_alarms_destroy(a);
}

static void test_escalation(void)
{
    hmi_alarms_t *a = engine(POT_BOTH);
    tick();
    CHECK(feed(a, "ai.pot", 3.0));
    size_t n;
    const hmi_alarm_t *act = hmi_alarms_active(a, &n);
    CHECK_EQ_STR(act[0].severity, "warning");
    CHECK_EQ_STR(act[0].message, "Input Voltage 3V");
    char ts1[24];
    snprintf(ts1, sizeof ts1, "%s", act[0].timestamp);
    tick();
    CHECK(feed(a, "ai.pot", 5.0));
    act = hmi_alarms_active(a, &n);
    CHECK(n == 1);
    CHECK_EQ_STR(act[0].severity, "critical");
    CHECK_EQ_STR(act[0].timestamp, ts1);
    CHECK_EQ_STR(act[0].message, "Input Voltage 5V");
    CHECK_NEAR(hmi_value_as_num(&act[0].value, 0), 5.0, 1e-9);
    hmi_alarms_destroy(a);
}

static void test_no_change_returns_false(void)
{
    hmi_alarms_t *a = engine(POT_WARN);
    CHECK(feed(a, "ai.pot", 3.0));
    g_changes = 0;
    tick();
    CHECK(!feed(a, "ai.pot", 3.0));
    CHECK(!feed(a, "ai.pot", 3.5));
    CHECK(g_changes == 0);
    hmi_alarms_destroy(a);
}

static void test_percent_g(void)
{
    hmi_alarms_t *a = engine(POT_WARN);
    size_t n;
    feed(a, "ai.pot", 3.0);
    CHECK_EQ_STR(hmi_alarms_active(a, &n)[0].message, "Input Voltage 3V");
    hmi_alarms_destroy(a);
    a = engine(POT_WARN);
    feed(a, "ai.pot", 2.5);
    CHECK_EQ_STR(hmi_alarms_active(a, &n)[0].message, "Input Voltage 2.5V");
    hmi_alarms_destroy(a);
    a = engine("[{\"tag\":\"ai.pot\",\"label\":\"Input Voltage\",\"unit\":\"V\",\"warning\":{\"op\":\">\",\"value\":0}}]");
    feed(a, "ai.pot", 0.00001);
    CHECK(strstr(hmi_alarms_active(a, &n)[0].message, "1e") != NULL);
    hmi_alarms_destroy(a);
}

static void test_sorting(void)
{
    hmi_alarms_t *a = engine("[{\"tag\":\"ai.a\",\"label\":\"A\",\"critical\":{\"op\":\">\",\"value\":0}},"
                             "{\"tag\":\"ai.b\",\"label\":\"B\",\"critical\":{\"op\":\">\",\"value\":0}},"
                             "{\"tag\":\"ai.c\",\"label\":\"C\",\"warning\":{\"op\":\">\",\"value\":0}}]");
    tick_to(1); feed(a, "ai.a", 1);
    tick_to(2); feed(a, "ai.b", 1);
    tick_to(3); feed(a, "ai.c", 1);
    size_t n;
    const hmi_alarm_t *act = hmi_alarms_active(a, &n);
    CHECK(n == 3);
    CHECK_EQ_STR(act[0].tag, "ai.b");    // critical, newest first
    CHECK_EQ_STR(act[1].tag, "ai.a");
    CHECK_EQ_STR(act[2].tag, "ai.c");    // then warning
    // Escalating C to critical: it is the newest critical now.
    hmi_alarms_destroy(a);
    a = engine("[{\"tag\":\"ai.a\",\"critical\":{\"op\":\">\",\"value\":0}},"
               "{\"tag\":\"ai.c\",\"critical\":{\"op\":\">\",\"value\":5},\"warning\":{\"op\":\">\",\"value\":0}}]");
    tick_to(1); feed(a, "ai.a", 1);
    tick_to(2); feed(a, "ai.c", 1);
    act = hmi_alarms_active(a, &n);
    CHECK_EQ_STR(act[0].tag, "ai.a");
    CHECK(feed(a, "ai.c", 9));
    act = hmi_alarms_active(a, &n);
    CHECK_EQ_STR(act[0].tag, "ai.c");
    CHECK_EQ_STR(act[1].tag, "ai.a");
    hmi_alarms_destroy(a);
}

static void test_acknowledge_unknown(void)
{
    hmi_alarms_t *a = engine(POT_WARN);
    g_changes = 0;
    CHECK(!hmi_alarms_acknowledge(a, "nope"));
    CHECK(!hmi_alarms_acknowledge(a, "ai.pot"));   // defined but inactive
    CHECK(!hmi_alarms_acknowledge(a, NULL));
    CHECK(g_changes == 0);
    hmi_alarms_destroy(a);
}

static void test_tags_dedupe_and_malformed(void)
{
    hmi_alarms_t *a = engine("[{\"tag\":\"ai.a\"},{\"tag\":\"ai.a\"},42,{\"label\":\"no tag\"},{\"tag\":7},{\"tag\":\"ai.b\"}]");
    CHECK(hmi_alarms_tag_count(a) == 2);
    CHECK_EQ_STR(hmi_alarms_tag(a, 0), "ai.a");
    CHECK_EQ_STR(hmi_alarms_tag(a, 1), "ai.b");
    CHECK_EQ_STR(hmi_alarms_tag(a, 2), "");
    CHECK(!feed(a, "ai.a", 1e9));         // no thresholds: never fires
    hmi_alarms_destroy(a);
}

static void test_value_keeps_type(void)
{
    hmi_alarms_t *a = engine("[{\"tag\":\"s\",\"warning\":{\"op\":\">\",\"value\":1}}]");
    hmi_value_t v = hmi_value_str("2.5");   // a numeric string reads as 2.5 and is kept as text
    const char *tags[1] = {"s"};
    CHECK(hmi_alarms_evaluate(a, tags, &v, 1));
    hmi_value_free(&v);
    size_t n;
    const hmi_alarm_t *act = hmi_alarms_active(a, &n);
    CHECK(act[0].value.kind == HMI_V_STR);
    CHECK_EQ_STR(hmi_value_as_str(&act[0].value, ""), "2.5");
    CHECK_EQ_STR(act[0].label, "s");      // label defaults to the tag
    CHECK_EQ_STR(act[0].message, "s 2.5");
    hmi_alarms_destroy(a);
}

static void test_active_value_shape(void)
{
    hmi_alarms_t *a = engine(POT_BOTH);
    tick_to(7);
    feed(a, "ai.pot", 5);
    hmi_alarms_acknowledge(a, "ai.pot");
    hmi_value_t list = hmi_alarms_active_value(a);
    CHECK(list.kind == HMI_V_LIST);
    CHECK(list.count == 1);
    const hmi_value_t *row = &list.items[0];
    CHECK(row->kind == HMI_V_LIST && row->count == 7);
    CHECK_EQ_STR(hmi_value_as_str(&row->items[0], ""), "ai.pot");
    CHECK_EQ_STR(hmi_value_as_str(&row->items[1], ""), "Input Voltage");
    CHECK_EQ_STR(hmi_value_as_str(&row->items[2], ""), "critical");
    CHECK(row->items[3].kind == HMI_V_NUM);
    CHECK_NEAR(row->items[3].n, 5, 1e-9);
    CHECK_EQ_STR(hmi_value_as_str(&row->items[4], ""), "Input Voltage 5V");
    CHECK_EQ_STR(hmi_value_as_str(&row->items[5], ""), "2025-01-01T00:00:07");
    CHECK(row->items[6].kind == HMI_V_BOOL && row->items[6].b);
    hmi_value_free(&list);
    hmi_alarms_destroy(a);
    a = engine("[]");
    list = hmi_alarms_active_value(a);
    CHECK(list.kind == HMI_V_LIST && list.count == 0);
    hmi_value_free(&list);
    hmi_alarms_destroy(a);
}

static void test_manifest_file(void)
{
    // A manifest on disk and a missing one.
    const char *dir = getenv("TMPDIR") ? getenv("TMPDIR") : "/tmp";
    char path[512];
    snprintf(path, sizeof path, "%s/hmi-ui-test-alarms-manifest.json", dir);
    FILE *f = fopen(path, "w");
    CHECK(f != NULL);
    if (f) {
        fputs("{\"app\":\"x\",\"alarms\":[{\"tag\":\"ai.pot\",\"label\":\"Input Voltage\",\"unit\":\"V\","
              "\"warning\":{\"op\":\">\",\"value\":2.5},\"critical\":{\"op\":\">\",\"value\":3.0}}]}", f);
        fclose(f);
    }
    // hmi_alarms_create wants the apps dir; give it a dir holding manifest.json
    char appdir[512];
    snprintf(appdir, sizeof appdir, "%s/hmi-ui-test-alarms", dir);
    char mpath[600];
    snprintf(mpath, sizeof mpath, "%s/manifest.json", appdir);
#ifdef _WIN32
    _mkdir(appdir);
#else
    mkdir(appdir, 0755);
#endif
    (void)rename(path, mpath);
    hmi_alarms_t *a = hmi_alarms_create(appdir);
    CHECK(hmi_alarms_tag_count(a) == 1);
    CHECK_EQ_STR(hmi_alarms_tag(a, 0), "ai.pot");
    CHECK(feed(a, "ai.pot", 3.2));
    size_t n;
    CHECK_EQ_STR(hmi_alarms_active(a, &n)[0].severity, "critical");
    hmi_alarms_destroy(a);
    remove(mpath);
    a = hmi_alarms_create("/nonexistent/apps");
    CHECK(hmi_alarms_tag_count(a) == 0);
    hmi_alarms_destroy(a);
    a = hmi_alarms_create(NULL);
    CHECK(hmi_alarms_tag_count(a) == 0);
    hmi_alarms_destroy(a);
}

int main(void)
{
    test_empty();
    test_ops();
    test_critical_wins();
    test_warning_only();
    test_null_clears();
    test_json_null_inactive();
    test_threshold_must_be_numeric();
    test_same_second_ties();
    test_partial_delivery_keeps_values();
    test_persistence();
    test_escalation();
    test_no_change_returns_false();
    test_percent_g();
    test_sorting();
    test_acknowledge_unknown();
    test_tags_dedupe_and_malformed();
    test_value_keeps_type();
    test_active_value_shape();
    test_manifest_file();
    return check_summary("test_alarms");
}
