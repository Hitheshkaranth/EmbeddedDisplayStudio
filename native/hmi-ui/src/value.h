// value.h -- the runtime's variant: what a property, a binding result or a
// tag value is. Small, copyable by hmi_value_copy, freed by hmi_value_free.
//
// FROZEN (Phase 3 contract): every worker reads and writes hmi_value_t through
// these calls; nobody adds fields.
#pragma once

#include <stdbool.h>
#include <stddef.h>

typedef enum {
    HMI_V_NULL,     // JSON null / tag not yet seen
    HMI_V_BOOL,
    HMI_V_NUM,      // every JSON number, ints included
    HMI_V_STR,
    HMI_V_LIST,     // items[count], each an hmi_value_t
} hmi_value_kind_t;

typedef struct hmi_value {
    hmi_value_kind_t kind;
    bool b;
    double n;
    char *s;                    // owned; NULL unless HMI_V_STR
    struct hmi_value *items;    // owned; NULL unless HMI_V_LIST
    size_t count;
} hmi_value_t;

hmi_value_t hmi_value_null(void);
hmi_value_t hmi_value_bool(bool b);
hmi_value_t hmi_value_num(double n);
hmi_value_t hmi_value_str(const char *s);        // copies
hmi_value_t hmi_value_copy(const hmi_value_t *v);
void hmi_value_free(hmi_value_t *v);             // safe on NULL/HMI_V_NULL; leaves it HMI_V_NULL

// Coercions with the loader's semantics: a string "12.5" reads as 12.5, a
// bool as 0/1, null/list as `def`. Strings are the owned pointer or `def`.
double hmi_value_as_num(const hmi_value_t *v, double def);
bool hmi_value_as_bool(const hmi_value_t *v, bool def);
const char *hmi_value_as_str(const hmi_value_t *v, const char *def);
bool hmi_value_equal(const hmi_value_t *a, const hmi_value_t *b);

// Text form for logs: "3.2", "true", "\"HOT\"", "null", "[3 items]". Static
// buffer, not re-entrant.
const char *hmi_value_debug(const hmi_value_t *v);

// cJSON bridge (used by the model loader and the tag engine).
struct cJSON;
hmi_value_t hmi_value_from_json(const struct cJSON *j);
struct cJSON *hmi_value_to_json(const hmi_value_t *v);  // caller owns
