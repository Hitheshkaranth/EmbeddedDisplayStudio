// tests/test_expr.c -- CONTRACT 13.2 expressions against the shared table
// tests/fixtures/expr_cases.json (the Python side runs the same rows).
// Wave 1 gate for W2 (FROZEN).
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "check.h"
#include "expr.h"

static const cJSON *g_values;
static hmi_value_t g_hold[64];
static size_t g_nhold;

static const hmi_value_t *lookup(const char *tag, void *user)
{
    (void)user;
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(g_values, tag);
    if (!v || g_nhold >= 64) return NULL;
    g_hold[g_nhold] = hmi_value_from_json(v);
    return &g_hold[g_nhold++];
}

static char *slurp(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = malloc((size_t)n + 1);
    fread(buf, 1, (size_t)n, f);
    buf[n] = 0;
    fclose(f);
    return buf;
}

static bool same(const hmi_value_t *got, const cJSON *want)
{
    if (cJSON_IsNull(want)) return got->kind == HMI_V_NULL;
    if (cJSON_IsBool(want)) return got->kind == HMI_V_BOOL && got->b == (bool)cJSON_IsTrue(want);
    if (cJSON_IsNumber(want)) return got->kind == HMI_V_NUM && fabs(got->n - want->valuedouble) < 1e-9;
    if (cJSON_IsString(want)) return got->kind == HMI_V_STR && strcmp(got->s, want->valuestring) == 0;
    return false;
}

int main(void)
{
    char *text = slurp(HMI_REPO_ROOT "/tests/fixtures/expr_cases.json");
    CHECK(text != NULL);
    cJSON *rows = text ? cJSON_Parse(text) : NULL;
    CHECK(cJSON_IsArray(rows));
    int n = 0;
    const cJSON *row;
    cJSON_ArrayForEach(row, rows) {
        const char *src = cJSON_GetStringValue(cJSON_GetObjectItem(row, "expr"));
        g_values = cJSON_GetObjectItem(row, "values");
        bool want_error = cJSON_IsTrue(cJSON_GetObjectItem(row, "error"));
        char err[200] = "";
        hmi_expr_t *e = hmi_expr_compile(src, err, sizeof err);
        ++n;
        if (want_error) {
            CHECK(e == NULL);
            if (e) fprintf(stderr, "  row %d: expected a compile error: %.80s\n", n, src);
            else CHECK(err[0] != '\0');
            hmi_expr_free(e);
            continue;
        }
        CHECK(e != NULL);
        if (!e) { fprintf(stderr, "  row %d: %.80s -> compile error %s\n", n, src, err); continue; }
        // Tags: every key of "values" the expression names appears once.
        for (size_t i = 0; i < hmi_expr_tag_count(e); i++)
            for (size_t k = i + 1; k < hmi_expr_tag_count(e); k++)
                CHECK(strcmp(hmi_expr_tag(e, i), hmi_expr_tag(e, k)) != 0);
        g_nhold = 0;
        hmi_value_t got = hmi_expr_eval(e, lookup, NULL);
        const cJSON *want = cJSON_GetObjectItem(row, "expect");
        bool ok = same(&got, want);
        CHECK(ok);
        if (!ok) {
            char *w = cJSON_PrintUnformatted(want);
            fprintf(stderr, "  row %d: %.80s -> %s, want %s\n", n, src, hmi_value_debug(&got), w);
            free(w);
        }
        hmi_value_free(&got);
        for (size_t i = 0; i < g_nhold; i++) hmi_value_free(&g_hold[i]);
        hmi_expr_free(e);
    }
    CHECK(n > 90);

    // Tag order: first appearance.
    char err[200];
    hmi_expr_t *e = hmi_expr_compile("b.x + a.y * b.x - c.z", err, sizeof err);
    CHECK(e && hmi_expr_tag_count(e) == 3);
    if (e && hmi_expr_tag_count(e) == 3) {
        CHECK_EQ_STR(hmi_expr_tag(e, 0), "b.x");
        CHECK_EQ_STR(hmi_expr_tag(e, 1), "a.y");
        CHECK_EQ_STR(hmi_expr_tag(e, 2), "c.z");
    }
    hmi_expr_free(e);
    cJSON_Delete(rows);
    free(text);
    return check_summary("test_expr");
}
