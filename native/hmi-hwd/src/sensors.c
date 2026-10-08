/*
 * sensors.c -- I2C and SPI sensors (CONTRACT 14.6, "i2c", "spi").
 * OWNER: A4.
 *
 *   "i2c": {"sensors": {"i2c.cab.temp": {"bus": 1, "address": "0x48", "device": "tmp102"},
 *                       "i2c.io.out":   {"bus": 1, "address": "0x20", "register": "0x0A",
 *                                        "type": "uint8", "writable": true}}},
 *   "spi": {"sensors": {"spi.adc.ch0": {"bus": 1, "cs": 0, "mode": 0, "speed_hz": 1000000,
 *                                       "tx": "01 80 00", "rx_offset": 1, "length": 2,
 *                                       "type": "uint16", "mask": "0x03FF", "scale": 0.00322}}}
 *
 * Real mode: a reader thread (started by start(), stopped by destroy())
 * reads every sensor at its period_ms through /dev/i2c-<bus> (I2C_RDWR: a
 * register write then a read) or /dev/spidev<bus>.<cs> (SPI_IOC_MESSAGE(1)),
 * decodes it (presets or the generic rule) and stores the value; a failed
 * transaction stores null with quality "bad". A writable generic I2C tag
 * writes its register (synchronously: one short transaction).
 *
 * Sim mode: no device is opened; poll(now) computes each value from `now`
 * (hwd_sim_ramp) so tests are deterministic -- presets in the CONTRACT
 * ranges, generic tags across their type's range; written values are kept;
 * HWD_SIM_FAIL tags read as failed.
 */
#include "backend.h"
#include "periph.h"

#include <errno.h>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <linux/spi/spidev.h>
#include <math.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define SENS_MAX 64
#define SENS_TX_MAX 32
#define PERIOD_MIN_MS 100
#define PERIOD_MAX_MS 3600000
#define PERIOD_DEFAULT_MS 1000

typedef enum { DEV_GENERIC = 0, DEV_TMP102, DEV_LM75, DEV_SHT3X, DEV_INA219, DEV_ADS1115 } sens_dev;
typedef enum { M_DEFAULT = 0, M_TEMPERATURE, M_HUMIDITY, M_BUS_VOLTAGE, M_CURRENT } sens_measure;

typedef struct {
    char tag[HWD_MAX_TAG];
    bool spi;
    int bus;
    int addr;                 /* I2C 7-bit address */
    int cs, mode;             /* SPI */
    uint32_t speed_hz;
    sens_dev dev;
    sens_measure measure;
    int channel;              /* ads1115 */
    double shunt_ohm;         /* ina219 */
    int reg;                  /* generic I2C register, -1 = none */
    sens_type type;
    bool big_endian;
    uint32_t mask;
    int shift;
    double scale, offset;
    double period_s;
    bool writable;
    uint8_t tx[SENS_TX_MAX];
    int tx_len, rx_offset, length;

    int fd;                   /* reader thread / write: device node, -1 closed */
    double next_due;          /* mono (real) or `now` (sim) */
    bool written;             /* sim: a write holds the value */
} sensor;

typedef struct {
    hwd_tagstore *store;
    bool sim;
    sensor s[SENS_MAX];
    int n;
    pthread_t thread;
    bool thread_on;
    volatile bool stop;
    pthread_mutex_t io;       /* device I/O: the reader thread vs write() */
    uint64_t errors;
} sens_backend;

/* ---- config parsing (shared by validate and create) ------------------- */

/* "0x48", "72" or a JSON integer. */
static bool get_int(const cJSON *j, long *out)
{
    if (cJSON_IsNumber(j)) {
        if (!isfinite(j->valuedouble) || j->valuedouble != floor(j->valuedouble)) return false;
        *out = (long)j->valuedouble;
        return true;
    }
    if (cJSON_IsString(j) && j->valuestring[0]) {
        char *end;
        errno = 0;
        long v = strtol(j->valuestring, &end, 0);
        if (errno || *end) return false;
        *out = v;
        return true;
    }
    return false;
}

static int parse_hex_bytes(const char *text, uint8_t *out, int max)
{
    int n = 0;
    const char *p = text;
    while (*p) {
        while (*p == ' ' || *p == ',' || *p == ':') p++;
        if (!*p) break;
        if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) p += 2;
        int v = 0;
        for (int k = 0; k < 2; k++, p++) {
            char c = *p;
            int d = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10
                  : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
            if (d < 0) return -1;
            v = v * 16 + d;
        }
        if (n >= max) return -1;
        out[n++] = (uint8_t)v;
    }
    return n;
}

