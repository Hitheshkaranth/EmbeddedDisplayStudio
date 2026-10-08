/* test_io.c -- A3's gate: GPIO/ADC sim, the native UART and the serial
 * backend over a real pseudo-terminal (the same tty code path a USB-serial
 * adapter takes). FROZEN (skeleton). */
#include "check.h"
#include "backend.h"

#include <fcntl.h>
#include <pty.h>
#include <stdlib.h>
#include <termios.h>
#include <unistd.h>

static hwd_value get(hwd_tagstore *s, const char *tag) { return hwd_tagstore_get(s, tag); }

static void test_io_sim(void)
{
    hwd_config c;
    memset(&c, 0, sizeof c);
    cJSON *gpio = cJSON_Parse("{\"chip\":\"/dev/gpiochip3\",\"outputs\":{\"do.relay1\":{\"offset\":5,"
                              "\"active_low\":false,\"initial\":0,\"safe_state\":0}},"
                              "\"inputs\":{\"di.estop\":{\"offset\":4,\"active_low\":true}}}");
    cJSON *adc = cJSON_Parse("{\"device_name\":\"ads1015\",\"channels\":{\"ai.pot\":{\"channel_file\":\"in_voltage0_raw\","
                             "\"scale_file\":\"in_voltage0_scale\"},\"ai.rail\":{\"channel_file\":\"in_voltage1_raw\"}}}");
    c.gpio = gpio;
    c.adc = adc;
    char err[256];
    CHECK(hwd_backend_io.validate(&c, err, sizeof err) == 0);
    hwd_tagstore *s = hwd_tagstore_create();
    hwd_backend_opts o = {.sim = true, .poll_interval_ms = 50};
    setenv("HWD_SIM_FAIL", "ai.rail", 1);
    void *b = s ? hwd_backend_io.create(&c, s, &o, err, sizeof err) : NULL;
    CHECK(b != NULL);
    if (b) {
        if (hwd_backend_io.start) hwd_backend_io.start(b);
        CHECK(hwd_tagstore_writable(s, "do.relay1"));
        CHECK(!hwd_tagstore_writable(s, "di.estop"));
        CHECK(hwd_backend_io.owns(b, "do.relay1") && hwd_backend_io.owns(b, "ai.pot"));
        hwd_value one = hwd_int(1);
        CHECK(hwd_backend_io.write(b, "do.relay1", &one) == HWD_OK);
        CHECK(hwd_backend_io.write(b, "di.estop", &one) == HWD_ERR_NOT_WRITABLE);
        hwd_backend_io.poll(b, 1.0);
        hwd_value v = get(s, "do.relay1");
        CHECK(v.kind == HWD_BOOL && v.u.b);                   /* read-back of the driven state */
        v = get(s, "di.estop");
        CHECK(v.kind == HWD_BOOL && !v.u.b);                  /* sim inputs read inactive */
        v = get(s, "ai.pot");
        CHECK(v.kind == HWD_FLOAT);
        v = get(s, "ai.rail");
        CHECK(v.kind == HWD_NULL);                            /* HWD_SIM_FAIL */
        char q[8];
        CHECK(hwd_tagstore_quality(s, "ai.rail", q, sizeof q) && strcmp(q, "bad") == 0);
        CHECK(hwd_backend_io.errors(b) >= 1);
        if (hwd_backend_io.safe_state) hwd_backend_io.safe_state(b);
        hwd_backend_io.poll(b, 1.1);
        v = get(s, "do.relay1");
        CHECK(v.kind == HWD_BOOL && !v.u.b);                  /* driven to safe_state */
        hwd_backend_io.destroy(b);
    }
    unsetenv("HWD_SIM_FAIL");
    if (s) hwd_tagstore_destroy(s);
    cJSON_Delete(gpio);
    cJSON_Delete(adc);
}

static void raw(int fd)
{
    struct termios t;
    tcgetattr(fd, &t);
    cfmakeraw(&t);
    tcsetattr(fd, TCSANOW, &t);
}

static bool wait_str(hwd_tagstore *s, const hwd_backend_ops *ops, void *b, const char *tag,
                     const char *want, double *now)
{
    for (int i = 0; i < 200; i++) {
        if (ops->poll) ops->poll(b, *now);
        *now += 0.01;
        hwd_value v = hwd_tagstore_get(s, tag);
        bool ok = v.kind == HWD_STR && strcmp(v.u.s, want) == 0;
        hwd_value_clear(&v);
        if (ok) return true;
        usleep(10000);
    }
    return false;
}

