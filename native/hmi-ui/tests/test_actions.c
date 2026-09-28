// tests/test_actions.c -- CONTRACT 13.1 action lists, kinds and confirmation.
// Wave 1 gate for W1 (FROZEN): actions.c must make every check pass.
#include <sys/stat.h>

#include "actions.h"
#include "alarms.h"
#include "check.h"
#include "modal.h"
#include "rt_harness.h"

static const char *DESIGN =
    "{\"version\":1,\"name\":\"acts\",\"screen\":{\"width\":800,\"height\":480},\"pages\":["
    "{\"id\":\"main\",\"name\":\"Main\",\"widgets\":["
    " {\"type\":\"ShButton\",\"id\":\"bList\",\"geometry\":{\"x\":0,\"y\":0,\"width\":100,\"height\":40},"
    "  \"actions\":{\"clicked\":[{\"kind\":\"write\",\"tag\":\"a.x\",\"value\":1},{\"kind\":\"pulse\",\"tag\":\"a.y\",\"ms\":120}]}},"
    " {\"type\":\"ShButton\",\"id\":\"bToggle\",\"geometry\":{\"x\":0,\"y\":50,\"width\":100,\"height\":40},"
    "  \"actions\":{\"clicked\":{\"kind\":\"toggle\",\"tag\":\"d.run\"}}},"
    " {\"type\":\"ShButton\",\"id\":\"bInc\",\"geometry\":{\"x\":0,\"y\":100,\"width\":100,\"height\":40},"
    "  \"actions\":{\"clicked\":{\"kind\":\"increment\",\"tag\":\"s.set\",\"step\":5,\"max\":20}}},"
    " {\"type\":\"ShButton\",\"id\":\"bDec\",\"geometry\":{\"x\":0,\"y\":150,\"width\":100,\"height\":40},"
    "  \"actions\":{\"clicked\":{\"kind\":\"decrement\",\"tag\":\"s.set\",\"step\":5,\"min\":0}}},"
    " {\"type\":\"ShButton\",\"id\":\"bConfirm\",\"geometry\":{\"x\":0,\"y\":200,\"width\":100,\"height\":40},"
    "  \"actions\":{\"clicked\":[{\"kind\":\"write\",\"tag\":\"c.go\",\"value\":true},"
    "                          {\"kind\":\"pulse\",\"tag\":\"c.horn\",\"ms\":50,\"confirm\":\"Start pump?\"},"
    "                          {\"kind\":\"write\",\"tag\":\"c.other\",\"value\":2,\"confirm\":\"second text\"}]}},"
    " {\"type\":\"ShButton\",\"id\":\"bAck\",\"geometry\":{\"x\":200,\"y\":0,\"width\":100,\"height\":40},"
    "  \"actions\":{\"clicked\":{\"kind\":\"ack\",\"tag\":\"a.t\"}}},"
    " {\"type\":\"ShButton\",\"id\":\"bAckAll\",\"geometry\":{\"x\":200,\"y\":50,\"width\":100,\"height\":40},"
    "  \"actions\":{\"clicked\":{\"kind\":\"ack\",\"tag\":\"*\"}}},"
    " {\"type\":\"ShButton\",\"id\":\"bUnknown\",\"geometry\":{\"x\":200,\"y\":100,\"width\":100,\"height\":40},"
    "  \"actions\":{\"clicked\":[{\"kind\":\"explode\"},{\"kind\":\"write\",\"tag\":\"u.after\",\"value\":7}]}},"
    " {\"type\":\"ShButton\",\"id\":\"bNav\",\"geometry\":{\"x\":200,\"y\":150,\"width\":100,\"height\":40},"
    "  \"actions\":{\"clicked\":{\"kind\":\"navigate\",\"page\":\"p2\"}}}"
    "]},"
    "{\"id\":\"p2\",\"name\":\"Two\",\"widgets\":["
    " {\"type\":\"ShButton\",\"id\":\"bBack\",\"geometry\":{\"x\":0,\"y\":0,\"width\":100,\"height\":40},"
    "  \"actions\":{\"clicked\":{\"kind\":\"back\"}}},"
    " {\"type\":\"ShButton\",\"id\":\"bNav3\",\"geometry\":{\"x\":0,\"y\":50,\"width\":100,\"height\":40},"
    "  \"actions\":{\"clicked\":{\"kind\":\"navigate\",\"page\":\"p3\"}}}"
    "]},"
    "{\"id\":\"p3\",\"name\":\"Three\",\"widgets\":["
    " {\"type\":\"ShButton\",\"id\":\"bBack3\",\"geometry\":{\"x\":0,\"y\":0,\"width\":100,\"height\":40},"
    "  \"actions\":{\"clicked\":{\"kind\":\"back\"}}}"
    "]}]}";

