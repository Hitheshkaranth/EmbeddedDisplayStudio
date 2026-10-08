/* test_core.c -- A1's gate: tag store, config, protocol, subscribers.
 * FROZEN (skeleton): the worker makes it pass; it does not edit it. */
#include "check.h"
#include "config.h"
#include "proto.h"
#include "subs.h"
#include "tagstore.h"

#include <arpa/inet.h>
#include <stdlib.h>

static cJSON *parse(const char *s) { return s ? cJSON_Parse(s) : NULL; }

static void test_util(void)
{
    CHECK(hwd_tag_valid("ai.pot"));
    CHECK(hwd_tag_valid("mb.train.next_station"));
    CHECK(!hwd_tag_valid("pot"));
    CHECK(!hwd_tag_valid("Ai.pot"));
    CHECK(!hwd_tag_valid("ai..pot"));
    CHECK(!hwd_tag_valid("1ai.pot"));
    CHECK_STR(hwd_err_name(HWD_ERR_UNKNOWN_TAG), "unknown_tag");
    CHECK_STR(hwd_err_name(HWD_ERR_NO_HISTORY), "no_history");
}

static void test_store(void)
{
    hwd_tagstore *s = hwd_tagstore_create();
    CHECK(s != NULL);
    if (!s) return;
    CHECK(hwd_tagstore_register(s, "do.relay1", hwd_bool(false), true));
    CHECK(hwd_tagstore_register(s, "ai.pot", hwd_null(), false));
    CHECK(hwd_tagstore_register(s, "serial.scan.rx", hwd_str("x"), false));
    CHECK(!hwd_tagstore_register(s, "do.relay1", hwd_bool(true), true));   /* duplicate */
    CHECK(!hwd_tagstore_register(s, "Bad", hwd_null(), false));            /* invalid name */
    CHECK(hwd_tagstore_count(s) == 3);
    CHECK(hwd_tagstore_exists(s, "ai.pot"));
    CHECK(!hwd_tagstore_exists(s, "ai.nope"));
    CHECK(hwd_tagstore_writable(s, "do.relay1"));
    CHECK(!hwd_tagstore_writable(s, "ai.pot"));
    hwd_value v = hwd_float(1.5);
    CHECK(hwd_tagstore_set(s, "ai.pot", &v));
    hwd_value got = hwd_tagstore_get(s, "ai.pot");
    CHECK(got.kind == HWD_FLOAT && got.u.f == 1.5);
    hwd_value str = hwd_tagstore_get(s, "serial.scan.rx");
    CHECK(str.kind == HWD_STR && strcmp(str.u.s, "x") == 0);
    hwd_value_clear(&str);
    CHECK(!hwd_tagstore_set(s, "ai.nope", &v));
    const char *names[8];
    size_t n = hwd_tagstore_names(s, names, 8);
    CHECK(n == 3);
    if (n == 3) {
        CHECK_STR(names[0], "do.relay1");      /* registration order */
        CHECK_STR(names[2], "serial.scan.rx");
    }
    char q[16];
    CHECK(!hwd_tagstore_quality(s, "ai.pot", q, sizeof q));
    hwd_tagstore_set_quality(s, "ai.pot", "bad");
    CHECK(hwd_tagstore_quality(s, "ai.pot", q, sizeof q) && strcmp(q, "bad") == 0);
    hwd_tagstore_set_quality(s, "ai.pot", NULL);
    CHECK(!hwd_tagstore_quality(s, "ai.pot", q, sizeof q));
    hwd_tagstore_destroy(s);
}

