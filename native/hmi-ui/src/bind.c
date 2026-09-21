// bind.c -- the binding engine. Owner: W2.
//
// Implements all rules from bind.h: scaling, format, units, thresholds,
// state levels, series, two-way state, sim tags, ShTripInfo formatting.

#include "bind.h"
#include "gen/kit_schema.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// ---------------------------------------------------------------------------
// Tables copied from qml_generator.py and kit_schema.json
// ---------------------------------------------------------------------------

static const char *state_types[] = {
    "ShValueTile", "ShStatDot", "ShDataField", "ShAnnunciator",
};
static const char *state_props[] = {
    "state", "state", "severity", "severity",
};
static const char *state_levels[][3] = {
    {"ok", "warn", "fault"},
    {"ok", "warn", "fault"},
    {"advisory", "caution", "warning"},
    {"advisory", "caution", "warning"},
};
static const size_t n_state_types = sizeof(state_types) / sizeof(state_types[0]);

// > and >= operators for threshold_properties
static const char *tprop_type[]      = { "ShGauge", "ShEngineGauge", "ShEngineBar", "ShNumDisplay" };
static const char *tprop_warn_op[]   = { ">",   ">",   ">",  ">"  };
static const char *tprop_warn_prop[] = { "thresholdWarning", "cautionHigh", "cautionValue", "warningHigh" };
static const char *tprop_crit_op[]   = { ">",   NULL,  ">",  ">"  };
static const char *tprop_crit_prop[] = { "thresholdFault", NULL, "warningValue", "faultHigh" };
static const size_t n_tprops = 4;

// < operators for threshold_properties
static const char *tprop_type_lt[]   = { NULL, NULL, NULL, "ShNumDisplay" };
static const char *tprop_lt_op[]     = { NULL, NULL, NULL, "<"  };
static const char *tprop_lt_prop[]   = { NULL, NULL, NULL, "warningLow" };
static const char *tprop_crit_lt_op[]= { NULL, NULL, NULL, "<"  };
static const char *tprop_crit_lt_prop[]= { NULL, NULL, NULL, "faultLow" };

// <= operators for threshold_properties
static const char *tprop_type_le[]   = { NULL, NULL, NULL, "ShNumDisplay" };
static const char *tprop_le_op[]     = { NULL, NULL, NULL, "<=" };
static const char *tprop_le_prop[]   = { NULL, NULL, NULL, "warningLow" };
static const char *tprop_crit_le_op[]= { NULL, NULL, NULL, "<=" };
static const char *tprop_crit_le_prop[]= { NULL, NULL, NULL, "faultLow" };

// (type, prop) -> series
static const char *series_type[]  = { "ShTrendChart", "ShAlarmTable" };
static const char *series_prop[]  = { "data", "alarms" };
static const size_t n_series = sizeof(series_type) / sizeof(series_type[0]);

// ---------------------------------------------------------------------------
// Index: tag -> bindings that reference it
// ---------------------------------------------------------------------------

typedef struct {
    const char *tag;
    hmi_widget_t *widget;
    size_t bind_idx;
    const hmi_binding_t *binding;
} bind_idx_entry_t;

struct hmi_bind {
    hmi_bind_apply_cb apply;
    void *user;
    hmi_page_t *page;
    bind_idx_entry_t *idx;
    size_t n_idx;
    size_t cap_idx;
};

hmi_bind_t *hmi_bind_create(hmi_bind_apply_cb apply, void *user)
{
    hmi_bind_t *b = calloc(1, sizeof *b);
    b->apply = apply;
    b->user = user;
    return b;
}

// ---------------------------------------------------------------------------
// Threshold parsing and evaluation
// ---------------------------------------------------------------------------

bool hmi_bind_parse_threshold(const char *text, char op[3], double *number)
{
    if (!text || !*text) return false;
    const char *p = text;
    int len = 0;
    while (p[len] && p[len] != ' ' && p[len] != '\t') {
        if (p[len] >= '0' && p[len] <= '9') break;
        if (len > 0 && p[len] == '-') break;
        len++;
    }
    if (len == 0 || len > 2) return false;
    for (int i = 0; i < len; i++) {
        char c = p[i];
        if (c != '>' && c != '<' && c != '=' && c != '!') return false;
    }
    if (len == 1 && p[0] == '=') return false;
    memcpy(op, p, len);
    op[len] = '\0';
    p += len;
    while (*p == ' ' || *p == '\t') p++;
    if (!*p) return false;
    char *endptr = NULL;
    *number = strtod(p, &endptr);
    if (endptr == p) return false;
    return true;
}

