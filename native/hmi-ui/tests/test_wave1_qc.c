// tests/test_wave1_qc.c -- defects found reviewing the wave 1 swarm, pinned.
#include <sys/stat.h>

#include "actions.h"
#include "alarms.h"
#include "check.h"
#include "modal.h"
#include "rt_harness.h"

static const char *DESIGN =
    "{\"version\":1,\"name\":\"qc\",\"screen\":{\"width\":800,\"height\":480},\"pages\":[{\"id\":\"main\",\"widgets\":["
    " {\"type\":\"ShButton\",\"id\":\"plain\",\"geometry\":{\"x\":0,\"y\":0,\"width\":100,\"height\":40},"
    "  \"actions\":{\"clicked\":{\"kind\":\"write\",\"tag\":\"q.plain\",\"value\":5}}},"
    " {\"type\":\"ShButton\",\"id\":\"asks\",\"geometry\":{\"x\":0,\"y\":50,\"width\":100,\"height\":40},"
    "  \"actions\":{\"clicked\":{\"kind\":\"write\",\"tag\":\"q.asks\",\"value\":1,\"confirm\":\"Go?\"}}},"
    " {\"type\":\"ShAlarmTable\",\"id\":\"table\",\"geometry\":{\"x\":200,\"y\":0,\"width\":350,\"height\":216},"
    "  \"actions\":{\"alarmActivated\":{\"kind\":\"write\",\"tag\":\"q.legacy\"}}},"
    " {\"type\":\"ShButton\",\"id\":\"ackall\",\"geometry\":{\"x\":0,\"y\":100,\"width\":100,\"height\":40},"
    "  \"actions\":{\"clicked\":{\"kind\":\"ack\",\"tag\":\"*\"}}},"
    " {\"type\":\"ShButton\",\"id\":\"shelve\",\"geometry\":{\"x\":0,\"y\":150,\"width\":100,\"height\":40},"
    "  \"actions\":{\"clicked\":{\"kind\":\"shelve\",\"tag\":\"q.u\",\"ms\":60000}}}"
    "]}]}";

static const char *MANIFEST =
    "{\"schema\":1,\"name\":\"qc\",\"version\":\"1.0.0\",\"entry\":\"project.edsui\",\"runtime\":\"edsui\","
    "\"alarms\":[{\"tag\":\"q.t\",\"label\":\"T\",\"critical\":{\"op\":\">\",\"value\":5}},"
    "            {\"tag\":\"q.u\",\"label\":\"U\",\"warning\":{\"op\":\">\",\"value\":5}},"
    "            {\"tag\":\"q.v\",\"label\":\"V\",\"warning\":{\"op\":\">\",\"value\":5}}]}";

int main(void)
{
    char dir[] = "/tmp/hmi-qc-XXXXXX";
    CHECK(mkdtemp(dir) != NULL);
    char path[600];
    snprintf(path, sizeof path, "%s/manifest.json", dir);
    FILE *f = fopen(path, "w");
    fputs(MANIFEST, f);
    fclose(f);

    rt_t h;
    CHECK(rt_open_dir(&h, DESIGN, true, dir));
    rt_wait_client(&h, 3000);

    // 1. A list without `confirm` still runs while another popup is open.
    CHECK(hmi_modal_claim("keypad"));
    hmi_runtime_signal(rt_widget(&h, "plain"), "clicked", NULL);
    cJSON *c = rt_next_command(&h, 800);
    CHECK(c && strcmp(rt_cmd_str(c, "tag"), "q.plain") == 0);
    cJSON_Delete(c);
    hmi_modal_release("keypad");

    // 2. Answering deletes the dialog.
    uint32_t before = lv_obj_get_child_count(lv_layer_top());
    hmi_runtime_signal(rt_widget(&h, "asks"), "clicked", NULL);
    CHECK(lv_obj_get_child_count(lv_layer_top()) == before + 1);
    hmi_actions_answer_confirm(false);
    rt_pump(&h, 50);
    CHECK(lv_obj_get_child_count(lv_layer_top()) == before);

    // 3. Legacy: a write on alarmActivated acknowledges the alarm, writes nothing.
    rt_frame(&h, "{\"q.t\":9}");
    hmi_value_t tag = hmi_value_str("q.t");
    hmi_runtime_signal(rt_widget(&h, "table"), "alarmActivated", &tag);
    hmi_value_free(&tag);
    size_t n = 0;
    const hmi_alarm_t *list = hmi_alarms_active(hmi_runtime_alarms(h.rt), &n);
    CHECK(n == 1 && list[0].acknowledged);
    c = rt_next_command(&h, 300);
    CHECK(c == NULL);
    cJSON_Delete(c);

    // 4. Across workers: W1's dispatch into W3's engine -- ack "*" and shelve.
    rt_frame(&h, "{\"q.u\":9,\"q.v\":9}");
    hmi_runtime_signal(rt_widget(&h, "ackall"), "clicked", NULL);
    list = hmi_alarms_active(hmi_runtime_alarms(h.rt), &n);
    size_t acked = 0;
    for (size_t i = 0; i < n; i++) acked += list[i].acknowledged;
    CHECK(n == 3 && acked == 3);
    hmi_runtime_signal(rt_widget(&h, "shelve"), "clicked", NULL);
    CHECK(hmi_alarms_is_shelved(hmi_runtime_alarms(h.rt), "q.u"));
    list = hmi_alarms_active(hmi_runtime_alarms(h.rt), &n);
    CHECK(n == 2);

    rt_close(&h);
    remove(path);
    rmdir(dir);
    return check_summary("test_wave1_qc");
}
