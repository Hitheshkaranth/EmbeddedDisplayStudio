// tests/test_input.c -- CONTRACT 13.5 keypad, keyboard and the two widgets.
// Wave 1 gate for W5 (FROZEN).
#include "check.h"
#include "input.h"
#include "modal.h"
#include "rt_harness.h"

static int g_num_calls;
static double g_num;
static int g_text_calls;
static char g_text[128];

static void on_num(double v, void *user) { (void)user; ++g_num_calls; g_num = v; }
static void on_text(const char *t, void *user) { (void)user; ++g_text_calls; snprintf(g_text, sizeof g_text, "%s", t); }

static void press_all(const char *keys)   // "15.7" -> "1","5",".","7"
{
    for (const char *k = keys; *k; k++) {
        char key[2] = {*k, 0};
        CHECK(hmi_input_press(key));
    }
}

static void test_keypad(hmi_widget_t *w)
{
    g_num_calls = 0;
    CHECK(!hmi_input_is_open());
    CHECK(hmi_input_open_numeric(w, 12.5, 0, 100, 1, on_num, NULL));
    CHECK(hmi_input_is_open());
    CHECK_EQ_STR(hmi_modal_owner(), "keypad");
    CHECK(lv_obj_get_child_count(lv_layer_top()) > 0);
    CHECK_EQ_STR(hmi_input_entry(), "12.5");
    CHECK(!hmi_input_open_numeric(w, 1, 0, 1, 0, on_num, NULL));   // one at a time
    CHECK(hmi_input_press("C"));
    CHECK_EQ_STR(hmi_input_entry(), "");
    press_all("150");
    CHECK(hmi_input_press("OK"));                  // out of range: stays open
    CHECK(hmi_input_is_open());
    CHECK(hmi_input_error_shown());
    CHECK(g_num_calls == 0);
    CHECK(hmi_input_press("BS"));
    CHECK_EQ_STR(hmi_input_entry(), "15");
    press_all(".7.");                              // a second "." is ignored
    CHECK_EQ_STR(hmi_input_entry(), "15.7");
    CHECK(hmi_input_press("OK"));
    CHECK(g_num_calls == 1);
    CHECK_NEAR(g_num, 15.7, 1e-9);
    CHECK(!hmi_input_is_open());
    CHECK(hmi_modal_owner() == NULL);
    CHECK(!hmi_input_press("1"));                  // closed

    // minus toggles; min 0 refuses a negative; rounding to decimals
    CHECK(hmi_input_open_numeric(w, 3, 0, 10, 0, on_num, NULL));
    CHECK_EQ_STR(hmi_input_entry(), "3");
    CHECK(hmi_input_press("-"));
    CHECK_EQ_STR(hmi_input_entry(), "-3");
    CHECK(hmi_input_press("OK"));
    CHECK(hmi_input_is_open());
    CHECK(hmi_input_press("-"));
    CHECK_EQ_STR(hmi_input_entry(), "3");
    press_all(".6");
    CHECK(hmi_input_press("OK"));
    CHECK(g_num_calls == 2);
    CHECK_NEAR(g_num, 4, 1e-9);                    // 3.6 rounded to 0 decimals

    // empty entry is not a number; cancel calls nothing
    CHECK(hmi_input_open_numeric(w, 5, 0, 10, 0, on_num, NULL));
    CHECK(hmi_input_press("C"));
    CHECK(hmi_input_press("OK"));
    CHECK(hmi_input_is_open() && hmi_input_error_shown());
    CHECK(hmi_input_press("CANCEL"));
    CHECK(!hmi_input_is_open());
    CHECK(g_num_calls == 2);
    CHECK(!hmi_input_press("NOPE"));

    // the slot is taken by someone else
    CHECK(hmi_modal_claim("confirm"));
    CHECK(!hmi_input_open_numeric(w, 5, 0, 10, 0, on_num, NULL));
    CHECK(!hmi_input_open_text(w, "x", on_text, NULL));
    hmi_modal_release("confirm");
}

