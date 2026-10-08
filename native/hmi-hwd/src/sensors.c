/*
 * sensors.c -- I2C and SPI sensors (CONTRACT 14.6, "i2c", "spi").
 * OWNER: A4. STUB written with the skeleton: every function compiles
 * and fails safe; the owner replaces the bodies (not the signatures).
 */
#include "backend.h"

static int v_validate(const hwd_config *cfg, char *err, size_t errlen)
{ (void)cfg; (void)err; (void)errlen; return 0; }
static void *v_create(const hwd_config *cfg, hwd_tagstore *store, const hwd_backend_opts *opts,
                      char *err, size_t errlen)
{ (void)cfg; (void)store; (void)opts; if (errlen) err[0] = '\0'; return NULL; }
static bool v_owns(void *self, const char *tag) { (void)self; (void)tag; return false; }
static hwd_err v_write(void *self, const char *tag, const hwd_value *v)
{ (void)self; (void)tag; (void)v; return HWD_ERR_NOT_WRITABLE; }
static hwd_err v_command(void *self, const char *cmd, const cJSON *msg, cJSON *reply)
{ (void)self; (void)cmd; (void)msg; (void)reply; return HWD_ERR_UNKNOWN_CMD; }
static uint64_t v_errors(void *self) { (void)self; return 0; }
static void v_destroy(void *self) { (void)self; }

const hwd_backend_ops hwd_backend_sensors = {
    "sensors", v_validate, v_create, NULL, NULL, v_owns, v_write, v_command, NULL, v_errors, v_destroy,
};

/* ---- periph.h sensor decoding (A4) ------------------------------------ */
#include "periph.h"
#include <string.h>
#include <math.h>

bool sens_parse_type(const char *name, sens_type *t)
{
    if (!name || !t) return false;
    if      (!strcmp(name, "uint8"))  *t = SENS_U8;
    else if (!strcmp(name, "int8"))   *t = SENS_I8;
    else if (!strcmp(name, "uint16")) *t = SENS_U16;
    else if (!strcmp(name, "int16"))  *t = SENS_I16;
    else if (!strcmp(name, "uint32")) *t = SENS_U32;
    else if (!strcmp(name, "int32"))  *t = SENS_I32;
    else if (!strcmp(name, "float32"))*t = SENS_F32;
    else return false;
    return true;
}

int sens_type_bytes(sens_type t)
{
    switch (t) {
    case SENS_U8:  case SENS_I8:  return 1;
    case SENS_U16: case SENS_I16: return 2;
    case SENS_U32: case SENS_I32: return 4;
    case SENS_F32:                 return 4;
    }
    return 0;
}

static uint32_t read_raw(const uint8_t *buf, sens_type t, bool big_endian)
{
    switch (t) {
    case SENS_U8:
        return buf[0];
    case SENS_I8: {
        int8_t x = (const int8_t *)buf[0];
        return (uint32_t)(int32_t)x;
    }
    case SENS_U16: {
        uint16_t x = big_endian ? ((uint16_t)buf[0] << 8 | buf[1])
                                : ((uint16_t)buf[1] << 8 | buf[0]);
        return x;
    }
    case SENS_I16: {
        uint16_t x = big_endian ? ((uint16_t)buf[0] << 8 | buf[1])
                                : ((uint16_t)buf[1] << 8 | buf[0]);
        return (uint32_t)(int16_t)x;
    }
    case SENS_U32: {
        uint32_t x = big_endian
            ? ((uint32_t)buf[0] << 24 | (uint32_t)buf[1] << 16 |
               (uint32_t)buf[2] << 8 | buf[3])
            : ((uint32_t)buf[3] << 24 | (uint32_t)buf[2] << 16 |
               (uint32_t)buf[1] << 8 | buf[0]);
        return x;
    }
    case SENS_I32: {
        uint32_t x = big_endian
            ? ((uint32_t)buf[0] << 24 | (uint32_t)buf[1] << 16 |
               (uint32_t)buf[2] << 8 | buf[3])
            : ((uint32_t)buf[3] << 24 | (uint32_t)buf[2] << 16 |
               (uint32_t)buf[1] << 8 | buf[0]);
        return (uint32_t)(int32_t)x;
    }
    case SENS_F32: {
        uint32_t x = big_endian
            ? ((uint32_t)buf[0] << 24 | (uint32_t)buf[1] << 16 |
               (uint32_t)buf[2] << 8 | buf[3])
            : ((uint32_t)buf[3] << 24 | (uint32_t)buf[2] << 16 |
               (uint32_t)buf[1] << 8 | buf[0]);
        float f;
        memcpy(&f, &x, sizeof f);
        return (uint32_t)f;
    }
    }
    return 0;
}

double sens_decode(const uint8_t *buf, sens_type t, bool big_endian, uint32_t mask, int shift,
                   double scale, double offset)
{
    if (!buf) return 0;
    uint32_t raw = read_raw(buf, t, big_endian);
    if (mask) raw &= mask;
    raw >>= shift;
    /* float raws are returned raw for the caller's scale/offset path. */
    if (t == SENS_F32) {
        uint32_t bits = raw;
        float f;
        memcpy(&f, &bits, sizeof f);
        return f * scale + offset;
    }
    return (double)raw * scale + offset;
}

double sens_tmp102_c(const uint8_t b[2])
{
    /* 12-bit left aligned, 0.0625 C/LSB, signed two's complement. */
    int16_t raw = (int16_t)((uint16_t)((uint16_t)b[0] << 8 | b[1]) >> 4);
    return raw * 0.0625;
}

static uint8_t crc8(const uint8_t *data, int len)
{
    uint8_t crc = 0xFF;
    for (int i = 0; i < len; i++) {
        crc ^= data[i];
        for (int b = 0; b < 8; b++) {
            if (crc & 0x80) crc = (crc << 1) ^ 0x31;
            else crc <<= 1;
        }
    }
    return crc;
}

bool sens_sht3x_crc_ok(const uint8_t b[6])
{
    return crc8(b, 4) == b[4] && crc8(b + 2, 4) == b[5];
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
    int16_t raw = (int16_t)((uint16_t)b[0] << 8 | b[1]);
    return (double)raw * 4.096 / 32768.0;
}

double sens_ina219_bus_v(const uint8_t b[2])
{
    /* bus voltage register is 13-bit unsigned, 12.5 mV/LSB. */
    uint16_t raw = (uint16_t)((uint16_t)b[0] << 8 | b[1]) >> 3;
    return raw * 0.0125;
}

double sens_ina219_current_a(const uint8_t b[2], double shunt_ohm)
{
    int16_t raw = (int16_t)((uint16_t)b[0] << 8 | b[1]);
    double shunt_uv = raw * 10.0;              /* 10 uV/LSB */
    return shunt_uv / 1e6 / shunt_ohm;
}