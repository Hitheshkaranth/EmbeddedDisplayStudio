// expr.c -- see expr.h (CONTRACT 13.2).
//
// A recursive-descent parser + evaluator. Limits: 512 characters, 16 distinct
// tags, nesting depth 32 (parentheses, function calls, unary operators).
// A null or string arithmetic operand, division/modulo by zero, a non-finite
// result, and a non-finite number all yield null (never a compile error).

#include "expr.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_LENGTH  512
#define MAX_TAGS    16
#define MAX_DEPTH   32

typedef enum {
    N_NUM, N_BOOL, N_STR, N_TAG, N_UNARY, N_BIN, N_CMP, N_AND, N_OR,
    N_TERN, N_CALL
} nodekind_t;

typedef struct node {
    nodekind_t kind;
    // N_NUM: double d
    // N_BOOL: bool b
    // N_STR: char *s (owned), size_t slen
    // N_TAG: char *s (owned to end of tag), size_t slen
    // N_UNARY: struct node *a
    // N_BIN: struct node *a, *b; enum {OP_ADD,OP_SUB,OP_MUL,OP_DIV,OP_MOD,OP_POW} op
    // N_CMP: struct node *a, *b; char op (== != < <= > >=)
    // N_AND / N_OR: struct node *a, *b
    // N_TERN: struct node *a (cond), *b (then), *c (else)
    // N_CALL: char *fname; struct node **args; size_t nargs
    double d;
    bool b;
    char *s;
    size_t slen;
    struct node *a, *b, *c;
    int op;
    char cop;
    const char *fname;
    struct node **args;
    size_t nargs;
} node_t;

typedef struct {
    char *tags[MAX_TAGS];
    size_t ntags;
} tagset_t;

typedef struct {
    const char *p, *end;
    node_t *root;
    tagset_t *tags;
    char err[80];
    int depth;
} parser_t;

// ---------------------------------------------------------------------------
// small helpers
// ---------------------------------------------------------------------------

static const char *skip_ws(const char *p)
{
    while (*p == ' ' || *p == '\t') p++;
    return p;
}

static bool is_digit(int c) { return c >= '0' && c <= '9'; }

static bool is_ident_start(int c) { return c >= 'a' && c <= 'z'; }

