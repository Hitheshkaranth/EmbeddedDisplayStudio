/* test_can.c -- A2's gate for CAN signal packing (DBC numbering) and the
 * can backend in sim mode. FROZEN (skeleton). */
#include "check.h"
#include "backend.h"
#include "periph.h"

static void test_bits(void)
{
    uint8_t d[8] = {0x34, 0x12, 0, 0, 0, 0, 0, 0};
    CHECK(can_get_bits(d, 0, 16, false) == 0x1234);          /* Intel */
    CHECK(can_get_bits(d, 4, 4, false) == 0x3);
    uint8_t m[8] = {0x12, 0x34, 0, 0, 0, 0, 0, 0};
    CHECK(can_get_bits(m, 7, 16, true) == 0x1234);           /* Motorola, MSB at bit 7 */
    uint8_t m12[8] = {0xAB, 0xC0, 0, 0, 0, 0, 0, 0};
    CHECK(can_get_bits(m12, 7, 12, true) == 0xABC);
    uint8_t out[8] = {0};
    can_set_bits(out, 8, 8, false, 0x5A);
    CHECK(out[1] == 0x5A && out[0] == 0);
    can_set_bits(out, 0, 1, false, 1);
    CHECK(out[0] == 0x01 && out[1] == 0x5A);
    uint8_t mo[8] = {0};
    can_set_bits(mo, 7, 16, true, 0xBEEF);
    CHECK(mo[0] == 0xBE && mo[1] == 0xEF);
    CHECK(can_get_bits(mo, 7, 16, true) == 0xBEEF);
    CHECK(can_sign_extend(0xFFF, 12) == -1);
    CHECK(can_sign_extend(0x7FF, 12) == 0x7FF);
    uint32_t id;
    CHECK(can_parse_id("0x123", false, &id) && id == 0x123);
    CHECK(can_parse_id("291", false, &id) && id == 291);
    CHECK(!can_parse_id("0x800", false, &id));               /* past 11 bits */
    CHECK(can_parse_id("0x1FFFFFFF", true, &id) && id == 0x1FFFFFFF);
    CHECK(!can_parse_id("zz", false, &id));
    uint8_t h[8];
    CHECK(can_parse_hex("0102AABB", h) == 4 && h[0] == 1 && h[3] == 0xBB);
    CHECK(can_parse_hex("01 02 aa bb", h) == 4 && h[2] == 0xAA);
    CHECK(can_parse_hex("0g", h) == -1);
    CHECK(can_parse_hex("010203040506070809", h) == -1);    /* more than 8 */
}

static void test_sim_backend(void)
{
    hwd_config c;
    memset(&c, 0, sizeof c);
    cJSON *can = cJSON_Parse(
        "{\"interface\":\"can0\",\"signals\":{"
        "\"can.motor.rpm\":{\"id\":\"0x123\",\"start_bit\":0,\"length\":16,\"scale\":0.25},"
        "\"can.motor.enable\":{\"id\":\"0x200\",\"start_bit\":0,\"length\":1,\"writable\":true}}}");
    c.can = can;
    char err[256];
    CHECK(hwd_backend_can.validate(&c, err, sizeof err) == 0);
    hwd_tagstore *s = hwd_tagstore_create();
    hwd_backend_opts o = {.sim = true, .poll_interval_ms = 100};
    void *b = s ? hwd_backend_can.create(&c, s, &o, err, sizeof err) : NULL;
    CHECK(b != NULL);
    if (b) {
        if (hwd_backend_can.start) hwd_backend_can.start(b);
        CHECK(hwd_tagstore_exists(s, "can.motor.rpm"));
        CHECK(hwd_tagstore_exists(s, "sys.can_online"));
        CHECK(hwd_tagstore_writable(s, "can.motor.enable"));
        CHECK(!hwd_tagstore_writable(s, "can.motor.rpm"));
        CHECK(hwd_backend_can.owns(b, "can.motor.rpm"));
        if (hwd_backend_can.poll) hwd_backend_can.poll(b, 10.0);
        hwd_value v = hwd_tagstore_get(s, "can.motor.rpm");
        CHECK(v.kind == HWD_FLOAT || v.kind == HWD_INT);    /* sim ramps */
        hwd_value on = hwd_bool(true);
        CHECK(hwd_backend_can.write(b, "can.motor.enable", &on) == HWD_OK);
        CHECK(hwd_backend_can.write(b, "can.motor.rpm", &on) == HWD_ERR_NOT_WRITABLE);
        if (hwd_backend_can.poll) hwd_backend_can.poll(b, 10.2);
        hwd_value e = hwd_tagstore_get(s, "can.motor.enable");          /* echoed in sim */
        CHECK((e.kind == HWD_BOOL && e.u.b) || (e.kind == HWD_INT && e.u.i == 1) ||
              (e.kind == HWD_FLOAT && e.u.f == 1));
        cJSON *msg = cJSON_Parse("{\"cmd\":\"can_tx\",\"id\":\"0x321\",\"data\":\"0102\"}");
        cJSON *reply = cJSON_CreateObject();
        CHECK(hwd_backend_can.command(b, "can_tx", msg, reply) == HWD_OK);
        CHECK(hwd_backend_can.command(b, "serial_tx", msg, reply) == HWD_ERR_UNKNOWN_CMD);
        cJSON_Delete(msg);
        cJSON_Delete(reply);
        hwd_backend_can.destroy(b);
    }
    if (s) hwd_tagstore_destroy(s);
    cJSON_Delete(can);
    cJSON *bad = cJSON_Parse("{\"interface\":\"can0\",\"signals\":{\"can.x\":{\"id\":\"0x800\",\"start_bit\":0,\"length\":8}}}");
    c.can = bad;
    CHECK(hwd_backend_can.validate(&c, err, sizeof err) != 0);
    cJSON_Delete(bad);
}

int main(void)
{
    test_bits();
    test_sim_backend();
    CHECK_DONE();
}
