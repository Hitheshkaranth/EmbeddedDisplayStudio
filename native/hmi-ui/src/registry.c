// registry.c -- see registry.h.
#include "registry.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gen/kit_schema.h"
#include "log.h"
#include "runtime.h"

static const hmi_widget_ops_t *g_ops[96];
static size_t g_nops;

void hmi_registry_register(const hmi_widget_ops_t *ops)
{
    for (size_t i = 0; i < g_nops; ++i)
        if (strcmp(g_ops[i]->type, ops->type) == 0) { g_ops[i] = ops; return; }
    if (g_nops < sizeof g_ops / sizeof g_ops[0])
        g_ops[g_nops++] = ops;
}

const hmi_widget_ops_t *hmi_registry_find(const char *type)
{
    for (size_t i = 0; i < g_nops; ++i)
        if (strcmp(g_ops[i]->type, type) == 0) return g_ops[i];
    return NULL;
}

// Schema defaults parsed once per (type, prop): a small cache keyed by the
// schema entry's address.
typedef struct { const hmi_prop_schema_t *ps; hmi_value_t value; } default_entry_t;
static default_entry_t g_defaults[1024];
static size_t g_ndefaults;

static const hmi_value_t *schema_default(const hmi_widget_t *w, const char *prop)
{
    const hmi_type_schema_t *t = hmi_kit_find(w->type);
    const hmi_prop_schema_t *ps = hmi_kit_find_prop(t, prop);
    if (!ps || !ps->default_value)
        return NULL;
    for (size_t i = 0; i < g_ndefaults; ++i)
        if (g_defaults[i].ps == ps) return &g_defaults[i].value;
    if (g_ndefaults >= sizeof g_defaults / sizeof g_defaults[0])
        return NULL;
    hmi_value_t v;
    switch (ps->kind) {
    case HMI_KIND_BOOL: v = hmi_value_bool(strcmp(ps->default_value, "true") == 0); break;
    case HMI_KIND_INT:
    case HMI_KIND_FLOAT: v = hmi_value_num(strtod(ps->default_value, NULL)); break;
    default: v = hmi_value_str(ps->default_value); break;
    }
    g_defaults[g_ndefaults] = (default_entry_t){ps, v};
    return &g_defaults[g_ndefaults++].value;
}

const hmi_value_t *hmi_widget_get(const hmi_widget_t *w, const char *prop)
{
    const hmi_value_t *v = hmi_widget_prop(w, prop);
    if (v && v->kind != HMI_V_NULL)
        return v;
    return schema_default(w, prop);
}

double hmi_widget_num(const hmi_widget_t *w, const char *prop, double def)
{
    return hmi_value_as_num(hmi_widget_get(w, prop), def);
}

bool hmi_widget_bool(const hmi_widget_t *w, const char *prop, bool def)
{
    return hmi_value_as_bool(hmi_widget_get(w, prop), def);
}

const char *hmi_widget_str(const hmi_widget_t *w, const char *prop, const char *def)
{
    return hmi_value_as_str(hmi_widget_get(w, prop), def);
}

const char *hmi_widget_asset_path(const hmi_widget_t *w, const char *relative, char *buf, size_t len)
{
    const hmi_runtime_t *rt = hmi_runtime_of(w);
    const hmi_project_t *p = hmi_runtime_project(rt);
    if (!relative) relative = "";
    if (relative[0] == '/' || !p)
        snprintf(buf, len, "A:%s", relative);
    else
        snprintf(buf, len, "A:%s/%s", p->dir, relative);
    return buf;
}

void hmi_widget_emit(hmi_widget_t *w, const char *signal, const hmi_value_t *arg)
{
    hmi_runtime_signal(w, signal, arg);
}

void hmi_widget_apply_common(hmi_widget_t *w)
{
    lv_obj_t *obj = (lv_obj_t *)w->native;
    if (!obj) return;
    lv_obj_set_pos(obj, (int32_t)w->x, (int32_t)w->y);
    lv_obj_set_size(obj, (int32_t)w->width, (int32_t)w->height);
    lv_obj_set_style_opa(obj, (lv_opa_t)(hmi_widget_num(w, "opacity", 1.0) * 255.0), 0);
    if (hmi_widget_bool(w, "visible", true))
        lv_obj_remove_flag(obj, LV_OBJ_FLAG_HIDDEN);
    else
        lv_obj_add_flag(obj, LV_OBJ_FLAG_HIDDEN);
    // Page children are laid out by absolute coordinates; nothing scrolls.
    lv_obj_remove_flag(obj, LV_OBJ_FLAG_SCROLLABLE);
}
