/*
 * proto.c -- CONTRACT 2 parsing, acks and frames (proto.h).
 * OWNER: A1. STUB written with the skeleton: every function compiles
 * and fails safe; the owner replaces the bodies (not the signatures).
 */
#include "proto.h"
#include "hwd.h"

#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Best-effort id recovery from malformed JSON (CONTRACT 2.3): scan for the
 * first "id":"..." (up to 64 chars) the way the Python regex does. */
static void recover_id(hwd_cmd *cmd, const char *data, size_t len)
{
    /* Work on a NUL-terminated buffer; len is bounded by HWD_MAX_DGRAM. */
    char buf[HWD_MAX_DGRAM + 1];
    size_t n = len < sizeof buf - 1 ? len : sizeof buf - 1;
    memcpy(buf, data, n);
    buf[n] = '\0';

    const char *p = buf;
    while (*p) {
        if ((unsigned char)p[0] == '"' && p[1] == 'i' && p[2] == 'd' && p[3] == '"') {
            const char *q = p + 4;
            while (*q && *q != ':') q++;
            if (*q == ':') {
                q++;
                while (*q && (*q == ' ' || *q == '\t')) q++;
                if (*q == '"') {
                    q++;
                    char out[HWD_MAX_ID + 1];
                    size_t i = 0;
                    while (*q && *q != '"' && i < HWD_MAX_ID) out[i++] = *q++;
                    out[i] = '\0';
                    if (i) {
                        strncpy(cmd->id, out, HWD_MAX_ID);
                        cmd->id[HWD_MAX_ID] = '\0';
                        cmd->has_id = true;
                    }
                    return;
                }
            }
        }
        p++;
    }
}

static void parse_id(cJSON *root, hwd_cmd *cmd)
{
    cJSON *jid = cJSON_GetObjectItemCaseSensitive(root, "id");
    if (cJSON_IsString(jid) && jid->valuestring && jid->valuestring[0]) {
        strncpy(cmd->id, jid->valuestring, HWD_MAX_ID);
        cmd->id[HWD_MAX_ID] = '\0';
        cmd->has_id = true;
    }
}