static void test_config(void)
{
    hwd_config c;
    char err[256];
    CHECK(hwd_config_parse("{\"daemon\":{},\"gpio\":{}}", &c, err, sizeof err));
    CHECK(c.poll_interval_ms == 100);
    CHECK(c.cmd_port == 5000);
    CHECK_STR(c.sink_host, "127.0.0.1");
    CHECK(c.sink_port == 5001);
    CHECK(c.subscriber_ttl_s == 5);
    CHECK(c.discovery == true);
    CHECK(c.discovery_port == HWD_DISCOVERY_PORT);
    CHECK(c.gpio != NULL && c.adc == NULL && c.modbus == NULL && c.can == NULL);
    hwd_config_free(&c);

    CHECK(hwd_config_parse("{\"daemon\":{\"poll_interval_ms\":50,\"cmd_port\":6000,"
                           "\"telemetry_sink\":\"127.0.0.1:6001\",\"discovery\":false},"
                           "\"gpio\":{},\"can\":{\"interface\":\"vcan0\",\"signals\":{}}}",
                           &c, err, sizeof err));
    CHECK(c.poll_interval_ms == 50 && c.cmd_port == 6000 && c.sink_port == 6001);
    CHECK(c.discovery == false);
    CHECK(c.can != NULL);
    hwd_config_free(&c);

    CHECK(!hwd_config_parse("{\"gpio\":{}}", &c, err, sizeof err));               /* no daemon */
    hwd_config_free(&c);
    CHECK(!hwd_config_parse("{\"daemon\":{}}", &c, err, sizeof err));             /* no gpio */
    hwd_config_free(&c);
    CHECK(!hwd_config_parse("{\"daemon\":{\"poll_interval_ms\":0},\"gpio\":{}}", &c, err, sizeof err));
    hwd_config_free(&c);
    CHECK(!hwd_config_parse("{\"daemon\":{\"telemetry_sink\":\"nope\"},\"gpio\":{}}", &c, err, sizeof err));
    hwd_config_free(&c);
    CHECK(!hwd_config_parse("{\"daemon\":{},\"gpio\":{\"inputs\":{\"Bad.Tag\":{\"offset\":1}}}}", &c, err, sizeof err));
    hwd_config_free(&c);
    CHECK(!hwd_config_parse("not json", &c, err, sizeof err));
    hwd_config_free(&c);
}

static void test_parse(void)
{
    hwd_cmd c;
    const char *m = "{\"id\":\"c-17\",\"cmd\":\"set\",\"tag\":\"do.relay1\",\"value\":1}";
    CHECK(hwd_proto_parse(m, strlen(m), &c) == HWD_OK);
    CHECK(c.kind == HWD_CMD_SET && c.has_id && strcmp(c.id, "c-17") == 0);
    CHECK_STR(c.tag, "do.relay1");
    CHECK(c.value.kind == HWD_INT && c.value.u.i == 1);
    hwd_cmd_free(&c);

    m = "{\"cmd\":\"set\",\"tag\":\"do.relay1\",\"value\":true}";
    CHECK(hwd_proto_parse(m, strlen(m), &c) == HWD_OK);
    CHECK(!c.has_id && c.value.kind == HWD_BOOL && c.value.u.b);
    hwd_cmd_free(&c);

    m = "{\"id\":\"p\",\"cmd\":\"pulse\",\"tag\":\"do.relay1\",\"ms\":250}";
    CHECK(hwd_proto_parse(m, strlen(m), &c) == HWD_OK && c.kind == HWD_CMD_PULSE && c.ms == 250);
    hwd_cmd_free(&c);
    m = "{\"id\":\"p\",\"cmd\":\"pulse\",\"tag\":\"do.relay1\",\"ms\":20000}";
    CHECK(hwd_proto_parse(m, strlen(m), &c) == HWD_ERR_BAD_VALUE);
    hwd_cmd_free(&c);

    m = "{\"id\":\"s\",\"cmd\":\"subscribe\",\"ttl\":7}";
    CHECK(hwd_proto_parse(m, strlen(m), &c) == HWD_OK && c.kind == HWD_CMD_SUBSCRIBE && c.ttl == 7);
    hwd_cmd_free(&c);
    m = "{\"id\":\"h\",\"cmd\":\"history\",\"tag\":\"ai.pot\"}";
    CHECK(hwd_proto_parse(m, strlen(m), &c) == HWD_OK && c.kind == HWD_CMD_HISTORY);
    CHECK(c.seconds == 3600 && c.points == 200);
    hwd_cmd_free(&c);
    m = "{\"id\":\"u\",\"cmd\":\"uart_tx\",\"data\":\"PING\\r\\n\"}";
    CHECK(hwd_proto_parse(m, strlen(m), &c) == HWD_OK && c.kind == HWD_CMD_UART_TX);
    CHECK(c.data && strcmp(c.data, "PING\r\n") == 0);
    hwd_cmd_free(&c);
    m = "{\"id\":\"l\",\"cmd\":\"list\"}";
    CHECK(hwd_proto_parse(m, strlen(m), &c) == HWD_OK && c.kind == HWD_CMD_LIST);
    hwd_cmd_free(&c);

    m = "{\"id\":\"x\",\"cmd\":\"explode\"}";
    CHECK(hwd_proto_parse(m, strlen(m), &c) == HWD_ERR_UNKNOWN_CMD && c.has_id);
    hwd_cmd_free(&c);
    m = "[1,2]";
    CHECK(hwd_proto_parse(m, strlen(m), &c) == HWD_ERR_NOT_AN_OBJECT);
    hwd_cmd_free(&c);
    m = "{\"id\":\"broken\",\"cmd\":";
    CHECK(hwd_proto_parse(m, strlen(m), &c) == HWD_ERR_BAD_JSON);
    CHECK(c.has_id && strcmp(c.id, "broken") == 0);        /* recovered best-effort */
    hwd_cmd_free(&c);
    char *big = malloc(HWD_MAX_DGRAM + 10);
    memset(big, ' ', HWD_MAX_DGRAM + 9);
    big[HWD_MAX_DGRAM + 9] = 0;
    CHECK(hwd_proto_parse(big, HWD_MAX_DGRAM + 9, &c) == HWD_ERR_TOO_LARGE);
    hwd_cmd_free(&c);
    free(big);
}

