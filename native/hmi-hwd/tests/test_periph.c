/* test_periph.c -- A4's gate: HID scanner decoding (keymap and an evdev
 * stream through a FIFO), USB storage detection and export, sensor
 * decoding and presets, the sensors backend in sim mode, and the historian.
 * FROZEN (skeleton). */
#include "check.h"
#include "backend.h"
#include "history.h"
#include "periph.h"

#include <fcntl.h>
#include <linux/input.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

static char tmpdir[256];

static void test_keymap(void)
{
    CHECK(hid_key_char(KEY_A, false) == 'a');
    CHECK(hid_key_char(KEY_A, true) == 'A');
    CHECK(hid_key_char(KEY_1, false) == '1');
    CHECK(hid_key_char(KEY_1, true) == '!');
    CHECK(hid_key_char(KEY_MINUS, false) == '-');
    CHECK(hid_key_char(KEY_MINUS, true) == '_');
    CHECK(hid_key_char(KEY_SPACE, false) == ' ');
    CHECK(hid_key_char(KEY_ENTER, false) == 0);
    CHECK(hid_key_char(KEY_LEFTSHIFT, false) == 0);
}

static void key(int fd, int code, int value)
{
    struct input_event ev;
    memset(&ev, 0, sizeof ev);
    ev.type = EV_KEY;
    ev.code = code;
    ev.value = value;
    CHECK(write(fd, &ev, sizeof ev) == (ssize_t)sizeof ev);
}

static void test_hid_fifo(void)
{
    char fifo[300];
    snprintf(fifo, sizeof fifo, "%s/scanner", tmpdir);
    CHECK(mkfifo(fifo, 0600) == 0);
    char cfgtext[512];
    snprintf(cfgtext, sizeof cfgtext, "{\"devices\":{\"scanner\":{\"path\":\"%s\",\"grab\":true,\"eol\":\"enter\"}}}", fifo);
    hwd_config c;
    memset(&c, 0, sizeof c);
    cJSON *hid = cJSON_Parse(cfgtext);
    c.hid = hid;
    char err[256];
    CHECK(hwd_backend_hid.validate(&c, err, sizeof err) == 0);
    hwd_tagstore *s = hwd_tagstore_create();
    hwd_backend_opts o = {.sim = false, .poll_interval_ms = 50};
    void *b = s ? hwd_backend_hid.create(&c, s, &o, err, sizeof err) : NULL;
    CHECK(b != NULL);
    if (!b) { if (s) hwd_tagstore_destroy(s); cJSON_Delete(hid); return; }
    if (hwd_backend_hid.start) hwd_backend_hid.start(b);
    for (int i = 0; i < 5; i++) { hwd_backend_hid.poll(b, 1.0 + i * 0.1); usleep(20000); }
    int fd = open(fifo, O_WRONLY | O_NONBLOCK);              /* the backend holds the read end */
    CHECK(fd >= 0);
    if (fd >= 0) {
        key(fd, KEY_LEFTSHIFT, 1); key(fd, KEY_P, 1); key(fd, KEY_P, 0); key(fd, KEY_LEFTSHIFT, 0);
        key(fd, KEY_MINUS, 1); key(fd, KEY_MINUS, 0);
        key(fd, KEY_4, 1); key(fd, KEY_4, 0); key(fd, KEY_1, 1); key(fd, KEY_1, 0);
        key(fd, KEY_2, 1); key(fd, KEY_2, 0);
        key(fd, KEY_ENTER, 1); key(fd, KEY_ENTER, 0);
        bool ok = false;
        for (int i = 0; i < 200 && !ok; i++) {
            hwd_backend_hid.poll(b, 2.0 + i * 0.01);
            hwd_value v = hwd_tagstore_get(s, "hid.scanner.text");
            ok = v.kind == HWD_STR && strcmp(v.u.s, "P-412") == 0;
            hwd_value_clear(&v);
            usleep(10000);
        }
        CHECK(ok);
        hwd_value n = hwd_tagstore_get(s, "hid.scanner.count");
        CHECK(n.kind == HWD_INT && n.u.i == 1);
        hwd_value p = hwd_tagstore_get(s, "hid.scanner.present");
        CHECK(p.kind == HWD_BOOL && p.u.b);
        close(fd);
    }
    hwd_backend_hid.destroy(b);
    hwd_tagstore_destroy(s);
    cJSON_Delete(hid);
}

