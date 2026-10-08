/*
 * modbus.c -- the Modbus codec (modbus.h) and the backend serving "modbus" (TCP) and
 * "modbus_rtu" (CONTRACT 2.5, 14.2).
 * OWNER: A2. STUB written with the skeleton: every function compiles
 * and fails safe; the owner replaces the bodies (not the signatures).
 */
#include "modbus.h"
#include "backend.h"

int mb_type_registers(mb_type t) { (void)t; return 0; }
double mb_decode(mb_type t, const uint16_t *regs, bool little_words) { (void)t; (void)regs; (void)little_words; return 0; }
int mb_encode(mb_type t, double raw, uint16_t *regs, bool little_words) { (void)t; (void)raw; (void)regs; (void)little_words; return 0; }
size_t mb_req_read(uint8_t *buf, uint16_t tid, uint8_t unit, uint8_t fc, uint16_t addr, uint16_t count)
{ (void)buf; (void)tid; (void)unit; (void)fc; (void)addr; (void)count; return 0; }
size_t mb_req_write_single(uint8_t *buf, uint16_t tid, uint8_t unit, uint8_t fc, uint16_t addr, uint16_t value)
{ (void)buf; (void)tid; (void)unit; (void)fc; (void)addr; (void)value; return 0; }
size_t mb_req_write_multi(uint8_t *buf, uint16_t tid, uint8_t unit, uint16_t addr, const uint16_t *regs, uint16_t count)
{ (void)buf; (void)tid; (void)unit; (void)addr; (void)regs; (void)count; return 0; }
int mb_parse_read(const uint8_t *buf, size_t len, uint16_t tid, uint8_t fc, uint16_t count, uint8_t *bits, uint16_t *regs)
{ (void)buf; (void)len; (void)tid; (void)fc; (void)count; (void)bits; (void)regs; return -1; }
int mb_parse_write(const uint8_t *buf, size_t len, uint16_t tid, uint8_t fc)
{ (void)buf; (void)len; (void)tid; (void)fc; return -1; }
uint16_t mb_crc16(const uint8_t *buf, size_t len) { (void)buf; (void)len; return 0; }
size_t mb_rtu_req_read(uint8_t *buf, uint8_t unit, uint8_t fc, uint16_t addr, uint16_t count)
{ (void)buf; (void)unit; (void)fc; (void)addr; (void)count; return 0; }
size_t mb_rtu_req_write_single(uint8_t *buf, uint8_t unit, uint8_t fc, uint16_t addr, uint16_t value)
{ (void)buf; (void)unit; (void)fc; (void)addr; (void)value; return 0; }
size_t mb_rtu_req_write_multi(uint8_t *buf, uint8_t unit, uint16_t addr, const uint16_t *regs, uint16_t count)
{ (void)buf; (void)unit; (void)addr; (void)regs; (void)count; return 0; }
int mb_rtu_parse_read(const uint8_t *buf, size_t len, uint8_t unit, uint8_t fc, uint16_t count, uint8_t *bits, uint16_t *regs)
{ (void)buf; (void)len; (void)unit; (void)fc; (void)count; (void)bits; (void)regs; return -1; }
int mb_rtu_parse_write(const uint8_t *buf, size_t len, uint8_t unit, uint8_t fc)
{ (void)buf; (void)len; (void)unit; (void)fc; return -1; }

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

const hwd_backend_ops hwd_backend_modbus = {
    "modbus", v_validate, v_create, NULL, NULL, v_owns, v_write, v_command, NULL, v_errors, v_destroy,
};
