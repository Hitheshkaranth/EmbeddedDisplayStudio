// tests/check.h -- the smallest useful test harness: CHECK(cond), CHECK_EQ_*,
// a summary line, and a non-zero exit when anything failed or nothing ran.
#pragma once

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int g_checks, g_failures;

#define CHECK(cond) do { ++g_checks; if (!(cond)) { ++g_failures; \
    fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); } } while (0)
#define CHECK_EQ_STR(a, b) do { ++g_checks; const char *_a = (a), *_b = (b); \
    if (!_a || !_b || strcmp(_a, _b) != 0) { ++g_failures; \
    fprintf(stderr, "FAIL %s:%d: %s == %s  (\"%s\" vs \"%s\")\n", __FILE__, __LINE__, #a, #b, _a ? _a : "(null)", _b ? _b : "(null)"); } } while (0)
#define CHECK_NEAR(a, b, eps) do { ++g_checks; double _a = (a), _b = (b); \
    if (fabs(_a - _b) > (eps)) { ++g_failures; \
    fprintf(stderr, "FAIL %s:%d: %s ~= %s  (%g vs %g)\n", __FILE__, __LINE__, #a, #b, _a, _b); } } while (0)

static int check_summary(const char *name)
{
    fprintf(stderr, "%s: %d checks, %d failed\n", name, g_checks, g_failures);
    if (g_checks == 0) { fprintf(stderr, "%s: no checks ran\n", name); return 1; }
    return g_failures ? 1 : 0;
}
