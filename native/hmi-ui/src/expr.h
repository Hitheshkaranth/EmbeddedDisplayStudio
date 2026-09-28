// expr.h -- the CONTRACT 13.2 expression language. FROZEN (wave 1, W2).
//
// The grammar, value rules, functions and limits are CONTRACT 13.2, word for
// word; designer/model/expr.py implements the same language and
// tests/fixtures/expr_cases.json is the shared acceptance table (both sides
// must give the same result, or the same "error", for every row).
#pragma once

#include <stddef.h>

#include "value.h"

typedef struct hmi_expr hmi_expr_t;

// Compile `text`. NULL on a compile error, with a one-line reason in err
// (e.g. "unknown function 'sqrt' at 3", "too many tags", "unexpected ')' at 7").
hmi_expr_t *hmi_expr_compile(const char *text, char *err, size_t errlen);
void hmi_expr_free(hmi_expr_t *e);

// The distinct tags the expression names, in first-appearance order.
size_t hmi_expr_tag_count(const hmi_expr_t *e);
const char *hmi_expr_tag(const hmi_expr_t *e, size_t i);

// Current value of a tag, or NULL when never seen (then it reads as null).
typedef const hmi_value_t *(*hmi_expr_lookup_cb)(const char *tag, void *user);

// Evaluate. The result is owned by the caller (hmi_value_free); HMI_V_NULL
// for null. Never fails once compiled.
hmi_value_t hmi_expr_eval(const hmi_expr_t *e, hmi_expr_lookup_cb lookup, void *user);
