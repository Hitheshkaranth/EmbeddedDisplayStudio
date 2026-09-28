// expr.c -- see expr.h (CONTRACT 13.2). STUB: wave 1 W2 implements.
#include "expr.h"

#include <stdio.h>

hmi_expr_t *hmi_expr_compile(const char *text, char *err, size_t errlen)
{
    (void)text;
    if (err && errlen) snprintf(err, errlen, "expressions not implemented");
    return NULL;
}

void hmi_expr_free(hmi_expr_t *e) { (void)e; }

size_t hmi_expr_tag_count(const hmi_expr_t *e) { (void)e; return 0; }

const char *hmi_expr_tag(const hmi_expr_t *e, size_t i) { (void)e; (void)i; return ""; }

hmi_value_t hmi_expr_eval(const hmi_expr_t *e, hmi_expr_lookup_cb lookup, void *user)
{
    (void)e; (void)lookup; (void)user;
    return hmi_value_null();
}
