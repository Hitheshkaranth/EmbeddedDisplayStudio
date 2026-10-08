/*
 * proto.c -- CONTRACT 2 parsing, acks and frames (proto.h).
 * OWNER: A1. The parse rules follow daemon/hmi_hwd.py CommandProtocol:
 * size check, strict UTF-8, strict JSON (no trailing data, no raw control
 * characters in strings, no NaN/Infinity), object check, then the command.
 * Where a command carries both a tag and a bad value, kind and tag are filled
 * before the value is checked, so the daemon can answer unknown_tag /
 * not_writable first as the Python does.
 */
#include "proto.h"
#include "hwd.h"

#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Python's SUBSCRIBE_TTL_MAX_S. */
#define SUBSCRIBE_TTL_MAX_S 60.0
/* Python's _extract_id_best_effort looks at the first 512 bytes only. */
#define OVERSIZE_ID_SCAN 512

static bool is_ws(char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v'; }

/* Length of a UTF-8 sequence starting at p (bytes), 0 when invalid. */
static size_t utf8_seq(const unsigned char *p, size_t left)
{
    unsigned char c = p[0];
    if (c < 0x80) return 1;
    size_t n;
    unsigned int cp;
    if (c >= 0xC2 && c <= 0xDF) { n = 2; cp = c & 0x1F; }
    else if (c >= 0xE0 && c <= 0xEF) { n = 3; cp = c & 0x0F; }
    else if (c >= 0xF0 && c <= 0xF4) { n = 4; cp = c & 0x07; }
    else return 0;
    if (left < n) return 0;
    for (size_t i = 1; i < n; i++) {
        if ((p[i] & 0xC0) != 0x80) return 0;
        cp = (cp << 6) | (p[i] & 0x3F);
    }
    if (n == 3 && (cp < 0x800 || (cp >= 0xD800 && cp <= 0xDFFF))) return 0;
    if (n == 4 && (cp < 0x10000 || cp > 0x10FFFF)) return 0;
    return n;
}

/* Strict UTF-8 (Python's bytes.decode("utf-8")). */
static bool utf8_valid(const char *data, size_t len)
{
    const unsigned char *p = (const unsigned char *)data;
    size_t i = 0;
    while (i < len) {
        size_t n = utf8_seq(p + i, len - i);
        if (!n) return false;
        i += n;
    }
    return true;
}

/* Code points in a valid UTF-8 string. */
static size_t utf8_chars(const char *s)
{
    size_t n = 0;
    for (const unsigned char *p = (const unsigned char *)s; *p; p++)
        if ((*p & 0xC0) != 0x80) n++;
    return n;
}

/* Python's json.loads(strict=True) refuses raw control characters inside
 * strings; cJSON accepts them. Also refuses a NUL anywhere. */
static bool json_lexically_ok(const char *data, size_t len)
{
    bool in_str = false, esc = false;
    for (size_t i = 0; i < len; i++) {
        unsigned char c = (unsigned char)data[i];
        if (c == 0) return false;
        if (!in_str) {
            if (c == '"') in_str = true;
            continue;
        }
        if (esc) { esc = false; continue; }
        if (c == '\\') esc = true;
        else if (c == '"') in_str = false;
        else if (c < 0x20) return false;
    }
    return true;
}

/* Best-effort id recovery from malformed JSON (CONTRACT 2.3), the Python
 * regex  "id"\s*:\s*"([^"]{1,64})"  -- first match anywhere in the text. */
static void recover_id(hwd_cmd *cmd, const char *data, size_t len)
{
    for (size_t i = 0; i + 4 <= len; i++) {
        if (memcmp(data + i, "\"id\"", 4) != 0) continue;
        size_t j = i + 4;
        while (j < len && is_ws(data[j])) j++;
        if (j >= len || data[j] != ':') continue;
        j++;
        while (j < len && is_ws(data[j])) j++;
        if (j >= len || data[j] != '"') continue;
        j++;
        size_t start = j, chars = 0;
        bool ok = false;
        while (j < len && chars <= HWD_MAX_ID) {
            if (data[j] == '"') { ok = chars >= 1; break; }
            /* count code points (Python counts characters, not bytes) */
            if (((unsigned char)data[j] & 0xC0) != 0x80) chars++;
            j++;
        }
        if (!ok || chars > HWD_MAX_ID) continue;
        size_t n = j - start;
        if (n > HWD_MAX_ID) continue;           /* multibyte id too long for the buffer */
        if (memchr(data + start, '\0', n)) continue;
        memcpy(cmd->id, data + start, n);
        cmd->id[n] = '\0';
        cmd->has_id = true;
        return;
    }
}

/* id: a non-empty string of at most 64 characters, else none. */
static void parse_id(const cJSON *root, hwd_cmd *cmd)
{
    const cJSON *jid = cJSON_GetObjectItemCaseSensitive(root, "id");
    if (!cJSON_IsString(jid) || !jid->valuestring || !jid->valuestring[0]) return;
    size_t bytes = strlen(jid->valuestring);
    if (utf8_chars(jid->valuestring) > HWD_MAX_ID || bytes > HWD_MAX_ID) return;
    memcpy(cmd->id, jid->valuestring, bytes + 1);
    cmd->has_id = true;
}

/* A finite JSON number that is not a bool (cJSON keeps bools apart). */
static bool get_number(const cJSON *root, const char *key, double *out)
{
    const cJSON *j = cJSON_GetObjectItemCaseSensitive(root, key);
    if (!cJSON_IsNumber(j) || !isfinite(j->valuedouble)) return false;
    *out = j->valuedouble;
    return true;
}

/* tag: copied only when it is a string that fits; otherwise left "" (which
 * no registered tag matches -- never a truncated name that might). */
static void parse_tag(const cJSON *root, hwd_cmd *cmd)
{
    const cJSON *jt = cJSON_GetObjectItemCaseSensitive(root, "tag");
    if (!cJSON_IsString(jt) || !jt->valuestring) return;
    size_t n = strlen(jt->valuestring);
    if (n > HWD_MAX_TAG) return;
    memcpy(cmd->tag, jt->valuestring, n + 1);
}

static const struct { const char *name; hwd_cmd_kind kind; } CMDS[] = {
    {"set", HWD_CMD_SET}, {"pulse", HWD_CMD_PULSE}, {"uart_tx", HWD_CMD_UART_TX},
    {"subscribe", HWD_CMD_SUBSCRIBE}, {"unsubscribe", HWD_CMD_UNSUBSCRIBE},
    {"list", HWD_CMD_LIST}, {"ping", HWD_CMD_PING}, {"history", HWD_CMD_HISTORY},
    {"discover", HWD_CMD_DISCOVER},
};

static hwd_err parse_body(const cJSON *root, hwd_cmd *cmd)
{
    switch (cmd->kind) {
    case HWD_CMD_SET: {
        parse_tag(root, cmd);
        const cJSON *jv = cJSON_GetObjectItemCaseSensitive(root, "value");
        if (cJSON_IsBool(jv)) {
            cmd->value = hwd_bool(cJSON_IsTrue(jv));
        } else if (cJSON_IsNumber(jv)) {
            double d = jv->valuedouble;
            if (!isfinite(d)) return HWD_ERR_BAD_VALUE;
            if (d == floor(d) && fabs(d) < 9.007199254740992e15)
                cmd->value = hwd_int((int64_t)d);
            else
                cmd->value = hwd_float(d);
        } else if (cJSON_IsString(jv) && jv->valuestring) {
            cmd->value = hwd_str(jv->valuestring);
        } else {
            return HWD_ERR_BAD_VALUE;
        }
        return HWD_OK;
    }
    case HWD_CMD_PULSE: {
        parse_tag(root, cmd);
        double ms;
        if (!get_number(root, "ms", &ms) || ms < HWD_PULSE_MIN_MS || ms > HWD_PULSE_MAX_MS)
            return HWD_ERR_BAD_VALUE;
        cmd->ms = (int)ms;
        if (cmd->ms < HWD_PULSE_MIN_MS) cmd->ms = HWD_PULSE_MIN_MS;
        return HWD_OK;
    }
    case HWD_CMD_UART_TX: {
        const cJSON *jd = cJSON_GetObjectItemCaseSensitive(root, "data");
        if (!cJSON_IsString(jd) || !jd->valuestring) return HWD_ERR_BAD_VALUE;
        cmd->data = strdup(jd->valuestring);
        return cmd->data ? HWD_OK : HWD_ERR_HW_ERROR;
    }
    case HWD_CMD_SUBSCRIBE: {
        double ttl;
        if (get_number(root, "ttl", &ttl) && ttl > 0.0)
            cmd->ttl = ttl < SUBSCRIBE_TTL_MAX_S ? ttl : SUBSCRIBE_TTL_MAX_S;
        return HWD_OK;
    }
    case HWD_CMD_HISTORY: {
        parse_tag(root, cmd);
        cmd->seconds = 3600;
        cmd->points = 200;
        const cJSON *js = cJSON_GetObjectItemCaseSensitive(root, "seconds");
        const cJSON *jp = cJSON_GetObjectItemCaseSensitive(root, "points");
        hwd_err err = HWD_OK;
        if (js) {
            if (!cJSON_IsNumber(js) || !isfinite(js->valuedouble) ||
                js->valuedouble < 1 || js->valuedouble > 604800)
                err = HWD_ERR_BAD_VALUE;
            else
                cmd->seconds = js->valuedouble;
        }
        if (jp) {
            if (!cJSON_IsNumber(jp) || !isfinite(jp->valuedouble) ||
                jp->valuedouble < 1 || jp->valuedouble > 200)
                err = HWD_ERR_BAD_VALUE;
            else
                cmd->points = jp->valuedouble;
        }
        return err;
    }
    case HWD_CMD_UNSUBSCRIBE:
    case HWD_CMD_LIST:
    case HWD_CMD_PING:
    case HWD_CMD_DISCOVER:
        return HWD_OK;
    case HWD_CMD_NONE:
    default:
        return HWD_ERR_UNKNOWN_CMD;
    }
}

hwd_err hwd_proto_parse(const char *data, size_t len, hwd_cmd *cmd)
{
    if (!cmd) return HWD_ERR_BAD_JSON;
    memset(cmd, 0, sizeof *cmd);
    cmd->value = hwd_null();
    if (!data) return HWD_ERR_BAD_JSON;

    /* Oversized: dropped and counted; id best-effort from the head. */
    if (len > HWD_MAX_DGRAM) {
        recover_id(cmd, data, len < OVERSIZE_ID_SCAN ? len : OVERSIZE_ID_SCAN);
        return HWD_ERR_TOO_LARGE;
    }
    /* Non-UTF-8: dropped silently (no id recovery, as the Python). */
    if (!utf8_valid(data, len)) return HWD_ERR_BAD_JSON;

    cJSON *root = NULL;
    if (len > 0 && json_lexically_ok(data, len)) {
        char *buf = malloc(len + 1);
        if (!buf) return HWD_ERR_BAD_JSON;
        memcpy(buf, data, len);
        buf[len] = '\0';
        root = cJSON_ParseWithOpts(buf, NULL, true);   /* nothing may follow */
        free(buf);
    }
    if (!root) {
        recover_id(cmd, data, len);
        return HWD_ERR_BAD_JSON;
    }
    if (!cJSON_IsObject(root)) {
        cJSON_Delete(root);
        recover_id(cmd, data, len);
        return HWD_ERR_NOT_AN_OBJECT;
    }

    parse_id(root, cmd);

    const cJSON *jcmd = cJSON_GetObjectItemCaseSensitive(root, "cmd");
    if (!cJSON_IsString(jcmd) || !jcmd->valuestring) {
        cJSON_Delete(root);
        return HWD_ERR_UNKNOWN_CMD;
    }
    for (size_t i = 0; i < sizeof CMDS / sizeof CMDS[0]; i++)
        if (strcmp(jcmd->valuestring, CMDS[i].name) == 0) cmd->kind = CMDS[i].kind;
    if (cmd->kind == HWD_CMD_NONE) {
        cJSON_Delete(root);
        return HWD_ERR_UNKNOWN_CMD;
    }

    hwd_err err = parse_body(root, cmd);
    cJSON_Delete(root);
    return err;
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

static int cmp_names(const void *a, const void *b)
{
    return strcmp(*(const char *const *)a, *(const char *const *)b);
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
    qsort(names, n, sizeof names[0], cmp_names);   /* the list ack is sorted */
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