static bool is_ident_char(int c) { return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_'; }

static bool is_tag_char(int c) { return is_ident_char(c); }   // segment chars except the leading one rule below

static node_t *node_new(void)
{
    return calloc(1, sizeof(node_t));
}

static void free_node(node_t *n)
{
    if (!n) return;
    if (n->kind == N_STR || n->kind == N_TAG) free(n->s);
    if (n->kind == N_CALL) {
        if (n->args) {
            for (size_t i = 0; i < n->nargs; i++) free_node(n->args[i]);
            free(n->args);
        }
    }
    free_node(n->a);
    free_node(n->b);
    free_node(n->c);
    free(n);
}

static void tag_add(tagset_t *ts, const char *name, size_t len)
{
    for (size_t i = 0; i < ts->ntags; i++)
        if (strncpy(ts->tags[i], name, len + 1) && len == strlen(ts->tags[i]))
            return;
    if (ts->ntags >= MAX_TAGS) return;   // overflow: caller checks via error
    char *dup = malloc(len + 1);
    memcpy(dup, name, len);
    dup[len] = '\0';
    ts->tags[ts->ntags++] = dup;
}

// ---------------------------------------------------------------------------
// parser
// ---------------------------------------------------------------------------

static bool compile_error(parser_t *ps, const char *msg, int *tags_seen)
{
    if (!ps->err[0]) snprintf(ps->err, sizeof ps->err, "%s at %ld", msg, (long)(ps->p - ps->start));
    return false;
}

// parse a dotted tag: [a-z][a-z0-9]*(\.[a-z0-9_]+)+  (CONTRACT 2.5 / 13.2)
static node_t *parse_tag(parser_t *ps)
{
    const char *start = ps->p;
    if (!is_ident_start(*ps->p)) return NULL;
    ps->p++;
    while (is_ident_char(*ps->p)) ps->p++;
    // must contain at least one dot
    if (memchr(start, '.', (size_t)(ps->p - start)) == NULL) return NULL;
    while (*ps->p == '.') {
        ps->p++;
        if (!is_ident_char(*ps->p)) return NULL;
        while (is_ident_char(*ps->p)) ps->p++;
    }
    size_t len = (size_t)(ps->p - start);
    // the segment after the final dot may not end in '_'
    char after = ps->p[-1];
    if (after == '_') return NULL;
    node_t *n = node_new();
    n->kind = N_TAG;
    n->s = malloc(len + 1);
    memcpy(n->s, start, len);
    n->s[len] = '\0';
    n->slen = len;
    return n;
}

static node_t *parse_string(parser_t *ps)
{
    if (*ps->p != '"') return NULL;
    ps->p++;
    const char *start = ps->p;
    while (*ps->p && *ps->p != '"') {
        if (*ps->p == '\\') ps->p++;
        if (*ps->p == '"') break;
        ps->p++;
    }
    if (*ps->p != '"') return NULL;   // unterminated
    size_t len = (size_t)(ps->p - start);
    node_t *n = node_new();
    n->kind = N_STR;
    n->s = malloc(len + 1);
    memcpy(n->s, start, len);
    n->s[len] = '\0';
    n->slen = len;
    ps->p++;   // closing quote
    return n;
}

static node_t *parse_number(parser_t *ps)
{
    const char *start = ps->p;
    while (is_digit(*ps->p)) ps->p++;
    if (*ps->p == '.') {
        ps->p++;
        while (is_digit(*ps->p)) ps->p++;
    }
    node_t *n = node_new();
    n->kind = N_NUM;
    n->d = strtod(start, NULL);
    return n;
}

static const char *FUNCTIONS[] = {"abs", "floor", "ceil", "round", "min", "max", "clamp"};
static int FUNC_MIN[] = {1, 1, 1, 1, 2, 2, 3};
static int FUNC_MAX[] = {1, 1, 1, 2, -1, -1, 3};

// expr := ... (already in caller's precedence). We parse a full expression
// body here because functions take expr-lists and so do our binary ops.
static bool parse_binary(parser_t *ps, int maxprec, node_t **out);

static bool parse_call(parser_t *ps, node_t **out)
{
    const char *start = ps->p;
    while (is_ident_char(*ps->p)) ps->p++;
    size_t len = (size_t)(ps->p - start);
    for (size_t i = 0; i < sizeof(FUNCTIONS) / sizeof(FUNCTIONS[0]); i++) {
        if (len != strlen(FUNCTIONS[i])) continue;
        if (memcmp(start, FUNCTIONS[i], len) != 0) continue;
        // expect '('
        const char *paren = skip_ws(ps->p);
        if (*paren != '(') return compile_error(ps, "unknown function", ps->tags);
        ps->p = paren + 1;
        node_t *n = node_new();
        n->kind = N_CALL;
        n->fname = FUNCTIONS[i];
        size_t cap = 4, nargs = 0;
        node_t **args = malloc(cap * sizeof(node_t *));
        for (;;) {
            parser_t inner = {0};
            inner.start = ps->p; inner.end = ps->p; inner.tags = ps->tags;
            node_t *arg;
            if (!parse_binary(&inner, 4, &arg)) {
                // error already logged on the inner parser; discard it
                node_free(n); free(args);
                ps->p = inner.p;
                return false;
            }
            if (nargs >= cap) { cap *= 2; args = realloc(args, cap * sizeof(node_t *)); }
            args[nargs++] = arg;
            ps->p = inner.p;
            const char *q = skip_ws(ps->p);
            if (*q == ',') { ps->p = q + 1; continue; }
            if (*q == ')') { ps->p = q + 1; break; }
            compile_error(ps, "expected ',' or ')'", ps->tags);
            node_free(n); free(args);
            return false;
        }
        int min = FUNC_MIN[i], max = FUNC_MAX[i];
        if (nargs < (size_t)min || (max >= 0 && nargs > (size_t)max)) {
            compile_error(ps, "wrong number of arguments", ps->tags);
            node_free(n); free(args);
            return false;
        }
        n->args = args; n->nargs = nargs;
        *out = n;
        return true;
    }
    return compile_error(ps, "bad token", ps->tags);
}

static bool parse_primary(parser_t *ps, node_t **out)
{
    if (ps->depth >= MAX_DEPTH) return compile_error(ps, "too nested", ps->tags);
    const char *p = skip_ws(ps->p);
    ps->p = p;

    if (*p == '-') {
        if (!is_digit(p[1]) && p[1] != '.') {
            ps->p = p + 1;
            node_t *n = node_new();
            n->kind = N_UNARY;
            n->op = 1;   // negate
            if (!parse_primary(ps, &n->a)) { node_free(n); return false; }
            *out = n;
            return true;
        }
    }
    if (*p == '!') {
        ps->p = p + 1;
        ps->depth++;
        node_t *n = node_new();
        n->kind = N_UNARY;
        n->op = 0;   // logical not
        if (!parse_primary(ps, &n->a)) { ps->depth--; node_free(n); return false; }
        ps->depth--;
        *out = n;
        return true;
    }

    if (*p == '(') {
        ps->p = p + 1;
        ps->depth++;
        node_t *inner;
        if (!parse_binary(ps, 4, &inner)) { ps->depth--; return false; }
        const char *q = skip_ws(ps->p);
        if (*q != ')') { ps->depth--; return compile_error(ps, "expected ')'", ps->tags); }
        ps->p = q + 1;
        ps->depth--;
        *out = inner;
        return true;
    }

    if (*p == '"') {
        node_t *n = parse_string(ps);
        if (!n) return compile_error(ps, "bad string", ps->tags);
        *out = n;
        return true;
    }

    // true / false / tag
    if (is_ident_start(*p)) {
        const char *start = p;
        while (is_ident_char(*p)) p++;
        size_t len = (size_t)(p - start);
        if (len == 4 && memcmp(start, "true", 4) == 0) {
            node_t *n = node_new();
            n->kind = N_BOOL; n->b = true;
            ps->p = p;
            *out = n;
            return true;
        }
        if (len == 5 && memcmp(start, "false", 5) == 0) {
            node_t *n = node_new();
            n->kind = N_BOOL; n->b = false;
            ps->p = p;
            *out = n;
            return true;
        }
        // tag
        ps->p = start;
        node_t *n = parse_tag(ps);
        if (!n) return compile_error(ps, "bad tag", ps->tags);
        if (ps->tags->ntags > MAX_TAGS) { node_free(n); return compile_error(ps, "too many tags", ps->tags); }
        tag_add(ps->tags, n->s, n->slen);
        *out = n;
        return true;
    }

    if (is_digit(*p) || (*p == '.' && is_digit(p[1]))) {
        node_t *n = parse_number(ps);
        if (!isfinite(n->d)) return compile_error(ps, "bad number", ps->tags);
        *out = n;
        return true;
    }

    return compile_error(ps, "unexpected character", ps->tags);
}

// Precedence climbing: * / % bind tightest, then + -, then comparisons, then
// &&, then ||. (Ternary handled by the caller, parse_expr.)
static bool parse_binary(parser_t *ps, int maxprec, node_t **out)
{
    node_t *left;
    if (!parse_primary(ps, &left)) return false;
    for (;;) {
        const char *p = skip_ws(ps->p);
        ps->p = p;
        if (*p == '*') { ps->p = p + 1; if (maxprec < 3) break; node_t *n = node_new(); n->kind = N_BIN; n->op = 0; n->a = left; if (!parse_binary(ps, 3, &n->b)) { node_free(n); return false; } left = n; continue; }
        if (*p == '/') { ps->p = p + 1; if (maxprec < 3) break; node_t *n = node_new(); n->kind = N_BIN; n->op = 1; n->a = left; if (!parse_binary(ps, 3, &n->b)) { node_free(n); return false; } left = n; continue; }
        if (*p == '%') { ps->p = p + 1; if (maxprec < 3) break; node_t *n = node_new(); n->kind = N_BIN; n->op = 2; n->a = left; if (!parse_binary(ps, 3, &n->b)) { node_free(n); return false; } left = n; continue; }
        if (*p == '+') { ps->p = p + 1; if (maxprec < 2) break; node_t *n = node_new(); n->kind = N_BIN; n->op = 3; n->a = left; if (!parse_binary(ps, 2, &n->b)) { node_free(n); return false; } left = n; continue; }
        if (*p == '-') { ps->p = p + 1; if (maxprec < 2) break; node_t *n = node_new(); n->kind = N_BIN; n->op = 4; n->a = left; if (!parse_binary(ps, 2, &n->b)) { node_free(n); return false; } left = n; continue; }
        if (*p == '=' && p[1] == '=') { ps->p = p + 2; if (maxprec < 1) break; node_t *n = node_new(); n->kind = N_CMP; n->cop = '='; n->a = left; if (!parse_binary(ps, 1, &n->b)) { node_free(n); return false; } left = n; continue; }
        if (*p == '!' && p[1] == '=') { ps->p = p + 2; if (maxprec < 1) break; node_t *n = node_new(); n->kind = N_CMP; n->cop = '!'; n->a = left; if (!parse_binary(ps, 1, &n->b)) { node_free(n); return false; } left = n; continue; }
        if (*p == '<') { ps->p = p + 1; if (maxprec < 1) break; node_t *n = node_new(); n->kind = N_CMP; n->cop = '<'; n->a = left; if (!parse_binary(ps, 1, &n->b)) { node_free(n); return false; } left = n; continue; }
        if (*p == '>') { ps->p = p + 1; if (maxprec < 1) break; node_t *n = node_new(); n->kind = N_CMP; n->cop = '>'; n->a = left; if (!parse_binary(ps, 1, &n->b)) { node_free(n); return false; } left = n; continue; }
        if (*p == '<' && p[1] == '=') { ps->p = p + 2; if (maxprec < 1) break; node_t *n = node_new(); n->kind = N_CMP; n->cop = '<'; n->a = left; if (!parse_binary(ps, 1, &n->b)) { node_free(n); return false; } left = n; continue; }
        if (*p == '>' && p[1] == '=') { ps->p = p + 2; if (maxprec < 1) break; node_t *n = node_new(); n->kind = N_CMP; n->cop = '>'; n->a = left; if (!parse_binary(ps, 1, &n->b)) { node_free(n); return false; } left = n; continue; }
        if (*p == '&' && p[1] == '&') { ps->p = p + 2; if (maxprec < 0) break; node_t *n = node_new(); n->kind = N_AND; n->a = left; if (!parse_binary(ps, 0, &n->b)) { node_free(n); return false; } left = n; continue; }
        if (*p == '|' && p[1] == '|') { ps->p = p + 2; if (maxprec < 0) break; node_t *n = node_new(); n->kind = N_OR; n->a = left; if (!parse_binary(ps, 0, &n->b)) { node_free(n); return false; } left = n; continue; }
        break;
    }
    *out = left;
    return true;
}

static bool parse_expr(parser_t *ps, node_t **out)
{
    node_t *n;
    if (!parse_binary(ps, 1, &n)) return false;
    const char *p = skip_ws(ps->p);
    ps->p = p;
    if (*p != '?') { *out = n; return true; }
    ps->p = p + 1;
    ps->depth++;
    node_t *a;
    if (!parse_binary(ps, 1, &a)) { ps->depth--; node_free(n); return false; }
    const char *q = skip_ws(ps->p);
    ps->p = q;
    if (*q != ':') { compile_error(ps, "expected ':'", ps->tags); ps->depth--; node_free(n); node_free(a); return false; }
    ps->p = q + 1;
    ps->depth++;
    node_t *c;
    if (!parse_binary(ps, 1, &c)) { ps->depth--; node_free(n); node_free(a); return false; }
    ps->depth--;
    node_t *tern = node_new();
    tern->kind = N_TERN;
    tern->a = n;
    tern->b = a;
    tern->c = c;
    *out = tern;
    return true;
}

// ---------------------------------------------------------------------------
// public API
// ---------------------------------------------------------------------------

typedef struct hmi_expr {
    node_t *root;
    char **tags;
    size_t ntags;
} expr_impl_t;

hmi_expr_t *hmi_expr_compile(const char *text, char *err, size_t errlen)
{
    if (err && errlen) err[0] = '\0';
    if (!text) {
        if (err && errlen) snprintf(err, errlen, "null expression");
        return NULL;
    }
    size_t len = strlen(text);
    if (len == 0 || len > MAX_LENGTH) {
        if (err && errlen) snprintf(err, errlen, "%s", len == 0 ? "empty expression" : "too long");
        return NULL;
    }
    parser_t ps;
    memset(&ps, 0, sizeof ps);
    ps.start = text;
    ps.p = text;
    ps.end = text + len;
    ps.tags = &ts;
    node_t *root = NULL;
    if (!parse_expr(&ps, &root)) {
        if (err && errlen) snprintf(err, errlen, "%s", ps.err[0] ? ps.err : "parse error");
        return NULL;
    }
    const char *p = skip_ws(ps.p);
    if (*p != '\0') {
        if (err && errlen) snprintf(err, errlen, "unexpected '%c'", *p);
        return NULL;
    }
    expr_impl_t *e = calloc(1, sizeof *e);
    e->root = root;
    e->tags = malloc(sizeof(char *) * (ps.tags->ntags ? ps.tags->ntags : 1));
    memcpy(e->tags, ps.tags->tags, sizeof(char *) * ps.tags->ntags);
    e->ntags = ps.tags->ntags;
    return (hmi_expr_t *)e;
}

void hmi_expr_free(hmi_expr_t *e)
{
    if (!e) return;
    expr_impl_t *e_ = (expr_impl_t *)e;
    free_node(e_->root);
    for (size_t i = 0; i < e_->ntags; i++) free(e_->tags[i]);
    free(e_->tags);
    free(e);
}

size_t hmi_expr_tag_count(const hmi_expr_t *e)
{
    return e ? ((expr_impl_t *)e)->ntags : 0;
}

const char *hmi_expr_tag(const hmi_expr_t *e, size_t i)
{
    expr_impl_t *e_ = (expr_impl_t *)e;
    if (!e_ || i >= e_->ntags) return "";
    return e_->tags[i];
}

// ---------------------------------------------------------------------------
// evaluator
// ---------------------------------------------------------------------------

static bool truthy_val(const hmi_value_t *v)
{
    switch (v->kind) {
    case HMI_V_NULL: return false;
    case HMI_V_BOOL: return v->b;
    case HMI_V_NUM: return v->n != 0.0;
    case HMI_V_STR: {
        if (!v->s || !*v->s) return false;
        return strcmp(v->s, "false") != 0 && strcmp(v->s, "0") != 0;
    }
    default: return true;
    }
}

static hmi_value_t nullval(void) { return hmi_value_null(); }

static hmi_value_t numval(double x)
{
    if (!isfinite(x)) return nullval();
    return hmi_value_num(x);
}

static hmi_value_t boolval(bool b) { return hmi_value_bool(b); }

static const char *FUNC_NAME[] = {"abs", "floor", "ceil", "round", "min", "max", "clamp"};
static int FUNC_NARGS[] = {1, 1, 1, -1, 2, 2, 3};

static hmi_value_t eval_call(expr_impl_t *e_, const node_t *n,
                             hmi_expr_lookup_cb lookup, void *user)
{
    for (size_t i = 0; i < 7; i++) {
        if (strcmp(n->fname, FUNC_NAME[i]) != 0) continue;
        if (i == 3) {   // round: 1 or 2 args
            if (n->nargs != 1 && n->nargs != 2) return nullval();
        } else if (FUNC_NARGS[i] != (int)n->nargs) {
            return nullval();
        }
        switch (i) {
        case 0: {   // abs
            hmi_value_t a = eval(n->a, lookup, user);
            if (a.kind != HMI_V_NUM && a.kind != HMI_V_BOOL) { hmi_value_free(&a); return nullval(); }
            hmi_value_t r = numval(fabs(a.n));
            hmi_value_free(&a);
            return r;
        }
        case 1: {   // floor
            hmi_value_t a = eval(n->a, lookup, user);
            if (a.kind != HMI_V_NUM && a.kind != HMI_V_BOOL) { hmi_value_free(&a); return nullval(); }
            hmi_value_t r = hmi_value_num(floor(a.n));
            hmi_value_free(&a);
            return r;
        }
        case 2: {   // ceil
            hmi_value_t a = eval(n->a, lookup, user);
            if (a.kind != HMI_V_NUM && a.kind != HMI_V_BOOL) { hmi_value_free(&a); return nullval(); }
            hmi_value_t r = hmi_value_num(ceil(a.n));
            hmi_value_free(&a);
            return r;
        }
        case 3: {   // round
            hmi_value_t a = eval(n->a, lookup, user);
            if (a.kind != HMI_V_NUM && a.kind != HMI_V_BOOL) { hmi_value_free(&a); return nullval(); }
            if (n->nargs == 2) {
                hmi_value_t b = eval(n->b, lookup, user);
                if (b.kind != HMI_V_NUM) { hmi_value_free(&a); hmi_value_free(&b); return nullval(); }
                int digits = (int)b.n;
                hmi_value_free(&b);
                if (digits < 0 || digits > 6) { hmi_value_free(&a); return nullval(); }
                double factor = pow(10.0, digits);
                hmi_value_t r = hmi_value_num(round(a.n * factor) / factor);
                hmi_value_free(&a);
                return r;
            }
            hmi_value_t r = hmi_value_num(round(a.n));
            hmi_value_free(&a);
            return r;
        }
        case 4: {   // min
            double m = INFINITY;
            for (size_t k = 0; k < n->nargs; k++) {
                hmi_value_t v = eval(n->args[k], lookup, user);
                if (v.kind != HMI_V_NUM && v.kind != HMI_V_BOOL) { hmi_value_free(&v); return nullval(); }
                if (v.n < m) m = v.n;
                hmi_value_free(&v);
            }
            return numval(m);
        }
        case 5: {   // max
            double m = -INFINITY;
            for (size_t k = 0; k < n->nargs; k++) {
                hmi_value_t v = eval(n->args[k], lookup, user);
                if (v.kind != HMI_V_NUM && v.kind != HMI_V_BOOL) { hmi_value_free(&v); return nullval(); }
                if (v.n > m) m = v.n;
                hmi_value_free(&v);
            }
            return numval(m);
        }
        case 6: {   // clamp
            hmi_value_t x = eval(n->args[0], lookup, user);
            hmi_value_t lo = eval(n->args[1], lookup, user);
            hmi_value_t hi = eval(n->args[2], lookup, user);
            bool ok = x.kind != HMI_V_NULL && lo.kind != HMI_V_NULL && hi.kind != HMI_V_NULL;
            double r = (ok && lo.n > hi.n) ? hi.n : (ok ? x.n : 0.0);
            if (ok) {
                if (r < lo.n) r = lo.n;
                if (r > hi.n) r = hi.n;
            }
            hmi_value_free(&x);
            hmi_value_free(&lo);
            hmi_value_free(&hi);
            return numval(ok ? r : 0.0);
        }
        }
        return nullval();
    }
    return nullval();
}

static hmi_value_t eval_cmp(int op, hmi_value_t a, hmi_value_t b)
{
    if (a.kind == HMI_V_STR && b.kind == HMI_V_STR) {
        if (op == '=') return boolval(strcmp(a.s ? a.s : "", b.s ? b.s : "") == 0);
        if (op == '!') return boolval(strcmp(a.s ? a.s : "", b.s ? b.s : "") != 0);
        return boolval(false);   // string < > <= >= are false
    }
    if (a.kind != HMI_V_NULL && b.kind != HMI_V_NULL) {
        double av = hmi_value_as_num(&a, 0.0), bv = hmi_value_as_num(&b, 0.0);
        switch (op) {
        case '=': return boolval(av == bv);
        case '!': return boolval(av != bv);
        case '<': return boolval(av < bv);
        case '>': return boolval(av > bv);
        }
    }
    return boolval(false);
}

hmi_value_t hmi_expr_eval(const hmi_expr_t *e, hmi_expr_lookup_cb lookup, void *user)
{
    expr_impl_t *e_ = (expr_impl_t *)e;
    if (!e_) return nullval();
    return eval(e_->root, lookup, user);
}