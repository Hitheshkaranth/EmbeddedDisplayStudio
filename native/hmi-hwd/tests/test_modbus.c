/* test_modbus.c -- A2's gate for the Modbus codec (TCP + RTU) and the
 * backend's config validation. FROZEN (skeleton). */
#include "check.h"
#include "backend.h"
#include "modbus.h"

static void test_types(void)
{
    CHECK(mb_type_registers(MB_BOOL) == 1);
    CHECK(mb_type_registers(MB_INT16) == 1 && mb_type_registers(MB_UINT16) == 1);
    CHECK(mb_type_registers(MB_INT32) == 2 && mb_type_registers(MB_FLOAT32) == 2);
    uint16_t r[2];
    r[0] = 0xFFFF;
    CHECK(mb_decode(MB_INT16, r, false) == -1);
    CHECK(mb_decode(MB_UINT16, r, false) == 65535);
    r[0] = 0x0001; r[1] = 0x0000;
    CHECK(mb_decode(MB_INT32, r, false) == 65536);        /* big words: high first */
    CHECK(mb_decode(MB_INT32, r, true) == 1);             /* little words: low first */
    r[0] = 0x3FC0; r[1] = 0x0000;
    CHECK_NEAR(mb_decode(MB_FLOAT32, r, false), 1.5, 1e-9);
    r[0] = 0x0000; r[1] = 0xC010;
    CHECK_NEAR(mb_decode(MB_FLOAT32, r, true), -2.25, 1e-9);
    uint16_t w[2] = {0, 0};
    CHECK(mb_encode(MB_FLOAT32, 1.5, w, false) == 2 && w[0] == 0x3FC0 && w[1] == 0);
    CHECK(mb_encode(MB_INT16, -2, w, false) == 1 && w[0] == 0xFFFE);
    CHECK(mb_encode(MB_UINT32, 65537, w, false) == 2 && w[0] == 1 && w[1] == 1);
    CHECK(mb_encode(MB_INT32, 70000, w, true) == 2 && w[0] == (70000 & 0xFFFF) && w[1] == 1);
}

static void test_tcp(void)
{
    uint8_t b[260];
    size_t n = mb_req_read(b, 1, 1, 3, 100, 2);
    const uint8_t want[] = {0, 1, 0, 0, 0, 6, 1, 3, 0, 100, 0, 2};
    CHECK(n == sizeof want && memcmp(b, want, n) == 0);
    n = mb_req_write_single(b, 7, 1, 6, 1, 3);
    const uint8_t w6[] = {0, 7, 0, 0, 0, 6, 1, 6, 0, 1, 0, 3};
    CHECK(n == sizeof w6 && memcmp(b, w6, n) == 0);
    n = mb_req_write_single(b, 8, 1, 5, 0, 0xFF00);       /* coil on */
    CHECK(n == 12 && b[10] == 0xFF && b[11] == 0x00);
    uint16_t regs2[2] = {0x3FC0, 0x0000};
    n = mb_req_write_multi(b, 9, 1, 10, regs2, 2);
    const uint8_t w16[] = {0, 9, 0, 0, 0, 11, 1, 16, 0, 10, 0, 2, 4, 0x3F, 0xC0, 0, 0};
    CHECK(n == sizeof w16 && memcmp(b, w16, n) == 0);

    /* responses */
    const uint8_t r3[] = {0, 1, 0, 0, 0, 7, 1, 3, 4, 0x00, 0x0A, 0x00, 0x0B};
    uint16_t regs[2] = {0, 0};
    CHECK(mb_parse_read(r3, sizeof r3, 1, 3, 2, NULL, regs) == 0);
    CHECK(regs[0] == 10 && regs[1] == 11);
    CHECK(mb_parse_read(r3, sizeof r3, 2, 3, 2, NULL, regs) == -1);   /* wrong transaction */
    CHECK(mb_parse_read(r3, 9, 1, 3, 2, NULL, regs) == -1);           /* short */
    const uint8_t ex[] = {0, 1, 0, 0, 0, 3, 1, 0x83, 0x02};
    CHECK(mb_parse_read(ex, sizeof ex, 1, 3, 2, NULL, regs) == 2);    /* illegal address */
    const uint8_t r1[] = {0, 5, 0, 0, 0, 4, 1, 1, 1, 0x05};           /* coils 0,2 on */
    uint8_t bits[3] = {9, 9, 9};
    CHECK(mb_parse_read(r1, sizeof r1, 5, 1, 3, bits, NULL) == 0);
    CHECK(bits[0] == 1 && bits[1] == 0 && bits[2] == 1);
    CHECK(mb_parse_write(w6, sizeof w6, 7, 6) == 0);                  /* FC6 echoes */
    const uint8_t e16[] = {0, 9, 0, 0, 0, 6, 1, 16, 0, 10, 0, 2};
    CHECK(mb_parse_write(e16, sizeof e16, 9, 16) == 0);
}

