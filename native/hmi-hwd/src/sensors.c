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
bool sens_parse_type(const char *name, sens_type *t) { (void)name; (void)t; return false; }
int sens_type_bytes(sens_type t) { (void)t; return 0; }
double sens_decode(const uint8_t *buf, sens_type t, bool big_endian, uint32_t mask, int shift,
                   double scale, double offset)
{ (void)buf; (void)t; (void)big_endian; (void)mask; (void)shift; (void)scale; (void)offset; return 0; }
double sens_tmp102_c(const uint8_t b[2]) { (void)b; return 0; }
double sens_sht3x_temp_c(const uint8_t b[6]) { (void)b; return 0; }
double sens_sht3x_rh(const uint8_t b[6]) { (void)b; return 0; }
bool sens_sht3x_crc_ok(const uint8_t b[6]) { (void)b; return false; }
double sens_ads1115_volts(const uint8_t b[2]) { (void)b; return 0; }
double sens_ina219_bus_v(const uint8_t b[2]) { (void)b; return 0; }
double sens_ina219_current_a(const uint8_t b[2], double shunt_ohm) { (void)b; (void)shunt_ohm; return 0; }
