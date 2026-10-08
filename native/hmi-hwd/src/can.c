/*
 * can.c -- SocketCAN signals and frames (CONTRACT 14.3, "can").
 * OWNER: A2. STUB written with the skeleton: every function compiles
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

const hwd_backend_ops hwd_backend_can = {
    "can", v_validate, v_create, NULL, NULL, v_owns, v_write, v_command, NULL, v_errors, v_destroy,
};

/* ---- periph.h CAN codec (A2) ------------------------------------------ */
#include "periph.h"
uint64_t can_get_bits(const uint8_t data[8], int start_bit, int length, bool big_endian)
{ (void)data; (void)start_bit; (void)length; (void)big_endian; return 0; }
void can_set_bits(uint8_t data[8], int start_bit, int length, bool big_endian, uint64_t raw)
{ (void)data; (void)start_bit; (void)length; (void)big_endian; (void)raw; }
int64_t can_sign_extend(uint64_t raw, int length) { (void)raw; (void)length; return 0; }
bool can_parse_id(const char *text, bool extended, uint32_t *id) { (void)text; (void)extended; (void)id; return false; }
int can_parse_hex(const char *text, uint8_t out[8]) { (void)text; (void)out; return -1; }