static void test_rtu(void)
{
    const uint8_t req[] = {1, 3, 0, 0, 0, 0x0A};
    CHECK(mb_crc16(req, sizeof req) == 0xCDC5);
    uint8_t b[260];
    size_t n = mb_rtu_req_read(b, 1, 3, 0, 10);
    const uint8_t want[] = {1, 3, 0, 0, 0, 0x0A, 0xC5, 0xCD};
    CHECK(n == sizeof want && memcmp(b, want, n) == 0);
    n = mb_rtu_req_write_single(b, 1, 6, 1, 3);
    const uint8_t w6[] = {1, 6, 0, 1, 0, 3, 0x98, 0x0B};
    CHECK(n == sizeof w6 && memcmp(b, w6, n) == 0);
    const uint8_t resp[] = {1, 3, 4, 0, 0x0A, 0, 0x0B, 0x9B, 0xF6};
    uint16_t regs[2] = {0, 0};
    CHECK(mb_rtu_parse_read(resp, sizeof resp, 1, 3, 2, NULL, regs) == 0);
    CHECK(regs[0] == 10 && regs[1] == 11);
    uint8_t bad[sizeof resp];
    memcpy(bad, resp, sizeof resp);
    bad[4] ^= 1;
    CHECK(mb_rtu_parse_read(bad, sizeof bad, 1, 3, 2, NULL, regs) == -1);   /* CRC */
    CHECK(mb_rtu_parse_read(resp, sizeof resp, 2, 3, 2, NULL, regs) == -1);  /* other unit */
    CHECK(mb_rtu_parse_write(w6, sizeof w6, 1, 6) == 0);
}

static void test_validate(void)
{
    hwd_config c;
    memset(&c, 0, sizeof c);
    char err[256];
    const char *cases[][2] = {
        {"{\"host\":\"127.0.0.1\",\"tags\":{\"mb.a\":{\"kind\":\"holding\",\"address\":0,\"type\":\"int16\"}}}", "ok"},
        {"{\"tags\":{}}", "bad"},                                                          /* no host */
        {"{\"host\":\"h\",\"port\":99999,\"tags\":{}}", "bad"},
        {"{\"host\":\"h\",\"tags\":{\"mb.a\":{\"kind\":\"coil\",\"address\":0,\"type\":\"int16\"}}}", "bad"},
        {"{\"host\":\"h\",\"tags\":{\"mb.a\":{\"kind\":\"input\",\"address\":0,\"type\":\"int16\",\"writable\":true}}}", "bad"},
        {"{\"host\":\"h\",\"tags\":{\"mb.a\":{\"kind\":\"nope\",\"address\":0}}}", "bad"},
        {"{\"host\":\"h\",\"tags\":{\"mb.a\":{\"kind\":\"input\",\"address\":0,\"type\":\"uint16\",\"enum\":[\"A\",\"B\"]}}}", "ok"},
        {"{\"host\":\"h\",\"tags\":{\"mb.a\":{\"kind\":\"input\",\"address\":0,\"type\":\"float32\",\"enum\":[\"A\"]}}}", "bad"},
    };
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        cJSON *m = cJSON_Parse(cases[i][0]);
        c.modbus = m;
        int rc = hwd_backend_modbus.validate(&c, err, sizeof err);
        if (strcmp(cases[i][1], "ok") == 0) CHECK(rc == 0);
        else CHECK(rc != 0 && err[0]);
        if (rc != 0 && strcmp(cases[i][1], "ok") == 0) fprintf(stderr, "  case %zu: %s\n", i, err);
        cJSON_Delete(m);
    }
    c.modbus = NULL;
    cJSON *rtu = cJSON_Parse("{\"path\":\"/dev/ttyUSB1\",\"baudrate\":19200,\"tags\":{\"mb.rtu.t\":"
                             "{\"unit\":3,\"kind\":\"input\",\"address\":0,\"type\":\"int16\",\"scale\":0.1}}}");
    c.modbus_rtu = rtu;
    CHECK(hwd_backend_modbus.validate(&c, err, sizeof err) == 0);
    cJSON_Delete(rtu);
}

int main(void)
{
    test_types();
    test_tcp();
    test_rtu();
    test_validate();
    CHECK_DONE();
}