#define FAIL(...) do { snprintf(err, errlen, __VA_ARGS__); return -1; } while (0)

static int parse_sensor(const char *tag, const cJSON *j, bool spi, sensor *s, char *err, size_t errlen)
{
    const char *sec = spi ? "spi" : "i2c";
    memset(s, 0, sizeof *s);
    s->fd = -1;
    s->reg = -1;
    s->scale = 1.0;
    s->big_endian = true;
    s->shunt_ohm = 0.1;
    s->spi = spi;
    s->type = SENS_U16;
    if (!hwd_tag_valid(tag) || strlen(tag) >= sizeof s->tag) FAIL("%s: bad tag name '%s'", sec, tag);
    snprintf(s->tag, sizeof s->tag, "%s", tag);
    if (!cJSON_IsObject(j)) FAIL("%s.%s: must be an object", sec, tag);
    long v;
    if (!get_int(cJSON_GetObjectItemCaseSensitive(j, "bus"), &v) || v < 0 || v > 255)
        FAIL("%s %s: bus must be an integer 0..255", sec, tag);
    s->bus = (int)v;

    const cJSON *pj = cJSON_GetObjectItemCaseSensitive(j, "period_ms");
    double period = PERIOD_DEFAULT_MS;
    if (pj) {
        if (!cJSON_IsNumber(pj) || !(pj->valuedouble >= PERIOD_MIN_MS && pj->valuedouble <= PERIOD_MAX_MS))
            FAIL("%s %s: period_ms must be 100..3600000", sec, tag);
        period = pj->valuedouble;
    }
    s->period_s = period / 1000.0;

    if (spi) {
        if (!get_int(cJSON_GetObjectItemCaseSensitive(j, "cs"), &v) || v < 0 || v > 255)
            FAIL("spi %s: cs must be an integer 0..255", tag);
        s->cs = (int)v;
        const cJSON *m = cJSON_GetObjectItemCaseSensitive(j, "mode");
        if (m) {
            if (!get_int(m, &v) || v < 0 || v > 3) FAIL("spi %s: mode must be 0..3", tag);
            s->mode = (int)v;
        }
        s->speed_hz = 1000000;
        const cJSON *sp = cJSON_GetObjectItemCaseSensitive(j, "speed_hz");
        if (sp) {
            if (!get_int(sp, &v) || v < 1000 || v > 100000000) FAIL("spi %s: speed_hz must be 1000..100000000", tag);
            s->speed_hz = (uint32_t)v;
        }
        if (cJSON_GetObjectItemCaseSensitive(j, "device")) FAIL("spi %s: SPI sensors have no presets; use type", tag);
    } else {
        if (!get_int(cJSON_GetObjectItemCaseSensitive(j, "address"), &v) || v < 0x03 || v > 0x77)
            FAIL("i2c %s: address must be 0x03..0x77", tag);
        s->addr = (int)v;
    }

    const cJSON *dj = cJSON_GetObjectItemCaseSensitive(j, "device");
    const char *meas = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(j, "measure"));
    if (cJSON_GetObjectItemCaseSensitive(j, "measure") && !meas) FAIL("i2c %s: measure must be a string", tag);
    if (dj) {
        const char *d = cJSON_GetStringValue(dj);
        if (!d) FAIL("i2c %s: device must be a string", tag);
        if (!strcmp(d, "tmp102")) s->dev = DEV_TMP102;
        else if (!strcmp(d, "lm75")) s->dev = DEV_LM75;
        else if (!strcmp(d, "sht3x")) s->dev = DEV_SHT3X;
        else if (!strcmp(d, "ina219")) s->dev = DEV_INA219;
        else if (!strcmp(d, "ads1115")) s->dev = DEV_ADS1115;
        else FAIL("i2c %s: unknown device '%s' (tmp102, lm75, sht3x, ina219, ads1115)", tag, d);
        if (cJSON_GetObjectItemCaseSensitive(j, "type")) FAIL("i2c %s: a preset device takes no type", tag);
        if (cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(j, "writable"))) FAIL("i2c %s: a preset is not writable", tag);
        switch (s->dev) {
        case DEV_TMP102: case DEV_LM75:
            if (meas && strcmp(meas, "temperature")) FAIL("i2c %s: measure must be temperature", tag);
            s->measure = M_TEMPERATURE;
            break;
        case DEV_SHT3X:
            if (!meas || !strcmp(meas, "temperature")) s->measure = M_TEMPERATURE;
            else if (!strcmp(meas, "humidity")) s->measure = M_HUMIDITY;
            else FAIL("i2c %s: measure must be temperature or humidity", tag);
            break;
        case DEV_INA219: {
            if (!meas || !strcmp(meas, "bus_voltage")) s->measure = M_BUS_VOLTAGE;
            else if (!strcmp(meas, "current")) s->measure = M_CURRENT;
            else FAIL("i2c %s: measure must be bus_voltage or current", tag);
            const cJSON *sh = cJSON_GetObjectItemCaseSensitive(j, "shunt_ohm");
            if (sh) {
                if (!cJSON_IsNumber(sh) || !(sh->valuedouble > 0) || !isfinite(sh->valuedouble))
                    FAIL("i2c %s: shunt_ohm must be > 0", tag);
                s->shunt_ohm = sh->valuedouble;
            }
            break;
        }
        case DEV_ADS1115: {
            const cJSON *ch = cJSON_GetObjectItemCaseSensitive(j, "channel");
            if (ch) {
                if (!get_int(ch, &v) || v < 0 || v > 3) FAIL("i2c %s: channel must be 0..3", tag);
                s->channel = (int)v;
            }
            if (meas && strcmp(meas, "voltage")) FAIL("i2c %s: measure must be voltage", tag);
            break;
        }
        case DEV_GENERIC:
            break;
        }
        return 0;
    }

    /* generic */
    const char *tn = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(j, "type"));
    if (!tn || !sens_parse_type(tn, &s->type))
        FAIL("%s %s: needs a device preset or a type (uint8, int8, uint16, int16, uint32, int32, float32)", sec, tag);
    const cJSON *bo = cJSON_GetObjectItemCaseSensitive(j, "byte_order");
    if (bo) {
        const char *b = cJSON_GetStringValue(bo);
        if (!b || (strcmp(b, "big") && strcmp(b, "little"))) FAIL("%s %s: byte_order must be big or little", sec, tag);
        s->big_endian = !strcmp(b, "big");
    }
    const cJSON *mj = cJSON_GetObjectItemCaseSensitive(j, "mask");
    if (mj) {
        if (!get_int(mj, &v) || v < 0 || v > 0xFFFFFFFFL) FAIL("%s %s: mask must be 0..0xFFFFFFFF", sec, tag);
        s->mask = (uint32_t)v;
    }
    const cJSON *sj = cJSON_GetObjectItemCaseSensitive(j, "shift");
    if (sj) {
        if (!get_int(sj, &v) || v < 0 || v > 31) FAIL("%s %s: shift must be 0..31", sec, tag);
        s->shift = (int)v;
    }
    const cJSON *sc = cJSON_GetObjectItemCaseSensitive(j, "scale");
    if (sc) {
        if (!cJSON_IsNumber(sc) || !isfinite(sc->valuedouble) || sc->valuedouble == 0) FAIL("%s %s: scale must be a non-zero number", sec, tag);
        s->scale = sc->valuedouble;
    }
    const cJSON *of = cJSON_GetObjectItemCaseSensitive(j, "offset");
    if (of) {
        if (!cJSON_IsNumber(of) || !isfinite(of->valuedouble)) FAIL("%s %s: offset must be a number", sec, tag);
        s->offset = of->valuedouble;
    }
    if (s->type == SENS_F32 && (s->mask || s->shift)) FAIL("%s %s: float32 takes no mask or shift", sec, tag);
    int nbytes = sens_type_bytes(s->type);
    if (spi) {
        const char *tx = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(j, "tx"));
        if (cJSON_GetObjectItemCaseSensitive(j, "tx") && !tx) FAIL("spi %s: tx must be a hex string", tag);
        s->tx_len = tx ? parse_hex_bytes(tx, s->tx, SENS_TX_MAX) : 0;
        if (s->tx_len < 0) FAIL("spi %s: tx must be hex bytes, at most %d", tag, SENS_TX_MAX);
        const cJSON *ro = cJSON_GetObjectItemCaseSensitive(j, "rx_offset");
        if (ro) {
            if (!get_int(ro, &v) || v < 0 || v >= SENS_TX_MAX) FAIL("spi %s: rx_offset must be 0..%d", tag, SENS_TX_MAX - 1);
            s->rx_offset = (int)v;
        }
        s->length = nbytes;
        const cJSON *ln = cJSON_GetObjectItemCaseSensitive(j, "length");
        if (ln) {
            if (!get_int(ln, &v) || v < nbytes || v > 4) FAIL("spi %s: length must be %d..4 for its type", tag, nbytes);
            s->length = (int)v;
        }
        if (s->rx_offset + s->length > SENS_TX_MAX) FAIL("spi %s: rx_offset + length exceeds %d bytes", tag, SENS_TX_MAX);
        if (cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(j, "writable"))) FAIL("spi %s: SPI tags are read-only", tag);
    } else {
        const cJSON *rj = cJSON_GetObjectItemCaseSensitive(j, "register");
        if (rj) {
            if (!get_int(rj, &v) || v < 0 || v > 255) FAIL("i2c %s: register must be 0..0xFF", tag);
            s->reg = (int)v;
        }
        const cJSON *wj = cJSON_GetObjectItemCaseSensitive(j, "writable");
        if (wj && !cJSON_IsBool(wj)) FAIL("i2c %s: writable must be true/false", tag);
        s->writable = cJSON_IsTrue(wj);
        if (s->writable && s->type == SENS_F32 && (s->mask || s->shift)) FAIL("i2c %s: bad writable type", tag);
    }
    return 0;
}