static void test_replies(void)
{
    char *a = hwd_proto_ack("c-1", HWD_OK);
    cJSON *j = parse(a);
    CHECK(j && cJSON_IsTrue(cJSON_GetObjectItem(j, "ok")));
    CHECK(j && strcmp(cJSON_GetStringValue(cJSON_GetObjectItem(j, "t")), "ack") == 0);
    CHECK(j && strcmp(cJSON_GetStringValue(cJSON_GetObjectItem(j, "id")), "c-1") == 0);
    cJSON_Delete(j);
    free(a);
    a = hwd_proto_ack("c-2", HWD_ERR_NOT_WRITABLE);
    j = parse(a);
    CHECK(j && cJSON_IsFalse(cJSON_GetObjectItem(j, "ok")));
    CHECK(j && strcmp(cJSON_GetStringValue(cJSON_GetObjectItem(j, "err")), "not_writable") == 0);
    cJSON_Delete(j);
    free(a);

    hwd_tagstore *s = hwd_tagstore_create();
    if (!s) { CHECK(s != NULL); return; }
    hwd_tagstore_register(s, "ai.pot", hwd_float(1.25), false);
    hwd_tagstore_register(s, "di.estop", hwd_bool(false), false);
    hwd_tagstore_register(s, "ai.bad", hwd_null(), false);
    hwd_tagstore_set_quality(s, "ai.bad", "bad");

    a = hwd_proto_list_ack("l", s);
    j = parse(a);
    cJSON *tags = j ? cJSON_GetObjectItem(j, "tags") : NULL;
    CHECK(cJSON_GetArraySize(tags) == 3);
    if (cJSON_GetArraySize(tags) == 3) {      /* sorted */
        CHECK_STR(cJSON_GetArrayItem(tags, 0)->valuestring, "ai.bad");
        CHECK_STR(cJSON_GetArrayItem(tags, 2)->valuestring, "di.estop");
    }
    cJSON_Delete(j);
    free(a);

    a = hwd_proto_frame(s, 42, 1755600000.125);
    j = parse(a);
    CHECK(j != NULL);
    if (j) {
        CHECK_STR(cJSON_GetStringValue(cJSON_GetObjectItem(j, "t")), "tags");
        CHECK_STR(cJSON_GetStringValue(cJSON_GetObjectItem(j, "src")), "hmi-hwd");
        CHECK(cJSON_GetObjectItem(j, "seq")->valuedouble == 42);
        CHECK_NEAR(cJSON_GetObjectItem(j, "ts")->valuedouble, 1755600000.125, 0.002);
        cJSON *t = cJSON_GetObjectItem(j, "tags");
        CHECK(cJSON_GetObjectItem(t, "ai.pot")->valuedouble == 1.25);
        CHECK(cJSON_IsFalse(cJSON_GetObjectItem(t, "di.estop")));
        CHECK(cJSON_IsNull(cJSON_GetObjectItem(t, "ai.bad")));            /* null, never omitted */
        cJSON *q = cJSON_GetObjectItem(j, "q");
        CHECK(q && strcmp(cJSON_GetStringValue(cJSON_GetObjectItem(q, "ai.bad")), "bad") == 0);
        CHECK(q && cJSON_GetObjectItem(q, "ai.pot") == NULL);
    }
    cJSON_Delete(j);
    free(a);
    hwd_tagstore_set_quality(s, "ai.bad", NULL);
    a = hwd_proto_frame(s, 43, 1.0);
    j = parse(a);
    CHECK(j && cJSON_GetObjectItem(j, "q") == NULL);                    /* all good: no q */
    cJSON_Delete(j);
    free(a);

    cJSON *samples = cJSON_CreateArray();
    cJSON *pt = cJSON_CreateArray();
    cJSON_AddItemToArray(pt, cJSON_CreateNumber(1790569717123.0));
    cJSON_AddItemToArray(pt, cJSON_CreateNumber(612.5));
    cJSON_AddItemToArray(samples, pt);
    a = hwd_proto_history_ack("h", "ai.pot", samples);
    j = parse(a);
    cJSON *h = j ? cJSON_GetObjectItem(j, "history") : NULL;
    CHECK(h && strcmp(cJSON_GetStringValue(cJSON_GetObjectItem(h, "tag")), "ai.pot") == 0);
    CHECK(h && cJSON_GetArraySize(cJSON_GetObjectItem(h, "samples")) == 1);
    cJSON_Delete(j);
    free(a);
    hwd_tagstore_destroy(s);
}