hwd_err hwd_proto_parse(const char *data, size_t len, hwd_cmd *cmd)
{
    if (!cmd) return HWD_ERR_BAD_JSON;
    memset(cmd, 0, sizeof *cmd);

    /* oversized datagrams: counted + dropped; recover the id best-effort. */
    if (len > HWD_MAX_DGRAM) {
        recover_id(cmd, data, len);
        return HWD_ERR_TOO_LARGE;
    }

    if (len == 0) return HWD_ERR_BAD_JSON;

    cJSON *root = cJSON_ParseWithLength(data, len);
    if (!root) {
        recover_id(cmd, data, len);
        return HWD_ERR_BAD_JSON;
    }

    hwd_err err = HWD_ERR_BAD_JSON;
    cJSON *jcmd = cJSON_GetObjectItemCaseSensitive(root, "cmd");

    if (!cJSON_IsString(jcmd) || !jcmd->valuestring || !*jcmd->valuestring) {
        /* No usable cmd: not_an_object is impossible (we parsed an object),
         * so a missing/non-string cmd is unknown_cmd. */
        err = HWD_ERR_UNKNOWN_CMD;
    } else {
        const char *kind = jcmd->valuestring;
        if      (strcmp(kind, "set") == 0)     cmd->kind = HWD_CMD_SET;
        else if (strcmp(kind, "pulse") == 0)   cmd->kind = HWD_CMD_PULSE;
        else if (strcmp(kind, "uart_tx") == 0) cmd->kind = HWD_CMD_UART_TX;
        else if (strcmp(kind, "subscribe") == 0) cmd->kind = HWD_CMD_SUBSCRIBE;
        else if (strcmp(kind, "unsubscribe") == 0) cmd->kind = HWD_CMD_UNSUBSCRIBE;
        else if (strcmp(kind, "list") == 0)    cmd->kind = HWD_CMD_LIST;
        else if (strcmp(kind, "ping") == 0)    cmd->kind = HWD_CMD_PING;
        else if (strcmp(kind, "history") == 0) cmd->kind = HWD_CMD_HISTORY;
        else if (strcmp(kind, "discover") == 0) cmd->kind = HWD_CMD_DISCOVER;
        else                                   err = HWD_ERR_UNKNOWN_CMD;
    }

    if (err != HWD_OK) {
        if (!cmd->has_id) parse_id(root, cmd);
        cJSON_Delete(root);
        return err;
    }

    /* The frame is a JSON object here (it parsed); a non-object input can only
     * reach us via the oversized path, which already returned not_an_object. */
    (void)root;

    /* Optional opaque id (string, <= 64 chars). */
    parse_id(root, cmd);

    switch (cmd->kind) {
    case HWD_CMD_SET: {
        cJSON *jt = cJSON_GetObjectItemCaseSensitive(root, "tag");
        if (!cJSON_IsString(jt) || !jt->valuestring) {
            cJSON_Delete(root);
            return HWD_ERR_BAD_VALUE;
        }
        strncpy(cmd->tag, jt->valuestring, HWD_MAX_TAG);
        cmd->tag[HWD_MAX_TAG] = '\0';
        cJSON *jv = cJSON_GetObjectItemCaseSensitive(root, "value");
        if (cJSON_IsBool(jv)) {
            cmd->value = hwd_bool(cJSON_IsTrue(jv));
        } else if (cJSON_IsNumber(jv)) {
            double d = jv->valuedouble;
            if (!isfinite(d)) {
                cJSON_Delete(root);
                return HWD_ERR_BAD_VALUE;
            }
            int64_t as_int = (int64_t)d;
            if ((double)as_int == d && fabs(d) < 9.007199254740992e15)
                cmd->value = hwd_int(as_int);
            else
                cmd->value = hwd_float(d);
        } else if (cJSON_IsString(jv)) {
            cmd->value = hwd_str(jv->valuestring);
        } else {
            cJSON_Delete(root);
            return HWD_ERR_BAD_VALUE;
        }
        cJSON_Delete(root);
        return HWD_OK;
    }
    case HWD_CMD_PULSE: {
        cJSON *jt = cJSON_GetObjectItemCaseSensitive(root, "tag");
        if (!cJSON_IsString(jt) || !jt->valuestring) {
            cJSON_Delete(root);
            return HWD_ERR_BAD_VALUE;
        }
        strncpy(cmd->tag, jt->valuestring, HWD_MAX_TAG);
        cmd->tag[HWD_MAX_TAG] = '\0';
        cJSON *jms = cJSON_GetObjectItemCaseSensitive(root, "ms");
        if (!cJSON_IsNumber(jms) || cJSON_IsBool(jms) || !isfinite(jms->valuedouble)) {
            cJSON_Delete(root);
            return HWD_ERR_BAD_VALUE;
        }
        double ms = jms->valuedouble;
        if (ms < HWD_PULSE_MIN_MS || ms > HWD_PULSE_MAX_MS) {
            cJSON_Delete(root);
            return HWD_ERR_BAD_VALUE;
        }
        cmd->ms = (int)ms;
        cJSON_Delete(root);
        return HWD_OK;
    }
    case HWD_CMD_UART_TX: {
        cJSON *jd = cJSON_GetObjectItemCaseSensitive(root, "data");
        if (!cJSON_IsString(jd) || !jd->valuestring) {
            cJSON_Delete(root);
            return HWD_ERR_BAD_VALUE;
        }
        cmd->data = strdup(jd->valuestring);
        cJSON_Delete(root);
        return HWD_OK;
    }
    case HWD_CMD_SUBSCRIBE: {
        cJSON *jtl = cJSON_GetObjectItemCaseSensitive(root, "ttl");
        if (cJSON_IsNumber(jtl) && !cJSON_IsBool(jtl) && isfinite(jtl->valuedouble) && jtl->valuedouble > 0.0) {
            cmd->ttl = jtl->valuedouble;
        }
        cJSON_Delete(root);
        return HWD_OK;
    }
    case HWD_CMD_UNSUBSCRIBE:
    case HWD_CMD_LIST:
    case HWD_CMD_PING:
        cJSON_Delete(root);
        return HWD_OK;
    case HWD_CMD_HISTORY: {
        cJSON *jt = cJSON_GetObjectItemCaseSensitive(root, "tag");
        if (cJSON_IsString(jt) && jt->valuestring) {
            strncpy(cmd->tag, jt->valuestring, HWD_MAX_TAG);
            cmd->tag[HWD_MAX_TAG] = '\0';
        }
        cJSON *js = cJSON_GetObjectItemCaseSensitive(root, "seconds");
        if (cJSON_IsNumber(js) && !cJSON_IsBool(js) && isfinite(js->valuedouble))
            cmd->seconds = js->valuedouble;
        cJSON *jp = cJSON_GetObjectItemCaseSensitive(root, "points");
        if (cJSON_IsNumber(jp) && !cJSON_IsBool(jp) && isfinite(jp->valuedouble))
            cmd->points = jp->valuedouble;
        cJSON_Delete(root);
        return HWD_OK;
    }
    case HWD_CMD_DISCOVER:
        cJSON_Delete(root);
        return HWD_OK;
    case HWD_CMD_NONE:
    default:
        cJSON_Delete(root);
        return HWD_ERR_UNKNOWN_CMD;
    }
}

void hwd_cmd_free(hwd_cmd *cmd)
{
    if (!cmd) return;
    free(cmd->data);
    cmd->data = NULL;
    hwd_value_clear(&cmd->value);
}

char *hwd_proto_ack(const char *id, hwd_err err)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;
    cJSON_AddItemToObject(root, "t", cJSON_CreateString("ack"));
    if (id && *id)
        cJSON_AddItemToObject(root, "id", cJSON_CreateString(id));
    if (err == HWD_OK) {
        cJSON_AddItemToObject(root, "ok", cJSON_CreateBool(true));
    } else {
        cJSON_AddItemToObject(root, "ok", cJSON_CreateBool(false));
        cJSON_AddItemToObject(root, "err", cJSON_CreateString(hwd_err_name(err)));
    }
    char *out = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return out;
}

