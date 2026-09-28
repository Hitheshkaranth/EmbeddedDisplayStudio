// tests/test_alarms_v2.c -- CONTRACT 13.3 alarm engine: priority, latch,
// delay, deadband, message, shelving, ack-all, 9-field items, journal hook.
// Wave 1 gate for W3 (FROZEN). No LVGL: the engine runs on a fake clock.
#include <stdlib.h>
#include <unistd.h>

#include "alarms.h"
#include "check.h"
#include "journal.h"

static uint64_t g_mono;
static uint64_t mono(void *user) { (void)user; return g_mono; }
static const char *wall(void *user) { (void)user; return "2026-09-28T10:00:00"; }
static int g_changes;
static void changed(void *user) { (void)user; ++g_changes; }

static void feed(hmi_alarms_t *a, const char *tag, double v)
{
    hmi_value_t x = hmi_value_num(v);
    const char *tags[1] = {tag};
    hmi_alarms_evaluate(a, tags, &x, 1);
}

static void feed_null(hmi_alarms_t *a, const char *tag)
{
    hmi_value_t x = hmi_value_null();
    const char *tags[1] = {tag};
    hmi_alarms_evaluate(a, tags, &x, 1);
}

static const hmi_alarm_t *find(hmi_alarms_t *a, const char *tag)
{
    size_t n = 0;
    const hmi_alarm_t *list = hmi_alarms_active(a, &n);
    for (size_t i = 0; i < n; i++)
        if (strcmp(list[i].tag, tag) == 0) return &list[i];
    return NULL;
}

static hmi_alarms_t *make(const char *json)
{
    hmi_alarms_t *a = hmi_alarms_create_from_json(json);
    hmi_alarms_set_monotonic(a, mono, NULL);
    hmi_alarms_set_clock(a, wall, NULL);
    hmi_alarms_set_callback(a, changed, NULL);
    g_mono = 1000;
    g_changes = 0;
    return a;
}

static void test_priority_and_order(void)
{
    hmi_alarms_t *a = make("[{\"tag\":\"p.a\",\"label\":\"A\",\"warning\":{\"op\":\">\",\"value\":1}},"
                           " {\"tag\":\"p.b\",\"label\":\"B\",\"critical\":{\"op\":\">\",\"value\":1}},"
                           " {\"tag\":\"p.c\",\"label\":\"C\",\"priority\":4,\"critical\":{\"op\":\">\",\"value\":1}},"
                           " {\"tag\":\"p.d\",\"label\":\"D\",\"priority\":2,\"warning\":{\"op\":\">\",\"value\":1}}]");
    feed(a, "p.a", 5); feed(a, "p.b", 5); feed(a, "p.c", 5); feed(a, "p.d", 5);
    CHECK(find(a, "p.a") && find(a, "p.a")->priority == 3);   // warning default
    CHECK(find(a, "p.b") && find(a, "p.b")->priority == 1);   // critical default
    CHECK(find(a, "p.c") && find(a, "p.c")->priority == 4);
    CHECK(find(a, "p.d") && find(a, "p.d")->priority == 2);
    size_t n = 0;
    const hmi_alarm_t *list = hmi_alarms_active(a, &n);
    CHECK(n == 4);
    if (n == 4) {
        CHECK_EQ_STR(list[0].tag, "p.b");
        CHECK_EQ_STR(list[1].tag, "p.d");
        CHECK_EQ_STR(list[2].tag, "p.a");
        CHECK_EQ_STR(list[3].tag, "p.c");
    }
    // 9-field items
    hmi_value_t v = hmi_alarms_active_value(a);
    CHECK(v.kind == HMI_V_LIST && v.count == 4);
    if (v.count == 4) {
        const hmi_value_t *item = &v.items[0];
        CHECK(item->kind == HMI_V_LIST && item->count == 9);
        if (item->count == 9) {
            CHECK_NEAR(item->items[7].n, 1, 1e-9);
            CHECK_EQ_STR(hmi_value_as_str(&item->items[8], ""), "active");
        }
    }
    hmi_value_free(&v);
    CHECK(hmi_alarms_acknowledge_all(a) == 4);
    CHECK(hmi_alarms_acknowledge_all(a) == 0);
    hmi_alarms_destroy(a);
}