static void test_usb(void)
{
    char media[300], mount[300], mounts[300];
    snprintf(media, sizeof media, "%s/media", tmpdir);
    snprintf(mount, sizeof mount, "%s/media/usb0", tmpdir);
    snprintf(mounts, sizeof mounts, "%s/mounts", tmpdir);
    mkdir(media, 0700);
    mkdir(mount, 0700);
    FILE *f = fopen(mounts, "w");
    fprintf(f, "proc /proc proc rw 0 0\n/dev/sdb1 %s vfat rw 0 0\n", mount);
    fclose(f);
    setenv("HWD_PROC_MOUNTS", mounts, 1);
    char cfgtext[512];
    snprintf(cfgtext, sizeof cfgtext, "{\"storage\":{\"mount_root\":\"%s\",\"export_dir\":\"hmi-export\"}}", media);
    hwd_config c;
    memset(&c, 0, sizeof c);
    cJSON *usb = cJSON_Parse(cfgtext);
    c.usb = usb;
    char err[256];
    CHECK(hwd_backend_usb.validate(&c, err, sizeof err) == 0);
    hwd_tagstore *s = hwd_tagstore_create();
    hwd_backend_opts o = {.sim = false, .poll_interval_ms = 50};
    void *b = s ? hwd_backend_usb.create(&c, s, &o, err, sizeof err) : NULL;
    CHECK(b != NULL);
    if (b) {
        if (hwd_backend_usb.start) hwd_backend_usb.start(b);
        hwd_backend_usb.poll(b, 1.0);
        hwd_backend_usb.poll(b, 3.0);
        hwd_value p = hwd_tagstore_get(s, "usb.storage.present");
        CHECK(p.kind == HWD_BOOL && p.u.b);
        hwd_value path = hwd_tagstore_get(s, "usb.storage.path");
        CHECK(path.kind == HWD_STR && strcmp(path.u.s, mount) == 0);
        hwd_value_clear(&path);
        hwd_value free_mb = hwd_tagstore_get(s, "usb.storage.free_mb");
        CHECK(free_mb.kind == HWD_FLOAT && free_mb.u.f > 0);
        cJSON *msg = cJSON_Parse("{\"cmd\":\"usb_export\",\"what\":\"logs\"}");
        cJSON *reply = cJSON_CreateObject();
        CHECK(hwd_backend_usb.command(b, "usb_export", msg, reply) == HWD_OK);
        const char *file = cJSON_GetStringValue(cJSON_GetObjectItem(reply, "file"));
        CHECK(file && strstr(file, "/hmi-export/logs-") && access(file, R_OK) == 0);
        cJSON_Delete(msg);
        cJSON_Delete(reply);
        f = fopen(mounts, "w");                              /* unplugged */
        fprintf(f, "proc /proc proc rw 0 0\n");
        fclose(f);
        hwd_backend_usb.poll(b, 6.0);
        p = hwd_tagstore_get(s, "usb.storage.present");
        CHECK(p.kind == HWD_BOOL && !p.u.b);
        path = hwd_tagstore_get(s, "usb.storage.path");
        CHECK(path.kind == HWD_NULL);
        msg = cJSON_Parse("{\"cmd\":\"usb_export\",\"what\":\"logs\"}");
        reply = cJSON_CreateObject();
        CHECK(hwd_backend_usb.command(b, "usb_export", msg, reply) == HWD_ERR_HW_ERROR);
        cJSON_Delete(msg);
        cJSON_Delete(reply);
        hwd_backend_usb.destroy(b);
    }
    unsetenv("HWD_PROC_MOUNTS");
    if (s) hwd_tagstore_destroy(s);
    cJSON_Delete(usb);
}

