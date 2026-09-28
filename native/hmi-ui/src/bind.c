// bind.c -- the binding engine.
//
// Implements all rules from bind.h: scaling, format, units, thresholds,
// state levels, series, two-way state, sim tags, ShTripInfo formatting --
// plus CONTRACT 13.2: decimals, expression bindings and rules.

#include "bind.h"
#include "expr.h"
#include "gen/kit_schema.h"
#include "log.h"
#include "registry.h"

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
    const hmi_expr_t *expr;     // NULL for a plain tag binding
} bind_idx_entry_t;

// Last value of every tag seen, for expressions over several tags and for
// a page shown after its tags arrived.
typedef struct {
    char *tag;
    hmi_value_t value;
} tag_value_t;

struct hmi_bind {
    hmi_bind_apply_cb apply;
    void *user;
    hmi_page_t *page;
    bind_idx_entry_t *idx;
    size_t n_idx;
    size_t cap_idx;
    hmi_bind_history_cb history;
    void *history_user;
    hmi_expr_t **exprs;         // the current page's compiled expressions
    size_t n_exprs;
    tag_value_t *values;
    size_t n_values, cap_values;
};

hmi_bind_t *hmi_bind_create(hmi_bind_apply_cb apply, void *user)
{
    hmi_bind_t *b = calloc(1, sizeof *b);
    b->apply = apply;
    b->user = user;
    return b;
}

void hmi_bind_set_history(hmi_bind_t *b, hmi_bind_history_cb history, void *user)
{
    b->history = history;
    b->history_user = user;
}

