/*
 * serial.c -- USB and native serial ports with hotplug (CONTRACT 14.1, "serial").
 * OWNER: A3. STUB written with the skeleton: every function compiles
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

const hwd_backend_ops hwd_backend_serial = {
    "serial", v_validate, v_create, NULL, NULL, v_owns, v_write, v_command, NULL, v_errors, v_destroy,
};