static void test_decode(void)
{
    sens_type t;
    CHECK(sens_parse_type("uint16", &t) && t == SENS_U16 && sens_type_bytes(t) == 2);
    CHECK(sens_parse_type("float32", &t) && t == SENS_F32 && sens_type_bytes(t) == 4);
    CHECK(!sens_parse_type("int64", &t));
    const uint8_t b16[] = {0x12, 0x34};
    CHECK(sens_decode(b16, SENS_U16, true, 0, 0, 1, 0) == 0x1234);
    CHECK(sens_decode(b16, SENS_U16, false, 0, 0, 1, 0) == 0x3412);
    CHECK(sens_decode(b16, SENS_U16, true, 0x03FF, 0, 1, 0) == 0x234);
    CHECK_NEAR(sens_decode(b16, SENS_U16, true, 0x03FF, 2, 0.5, 1), 71.5, 1e-9);
    const uint8_t f[] = {0x3F, 0xC0, 0, 0};
    CHECK_NEAR(sens_decode(f, SENS_F32, true, 0, 0, 1, 0), 1.5, 1e-9);
    const uint8_t m1[] = {0xFF};
    CHECK(sens_decode(m1, SENS_I8, true, 0, 0, 1, 0) == -1);
    const uint8_t t25[] = {0x19, 0x00};
    CHECK_NEAR(sens_tmp102_c(t25), 25.0, 1e-9);
    const uint8_t tneg[] = {0xFF, 0xF0};
    CHECK_NEAR(sens_tmp102_c(tneg), -0.0625, 1e-9);
    const uint8_t sht[] = {0x66, 0x66, 0x93, 0x80, 0x00, 0xA2};
    CHECK(sens_sht3x_crc_ok(sht));
    CHECK_NEAR(sens_sht3x_temp_c(sht), 25.0, 0.01);
    CHECK_NEAR(sens_sht3x_rh(sht), 50.0, 0.01);
    const uint8_t shtbad[] = {0x66, 0x66, 0x00, 0x80, 0x00, 0xA2};
    CHECK(!sens_sht3x_crc_ok(shtbad));
    const uint8_t ads[] = {0x40, 0x00};
    CHECK_NEAR(sens_ads1115_volts(ads), 2.048, 1e-6);
    const uint8_t bus[] = {0x5D, 0xC0};
    CHECK_NEAR(sens_ina219_bus_v(bus), 12.0, 1e-9);
    const uint8_t shunt[] = {0x01, 0xF4};
    CHECK_NEAR(sens_ina219_current_a(shunt, 0.1), 0.05, 1e-9);
}

static void test_sensors_sim(void)
{
    hwd_config c;
    memset(&c, 0, sizeof c);
    cJSON *i2c = cJSON_Parse("{\"sensors\":{\"i2c.cab.temp\":{\"bus\":1,\"address\":\"0x48\",\"device\":\"tmp102\",\"period_ms\":100},"
                             "\"i2c.io.out\":{\"bus\":1,\"address\":\"0x20\",\"register\":\"0x0A\",\"type\":\"uint8\",\"writable\":true}}}");
    cJSON *spi = cJSON_Parse("{\"sensors\":{\"spi.adc.ch0\":{\"bus\":1,\"cs\":0,\"tx\":\"01 80 00\",\"rx_offset\":1,"
                             "\"length\":2,\"type\":\"uint16\",\"mask\":\"0x03FF\",\"scale\":0.00322,\"period_ms\":100}}}");
    c.i2c = i2c;
    c.spi = spi;
    char err[256];
    CHECK(hwd_backend_sensors.validate(&c, err, sizeof err) == 0);
    hwd_tagstore *s = hwd_tagstore_create();
    hwd_backend_opts o = {.sim = true, .poll_interval_ms = 50};
    void *b = s ? hwd_backend_sensors.create(&c, s, &o, err, sizeof err) : NULL;
    CHECK(b != NULL);
    if (b) {
        if (hwd_backend_sensors.start) hwd_backend_sensors.start(b);
        bool ok = false;
        for (int i = 0; i < 100 && !ok; i++) {
            hwd_backend_sensors.poll(b, 10.0 + i * 0.05);
            hwd_value v = hwd_tagstore_get(s, "i2c.cab.temp");
            ok = v.kind == HWD_FLOAT && v.u.f >= 22 && v.u.f <= 26;
            usleep(20000);
        }
        CHECK(ok);
        CHECK(hwd_tagstore_writable(s, "i2c.io.out"));
        hwd_value w = hwd_int(5);
        CHECK(hwd_backend_sensors.write(b, "i2c.io.out", &w) == HWD_OK);
        CHECK(hwd_backend_sensors.write(b, "i2c.cab.temp", &w) == HWD_ERR_NOT_WRITABLE);
        hwd_backend_sensors.destroy(b);
    }
    if (s) hwd_tagstore_destroy(s);
    cJSON_Delete(i2c);
    cJSON_Delete(spi);
    cJSON *bad = cJSON_Parse("{\"sensors\":{\"i2c.x\":{\"bus\":1,\"address\":\"0x48\",\"device\":\"nope\"}}}");
    c.i2c = bad;
    c.spi = NULL;
    CHECK(hwd_backend_sensors.validate(&c, err, sizeof err) != 0);
    cJSON_Delete(bad);
}