static void test_keyboard(hmi_widget_t *w)
{
    g_text_calls = 0;
    CHECK(hmi_input_open_text(w, "abc", on_text, NULL));
    CHECK_EQ_STR(hmi_modal_owner(), "keyboard");
    CHECK_EQ_STR(hmi_input_entry(), "abc");
    CHECK(hmi_input_set_text("hello"));
    CHECK(hmi_input_press("OK"));
    CHECK(g_text_calls == 1);
    CHECK_EQ_STR(g_text, "hello");
    CHECK(!hmi_input_is_open());
    CHECK(hmi_input_open_text(w, "abc", on_text, NULL));
    CHECK(hmi_input_press("CANCEL"));
    CHECK(g_text_calls == 1 && !hmi_input_is_open());
    CHECK(!hmi_input_set_text("x"));
}

static const char *DESIGN =
    "{\"version\":1,\"name\":\"in\",\"screen\":{\"width\":800,\"height\":480},\"pages\":[{\"id\":\"main\",\"widgets\":["
    "{\"type\":\"ShNumInput\",\"id\":\"num\",\"geometry\":{\"x\":0,\"y\":0,\"width\":240,\"height\":64},"
    " \"properties\":{\"value\":5,\"minValue\":0,\"maxValue\":50,\"decimalPlaces\":1},"
    " \"actions\":{\"valueChanged\":{\"kind\":\"write\",\"tag\":\"s.sp\"}}},"
    "{\"type\":\"ShNumInput\",\"id\":\"numOff\",\"geometry\":{\"x\":0,\"y\":80,\"width\":240,\"height\":64},"
    " \"properties\":{\"value\":5,\"enabled\":false}},"
    "{\"type\":\"ShInput\",\"id\":\"txt\",\"geometry\":{\"x\":300,\"y\":0,\"width\":200,\"height\":40},"
    " \"properties\":{\"text\":\"PUMP-1\"},"
    " \"actions\":{\"accepted\":{\"kind\":\"write\",\"tag\":\"s.name\"}}},"
    "{\"type\":\"ShInput\",\"id\":\"ro\",\"geometry\":{\"x\":300,\"y\":80,\"width\":200,\"height\":40},"
    " \"properties\":{\"text\":\"x\",\"readOnly\":true}}"
    "]}]}";

static void click(hmi_widget_t *w)
{
    lv_obj_send_event((lv_obj_t *)w->native, LV_EVENT_CLICKED, NULL);
}

static void test_widgets(void)
{
    rt_t h;
    CHECK(rt_open(&h, DESIGN, true));
    rt_wait_client(&h, 3000);
    hmi_widget_t *num = rt_widget(&h, "num");
    click(num);
    CHECK(hmi_input_is_open());
    CHECK_EQ_STR(hmi_input_entry(), "5.0");
    CHECK(hmi_input_press("C"));
    press_all("12.25");
    CHECK(hmi_input_press("OK"));
    rt_pump(&h, 30);
    cJSON *c = rt_next_command(&h, 800);
    CHECK(c && strcmp(rt_cmd_str(c, "tag"), "s.sp") == 0);
    CHECK_NEAR(rt_cmd_num(c, "value", -1), 12.3, 1e-9);    // rounded to 1 decimal
    cJSON_Delete(c);

    click(rt_widget(&h, "numOff"));
    CHECK(!hmi_input_is_open());

    click(rt_widget(&h, "txt"));
    CHECK(hmi_input_is_open());
    CHECK_EQ_STR(hmi_input_entry(), "PUMP-1");
    CHECK(hmi_input_set_text("PUMP-2"));
    CHECK(hmi_input_press("OK"));
    rt_pump(&h, 30);
    c = rt_next_command(&h, 800);
    CHECK(c && strcmp(rt_cmd_str(c, "tag"), "s.name") == 0);
    CHECK(c && strcmp(rt_cmd_str(c, "value") ? rt_cmd_str(c, "value") : "", "PUMP-2") == 0);
    cJSON_Delete(c);

    click(rt_widget(&h, "ro"));
    CHECK(!hmi_input_is_open());
    rt_close(&h);
}

int main(void)
{
    rt_lvgl_once();
    lv_tick_set_cb(rt_now_ms);
    hmi_project_t *p = rt_load_json(DESIGN);
    CHECK(p != NULL);
    if (p) {
        test_keypad(p->pages[0]->widgets[0]);
        test_keyboard(p->pages[0]->widgets[2]);
        hmi_project_free(p);
    }
    test_widgets();
    return check_summary("test_input");
}