static int parse_section(const cJSON *sec, bool spi, sensor *out, int *n, char *err, size_t errlen)
{
    const char *name = spi ? "spi" : "i2c";
    if (!cJSON_IsObject(sec)) FAIL("%s: must be an object", name);
    const cJSON *sensors = cJSON_GetObjectItemCaseSensitive(sec, "sensors");
    if (!cJSON_IsObject(sensors)) FAIL("%s: sensors must be an object", name);
    for (const cJSON *j = sensors->child; j; j = j->next) {
        if (*n >= SENS_MAX) FAIL("%s: at most %d sensors", name, SENS_MAX);
        if (parse_sensor(j->string, j, spi, &out[*n], err, errlen) != 0) return -1;
        for (int k = 0; k < *n; k++)
            if (!strcmp(out[k].tag, out[*n].tag)) FAIL("%s: tag '%s' configured twice", name, j->string);
        (*n)++;
    }
    return 0;
}

static int v_validate(const hwd_config *cfg, char *err, size_t errlen)
{
    if (!cfg || (!cfg->i2c && !cfg->spi)) return 0;
    sensor *tmp = calloc(SENS_MAX, sizeof *tmp);
    if (!tmp) FAIL("sensors: out of memory");
    int n = 0, rc = 0;
    if (cfg->i2c) rc = parse_section(cfg->i2c, false, tmp, &n, err, errlen);
    if (rc == 0 && cfg->spi) rc = parse_section(cfg->spi, true, tmp, &n, err, errlen);
    free(tmp);
    return rc;
}