static void test_history(void)
{
    char cfgtext[512];
    snprintf(cfgtext, sizeof cfgtext,
             "{\"path\":\"%s/hist.db\",\"retention_days\":7,\"tags\":{\"ai.pot\":{\"period_ms\":100,\"deadband\":0.5}}}",
             tmpdir);
    cJSON *h = cJSON_Parse(cfgtext);
    char err[256];
    CHECK(hwd_history_validate(h, err, sizeof err) == 0);
    hwd_history *hist = hwd_history_create(h, err, sizeof err);
    CHECK(hist != NULL);
    if (!hist) { cJSON_Delete(h); return; }
    CHECK(hwd_history_logs(hist, "ai.pot"));
    CHECK(!hwd_history_logs(hist, "ai.other"));
    double t0 = 1790000000.0;
    int kept = 0;
    for (int i = 0; i < 10; i++) {
        hwd_value v = hwd_float(i * 1.0);
        kept += hwd_history_observe(hist, "ai.pot", &v, t0 + i * 0.2);
    }
    CHECK(kept == 10);
    hwd_value same = hwd_float(9.2);                          /* inside the deadband */
    CHECK(!hwd_history_observe(hist, "ai.pot", &same, t0 + 2.2));
    hwd_history_destroy(hist);                                /* flushes */
    hist = hwd_history_create(h, err, sizeof err);
    CHECK(hist != NULL);
    if (hist) {
        cJSON *all = hwd_history_query(hist, "ai.pot", 3600, 200, t0 + 3);
        CHECK(cJSON_GetArraySize(all) == 10);
        cJSON *first = cJSON_GetArrayItem(all, 0);
        CHECK(first && cJSON_GetArrayItem(first, 0)->valuedouble == t0 * 1000.0);
        CHECK(first && cJSON_GetArrayItem(first, 1)->valuedouble == 0.0);
        cJSON_Delete(all);
        /* (t0-0.1, t0+1.9] in two 1-s buckets, (lo, hi] each: t0..t0+0.8 and
         * t0+1.0..t0+1.8 -- each bucket's LAST sample is kept. */
        cJSON *two = hwd_history_query(hist, "ai.pot", 2, 2, t0 + 1.9);
        CHECK(cJSON_GetArraySize(two) == 2);
        cJSON *a = cJSON_GetArrayItem(two, 0), *z = cJSON_GetArrayItem(two, 1);
        CHECK(a && cJSON_GetArrayItem(a, 1)->valuedouble == 4.0);
        CHECK(z && cJSON_GetArrayItem(z, 1)->valuedouble == 9.0);
        cJSON_Delete(two);
        hwd_value flag = hwd_bool(true);                      /* bools are not logged */
        CHECK(!hwd_history_observe(hist, "ai.pot", &flag, t0 + 100));
        hwd_history_destroy(hist);
    }
    cJSON_Delete(h);
    cJSON *bad = cJSON_Parse("{\"path\":\"/tmp/x.db\",\"retention_days\":0,\"tags\":{}}");
    CHECK(hwd_history_validate(bad, err, sizeof err) != 0);
    cJSON_Delete(bad);
}

int main(void)
{
    snprintf(tmpdir, sizeof tmpdir, "/tmp/hwd-periph-XXXXXX");
    if (!mkdtemp(tmpdir)) { fprintf(stderr, "mkdtemp failed\n"); return 2; }
    test_keymap();
    test_hid_fifo();
    test_usb();
    test_decode();
    test_sensors_sim();
    test_history();
    CHECK_DONE();
}
