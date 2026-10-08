/*
 * proto.c -- CONTRACT 2 parsing, acks and frames (proto.h).
 * OWNER: A1. STUB written with the skeleton: every function compiles
 * and fails safe; the owner replaces the bodies (not the signatures).
 */
#include "proto.h"
#include <stdlib.h>
#include <string.h>

hwd_err hwd_proto_parse(const char *data, size_t len, hwd_cmd *cmd)
{ (void)data; (void)len; memset(cmd, 0, sizeof *cmd); return HWD_ERR_BAD_JSON; }
void hwd_cmd_free(hwd_cmd *cmd) { if (!cmd) return; free(cmd->data); cmd->data = NULL; hwd_value_clear(&cmd->value); }
char *hwd_proto_ack(const char *id, hwd_err err) { (void)id; (void)err; return NULL; }
char *hwd_proto_list_ack(const char *id, hwd_tagstore *store) { (void)id; (void)store; return NULL; }
char *hwd_proto_ping_ack(const char *id) { (void)id; return NULL; }
char *hwd_proto_history_ack(const char *id, const char *tag, cJSON *samples)
{ (void)id; (void)tag; cJSON_Delete(samples); return NULL; }
char *hwd_proto_frame(hwd_tagstore *store, uint32_t seq, double ts) { (void)store; (void)seq; (void)ts; return NULL; }