/* ---- device I/O (real mode) ------------------------------------------- */

static void sleep_ms(int ms)
{
    struct timespec ts = {ms / 1000, (long)(ms % 1000) * 1000000L};
    while (nanosleep(&ts, &ts) != 0 && errno == EINTR) {}
}

static int dev_open(sensor *s)
{
    if (s->fd >= 0) return s->fd;
    char path[64];
    if (s->spi) snprintf(path, sizeof path, "/dev/spidev%d.%d", s->bus, s->cs);
    else snprintf(path, sizeof path, "/dev/i2c-%d", s->bus);
    int fd = open(path, O_RDWR | O_CLOEXEC);
    if (fd < 0) return -1;
    if (s->spi) {
        uint8_t mode = (uint8_t)s->mode, bits = 8;
        uint32_t speed = s->speed_hz;
        if (ioctl(fd, SPI_IOC_WR_MODE, &mode) < 0 || ioctl(fd, SPI_IOC_WR_BITS_PER_WORD, &bits) < 0 ||
            ioctl(fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed) < 0) {
            close(fd);
            return -1;
        }
    }
    s->fd = fd;
    return fd;
}

static void dev_close(sensor *s)
{
    if (s->fd >= 0) close(s->fd);
    s->fd = -1;
}

/* One I2C_RDWR: write `w` (may be empty) then read `r` (may be empty). */
static int i2c_xfer(int fd, int addr, const uint8_t *w, int wlen, uint8_t *r, int rlen)
{
    struct i2c_msg msgs[2];
    int n = 0;
    if (wlen > 0) msgs[n++] = (struct i2c_msg){.addr = (uint16_t)addr, .flags = 0, .len = (uint16_t)wlen, .buf = (uint8_t *)w};
    if (rlen > 0) msgs[n++] = (struct i2c_msg){.addr = (uint16_t)addr, .flags = I2C_M_RD, .len = (uint16_t)rlen, .buf = r};
    struct i2c_rdwr_ioctl_data data = {.msgs = msgs, .nmsgs = (uint32_t)n};
    return ioctl(fd, I2C_RDWR, &data) == n ? 0 : -1;
}