static const char *MANIFEST =
    "{\"schema\":1,\"name\":\"acts\",\"version\":\"1.0.0\",\"entry\":\"project.edsui\",\"runtime\":\"edsui\","
    "\"alarms\":[{\"tag\":\"a.t\",\"label\":\"Temp\",\"critical\":{\"op\":\">\",\"value\":5}},"
    "            {\"tag\":\"a.u\",\"label\":\"Other\",\"warning\":{\"op\":\">\",\"value\":5}}]}";

static void click(rt_t *h, const char *id)
{
    hmi_widget_t *w = rt_widget(h, id);
    CHECK(w != NULL);
    if (w) hmi_runtime_signal(w, "clicked", NULL);
    rt_pump(h, 20);
}

static void expect_set(rt_t *h, const char *tag, double value)
{
    cJSON *c = rt_next_command(h, 800);
    CHECK(c != NULL);
    CHECK_EQ_STR(rt_cmd_str(c, "cmd"), "set");
    CHECK_EQ_STR(rt_cmd_str(c, "tag"), tag);
    CHECK_NEAR(rt_cmd_num(c, "value", -999), value, 1e-9);
    cJSON_Delete(c);
}

static void expect_nothing(rt_t *h)
{
    cJSON *c = rt_next_command(h, 250);
    CHECK(c == NULL);
    if (c) { fprintf(stderr, "unexpected command: %s\n", cJSON_PrintUnformatted(c)); cJSON_Delete(c); }
}

static void test_truthy(void)
{
    hmi_value_t v;
    CHECK(!hmi_actions_truthy(NULL));
    v = hmi_value_null(); CHECK(!hmi_actions_truthy(&v));
    v = hmi_value_bool(true); CHECK(hmi_actions_truthy(&v));
    v = hmi_value_bool(false); CHECK(!hmi_actions_truthy(&v));
    v = hmi_value_num(0); CHECK(!hmi_actions_truthy(&v));
    v = hmi_value_num(-0.5); CHECK(hmi_actions_truthy(&v));
    v = hmi_value_str(""); CHECK(!hmi_actions_truthy(&v)); hmi_value_free(&v);
    v = hmi_value_str("false"); CHECK(!hmi_actions_truthy(&v)); hmi_value_free(&v);
    v = hmi_value_str("0"); CHECK(!hmi_actions_truthy(&v)); hmi_value_free(&v);
    v = hmi_value_str("RUN"); CHECK(hmi_actions_truthy(&v)); hmi_value_free(&v);
}

static void test_list_runs_in_order(rt_t *h)
{
    click(h, "bList");
    expect_set(h, "a.x", 1);
    cJSON *c = rt_next_command(h, 800);
    CHECK_EQ_STR(rt_cmd_str(c, "cmd"), "pulse");
    CHECK_EQ_STR(rt_cmd_str(c, "tag"), "a.y");
    CHECK_NEAR(rt_cmd_num(c, "ms", 0), 120, 1e-9);
    cJSON_Delete(c);
}

static void test_toggle(rt_t *h)
{
    click(h, "bToggle");                     // never seen: counts as false
    expect_set(h, "d.run", 1);
    rt_frame(h, "{\"d.run\":true}");
    click(h, "bToggle");
    expect_set(h, "d.run", 0);
    rt_frame(h, "{\"d.run\":\"0\"}");        // "0" is not truthy
    click(h, "bToggle");
    expect_set(h, "d.run", 1);
}

static void test_increment_decrement(rt_t *h)
{
    click(h, "bInc");                        // never seen: 0 + 5
    expect_set(h, "s.set", 5);
    rt_frame(h, "{\"s.set\":18}");
    click(h, "bInc");                        // 23 clamped to max 20
    expect_set(h, "s.set", 20);
    rt_frame(h, "{\"s.set\":3}");
    click(h, "bDec");                        // -2 clamped to min 0
    expect_set(h, "s.set", 0);
    rt_frame(h, "{\"s.set\":12.5}");
    click(h, "bDec");
    expect_set(h, "s.set", 7.5);
}

