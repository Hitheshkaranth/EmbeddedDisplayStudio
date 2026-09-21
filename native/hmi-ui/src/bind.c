// bind.c -- the binding engine. Owner: W2.
//
// The base skeleton implements only the plain path -- a binding delivers
// its tag's value unchanged, and 0 before the tag arrives -- so the tag
// engine (W1) and the probe can be exercised end to end. W2 replaces the
// TODOs with the full rules in bind.h (scaling, format, units, thresholds,
// state levels, series, two-way state, sim tags, ShTripInfo formatting).
// The specification is designer/generators/qml_generator.py (_widget,
// _value_expression, _derived_properties) and schema/kit_schema.json.
#include "bind.h"

#include <stdlib.h>
#include <string.h>

struct hmi_bind {
    hmi_bind_apply_cb apply;
    void *user;
    hmi_page_t *page;
};

hmi_bind_t *hmi_bind_create(hmi_bind_apply_cb apply, void *user)
{
    hmi_bind_t *b = calloc(1, sizeof *b);
    b->apply = apply;
    b->user = user;
    return b;
}

void hmi_bind_destroy(hmi_bind_t *b) { free(b); }

// -- page registration: apply fallbacks -------------------------------------------
typedef struct { hmi_bind_t *b; } ctx_t;

static void apply_fallbacks(hmi_widget_t *w, void *user)
{
    ctx_t *c = user;
    for (size_t i = 0; i < w->nbindings; ++i) {
        const hmi_binding_t *bd = &w->bindings[i];
        if (!bd->tag[0]) continue;
        // TODO(W2): rule 1 fallback "" for str-typed props; rule 2 units;
        // rule 3 threshold_properties; rule 4 series; rule 6 sim tags.
        hmi_value_t zero = hmi_value_num(0);
        c->b->apply(w, bd->prop, &zero, c->b->user);
    }
}

void hmi_bind_page(hmi_bind_t *b, hmi_page_t *page)
{
    b->page = page;
    ctx_t c = {b};
    hmi_page_visit(page, apply_fallbacks, &c);
}

// -- tag delivery ------------------------------------------------------------------
typedef struct { hmi_bind_t *b; const char *tag; const hmi_value_t *value; } tag_ctx_t;

static void deliver(hmi_widget_t *w, void *user)
{
    tag_ctx_t *c = user;
    for (size_t i = 0; i < w->nbindings; ++i) {
        const hmi_binding_t *bd = &w->bindings[i];
        if (strcmp(bd->tag, c->tag) != 0) continue;
        // TODO(W2): multiplier/offset/format, thresholds -> state levels,
        // ShTripInfo row1Value formatting, series, two-way state.
        c->b->apply(w, bd->prop, c->value, c->b->user);
    }
}

void hmi_bind_on_tag(hmi_bind_t *b, const char *tag, const hmi_value_t *value)
{
    if (!b->page) return;
    tag_ctx_t c = {b, tag, value};
    hmi_page_visit(b->page, deliver, &c);
}

bool hmi_bind_parse_threshold(const char *text, char op[3], double *number)
{
    (void)text; (void)op; (void)number;
    return false;   // TODO(W2)
}

bool hmi_bind_threshold_trips(double value, const char *op, double number)
{
    (void)value; (void)op; (void)number;
    return false;   // TODO(W2)
}