static int i2c_read_reg(int fd, int addr, int reg, uint8_t *r, int rlen)
{
    uint8_t w = (uint8_t)reg;
    return i2c_xfer(fd, addr, reg >= 0 ? &w : NULL, reg >= 0 ? 1 : 0, r, rlen);
}

/* Read one sensor; true with *out on success. Caller holds b->io. */
static bool read_sensor(sensor *s, double *out)
{
    int fd = dev_open(s);
    if (fd < 0) return false;
    uint8_t b[8] = {0};
    bool ok = false;
    if (s->spi) {
        uint8_t tx[SENS_TX_MAX] = {0}, rx[SENS_TX_MAX] = {0};
        int len = s->tx_len > s->rx_offset + s->length ? s->tx_len : s->rx_offset + s->length;
        memcpy(tx, s->tx, (size_t)s->tx_len);
        struct spi_ioc_transfer tr;
        memset(&tr, 0, sizeof tr);
        tr.tx_buf = (uintptr_t)tx;
        tr.rx_buf = (uintptr_t)rx;
        tr.len = (uint32_t)len;
        tr.speed_hz = s->speed_hz;
        tr.bits_per_word = 8;
        if (ioctl(fd, SPI_IOC_MESSAGE(1), &tr) >= 1) {
            *out = sens_decode(rx + s->rx_offset, s->type, s->big_endian, s->mask, s->shift, s->scale, s->offset);
            ok = true;
        }
    } else {
        switch (s->dev) {
        case DEV_TMP102: case DEV_LM75:
            if (i2c_read_reg(fd, s->addr, 0x00, b, 2) == 0) { *out = sens_tmp102_c(b); ok = true; }
            break;
        case DEV_SHT3X: {
            const uint8_t cmd[2] = {0x24, 0x00};       /* single shot, high repeatability, no stretch */
            if (i2c_xfer(fd, s->addr, cmd, 2, NULL, 0) != 0) break;
            sleep_ms(16);
            if (i2c_xfer(fd, s->addr, NULL, 0, b, 6) != 0 || !sens_sht3x_crc_ok(b)) break;
            *out = s->measure == M_HUMIDITY ? sens_sht3x_rh(b) : sens_sht3x_temp_c(b);
            ok = true;
            break;
        }
        case DEV_INA219:
            if (s->measure == M_CURRENT) {
                if (i2c_read_reg(fd, s->addr, 0x01, b, 2) == 0) { *out = sens_ina219_current_a(b, s->shunt_ohm); ok = true; }
            } else if (i2c_read_reg(fd, s->addr, 0x02, b, 2) == 0) {
                *out = sens_ina219_bus_v(b);
                ok = true;
            }
            break;
        case DEV_ADS1115: {
            /* OS=1 start, MUX=1xx AINn vs GND, PGA=001 +-4.096 V, MODE=1
             * single shot, DR=100 128 SPS, comparator off (11). */
            uint16_t cfgw = (uint16_t)(0x8000 | ((4 + s->channel) << 12) | (1 << 9) | (1 << 8) | (4 << 5) | 0x3);
            const uint8_t w[3] = {0x01, (uint8_t)(cfgw >> 8), (uint8_t)cfgw};
            if (i2c_xfer(fd, s->addr, w, 3, NULL, 0) != 0) break;
            sleep_ms(9);
            if (i2c_read_reg(fd, s->addr, 0x00, b, 2) == 0) { *out = sens_ads1115_volts(b); ok = true; }
            break;
        }
        case DEV_GENERIC:
            if (i2c_read_reg(fd, s->addr, s->reg, b, sens_type_bytes(s->type)) == 0) {
                *out = sens_decode(b, s->type, s->big_endian, s->mask, s->shift, s->scale, s->offset);
                ok = true;
            }
            break;
        }
    }
    if (!ok) dev_close(s);     /* reopen next time (hotplug, bus reset) */
    return ok;
}

static bool is_int_type(sens_type t) { return t != SENS_F32; }

static void store(sens_backend *b, sensor *s, bool ok, double value)
{
    hwd_value v;
    if (!ok || !isfinite(value)) v = hwd_null();
    else if (s->dev == DEV_GENERIC && is_int_type(s->type) && s->scale == 1.0 && s->offset == 0.0)
        v = hwd_int((int64_t)llround(value));
    else v = hwd_float(value);
    hwd_tagstore_set(b->store, s->tag, &v);
    hwd_tagstore_set_quality(b->store, s->tag, v.kind == HWD_NULL ? "bad" : NULL);
}