char *hwd_proto_list_ack(const char *id, hwd_tagstore *store)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;
    cJSON_AddItemToObject(root, "t", cJSON_CreateString("ack"));
    if (id && *id)
        cJSON_AddItemToObject(root, "id", cJSON_CreateString(id));
    cJSON_AddItemToObject(root, "ok", cJSON_CreateBool(true));

    const char *names[HWD_MAX_TAGS];
    size_t n = hwd_tagstore_names(store, names, HWD_MAX_TAGS);
    /* sort names ascending (list ack sorts on its own). */
    for (size_t i = 0; i < n; i++)
        for (size_t j = i + 1; j < n; j++)
            if (strcmp(names[i], names[j]) > 0) {
                const char *tmp = names[i];
                names[i] = names[j];
                names[j] = tmp;
            }
    cJSON *arr = cJSON_CreateArray();
    for (size_t i = 0; i < n; i++)
        cJSON_AddItemToArray(arr, cJSON_CreateString(names[i]));
    cJSON_AddItemToObject(root, "tags", arr);

    char *out = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return out;
}

char *hwd_proto_ping_ack(const char *id)
{
    return hwd_proto_ack(id, HWD_OK);
}

char *hwd_proto_history_ack(const char *id, const char *tag, cJSON *samples)
{
    /* ownership of samples taken; fall back to empty samples when the reply
     * would exceed HWD_MAX_DGRAM. */
    cJSON *root = cJSON_CreateObject();
    if (!root) { cJSON_Delete(samples); return NULL; }
    cJSON_AddItemToObject(root, "t", cJSON_CreateString("ack"));
    if (id && *id)
        cJSON_AddItemToObject(root, "id", cJSON_CreateString(id));
    cJSON_AddItemToObject(root, "ok", cJSON_CreateBool(true));

    cJSON *hist = cJSON_CreateObject();
    cJSON_AddItemToObject(hist, "tag", cJSON_CreateString(tag ? tag : ""));
    cJSON_AddItemToObject(hist, "samples", samples);
    cJSON_AddItemToObject(root, "history", hist);

    char *out = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);

    size_t cap = strlen(out ? out : "");
    if (cap > HWD_MAX_DGRAM) {
        cJSON *root2 = cJSON_CreateObject();
        cJSON_AddItemToObject(root2, "t", cJSON_CreateString("ack"));
        if (id && *id)
            cJSON_AddItemToObject(root2, "id", cJSON_CreateString(id));
        cJSON_AddItemToObject(root2, "ok", cJSON_CreateBool(true));
        cJSON *hist2 = cJSON_CreateObject();
        cJSON_AddItemToObject(hist2, "tag", cJSON_CreateString(tag ? tag : ""));
        cJSON_AddItemToObject(hist2, "samples", cJSON_CreateArray());
        cJSON_AddItemToObject(root2, "history", hist2);
        char *out2 = cJSON_PrintUnformatted(root2);
        cJSON_Delete(root2);
        free(out);
        return out2;
    }
    return out;
}

char *hwd_proto_frame(hwd_tagstore *store, uint32_t seq, double ts)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;
    cJSON_AddItemToObject(root, "t", cJSON_CreateString("tags"));
    cJSON_AddItemToObject(root, "seq", cJSON_CreateNumber((double)seq));
    cJSON_AddItemToObject(root, "ts", cJSON_CreateNumber(ts));
    cJSON_AddItemToObject(root, "src", cJSON_CreateString("hmi-hwd"));

    const char *names[HWD_MAX_TAGS];
    size_t n = hwd_tagstore_names(store, names, HWD_MAX_TAGS);

    cJSON *tags = cJSON_CreateObject();
    for (size_t i = 0; i < n; i++) {
        hwd_value v = hwd_tagstore_get(store, names[i]);
        cJSON *jv;
        switch (v.kind) {
        case HWD_NULL: jv = cJSON_CreateNull(); break;
        case HWD_BOOL: jv = cJSON_CreateBool(v.u.b); break;
        case HWD_INT:  jv = cJSON_CreateNumber((double)v.u.i); break;
        case HWD_FLOAT: jv = cJSON_CreateNumber(v.u.f); break;
        case HWD_STR:  jv = cJSON_CreateString(v.u.s ? v.u.s : ""); break;
        default:       jv = cJSON_CreateNull(); break;
        }
        cJSON_AddItemToObject(tags, names[i], jv);
        hwd_value_clear(&v);
    }
    cJSON_AddItemToObject(root, "tags", tags);

    /* "q" only when some tag is not good. */
    cJSON *qmap = cJSON_CreateObject();
    for (size_t i = 0; i < n; i++) {
        char q[16];
        if (hwd_tagstore_quality(store, names[i], q, sizeof q))
            cJSON_AddItemToObject(qmap, names[i], cJSON_CreateString(q));
    }
    if (qmap->child != NULL)
        cJSON_AddItemToObject(root, "q", qmap);
    else
        cJSON_Delete(qmap);

    char *out = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return out;
}