static void test_latch(void)
{
    hmi_alarms_t *a = make("[{\"tag\":\"l.x\",\"label\":\"X\",\"latch\":true,\"critical\":{\"op\":\">\",\"value\":5}}]");
    feed(a, "l.x", 9);
    CHECK(find(a, "l.x") != NULL);
    feed(a, "l.x", 1);                              // condition gone, not acked
    const hmi_alarm_t *al = find(a, "l.x");
    CHECK(al && al->cleared);
    CHECK(al && al->value.kind == HMI_V_NUM && al->value.n == 9);   // value frozen
    hmi_value_t v = hmi_alarms_active_value(a);
    CHECK(v.count == 1 && v.items[0].count == 9 &&
          strcmp(hmi_value_as_str(&v.items[0].items[8], ""), "cleared") == 0);
    hmi_value_free(&v);
    CHECK(hmi_alarms_acknowledge(a, "l.x"));        // ack removes a cleared latch
    CHECK(find(a, "l.x") == NULL);
    // acked while active, then clears: gone at once
    feed(a, "l.x", 9);
    CHECK(hmi_alarms_acknowledge(a, "l.x"));
    feed(a, "l.x", 1);
    CHECK(find(a, "l.x") == NULL);
    hmi_alarms_destroy(a);

    // without latch nothing lingers
    a = make("[{\"tag\":\"l.y\",\"label\":\"Y\",\"critical\":{\"op\":\">\",\"value\":5}}]");
    feed(a, "l.y", 9);
    feed(a, "l.y", 1);
    CHECK(find(a, "l.y") == NULL);
    hmi_alarms_destroy(a);
}

static void test_delay(void)
{
    hmi_alarms_t *a = make("[{\"tag\":\"d.x\",\"label\":\"X\",\"delay_ms\":2000,\"warning\":{\"op\":\">\",\"value\":5}}]");
    feed(a, "d.x", 9);
    CHECK(find(a, "d.x") == NULL);                  // not yet
    g_mono += 1500; hmi_alarms_tick(a);
    CHECK(find(a, "d.x") == NULL);
    feed(a, "d.x", 1);                              // dropped before the delay: restarts
    feed(a, "d.x", 9);
    g_mono += 1500; hmi_alarms_tick(a);
    CHECK(find(a, "d.x") == NULL);
    int before = g_changes;
    g_mono += 600; hmi_alarms_tick(a);              // held 2100 ms
    CHECK(find(a, "d.x") != NULL);
    CHECK(g_changes == before + 1);
    hmi_alarms_destroy(a);
}

static void test_deadband(void)
{
    hmi_alarms_t *a = make("[{\"tag\":\"b.x\",\"label\":\"X\",\"deadband\":2,\"critical\":{\"op\":\">\",\"value\":80}},"
                           " {\"tag\":\"b.y\",\"label\":\"Y\",\"deadband\":2,\"warning\":{\"op\":\"<\",\"value\":10}}]");
    feed(a, "b.x", 81);
    CHECK(find(a, "b.x") != NULL);
    feed(a, "b.x", 79);                             // within the deadband: still active
    CHECK(find(a, "b.x") != NULL);
    feed(a, "b.x", 78);                             // 2 past the threshold: clears
    CHECK(find(a, "b.x") == NULL);
    feed(a, "b.y", 9);
    CHECK(find(a, "b.y") != NULL);
    feed(a, "b.y", 11);
    CHECK(find(a, "b.y") != NULL);
    feed(a, "b.y", 12);
    CHECK(find(a, "b.y") == NULL);
    hmi_alarms_destroy(a);
}