static void *reader(void *arg)
{
    sens_backend *b = arg;
    while (!b->stop) {
        double now = hwd_mono();
        double next = now + 0.05;
        for (int i = 0; i < b->n && !b->stop; i++) {
            sensor *s = &b->s[i];
            if (now < s->next_due) {
                if (s->next_due < next) next = s->next_due;
                continue;
            }
            s->next_due = now + s->period_s;
            double value = 0;
            pthread_mutex_lock(&b->io);
            bool ok = read_sensor(s, &value);
            pthread_mutex_unlock(&b->io);
            if (!ok) b->errors++;
            store(b, s, ok, value);
            now = hwd_mono();
        }
        double wait = next - hwd_mono();
        if (wait > 0.05) wait = 0.05;
        if (wait > 0) sleep_ms((int)(wait * 1000) + 1);
    }
    return NULL;
}

/* ---- sim -------------------------------------------------------------- */

static void type_range(sens_type t, double *lo, double *hi)
{
    switch (t) {
    case SENS_U8:  *lo = 0; *hi = 255; break;
    case SENS_I8:  *lo = -128; *hi = 127; break;
    case SENS_U16: *lo = 0; *hi = 65535; break;
    case SENS_I16: *lo = -32768; *hi = 32767; break;
    case SENS_U32: *lo = 0; *hi = 4294967295.0; break;
    case SENS_I32: *lo = -2147483648.0; *hi = 2147483647.0; break;
    case SENS_F32: *lo = 0; *hi = 100; break;
    }
}

static double sim_value(const sensor *s, double now, int idx)
{
    double period = 60.0 + idx * 7.0;          /* staggered so tags differ */
    switch (s->dev) {
    case DEV_TMP102: case DEV_LM75: return hwd_sim_ramp(now, 22.0, 26.0, period);
    case DEV_SHT3X:
        return s->measure == M_HUMIDITY ? hwd_sim_ramp(now, 40.0, 50.0, period) : hwd_sim_ramp(now, 22.0, 26.0, period);
    case DEV_INA219:
        return s->measure == M_CURRENT ? hwd_sim_ramp(now, 0.4, 0.6, period) : hwd_sim_ramp(now, 23.8, 24.2, period);
    case DEV_ADS1115: return hwd_sim_ramp(now, 0.0, 3.3, period);
    case DEV_GENERIC: break;
    }
    double lo = 0, hi = 0;
    type_range(s->type, &lo, &hi);
    if (s->type != SENS_F32 && s->mask) { lo = 0; hi = (double)s->mask; }
    if (s->type != SENS_F32 && s->shift) { lo = floor(lo / (double)(1u << s->shift)); hi = floor(hi / (double)(1u << s->shift)); }
    double raw = hwd_sim_ramp(now, lo, hi, period);
    if (s->type != SENS_F32) raw = floor(raw + 0.5);
    return raw * s->scale + s->offset;
}

/* ---- backend ---------------------------------------------------------- */

static void v_destroy(void *self);

static void *v_create(const hwd_config *cfg, hwd_tagstore *st, const hwd_backend_opts *opts,
                      char *err, size_t errlen)
{
    if (errlen) err[0] = '\0';
    if (!cfg || (!cfg->i2c && !cfg->spi)) return NULL;
    sens_backend *b = calloc(1, sizeof *b);
    if (!b) { snprintf(err, errlen, "sensors: out of memory"); return NULL; }
    pthread_mutex_init(&b->io, NULL);
    b->store = st;
    b->sim = opts && opts->sim;
    int rc = 0;
    if (cfg->i2c) rc = parse_section(cfg->i2c, false, b->s, &b->n, err, errlen);
    if (rc == 0 && cfg->spi) rc = parse_section(cfg->spi, true, b->s, &b->n, err, errlen);
    if (rc != 0) { v_destroy(b); return NULL; }
    for (int i = 0; i < b->n; i++) {
        sensor *s = &b->s[i];
        s->next_due = -1e300;
        if (!hwd_tagstore_register(st, s->tag, hwd_null(), s->writable)) {
            snprintf(err, errlen, "sensors: cannot register tag '%s'", s->tag);
            v_destroy(b);
            return NULL;
        }
        if (!b->sim && opts && opts->strict) {
            if (dev_open(s) < 0) {
                snprintf(err, errlen, "%s: cannot open its %s device: %s", s->tag, s->spi ? "SPI" : "I2C", strerror(errno));
                v_destroy(b);
                return NULL;
            }
        }
    }
    return b;
}

static void v_start(void *self)
{
    sens_backend *b = self;
    if (!b || b->sim || b->thread_on || b->n == 0) return;
    b->stop = false;
    if (pthread_create(&b->thread, NULL, reader, b) == 0) b->thread_on = true;
    else HWD_ERROR("sensors: cannot start the reader thread");
}