static struct sockaddr_in addr(int port)
{
    struct sockaddr_in a;
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port = htons(port);
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    return a;
}

static void test_subs(void)
{
    struct sockaddr_in sink = addr(5001), a = addr(6000), out[8];
    hwd_subs *s = hwd_subs_create(&sink, 5.0);
    CHECK(s != NULL);
    if (!s) return;
    CHECK(hwd_subs_targets(s, 100.0, out, 8) == 1);
    hwd_subs_subscribe(s, &a, 0, 100.0);                  /* default ttl 5 */
    CHECK(hwd_subs_targets(s, 101.0, out, 8) == 2);
    CHECK(ntohs(out[0].sin_port) == 5001);                /* the static sink first */
    CHECK(hwd_subs_targets(s, 106.0, out, 8) == 1);       /* expired */
    hwd_subs_subscribe(s, &a, 2.0, 200.0);
    CHECK(hwd_subs_targets(s, 201.0, out, 8) == 2);
    hwd_subs_unsubscribe(s, &a);
    CHECK(hwd_subs_targets(s, 201.0, out, 8) == 1);
    hwd_subs_subscribe(s, &sink, 5.0, 300.0);             /* the sink is never twice */
    CHECK(hwd_subs_targets(s, 301.0, out, 8) == 1);
    hwd_subs_destroy(s);
}

int main(void)
{
    test_util();
    test_store();
    test_config();
    test_parse();
    test_replies();
    test_subs();
    CHECK_DONE();
}