static void test_message_and_null(void)
{
    hmi_alarms_t *a = make("[{\"tag\":\"m.x\",\"label\":\"X\",\"message\":\"Coolant hot\",\"critical\":{\"op\":\">\",\"value\":5}},"
                           " {\"tag\":\"m.y\",\"label\":\"Y\",\"latch\":true,\"critical\":{\"op\":\">\",\"value\":5}}]");
    feed(a, "m.x", 9);
    CHECK(find(a, "m.x") && strcmp(find(a, "m.x")->message, "Coolant hot") == 0);
    feed_null(a, "m.x");
    CHECK(find(a, "m.x") == NULL);
    feed(a, "m.y", 9);
    feed_null(a, "m.y");                            // latched + unacked: stays listed
    CHECK(find(a, "m.y") && find(a, "m.y")->cleared);
    hmi_alarms_destroy(a);
}

static void test_shelve(void)
{
    hmi_alarms_t *a = make("[{\"tag\":\"s.x\",\"label\":\"X\",\"critical\":{\"op\":\">\",\"value\":5}}]");
    feed(a, "s.x", 9);
    CHECK(find(a, "s.x") != NULL);
    CHECK(!hmi_alarms_shelve(a, "nope.tag", 1000));
    CHECK(!hmi_alarms_shelve(a, "s.x", 0));
    CHECK(!hmi_alarms_shelve(a, "s.x", 86400001));
    int before = g_changes;
    CHECK(hmi_alarms_shelve(a, "s.x", 5000));
    CHECK(hmi_alarms_is_shelved(a, "s.x"));
    CHECK(find(a, "s.x") == NULL);
    CHECK(g_changes > before);
    feed(a, "s.x", 10);                             // does not raise while shelved
    CHECK(find(a, "s.x") == NULL);
    g_mono += 5001; hmi_alarms_tick(a);             // expired: re-evaluated on 10
    CHECK(!hmi_alarms_is_shelved(a, "s.x"));
    CHECK(find(a, "s.x") != NULL);
    hmi_alarms_destroy(a);
}

static void test_journal_hook(void)
{
    char path[] = "/tmp/hmi-aj-XXXXXX";
    int fd = mkstemp(path);
    close(fd);
    hmi_journal_t *j = hmi_journal_open(path, HMI_JOURNAL_MAX_BYTES);
    CHECK(j != NULL);
    hmi_alarms_t *a = make("[{\"tag\":\"j.x\",\"label\":\"JX\",\"critical\":{\"op\":\">\",\"value\":5}}]");
    hmi_alarms_set_journal(a, j);
    CHECK(hmi_alarms_journal(a) == j);
    feed(a, "j.x", 9);                              // raise
    hmi_alarms_acknowledge(a, "j.x");               // ack
    hmi_alarms_shelve(a, "j.x", 1000);              // shelve
    g_mono += 1001; hmi_alarms_tick(a);             // unshelve (+ raise again on 9)
    feed(a, "j.x", 1);                              // clear
    hmi_value_t recent = hmi_journal_recent(j, 20);
    CHECK(recent.kind == HMI_V_LIST && recent.count >= 5);
    // newest first: the last event was the clear
    if (recent.count >= 1 && recent.items[0].count == 9)
        CHECK_EQ_STR(hmi_value_as_str(&recent.items[0].items[4], ""), "clear");
    bool saw[5] = {0};
    const char *names[5] = {"raise", "ack", "shelve", "unshelve", "clear"};
    for (size_t i = 0; i < recent.count; i++)
        for (int k = 0; k < 5; k++)
            if (recent.items[i].count == 9 && strcmp(hmi_value_as_str(&recent.items[i].items[4], ""), names[k]) == 0)
                saw[k] = true;
    for (int k = 0; k < 5; k++) CHECK(saw[k]);
    hmi_value_free(&recent);
    hmi_alarms_destroy(a);
    hmi_journal_close(j);
    remove(path);
}

int main(void)
{
    test_priority_and_order();
    test_latch();
    test_delay();
    test_deadband();
    test_message_and_null();
    test_shelve();
    test_journal_hook();
    return check_summary("test_alarms_v2");
}