static void v_poll(void *self, double now)
{
    sens_backend *b = self;
    if (!b || !b->sim) return;      /* real reads happen in the thread */
    for (int i = 0; i < b->n; i++) {
        sensor *s = &b->s[i];
        if (s->written) continue;
        if (now < s->next_due && now >= s->next_due - s->period_s) continue;
        s->next_due = now + s->period_s;
        bool fail = hwd_sim_fails(s->tag);
        store(b, s, !fail, fail ? 0 : sim_value(s, now, i));
    }
}

static sensor *find(sens_backend *b, const char *tag)
{
    for (int i = 0; i < b->n; i++)
        if (!strcmp(b->s[i].tag, tag)) return &b->s[i];
    return NULL;
}

static bool v_owns(void *self, const char *tag)
{
    sens_backend *b = self;
    return b && tag && find(b, tag) != NULL;
}

/* Encode a raw integer/float into the register bytes of the type. */
static void encode(const sensor *s, double raw, uint8_t *out)
{
    int n = sens_type_bytes(s->type);
    uint32_t bits;
    if (s->type == SENS_F32) {
        float f = (float)raw;
        memcpy(&bits, &f, sizeof bits);
    } else {
        bits = (uint32_t)(int64_t)raw;
    }
    for (int i = 0; i < n; i++) {
        uint8_t byte = (uint8_t)(bits >> (8 * (s->big_endian ? n - 1 - i : i)));
        out[i] = byte;
    }
}

static hwd_err v_write(void *self, const char *tag, const hwd_value *v)
{
    sens_backend *b = self;
    sensor *s = b ? find(b, tag) : NULL;
    if (!s || !s->writable) return HWD_ERR_NOT_WRITABLE;
    double value;
    if (v->kind == HWD_INT) value = (double)v->u.i;
    else if (v->kind == HWD_FLOAT) value = v->u.f;
    else if (v->kind == HWD_BOOL) value = v->u.b ? 1.0 : 0.0;
    else return HWD_ERR_BAD_VALUE;
    if (!isfinite(value)) return HWD_ERR_BAD_VALUE;
    double raw = (value - s->offset) / s->scale;
    if (s->type != SENS_F32) {
        double lo = 0, hi = 0;
        type_range(s->type, &lo, &hi);
        raw = floor(raw + 0.5);
        if (raw < lo || raw > hi) return HWD_ERR_BAD_VALUE;
        if (s->shift || s->mask) {
            /* place the field back where a read finds it */
            int64_t r = (int64_t)raw << s->shift;
            if (s->mask && (r & ~(int64_t)s->mask)) return HWD_ERR_BAD_VALUE;
            raw = (double)r;
            if (raw > hi) return HWD_ERR_BAD_VALUE;
        }
    }
    if (!b->sim) {
        uint8_t w[5];
        int n = sens_type_bytes(s->type), wl = 0;
        if (s->reg >= 0) w[wl++] = (uint8_t)s->reg;
        encode(s, raw, w + wl);
        wl += n;
        pthread_mutex_lock(&b->io);
        int fd = dev_open(s);
        int rc = fd < 0 ? -1 : i2c_xfer(fd, s->addr, w, wl, NULL, 0);
        if (rc != 0) dev_close(s);
        pthread_mutex_unlock(&b->io);
        if (rc != 0) {
            b->errors++;
            HWD_WARN("%s: I2C write failed: %s", s->tag, strerror(errno));
            return HWD_ERR_HW_ERROR;
        }
    }
    s->written = true;
    store(b, s, true, value);
    return HWD_OK;
}

static hwd_err v_command(void *self, const char *cmd, const cJSON *msg, cJSON *reply)
{ (void)self; (void)cmd; (void)msg; (void)reply; return HWD_ERR_UNKNOWN_CMD; }

static uint64_t v_errors(void *self)
{
    sens_backend *b = self;
    return b ? b->errors : 0;
}

static void v_destroy(void *self)
{
    sens_backend *b = self;
    if (!b) return;
    if (b->thread_on) {
        b->stop = true;
        pthread_join(b->thread, NULL);
        b->thread_on = false;
    }
    for (int i = 0; i < b->n; i++) dev_close(&b->s[i]);
    pthread_mutex_destroy(&b->io);
    free(b);
}

const hwd_backend_ops hwd_backend_sensors = {
    "sensors", v_validate, v_create, v_start, v_poll, v_owns, v_write, v_command, NULL, v_errors, v_destroy,
};

/* ---- periph.h sensor decoding (A4) ------------------------------------ */