static void test_confirm(rt_t *h)
{
    CHECK(hmi_actions_pending_confirm() == NULL);
    click(h, "bConfirm");
    expect_nothing(h);                       // nothing runs before the answer
    CHECK_EQ_STR(hmi_actions_pending_confirm(), "Start pump?");   // the FIRST confirm text
    CHECK_EQ_STR(hmi_modal_owner(), "confirm");
    CHECK(lv_obj_get_child_count(lv_layer_top()) > 0);           // a dialog is on screen
    hmi_actions_answer_confirm(false);       // Cancel: none of the list
    rt_pump(h, 30);
    expect_nothing(h);
    CHECK(hmi_actions_pending_confirm() == NULL);
    CHECK(hmi_modal_owner() == NULL);

    click(h, "bConfirm");
    hmi_actions_answer_confirm(true);        // OK: the whole list, in order
    rt_pump(h, 30);
    expect_set(h, "c.go", 1);
    cJSON *c = rt_next_command(h, 800);
    CHECK_EQ_STR(rt_cmd_str(c, "cmd"), "pulse");
    CHECK_EQ_STR(rt_cmd_str(c, "tag"), "c.horn");
    cJSON_Delete(c);
    expect_set(h, "c.other", 2);
    CHECK(hmi_actions_pending_confirm() == NULL);
    CHECK(hmi_modal_owner() == NULL);

    // Another popup holds the slot: the list is refused, nothing pends.
    CHECK(hmi_modal_claim("keypad"));
    click(h, "bConfirm");
    CHECK(hmi_actions_pending_confirm() == NULL);
    hmi_actions_answer_confirm(true);
    expect_nothing(h);
    hmi_modal_release("keypad");
}

static void test_unknown_kind_is_skipped(rt_t *h)
{
    click(h, "bUnknown");
    expect_set(h, "u.after", 7);
}

static void test_ack(rt_t *h)
{
    hmi_alarms_t *a = hmi_runtime_alarms(h->rt);
    rt_frame(h, "{\"a.t\":9,\"a.u\":9}");
    size_t n = 0;
    const hmi_alarm_t *list = hmi_alarms_active(a, &n);
    CHECK(n == 2);
    click(h, "bAck");
    list = hmi_alarms_active(a, &n);
    for (size_t i = 0; i < n; i++) {
        if (strcmp(list[i].tag, "a.t") == 0) CHECK(list[i].acknowledged);
        if (strcmp(list[i].tag, "a.u") == 0) CHECK(!list[i].acknowledged);
    }
    // ack "*" (hmi_alarms_acknowledge_all) is W3's engine: checked after the
    // merge by tests/test_wave1_integration.c, not here.
}

static void test_back(rt_t *h)
{
    CHECK(!hmi_runtime_back(h->rt));          // nothing to go back to yet
    click(h, "bNav");
    rt_pump(h, 30);
    CHECK_EQ_STR(hmi_runtime_current_page(h->rt), "p2");
    click(h, "bNav3");
    rt_pump(h, 30);
    CHECK_EQ_STR(hmi_runtime_current_page(h->rt), "p3");
    click(h, "bBack3");
    rt_pump(h, 30);
    CHECK_EQ_STR(hmi_runtime_current_page(h->rt), "p2");
    click(h, "bBack");
    rt_pump(h, 30);
    CHECK_EQ_STR(hmi_runtime_current_page(h->rt), "main");
    CHECK(!hmi_runtime_back(h->rt));          // back does not push
}

int main(void)
{
    test_truthy();

    char dir[] = "/tmp/hmi-acts-XXXXXX";
    CHECK(mkdtemp(dir) != NULL);
    char path[600];
    snprintf(path, sizeof path, "%s/manifest.json", dir);
    FILE *f = fopen(path, "w");
    fputs(MANIFEST, f);
    fclose(f);

    rt_t h;
    CHECK(rt_open_dir(&h, DESIGN, true, dir));
    rt_wait_client(&h, 3000);
    test_list_runs_in_order(&h);
    test_toggle(&h);
    test_increment_decrement(&h);
    test_confirm(&h);
    test_unknown_kind_is_skipped(&h);
    test_ack(&h);
    test_back(&h);
    rt_close(&h);
    remove(path);
    rmdir(dir);
    return check_summary("test_actions");
}