static void test_serial_pty(void)
{
    int master, slave;
    char name[128];
    if (openpty(&master, &slave, name, NULL, NULL) != 0) { CHECK(!"openpty"); return; }
    raw(master);
    char cfgtext[512];
    snprintf(cfgtext, sizeof cfgtext,
             "{\"ports\":{\"scan\":{\"path\":\"%s\",\"baudrate\":9600,\"eol\":\"\\r\\n\"}}}", name);
    hwd_config c;
    memset(&c, 0, sizeof c);
    cJSON *serial = cJSON_Parse(cfgtext);
    c.serial = serial;
    char err[256];
    CHECK(hwd_backend_serial.validate(&c, err, sizeof err) == 0);
    hwd_tagstore *s = hwd_tagstore_create();
    hwd_backend_opts o = {.sim = false, .poll_interval_ms = 50};
    void *b = s ? hwd_backend_serial.create(&c, s, &o, err, sizeof err) : NULL;
    CHECK(b != NULL);
    if (b) {
        if (hwd_backend_serial.start) hwd_backend_serial.start(b);
        double now = 1.0;
        CHECK(hwd_tagstore_exists(s, "serial.scan.rx") && hwd_tagstore_exists(s, "serial.scan.present"));
        CHECK(write(master, "HELLO 42\r\n", 10) == 10);
        CHECK(wait_str(s, &hwd_backend_serial, b, "serial.scan.rx", "HELLO 42", &now));
        hwd_value p = hwd_tagstore_get(s, "serial.scan.present");
        CHECK(p.kind == HWD_BOOL && p.u.b);
        hwd_value n = hwd_tagstore_get(s, "serial.scan.rx_count");
        CHECK(n.kind == HWD_INT && n.u.i == 1);
        cJSON *msg = cJSON_Parse("{\"cmd\":\"serial_tx\",\"port\":\"scan\",\"data\":\"PING\"}");
        cJSON *reply = cJSON_CreateObject();
        CHECK(hwd_backend_serial.command(b, "serial_tx", msg, reply) == HWD_OK);
        char buf[16] = {0};
        usleep(50000);
        int got = (int)read(master, buf, sizeof buf - 1);
        CHECK(got == 4 && memcmp(buf, "PING", 4) == 0);
        cJSON_Delete(msg);
        msg = cJSON_Parse("{\"cmd\":\"serial_tx\",\"port\":\"nope\",\"data\":\"x\"}");
        CHECK(hwd_backend_serial.command(b, "serial_tx", msg, reply) != HWD_OK);
        cJSON_Delete(msg);
        cJSON_Delete(reply);
        hwd_backend_serial.destroy(b);
    }
    if (s) hwd_tagstore_destroy(s);
    cJSON_Delete(serial);
    close(master);
    close(slave);
}

static void test_serial_sim(void)
{
    hwd_config c;
    memset(&c, 0, sizeof c);
    cJSON *serial = cJSON_Parse("{\"ports\":{\"scan\":{\"path\":\"/dev/ttyUSB9\",\"baudrate\":9600}}}");
    c.serial = serial;
    char err[256];
    hwd_tagstore *s = hwd_tagstore_create();
    hwd_backend_opts o = {.sim = true, .poll_interval_ms = 50};
    void *b = s ? hwd_backend_serial.create(&c, s, &o, err, sizeof err) : NULL;
    CHECK(b != NULL);
    if (b) {
        if (hwd_backend_serial.start) hwd_backend_serial.start(b);
        hwd_backend_serial.poll(b, 100.0);
        hwd_backend_serial.poll(b, 102.5);                    /* a sim line every 2 s */
        hwd_value v = hwd_tagstore_get(s, "serial.scan.rx");
        CHECK(v.kind == HWD_STR && strncmp(v.u.s, "SIM ", 4) == 0);
        hwd_value_clear(&v);
        hwd_backend_serial.destroy(b);
    }
    if (s) hwd_tagstore_destroy(s);
    cJSON_Delete(serial);
}

static void test_uart_pty(void)
{
    int master, slave;
    char name[128];
    if (openpty(&master, &slave, name, NULL, NULL) != 0) { CHECK(!"openpty"); return; }
    raw(master);
    char cfgtext[512];
    snprintf(cfgtext, sizeof cfgtext, "{\"port\":\"%s\",\"baudrate\":115200}", name);
    hwd_config c;
    memset(&c, 0, sizeof c);
    cJSON *gpio = cJSON_Parse("{}");
    cJSON *uart = cJSON_Parse(cfgtext);
    c.gpio = gpio;
    c.uart = uart;
    char err[256];
    hwd_tagstore *s = hwd_tagstore_create();
    hwd_backend_opts o = {.sim = false, .poll_interval_ms = 50};
    void *b = s ? hwd_backend_io.create(&c, s, &o, err, sizeof err) : NULL;
    CHECK(b != NULL);
    if (b) {
        if (hwd_backend_io.start) hwd_backend_io.start(b);
        CHECK(hwd_tagstore_exists(s, "uart.rx"));
        CHECK(write(master, "A\nB\n", 4) == 4);
        bool two = false;
        for (int i = 0; i < 200 && !two; i++) {
            hwd_backend_io.poll(b, 1.0 + i * 0.01);
            hwd_value v = hwd_tagstore_get(s, "uart.rx");    /* cumulative line count */
            two = v.kind == HWD_INT && v.u.i == 2;
            usleep(10000);
        }
        CHECK(two);
        cJSON *msg = cJSON_Parse("{\"cmd\":\"uart_tx\",\"data\":\"PONG\"}");
        cJSON *reply = cJSON_CreateObject();
        CHECK(hwd_backend_io.command(b, "uart_tx", msg, reply) == HWD_OK);
        char buf[16] = {0};
        usleep(50000);
        CHECK(read(master, buf, sizeof buf - 1) == 4 && memcmp(buf, "PONG", 4) == 0);
        cJSON_Delete(msg);
        cJSON_Delete(reply);
        hwd_backend_io.destroy(b);
    }
    if (s) hwd_tagstore_destroy(s);
    cJSON_Delete(gpio);
    cJSON_Delete(uart);
    close(master);
    close(slave);
}

int main(void)
{
    test_io_sim();
    test_serial_pty();
    test_serial_sim();
    test_uart_pty();
    CHECK_DONE();
}