bool sens_parse_type(const char *name, sens_type *t)
{
    if (!name || !t) return false;
    if      (!strcmp(name, "uint8"))   *t = SENS_U8;
    else if (!strcmp(name, "int8"))    *t = SENS_I8;
    else if (!strcmp(name, "uint16"))  *t = SENS_U16;
    else if (!strcmp(name, "int16"))   *t = SENS_I16;
    else if (!strcmp(name, "uint32"))  *t = SENS_U32;
    else if (!strcmp(name, "int32"))   *t = SENS_I32;
    else if (!strcmp(name, "float32")) *t = SENS_F32;
    else return false;
    return true;
}

int sens_type_bytes(sens_type t)
{
    switch (t) {
    case SENS_U8:  case SENS_I8:  return 1;
    case SENS_U16: case SENS_I16: return 2;
    case SENS_U32: case SENS_I32: case SENS_F32: return 4;
    }
    return 0;
}

/* Bytes in `byte_order` -> unsigned bits of the type's width. */
static uint32_t raw_bits(const uint8_t *buf, int n, bool big_endian)
{
    uint32_t x = 0;
    for (int i = 0; i < n; i++) x = (x << 8) | buf[big_endian ? i : n - 1 - i];
    return x;
}

/* Generic decode: raw by byte order; a signed type is sign-extended; with
 * a mask the masked bits are taken as an unsigned field; >> shift
 * (arithmetic for a signed value); then * scale + offset. */
double sens_decode(const uint8_t *buf, sens_type t, bool big_endian, uint32_t mask, int shift,
                   double scale, double offset)
{
    if (!buf) return 0;
    int n = sens_type_bytes(t);
    uint32_t bits = raw_bits(buf, n, big_endian);
    if (t == SENS_F32) {
        float f;
        memcpy(&f, &bits, sizeof f);
        return (double)f * scale + offset;
    }
    int64_t v;
    switch (t) {
    case SENS_I8:  v = (int8_t)(uint8_t)bits; break;
    case SENS_I16: v = (int16_t)(uint16_t)bits; break;
    case SENS_I32: v = (int32_t)bits; break;
    default:       v = (int64_t)bits; break;
    }
    if (mask) v = (int64_t)(bits & mask);
    if (shift > 0 && shift < 32) v = v >= 0 ? v >> shift : -((-v - 1) >> shift) - 1;
    return (double)v * scale + offset;
}

double sens_tmp102_c(const uint8_t b[2])
{
    /* 12-bit left aligned, 0.0625 C/LSB, two's complement. */
    int16_t raw = (int16_t)(uint16_t)((uint16_t)b[0] << 8 | b[1]);
    return (double)(raw >> 4) * 0.0625;   /* arithmetic shift (gcc) */
}

static uint8_t crc8(const uint8_t *data, int len)
{
    uint8_t crc = 0xFF;
    for (int i = 0; i < len; i++) {
        crc ^= data[i];
        for (int k = 0; k < 8; k++) crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x31) : (uint8_t)(crc << 1);
    }
    return crc;
}

bool sens_sht3x_crc_ok(const uint8_t b[6])
{
    return crc8(b, 2) == b[2] && crc8(b + 3, 2) == b[5];
}

double sens_sht3x_temp_c(const uint8_t b[6])
{
    uint16_t raw = (uint16_t)((uint16_t)b[0] << 8 | b[1]);
    return -45.0 + 175.0 * (double)raw / 65535.0;
}

double sens_sht3x_rh(const uint8_t b[6])
{
    uint16_t raw = (uint16_t)((uint16_t)b[3] << 8 | b[4]);
    return 100.0 * (double)raw / 65535.0;
}

double sens_ads1115_volts(const uint8_t b[2])
{
    int16_t raw = (int16_t)(uint16_t)((uint16_t)b[0] << 8 | b[1]);
    return (double)raw * 4.096 / 32768.0;
}

double sens_ina219_bus_v(const uint8_t b[2])
{
    /* bus voltage register: bits 15..3, 4 mV/LSB. */
    uint16_t raw = (uint16_t)(((uint16_t)b[0] << 8 | b[1]) >> 3);
    return (double)raw * 0.004;
}

double sens_ina219_current_a(const uint8_t b[2], double shunt_ohm)
{
    /* shunt voltage register: signed, 10 uV/LSB. */
    int16_t raw = (int16_t)(uint16_t)((uint16_t)b[0] << 8 | b[1]);
    if (!(shunt_ohm > 0)) return NAN;
    return (double)raw * 10e-6 / shunt_ohm;
}
