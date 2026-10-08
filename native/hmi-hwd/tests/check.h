/* check.h -- the smallest test harness: CHECK keeps going, the exit status
 * is the number of failures. FROZEN (skeleton). */
#ifndef HWD_CHECK_H
#define HWD_CHECK_H
#include <math.h>
#include <stdio.h>
#include <string.h>

static int check_failures;
#define CHECK(cond) do { if (!(cond)) { check_failures++; \
    fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond); } } while (0)
#define CHECK_STR(a, b) do { const char *_a = (a), *_b = (b); \
    if (!_a || !_b || strcmp(_a, _b) != 0) { check_failures++; \
    fprintf(stderr, "%s:%d: \"%s\" != \"%s\"\n", __FILE__, __LINE__, _a ? _a : "(null)", _b ? _b : "(null)"); } } while (0)
#define CHECK_NEAR(a, b, eps) do { double _a = (a), _b = (b); \
    if (!(fabs(_a - _b) <= (eps))) { check_failures++; \
    fprintf(stderr, "%s:%d: %.6f != %.6f\n", __FILE__, __LINE__, _a, _b); } } while (0)
#define CHECK_DONE() do { \
        if (check_failures) fprintf(stderr, "%d check(s) failed\n", check_failures); \
        else fprintf(stderr, "all checks passed\n"); \
        return check_failures ? 1 : 0; \
    } while (0)
#endif