bool hmi_bind_threshold_trips(double value, const char *op, double number)
{
    if (strcmp(op, ">") == 0) return value > number;
    if (strcmp(op, ">=") == 0) return value >= number;
    if (strcmp(op, "<") == 0) return value < number;
    if (strcmp(op, "<=") == 0) return value <= number;
    if (strcmp(op, "==") == 0) return value == number;
    if (strcmp(op, "!=") == 0) return value != number;
    return false;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

static bool is_sim_tag(const char *tag)
{
    return strncmp(tag, "sim.", 4) == 0;
}

static int state_type_idx(const char *type)
{
    for (size_t i = 0; i < n_state_types; i++)
        if (strcmp(type, state_types[i]) == 0) return (int)i;
    return -1;
}

static const char *threshold_derive_prop(const char *type, const char *severity,
                                          const char *op, double value,
                                          char prop_buf[64], bool is_crit)
{
    (void)value; (void)is_crit;
    // Check >, >= operators
    for (size_t i = 0; i < n_tprops; i++) {
        if (strcmp(type, tprop_type[i]) != 0) continue;
        const char *check_op = (severity[0] == 'w') ? tprop_warn_op[i] : tprop_crit_op[i];
        const char *check_prop = (severity[0] == 'w') ? tprop_warn_prop[i] : tprop_crit_prop[i];
        if (check_op) {
            bool match = strcmp(op, check_op) == 0;
            if (!match && check_op[0] == '>' && op[0] == '>')
                match = true;
            if (match) {
                strncpy(prop_buf, check_prop, 63);
                prop_buf[63] = '\0';
                return prop_buf;
            }
        }
    }
    // Check < operators (treat < and <= as equivalent)
    for (size_t i = 0; i < n_tprops; i++) {
        if (!tprop_type_lt[i]) continue;
        if (strcmp(type, tprop_type_lt[i]) != 0) continue;
        const char *check_op = (severity[0] == 'w') ? tprop_lt_op[i] : tprop_crit_lt_op[i];
        const char *check_prop = (severity[0] == 'w') ? tprop_lt_prop[i] : tprop_crit_lt_prop[i];
        if (check_op) {
            bool match = strcmp(op, check_op) == 0;
            if (!match && check_op[0] == '<' && op[0] == '<')
                match = true;
            if (match) {
                strncpy(prop_buf, check_prop, 63);
                prop_buf[63] = '\0';
                return prop_buf;
            }
        }
    }
    // Check <= operators
    for (size_t i = 0; i < n_tprops; i++) {
        if (!tprop_type_le[i]) continue;
        if (strcmp(type, tprop_type_le[i]) != 0) continue;
        const char *check_op = (severity[0] == 'w') ? tprop_le_op[i] : tprop_crit_le_op[i];
        const char *check_prop = (severity[0] == 'w') ? tprop_le_prop[i] : tprop_crit_le_prop[i];
        if (check_op && strcmp(op, check_op) == 0) {
            strncpy(prop_buf, check_prop, 63);
            prop_buf[63] = '\0';
            return prop_buf;
        }
    }
    return NULL;
}

static bool is_series_property(const char *type, const char *prop)
{
    for (size_t i = 0; i < n_series; i++)
        if (strcmp(type, series_type[i]) == 0 && strcmp(prop, series_prop[i]) == 0)
            return true;
    return false;
}

static int find_bind_by_prop(hmi_widget_t *w, const char *prop)
{
    for (size_t i = 0; i < w->nbindings; i++)
        if (strcmp(w->bindings[i].prop, prop) == 0) return (int)i;
    return -1;
}

static const char *derive_state_level(const char *warn_text, const char *crit_text,
                                       double value, int state_idx)
{
    if (crit_text) {
        char op[3]; double num;
        if (hmi_bind_parse_threshold(crit_text, op, &num) &&
            hmi_bind_threshold_trips(value, op, num))
            return state_levels[state_idx][2];
    }
    if (warn_text) {
        char op[3]; double num;
        if (hmi_bind_parse_threshold(warn_text, op, &num) &&
            hmi_bind_threshold_trips(value, op, num))
            return state_levels[state_idx][1];
    }
    return state_levels[state_idx][0];
}

// ---------------------------------------------------------------------------
// Page visitor context & callbacks
// ---------------------------------------------------------------------------

typedef struct {
    hmi_bind_t *bind;
    const char *tag;
    const hmi_value_t *value;
    int phase;
} page_ctx_t;

static void build_index(hmi_widget_t *w, void *user)
{
    page_ctx_t *c = user;
    for (size_t i = 0; i < w->nbindings; i++) {
        const hmi_binding_t *bd = &w->bindings[i];
        if (!bd->tag[0]) continue;
        if (is_sim_tag(bd->tag)) continue;
        if (c->bind->n_idx >= c->bind->cap_idx) {
            c->bind->cap_idx = c->bind->cap_idx ? c->bind->cap_idx * 2 : 16;
            bind_idx_entry_t *tmp = realloc(c->bind->idx, c->bind->cap_idx * sizeof(bind_idx_entry_t));
            if (!tmp) return;
            c->bind->idx = tmp;
        }
        c->bind->idx[c->bind->n_idx].tag = bd->tag;
        c->bind->idx[c->bind->n_idx].widget = w;
        c->bind->idx[c->bind->n_idx].bind_idx = i;
        c->bind->idx[c->bind->n_idx].binding = bd;
        c->bind->n_idx++;
    }
}

static void apply_derived(hmi_widget_t *w, void *user)
{
    page_ctx_t *c = user;
    hmi_bind_t *b = c->bind;
    const char *wtype = w->type;
    int sidx = state_type_idx(wtype);

    if (c->phase == 1) {
        if (sidx >= 0) {
            const char *state_prop_name = state_props[sidx];
            for (size_t i = 0; i < w->nbindings; i++) {
                const hmi_binding_t *bd = &w->bindings[i];
                if (!bd->tag[0]) continue;
                if (is_sim_tag(bd->tag)) continue;
                const char *level = derive_state_level(bd->warning, bd->critical, 0.0, sidx);
                hmi_value_t lv = hmi_value_str(level);
                b->apply(w, state_prop_name, &lv, b->user);
                hmi_value_free(&lv);
                break;
            }
        }
        for (size_t i = 0; i < w->nbindings; i++) {
            const hmi_binding_t *bd = &w->bindings[i];
            if (!bd->tag[0]) continue;
            if (is_sim_tag(bd->tag)) continue;
            if (sidx >= 0) continue;
            hmi_value_t zero = hmi_value_num(0.0);
            b->apply(w, bd->prop, &zero, b->user);
            hmi_value_free(&zero);
        }
        for (size_t i = 0; i < w->nbindings; i++) {
            const hmi_binding_t *bd = &w->bindings[i];
            if (!bd->tag[0]) continue;
            if (is_sim_tag(bd->tag)) continue;
            char prop_name[64];
            if (bd->warning[0]) {
                char top[3]; double n;
                if (hmi_bind_parse_threshold(bd->warning, top, &n) &&
                    threshold_derive_prop(wtype, "warning", top, n, prop_name, false)) {
                    hmi_value_t v = hmi_value_num(n);
                    b->apply(w, prop_name, &v, b->user);
                    hmi_value_free(&v);
                }
            }
            if (bd->critical[0]) {
                char top[3]; double n;
                if (hmi_bind_parse_threshold(bd->critical, top, &n) &&
                    threshold_derive_prop(wtype, "critical", top, n, prop_name, true)) {
                    hmi_value_t v = hmi_value_num(n);
                    b->apply(w, prop_name, &v, b->user);
                    hmi_value_free(&v);
                }
            }
        }
    }
    if (c->phase == 2) {
        for (size_t i = 0; i < w->nbindings; i++) {
            const hmi_binding_t *bd = &w->bindings[i];
            if (!bd->tag[0]) continue;
            if (is_sim_tag(bd->tag)) continue;
            if (!bd->unit[0]) continue;
            const hmi_type_schema_t *ts = hmi_kit_find(wtype);
            if (ts) {
                if ((hmi_kit_find_prop(ts, "unit") || hmi_kit_find_prop(ts, "units")) &&
                    find_bind_by_prop(w, "unit") < 0 &&
                    find_bind_by_prop(w, "units") < 0) {
                    const char *uk = hmi_kit_find_prop(ts, "unit") ? "unit" : "units";
                    hmi_value_t uv = hmi_value_str(bd->unit);
                    b->apply(w, uk, &uv, b->user);
                    hmi_value_free(&uv);
                    break;
                }
            }
        }
    }
    if (c->phase == 3) {
        if (strcmp(wtype, "ShTripInfo") == 0) {
            for (size_t i = 0; i < w->nbindings; i++) {
                const hmi_binding_t *bd = &w->bindings[i];
                if (strcmp(bd->prop, "value") == 0 && bd->tag[0] && !is_sim_tag(bd->tag)) {
                    hmi_value_t v = hmi_value_num(0.0 * bd->multiplier + bd->offset);
                    b->apply(w, "row1Value", &v, b->user);
                    hmi_value_free(&v);
                    break;
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Page registration
// ---------------------------------------------------------------------------

void hmi_bind_page(hmi_bind_t *b, hmi_page_t *page)
{
    free(b->idx);
    b->idx = NULL;
    b->n_idx = 0;
    b->cap_idx = 0;
    b->page = page;

    page_ctx_t c = {b, NULL, NULL, 0};
    hmi_page_visit(page, build_index, &c);

    if (b->n_idx == 0) {
        b->idx = NULL;
        return;
    }

    c.phase = 1;
    hmi_page_visit(page, apply_derived, &c);
    c.phase = 2;
    hmi_page_visit(page, apply_derived, &c);
    c.phase = 3;
    hmi_page_visit(page, apply_derived, &c);
}

// ---------------------------------------------------------------------------
// Tag delivery
// ---------------------------------------------------------------------------

static void apply_tag_value(hmi_widget_t *widget, void *user)
{
    page_ctx_t *c = user;
    hmi_bind_t *b = c->bind;
    (void)widget;
    if (b->n_idx == 0) return;

    for (size_t k = 0; k < b->n_idx; k++) {
        if (strcmp(b->idx[k].tag, c->tag) != 0) continue;
        hmi_widget_t *w2 = b->idx[k].widget;
        const hmi_binding_t *bd = b->idx[k].binding;
        const char *wtype = w2->type;
        double display = hmi_value_as_num(c->value, 0.0) * bd->multiplier + bd->offset;
        if (is_sim_tag(c->tag)) continue;
        if (is_series_property(wtype, bd->prop)) {
            if (c->value->kind == HMI_V_LIST) {
                b->apply(w2, bd->prop, c->value, b->user);
            }
            continue;
        }
        int sidx = state_type_idx(wtype);
        if (sidx >= 0) {
            const char *level = derive_state_level(bd->warning, bd->critical, display, sidx);
            hmi_value_t lv = hmi_value_str(level);
            b->apply(w2, state_props[sidx], &lv, b->user);
            hmi_value_free(&lv);
            continue;
        }
        if (bd->format[0]) {
            char formatted[256];
            if (display == floor(display) && fabs(display) < 1e15) {
                snprintf(formatted, sizeof formatted, "%.0f", display);
            } else {
                snprintf(formatted, sizeof formatted, "%g", display);
            }
            char result[512] = "";
            const char *fmt = bd->format;
            const char *pct = strstr(fmt, "%1");
            if (pct) {
                size_t before = (size_t)(pct - fmt);
                if (before > sizeof(result) - 1) before = sizeof(result) - 1;
                strncpy(result, fmt, before);
                result[before] = '\0';
                strcat(result, formatted);
                strcat(result, pct + 2);
            } else {
                strncpy(result, fmt, sizeof(result) - 1);
            }
            hmi_value_t fv = hmi_value_str(result);
            b->apply(w2, bd->prop, &fv, b->user);
            hmi_value_free(&fv);
        } else {
            if (strcmp(wtype, "ShTripInfo") == 0 && strcmp(bd->prop, "value") == 0) {
                char row1[64];
                snprintf(row1, sizeof row1, "%.1f", display);
                hmi_value_t sv = hmi_value_str(row1);
                b->apply(w2, "row1Value", &sv, b->user);
                hmi_value_free(&sv);
            } else {
                if (bd->multiplier == 1.0 && bd->offset == 0.0 && !bd->format[0]) {
                    const hmi_type_schema_t *ts = hmi_kit_find(wtype);
                    if (ts) {
                        const hmi_prop_schema_t *ps = hmi_kit_find_prop(ts, bd->prop);
                        if (ps && ps->kind == HMI_KIND_STR) {
                            b->apply(w2, bd->prop, c->value, b->user);
                            continue;
                        }
                    }
                }
                hmi_value_t nv = hmi_value_num(display);
                b->apply(w2, bd->prop, &nv, b->user);
                hmi_value_free(&nv);
            }
        }
    }
}

void hmi_bind_on_tag(hmi_bind_t *b, const char *tag, const hmi_value_t *value)
{
    if (!b->idx) return;
    page_ctx_t c = {b, tag, value, 0};
    hmi_page_visit(b->page, apply_tag_value, &c);
}

void hmi_bind_destroy(hmi_bind_t *b)
{
    free(b->idx);
    free(b);
}