// Rule 4 for a scalar tag: the chart shows the tag's recent samples, scaled
// like any other reading, as many as the widget keeps.
static void apply_series_history(hmi_bind_t *b, hmi_widget_t *w, const hmi_binding_t *bd)
{
    const hmi_value_t *mp = hmi_widget_prop(w, "maxPoints");
    double want = mp ? hmi_value_as_num(mp, 100.0) : 100.0;
    size_t count = want < 2.0 ? 2 : (size_t)want;
    hmi_value_t list = b->history(bd->tag, count, b->history_user);
    for (size_t i = 0; i < list.count; i++)
        list.items[i].n = list.items[i].n * bd->multiplier + bd->offset;
    b->apply(w, bd->prop, &list, b->user);
    hmi_value_free(&list);
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

static bool has_threshold(const char *text)
{
    char op[3]; double num;
    return hmi_bind_parse_threshold(text, op, &num);
}

static bool trips(const char *text, double value)
{
    char op[3]; double num;
    return hmi_bind_parse_threshold(text, op, &num) && hmi_bind_threshold_trips(value, op, num);
}

// ---------------------------------------------------------------------------
// Tag values
// ---------------------------------------------------------------------------

static const hmi_value_t *known_value(const hmi_bind_t *b, const char *tag)
{
    for (size_t i = 0; i < b->n_values; i++)
        if (strcmp(b->values[i].tag, tag) == 0) return &b->values[i].value;
    return NULL;
}

static void remember_value(hmi_bind_t *b, const char *tag, const hmi_value_t *value)
{
    for (size_t i = 0; i < b->n_values; i++) {
        if (strcmp(b->values[i].tag, tag) != 0) continue;
        hmi_value_free(&b->values[i].value);
        b->values[i].value = hmi_value_copy(value);
        return;
    }
    if (b->n_values == b->cap_values) {
        size_t cap = b->cap_values ? b->cap_values * 2 : 32;
        tag_value_t *grown = realloc(b->values, cap * sizeof *grown);
        if (!grown) return;
        b->values = grown;
        b->cap_values = cap;
    }
    size_t len = strlen(tag);
    char *copy = malloc(len + 1);
    if (!copy) return;
    memcpy(copy, tag, len + 1);
    b->values[b->n_values].tag = copy;
    b->values[b->n_values].value = hmi_value_copy(value);
    b->n_values++;
}

static const hmi_value_t *expr_lookup(const char *tag, void *user)
{
    return known_value(user, tag);
}

// The binding's raw reading, owned: the expression's value or the tag's;
// HMI_V_NULL when the tag was never seen (or the expression is null).
static hmi_value_t raw_reading(hmi_bind_t *b, const hmi_binding_t *bd, const hmi_expr_t *ex)
{
    if (ex) return hmi_expr_eval(ex, expr_lookup, b);
    const hmi_value_t *v = known_value(b, bd->tag);
    return v ? hmi_value_copy(v) : hmi_value_null();
}

// ---------------------------------------------------------------------------
// Delivery
// ---------------------------------------------------------------------------

// A number as text: fixed decimals when the binding asks (13.2), else the
// shortest form that reads back as a display value (no "52.31000000000001").
static void number_text(char *out, size_t len, double v, int decimals)
{
    if (decimals >= 0)
        snprintf(out, len, "%.*f", decimals > 6 ? 6 : decimals, v);
    else if (v == floor(v) && fabs(v) < 1e15)
        snprintf(out, len, "%.0f", v);
    else
        snprintf(out, len, "%.15g", v);
}

static void apply_str(hmi_bind_t *b, hmi_widget_t *w, const char *prop, const char *text)
{
    hmi_value_t v = hmi_value_str(text);
    b->apply(w, prop, &v, b->user);
    hmi_value_free(&v);
}

static void apply_num(hmi_bind_t *b, hmi_widget_t *w, const char *prop, double n)
{
    hmi_value_t v = hmi_value_num(n);
    b->apply(w, prop, &v, b->user);
    hmi_value_free(&v);
}

// 13.2 rules: per target property the first rule the reading satisfies sets
// it; a property no rule matches goes back to the widget's declared value,
// else the kit default. A bound property is the binding's, never a rule's.
static void apply_rules(hmi_bind_t *b, hmi_widget_t *w, const hmi_binding_t *bd, double reading)
{
    for (size_t i = 0; i < bd->nrules; i++) {
        const char *prop = bd->rules[i].prop;
        bool seen = false;
        for (size_t j = 0; j < i && !seen; j++)
            seen = strcmp(bd->rules[j].prop, prop) == 0;
        if (seen || find_bind_by_prop(w, prop) >= 0) continue;
        const hmi_value_t *value = NULL;
        for (size_t j = i; j < bd->nrules && !value; j++)
            if (strcmp(bd->rules[j].prop, prop) == 0 && trips(bd->rules[j].when, reading))
                value = &bd->rules[j].value;
        if (!value) value = hmi_widget_get(w, prop);
        if (value && value->kind != HMI_V_NULL)
            b->apply(w, prop, value, b->user);
    }
}

// Evaluate one binding from the current tag values and push the results.
// `initial` is the page registration: a series then starts from the
// history already held, before the tag's next sample.
static void deliver(hmi_bind_t *b, hmi_widget_t *w, const hmi_binding_t *bd,
                    const hmi_expr_t *ex, bool initial)
{
    const char *wtype = w->type;
    hmi_value_t raw = raw_reading(b, bd, ex);
    if (is_series_property(wtype, bd->prop)) {
        if (raw.kind == HMI_V_LIST)
            b->apply(w, bd->prop, &raw, b->user);
        else if (b->history && bd->tag[0] && (raw.kind == HMI_V_NUM || initial))
            apply_series_history(b, w, bd);
        hmi_value_free(&raw);
        return;
    }

    // Rule 1: the reading in display units. An unseen tag (or a null
    // expression) reads 0 before scaling, as Bus.value(tag, 0) does; a
    // non-numeric value has no number (NaN: no threshold or rule trips).
    bool unseen = raw.kind == HMI_V_NULL;
    double reading = (unseen ? 0.0 : hmi_value_as_num(&raw, NAN)) * bd->multiplier + bd->offset;
    double shown = isnan(reading) ? bd->offset : reading;
    bool scaled = bd->multiplier != 1.0 || bd->offset != 0.0;
    const hmi_type_schema_t *ts = hmi_kit_find(wtype);
    const hmi_prop_schema_t *ps = ts ? hmi_kit_find_prop(ts, bd->prop) : NULL;
    bool str_prop = ps && ps->kind == HMI_KIND_STR;

    // Rule 3: a state type derives its state/severity only from a binding
    // with thresholds (qml_generator._derived); the bound property itself is
    // delivered either way, unless the derived one is that very property.
    bool derived = false;
    int sidx = state_type_idx(wtype);
    if (sidx >= 0 && (has_threshold(bd->warning) || has_threshold(bd->critical))) {
        const char *state_prop = state_props[sidx];
        apply_str(b, w, state_prop, derive_state_level(bd->warning, bd->critical, reading, sidx));
        derived = strcmp(bd->prop, state_prop) == 0;
        if (strcmp(wtype, "ShAnnunciator") == 0) {
            hmi_value_t lit = hmi_value_bool(trips(bd->critical, reading) || trips(bd->warning, reading));
            b->apply(w, "lit", &lit, b->user);
            derived = derived || strcmp(bd->prop, "lit") == 0;
        }
    }

    if (derived) {
        // nothing more: the thresholds decide this property
    } else if (strcmp(wtype, "ShTripInfo") == 0 && strcmp(bd->prop, "value") == 0) {
        // Rule 7: the trip box shows one decimal.
        char row1[64];
        snprintf(row1, sizeof row1, "%.1f", shown);
        apply_str(b, w, "row1Value", row1);
    } else if (unseen && str_prop && strcmp(bd->prop, "value") != 0 && !scaled && !bd->format[0]) {
        // A text property bound before its tag arrives reads "", not 0.
        apply_str(b, w, bd->prop, "");
    } else if (!unseen && raw.kind != HMI_V_NUM && !scaled && !bd->format[0]) {
        // Unscaled, unformatted: a bool or a string passes through unchanged,
        // as Bus.value() hands QML the raw value.
        b->apply(w, bd->prop, &raw, b->user);
    } else if (bd->format[0]) {
        // The format string comes from the design file and has no length
        // limit; build the text with bounded writes (a too-long format is
        // truncated, never overflowed).
        char number[64], result[512];
        number_text(number, sizeof number, shown, bd->decimals);
        const char *pct = strstr(bd->format, "%1");
        if (pct)
            snprintf(result, sizeof result, "%.*s%s%s", (int)(pct - bd->format), bd->format, number, pct + 2);
        else
            snprintf(result, sizeof result, "%s", bd->format);
        apply_str(b, w, bd->prop, result);
    } else if (str_prop && bd->decimals >= 0) {
        char number[64];
        number_text(number, sizeof number, shown, bd->decimals);
        apply_str(b, w, bd->prop, number);
    } else {
        apply_num(b, w, bd->prop, shown);
    }

    apply_rules(b, w, bd, reading);
    hmi_value_free(&raw);
}

// ---------------------------------------------------------------------------
// Page registration
// ---------------------------------------------------------------------------

static void index_add(hmi_bind_t *b, const char *tag, hmi_widget_t *w, size_t i, const hmi_expr_t *ex)
{
    if (b->n_idx >= b->cap_idx) {
        size_t cap = b->cap_idx ? b->cap_idx * 2 : 16;
        bind_idx_entry_t *tmp = realloc(b->idx, cap * sizeof *tmp);
        if (!tmp) return;
        b->idx = tmp;
        b->cap_idx = cap;
    }
    b->idx[b->n_idx++] = (bind_idx_entry_t){tag, w, i, &w->bindings[i], ex};
}

// Rule 3b: the threshold marks a binding sets once, at registration.
static void apply_marks(hmi_bind_t *b, hmi_widget_t *w, const hmi_binding_t *bd)
{
    char prop_name[64];
    char top[3]; double n;
    if (bd->warning[0] && hmi_bind_parse_threshold(bd->warning, top, &n) &&
        threshold_derive_prop(w->type, "warning", top, n, prop_name, false))
        apply_num(b, w, prop_name, n);
    if (bd->critical[0] && hmi_bind_parse_threshold(bd->critical, top, &n) &&
        threshold_derive_prop(w->type, "critical", top, n, prop_name, true))
        apply_num(b, w, prop_name, n);
}

// Rule 2: the first bound unit sets the widget's unit/units, unless bound.
static void apply_unit(hmi_bind_t *b, hmi_widget_t *w, const bool *active)
{
    const hmi_type_schema_t *ts = hmi_kit_find(w->type);
    if (!ts || find_bind_by_prop(w, "unit") >= 0 || find_bind_by_prop(w, "units") >= 0) return;
    const char *uk = hmi_kit_find_prop(ts, "unit") ? "unit" : hmi_kit_find_prop(ts, "units") ? "units" : NULL;
    if (!uk) return;
    for (size_t i = 0; i < w->nbindings; i++) {
        const hmi_binding_t *bd = &w->bindings[i];
        if (!active[i] || !bd->unit[0] || is_series_property(w->type, bd->prop)) continue;
        apply_str(b, w, uk, bd->unit);
        return;
    }
}

static bool keep_expr(hmi_bind_t *b, hmi_expr_t *ex)
{
    hmi_expr_t **grown = realloc(b->exprs, (b->n_exprs + 1) * sizeof *grown);
    if (!grown) { hmi_expr_free(ex); return false; }
    b->exprs = grown;
    b->exprs[b->n_exprs++] = ex;
    return true;
}

static void register_widget(hmi_widget_t *w, void *user)
{
    hmi_bind_t *b = user;
    if (!w->nbindings) return;
    bool *active = calloc(w->nbindings, sizeof *active);
    const hmi_expr_t **exprs = calloc(w->nbindings, sizeof *exprs);
    if (!active || !exprs) { free(active); free(exprs); return; }
    for (size_t i = 0; i < w->nbindings; i++) {
        const hmi_binding_t *bd = &w->bindings[i];
        if (bd->expr && bd->expr[0]) {
            // 13.2: an expression binding depends on every tag it names; one
            // that does not compile is unbound (the Designer reports it).
            char err[200];
            hmi_expr_t *ex = hmi_expr_compile(bd->expr, err, sizeof err);
            if (!ex) {
                hmi_log(HMI_LOG_WARNING, "%s.%s: expression not bound: %s", w->id, bd->prop, err);
                continue;
            }
            if (!keep_expr(b, ex)) continue;
            exprs[i] = ex;
            active[i] = true;
            for (size_t k = 0; k < hmi_expr_tag_count(ex); k++)
                index_add(b, hmi_expr_tag(ex, k), w, i, ex);
        } else if (bd->tag[0] && !is_sim_tag(bd->tag)) {
            active[i] = true;
            index_add(b, bd->tag, w, i, NULL);
        }
    }
    for (size_t i = 0; i < w->nbindings; i++)
        if (active[i] && !is_series_property(w->type, w->bindings[i].prop))
            apply_marks(b, w, &w->bindings[i]);
    apply_unit(b, w, active);
    for (size_t i = 0; i < w->nbindings; i++)
        if (active[i]) deliver(b, w, &w->bindings[i], exprs[i], true);
    free(active);
    free(exprs);
}

static void forget_page(hmi_bind_t *b)
{
    free(b->idx);
    b->idx = NULL;
    b->n_idx = 0;
    b->cap_idx = 0;
    for (size_t i = 0; i < b->n_exprs; i++) hmi_expr_free(b->exprs[i]);
    free(b->exprs);
    b->exprs = NULL;
    b->n_exprs = 0;
    b->page = NULL;
}

void hmi_bind_page(hmi_bind_t *b, hmi_page_t *page)
{
    forget_page(b);
    b->page = page;
    if (page) hmi_page_visit(page, register_widget, b);
}

// ---------------------------------------------------------------------------
// Tag delivery
// ---------------------------------------------------------------------------

void hmi_bind_refresh_series(hmi_bind_t *b, const char *tag)
{
    if (!b->history || !b->idx || !tag) return;
    for (size_t k = 0; k < b->n_idx; k++) {
        const hmi_binding_t *bd = b->idx[k].binding;
        hmi_widget_t *w = b->idx[k].widget;
        if (!b->idx[k].expr && strcmp(b->idx[k].tag, tag) == 0 && is_series_property(w->type, bd->prop))
            apply_series_history(b, w, bd);
    }
}

void hmi_bind_on_tag(hmi_bind_t *b, const char *tag, const hmi_value_t *value)
{
    // Rule 6: sim tags are the Designer's; the panel never sees them move.
    if (!tag || !value || is_sim_tag(tag)) return;
    remember_value(b, tag, value);
    for (size_t k = 0; k < b->n_idx; k++) {
        const bind_idx_entry_t *e = &b->idx[k];
        if (strcmp(e->tag, tag) == 0) deliver(b, e->widget, e->binding, e->expr, false);
    }
}

void hmi_bind_destroy(hmi_bind_t *b)
{
    if (!b) return;
    forget_page(b);
    for (size_t i = 0; i < b->n_values; i++) {
        free(b->values[i].tag);
        hmi_value_free(&b->values[i].value);
    }
    free(b->values);
    free(b);
}
