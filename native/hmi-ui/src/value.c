// value.c -- see value.h.
#include "value.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"

hmi_value_t hmi_value_null(void)
{
    hmi_value_t v;
    memset(&v, 0, sizeof v);
    v.kind = HMI_V_NULL;
    return v;
}

hmi_value_t hmi_value_bool(bool b)
{
    hmi_value_t v = hmi_value_null();
    v.kind = HMI_V_BOOL;
    v.b = b;
    return v;
}

hmi_value_t hmi_value_num(double n)
{
    hmi_value_t v = hmi_value_null();
    v.kind = HMI_V_NUM;
    v.n = n;
    return v;
}

hmi_value_t hmi_value_str(const char *s)
{
    hmi_value_t v = hmi_value_null();
    v.kind = HMI_V_STR;
    v.s = strdup(s ? s : "");
    return v;
}

hmi_value_t hmi_value_copy(const hmi_value_t *src)
{
    if (!src)
        return hmi_value_null();
    hmi_value_t v = *src;
    if (src->kind == HMI_V_STR) {
        v.s = strdup(src->s ? src->s : "");
    } else if (src->kind == HMI_V_LIST) {
        v.items = src->count ? calloc(src->count, sizeof(hmi_value_t)) : NULL;
        for (size_t i = 0; i < src->count; ++i)
            v.items[i] = hmi_value_copy(&src->items[i]);
    }
    return v;
}

void hmi_value_free(hmi_value_t *v)
{
    if (!v)
        return;
    if (v->kind == HMI_V_STR)
        free(v->s);
    if (v->kind == HMI_V_LIST) {
        for (size_t i = 0; i < v->count; ++i)
            hmi_value_free(&v->items[i]);
        free(v->items);
    }
    *v = hmi_value_null();
}

double hmi_value_as_num(const hmi_value_t *v, double def)
{
    if (!v)
        return def;
    switch (v->kind) {
    case HMI_V_NUM: return v->n;
    case HMI_V_BOOL: return v->b ? 1.0 : 0.0;
    case HMI_V_STR: {
        if (!v->s || !*v->s)
            return def;
        char *end = NULL;
        double d = strtod(v->s, &end);
        return (end && *end == '\0') ? d : def;
    }
    default: return def;
    }
}

bool hmi_value_as_bool(const hmi_value_t *v, bool def)
{
    if (!v)
        return def;
    switch (v->kind) {
    case HMI_V_BOOL: return v->b;
    case HMI_V_NUM: return v->n != 0.0;
    case HMI_V_STR:
        if (!v->s) return def;
        if (strcmp(v->s, "true") == 0 || strcmp(v->s, "1") == 0) return true;
        if (strcmp(v->s, "false") == 0 || strcmp(v->s, "0") == 0 || !*v->s) return false;
        return def;
    default: return def;
    }
}

const char *hmi_value_as_str(const hmi_value_t *v, const char *def)
{
    if (v && v->kind == HMI_V_STR && v->s)
        return v->s;
    return def;
}

bool hmi_value_equal(const hmi_value_t *a, const hmi_value_t *b)
{
    if (!a || !b)
        return a == b;
    if (a->kind != b->kind)
        return false;
    switch (a->kind) {
    case HMI_V_NULL: return true;
    case HMI_V_BOOL: return a->b == b->b;
    case HMI_V_NUM: return a->n == b->n;
    case HMI_V_STR: return strcmp(a->s ? a->s : "", b->s ? b->s : "") == 0;
    case HMI_V_LIST:
        if (a->count != b->count)
            return false;
        for (size_t i = 0; i < a->count; ++i)
            if (!hmi_value_equal(&a->items[i], &b->items[i]))
                return false;
        return true;
    }
    return false;
}

const char *hmi_value_debug(const hmi_value_t *v)
{
    static char buf[128];
    if (!v) return "null";
    switch (v->kind) {
    case HMI_V_NULL: return "null";
    case HMI_V_BOOL: return v->b ? "true" : "false";
    case HMI_V_NUM:
        if (v->n == floor(v->n) && fabs(v->n) < 1e15)
            snprintf(buf, sizeof buf, "%.0f", v->n);
        else
            snprintf(buf, sizeof buf, "%g", v->n);
        return buf;
    case HMI_V_STR: snprintf(buf, sizeof buf, "\"%s\"", v->s ? v->s : ""); return buf;
    case HMI_V_LIST: snprintf(buf, sizeof buf, "[%zu items]", v->count); return buf;
    }
    return "?";
}

hmi_value_t hmi_value_from_json(const cJSON *j)
{
    if (!j || cJSON_IsNull(j))
        return hmi_value_null();
    if (cJSON_IsBool(j))
        return hmi_value_bool(cJSON_IsTrue(j));
    if (cJSON_IsNumber(j))
        return hmi_value_num(cJSON_GetNumberValue(j));
    if (cJSON_IsString(j))
        return hmi_value_str(cJSON_GetStringValue(j));
    if (cJSON_IsArray(j)) {
        hmi_value_t v = hmi_value_null();
        v.kind = HMI_V_LIST;
        v.count = (size_t)cJSON_GetArraySize(j);
        v.items = v.count ? calloc(v.count, sizeof(hmi_value_t)) : NULL;
        size_t i = 0;
        const cJSON *e;
        cJSON_ArrayForEach(e, j) v.items[i++] = hmi_value_from_json(e);
        return v;
    }
    return hmi_value_null();   // objects are not values in this model
}

cJSON *hmi_value_to_json(const hmi_value_t *v)
{
    if (!v)
        return cJSON_CreateNull();
    switch (v->kind) {
    case HMI_V_BOOL: return cJSON_CreateBool(v->b);
    case HMI_V_NUM: return cJSON_CreateNumber(v->n);
    case HMI_V_STR: return cJSON_CreateString(v->s ? v->s : "");
    case HMI_V_LIST: {
        cJSON *arr = cJSON_CreateArray();
        for (size_t i = 0; i < v->count; ++i)
            cJSON_AddItemToArray(arr, hmi_value_to_json(&v->items[i]));
        return arr;
    }
    default: return cJSON_CreateNull();
    }
}
