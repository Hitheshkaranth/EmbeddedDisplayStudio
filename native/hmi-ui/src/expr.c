// expr.c -- see expr.h (CONTRACT 13.2).
//
// A tokenizer, a recursive-descent parser and a tree evaluator. Limits: 512
// characters, 16 distinct tags, nesting depth 32 (parentheses, function
// calls, unary operators). A null or string arithmetic operand, division or
// modulo by zero and a non-finite result all yield null at run time; only the
// text itself can be a compile error.

#include "expr.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_LENGTH  512
#define MAX_TAGS    16
#define MAX_DEPTH   32

// ---------------------------------------------------------------------------
// tokens
// ---------------------------------------------------------------------------

typedef enum {
    T_END, T_NUM, T_STR, T_WORD, T_OP, T_LPAREN, T_RPAREN, T_COMMA, T_QMARK, T_COLON
} tokkind_t;

typedef struct {
    tokkind_t kind;
    size_t pos;         // offset in the text, for error messages
    size_t len;         // T_WORD / T_OP: length of the text at pos
    double num;         // T_NUM
    char *str;          // T_STR: unescaped, owned
} token_t;

typedef enum {
    OP_ADD, OP_SUB, OP_MUL, OP_DIV, OP_MOD,
    OP_EQ, OP_NE, OP_LT, OP_LE, OP_GT, OP_GE,
    OP_NOT, OP_NEG,
} op_t;

typedef enum { N_NUM, N_BOOL, N_STR, N_TAG, N_UNARY, N_BIN, N_CMP, N_AND, N_OR, N_TERN, N_CALL } nodekind_t;

typedef enum { F_ABS, F_FLOOR, F_CEIL, F_ROUND, F_MIN, F_MAX, F_CLAMP } func_t;

static const struct { const char *name; int min, max; } FUNCS[] = {
    [F_ABS] = {"abs", 1, 1},     [F_FLOOR] = {"floor", 1, 1}, [F_CEIL] = {"ceil", 1, 1},
    [F_ROUND] = {"round", 1, 2}, [F_MIN] = {"min", 2, -1},    [F_MAX] = {"max", 2, -1},
    [F_CLAMP] = {"clamp", 3, 3},
};
#define NFUNCS (sizeof FUNCS / sizeof FUNCS[0])

typedef struct node {
    nodekind_t kind;
    double d;           // N_NUM
    bool b;             // N_BOOL
    char *s;            // N_STR (owned)
    size_t tag;         // N_TAG: index into the expression's tag list
    op_t op;            // N_UNARY, N_BIN, N_CMP
    func_t fn;          // N_CALL
    struct node *a, *b2, *c;    // operands; N_TERN: cond, then, else
    struct node **args; size_t nargs;   // N_CALL
} node_t;

struct hmi_expr {
    node_t *root;
    char *tags[MAX_TAGS];
    size_t ntags;
};

typedef struct {
    const char *text;
    token_t *toks; size_t ntoks, cap;
    size_t i;           // parser cursor into toks
    int depth;
    struct hmi_expr *e;
    char err[160];
} parser_t;

static void node_free(node_t *n)
{
    if (!n) return;
    free(n->s);
    for (size_t i = 0; i < n->nargs; i++) node_free(n->args[i]);
    free(n->args);
    node_free(n->a);
    node_free(n->b2);
    node_free(n->c);
    free(n);
}

static node_t *node_new(nodekind_t kind)
{
    node_t *n = calloc(1, sizeof *n);
    if (n) n->kind = kind;
    return n;
}

// First error wins: later ones are consequences of it.
static void fail(parser_t *ps, size_t pos, const char *fmt, const char *what)
{
    if (ps->err[0]) return;
    char msg[120];
    snprintf(msg, sizeof msg, fmt, what);
    snprintf(ps->err, sizeof ps->err, "%s at %zu", msg, pos);
}

static bool is_digit(char c) { return c >= '0' && c <= '9'; }
static bool is_lower(char c) { return c >= 'a' && c <= 'z'; }
static bool is_word(char c)
{
    return is_digit(c) || is_lower(c) || (c >= 'A' && c <= 'Z') || c == '_';
}

static bool push(parser_t *ps, token_t t)
{
    if (ps->ntoks == ps->cap) {
        size_t cap = ps->cap ? ps->cap * 2 : 32;
        token_t *grown = realloc(ps->toks, cap * sizeof *grown);
        if (!grown) { free(t.str); fail(ps, t.pos, "%s", "out of memory"); return false; }
        ps->toks = grown;
        ps->cap = cap;
    }
    ps->toks[ps->ntoks++] = t;
    return true;
}

static bool tokenize(parser_t *ps)
{
    const char *s = ps->text;
    size_t i = 0;
    for (;;) {
        while (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r') i++;
        token_t t = {.pos = i};
        char c = s[i];
        if (!c) { t.kind = T_END; return push(ps, t); }
        if (is_digit(c)) {
            // NUMBER := [0-9]+ ('.' [0-9]+)? -- no exponent, no leading '.'
            size_t j = i;
            while (is_digit(s[j])) j++;
            if (s[j] == '.' && is_digit(s[j + 1])) {
                j++;
                while (is_digit(s[j])) j++;
            }
            t.kind = T_NUM;
            t.num = strtod(s + i, NULL);
            i = j;
        } else if (c == '"') {
            size_t j = i + 1, n = 0;
            char *out = malloc(strlen(s + i) + 1);
            if (!out) { fail(ps, i, "%s", "out of memory"); return false; }
            while (s[j] && s[j] != '"') {
                if (s[j] == '\\') {
                    if (s[j + 1] != '"' && s[j + 1] != '\\') {
                        free(out);
                        fail(ps, j, "%s", "bad escape in string");
                        return false;
                    }
                    j++;
                }
                out[n++] = s[j++];
            }
            if (s[j] != '"') { free(out); fail(ps, i, "%s", "unterminated string"); return false; }
            out[n] = '\0';
            t.kind = T_STR;
            t.str = out;
            i = j + 1;
        } else if (is_word(c)) {
            // A word, possibly dotted; whether it is a tag, a keyword or a
            // function name is the parser's decision.
            size_t j = i;
            while (is_word(s[j])) j++;
            while (s[j] == '.' && is_word(s[j + 1])) {
                j++;
                while (is_word(s[j])) j++;
            }
            t.kind = T_WORD;
            t.len = j - i;
            i = j;
        } else {
            static const char *two[] = {"==", "!=", "<=", ">=", "&&", "||"};
            size_t len = 0;
            for (size_t k = 0; k < sizeof two / sizeof two[0]; k++)
                if (c == two[k][0] && s[i + 1] == two[k][1]) len = 2;
            if (!len && strchr("+-*/%<>!", c)) len = 1;
            if (len) {
                t.kind = T_OP;
                t.len = len;
            } else if (c == '(') { t.kind = T_LPAREN; len = 1; }
            else if (c == ')') { t.kind = T_RPAREN; len = 1; }
            else if (c == ',') { t.kind = T_COMMA; len = 1; }
            else if (c == '?') { t.kind = T_QMARK; len = 1; }
            else if (c == ':') { t.kind = T_COLON; len = 1; }
            else {
                char what[2] = {c, 0};
                fail(ps, i, "unexpected '%s'", what);
                return false;
            }
            i += len;
        }
        if (!push(ps, t)) return false;
    }
}

// ---------------------------------------------------------------------------
// parser
// ---------------------------------------------------------------------------

static const token_t *cur(parser_t *ps) { return &ps->toks[ps->i]; }

static bool is_op(parser_t *ps, const char *op)
{
    const token_t *t = cur(ps);
    return t->kind == T_OP && t->len == strlen(op) && memcmp(ps->text + t->pos, op, t->len) == 0;
}

static void fail_unexpected(parser_t *ps)
{
    const token_t *t = cur(ps);
    char what[64];
    switch (t->kind) {
    case T_END: fail(ps, t->pos, "%s", "unexpected end"); return;
    case T_NUM: snprintf(what, sizeof what, "number"); break;
    case T_STR: snprintf(what, sizeof what, "string"); break;
    case T_WORD: case T_OP:
        snprintf(what, sizeof what, "%.*s", (int)(t->len < 40 ? t->len : 40), ps->text + t->pos);
        break;
    default: snprintf(what, sizeof what, "%c", ps->text[t->pos]); break;
    }
    fail(ps, t->pos, "unexpected '%s'", what);
}

static bool enter(parser_t *ps)
{
    if (++ps->depth > MAX_DEPTH) {
        fail(ps, cur(ps)->pos, "%s", "too deeply nested");
        return false;
    }
    return true;
}

// TAG := [a-z][a-z0-9]*(\.[a-z0-9_]+)+   (CONTRACT 2.5)
static bool valid_tag(const char *s, size_t len)
{
    size_t i = 0;
    if (!len || !is_lower(s[0])) return false;
    while (i < len && (is_lower(s[i]) || is_digit(s[i]))) i++;
    if (i == len) return false;             // no dotted segment
    while (i < len) {
        if (s[i] != '.') return false;
        size_t start = ++i;
        while (i < len && (is_lower(s[i]) || is_digit(s[i]) || s[i] == '_')) i++;
        if (i == start) return false;
    }
    return true;
}

static node_t *parse_expr(parser_t *ps);

static node_t *parse_call(parser_t *ps, func_t fn, size_t pos)
{
    node_t *n = node_new(N_CALL);
    if (!n || !enter(ps)) { node_free(n); return NULL; }
    n->fn = fn;
    ps->i++;                                // '('
    for (;;) {
        node_t *arg = parse_expr(ps);
        if (!arg) { node_free(n); return NULL; }
        node_t **grown = realloc(n->args, (n->nargs + 1) * sizeof *grown);
        if (!grown) { node_free(arg); node_free(n); return NULL; }
        n->args = grown;
        n->args[n->nargs++] = arg;
        if (cur(ps)->kind != T_COMMA) break;
        ps->i++;
    }
    if (cur(ps)->kind != T_RPAREN) { fail_unexpected(ps); node_free(n); return NULL; }
    ps->i++;
    ps->depth--;
    int want_min = FUNCS[fn].min, want_max = FUNCS[fn].max;
    if ((int)n->nargs < want_min || (want_max >= 0 && (int)n->nargs > want_max)) {
        fail(ps, pos, "wrong number of arguments to %s()", FUNCS[fn].name);
        node_free(n);
        return NULL;
    }
    return n;
}

static node_t *parse_word(parser_t *ps)
{
    const token_t *t = cur(ps);
    const char *w = ps->text + t->pos;
    size_t len = t->len, pos = t->pos;
    if ((len == 4 && memcmp(w, "true", 4) == 0) || (len == 5 && memcmp(w, "false", 5) == 0)) {
        node_t *n = node_new(N_BOOL);
        if (n) n->b = len == 4;
        ps->i++;
        return n;
    }
    if (ps->toks[ps->i + 1].kind == T_LPAREN) {
        ps->i++;
        for (size_t f = 0; f < NFUNCS; f++)
            if (strlen(FUNCS[f].name) == len && memcmp(FUNCS[f].name, w, len) == 0)
                return parse_call(ps, (func_t)f, pos);
        char name[48];
        snprintf(name, sizeof name, "%.*s", (int)(len < 40 ? len : 40), w);
        fail(ps, pos, "unknown function '%s'", name);
        return NULL;
    }
    if (!valid_tag(w, len)) {
        char name[48];
        snprintf(name, sizeof name, "%.*s", (int)(len < 40 ? len : 40), w);
        fail(ps, pos, "'%s' is not a tag name", name);
        return NULL;
    }
    struct hmi_expr *e = ps->e;
    size_t k = 0;
    while (k < e->ntags && !(strlen(e->tags[k]) == len && memcmp(e->tags[k], w, len) == 0)) k++;
    if (k == e->ntags) {
        if (e->ntags >= MAX_TAGS) {
            snprintf(ps->err, sizeof ps->err, "too many tags");
            return NULL;
        }
        char *copy = malloc(len + 1);
        if (!copy) return NULL;
        memcpy(copy, w, len);
        copy[len] = '\0';
        e->tags[e->ntags++] = copy;
    }
    node_t *n = node_new(N_TAG);
    if (n) n->tag = k;
    ps->i++;
    return n;
}

static node_t *parse_unary(parser_t *ps)
{
    const token_t *t = cur(ps);
    if (is_op(ps, "!") || is_op(ps, "-")) {
        op_t op = ps->text[t->pos] == '!' ? OP_NOT : OP_NEG;
        if (!enter(ps)) return NULL;
        ps->i++;
        node_t *a = parse_unary(ps);
        if (!a) return NULL;
        ps->depth--;
        node_t *n = node_new(N_UNARY);
        if (!n) { node_free(a); return NULL; }
        n->op = op;
        n->a = a;
        return n;
    }
    switch (t->kind) {
    case T_NUM: {
        node_t *n = node_new(N_NUM);
        if (n) n->d = t->num;
        ps->i++;
        return n;
    }
    case T_STR: {
        node_t *n = node_new(N_STR);
        if (n) { n->s = t->str; ps->toks[ps->i].str = NULL; }
        ps->i++;
        return n;
    }
    case T_WORD:
        return parse_word(ps);
    case T_LPAREN: {
        if (!enter(ps)) return NULL;
        ps->i++;
        node_t *n = parse_expr(ps);
        if (!n) return NULL;
        if (cur(ps)->kind != T_RPAREN) { fail_unexpected(ps); node_free(n); return NULL; }
        ps->i++;
        ps->depth--;
        return n;
    }
    default:
        fail_unexpected(ps);
        return NULL;
    }
}

static node_t *binary(nodekind_t kind, op_t op, node_t *a, node_t *b)
{
    node_t *n = node_new(kind);
    if (!n) { node_free(a); node_free(b); return NULL; }
    n->op = op;
    n->a = a;
    n->b2 = b;
    return n;
}

static node_t *parse_prod(parser_t *ps)
{
    node_t *left = parse_unary(ps);
    while (left && (is_op(ps, "*") || is_op(ps, "/") || is_op(ps, "%"))) {
        char c = ps->text[cur(ps)->pos];
        ps->i++;
        node_t *right = parse_unary(ps);
        if (!right) { node_free(left); return NULL; }
        left = binary(N_BIN, c == '*' ? OP_MUL : c == '/' ? OP_DIV : OP_MOD, left, right);
    }
    return left;
}

static node_t *parse_sum(parser_t *ps)
{
    node_t *left = parse_prod(ps);
    while (left && (is_op(ps, "+") || is_op(ps, "-"))) {
        op_t op = ps->text[cur(ps)->pos] == '+' ? OP_ADD : OP_SUB;
        ps->i++;
        node_t *right = parse_prod(ps);
        if (!right) { node_free(left); return NULL; }
        left = binary(N_BIN, op, left, right);
    }
    return left;
}

// Comparisons do not chain: "1 < 2 == true" is a compile error.
static node_t *parse_cmp(parser_t *ps)
{
    static const struct { const char *text; op_t op; } CMPS[] = {
        {"==", OP_EQ}, {"!=", OP_NE}, {"<", OP_LT}, {"<=", OP_LE}, {">", OP_GT}, {">=", OP_GE},
    };
    node_t *left = parse_sum(ps);
    if (!left) return NULL;
    for (size_t k = 0; k < sizeof CMPS / sizeof CMPS[0]; k++) {
        if (!is_op(ps, CMPS[k].text)) continue;
        ps->i++;
        node_t *right = parse_sum(ps);
        if (!right) { node_free(left); return NULL; }
        return binary(N_CMP, CMPS[k].op, left, right);
    }
    return left;
}

static node_t *parse_and(parser_t *ps)
{
    node_t *left = parse_cmp(ps);
    while (left && is_op(ps, "&&")) {
        ps->i++;
        node_t *right = parse_cmp(ps);
        if (!right) { node_free(left); return NULL; }
        left = binary(N_AND, OP_EQ, left, right);
    }
    return left;
}

static node_t *parse_or(parser_t *ps)
{
    node_t *left = parse_and(ps);
    while (left && is_op(ps, "||")) {
        ps->i++;
        node_t *right = parse_and(ps);
        if (!right) { node_free(left); return NULL; }
        left = binary(N_OR, OP_EQ, left, right);
    }
    return left;
}

// expr := or ('?' expr ':' expr)?
static node_t *parse_expr(parser_t *ps)
{
    node_t *cond = parse_or(ps);
    if (!cond || cur(ps)->kind != T_QMARK) return cond;
    ps->i++;
    node_t *then = parse_expr(ps);
    if (!then) { node_free(cond); return NULL; }
    if (cur(ps)->kind != T_COLON) {
        fail_unexpected(ps);
        node_free(cond);
        node_free(then);
        return NULL;
    }
    ps->i++;
    node_t *other = parse_expr(ps);
    if (!other) { node_free(cond); node_free(then); return NULL; }
    node_t *n = node_new(N_TERN);
    if (!n) { node_free(cond); node_free(then); node_free(other); return NULL; }
    n->a = cond;
    n->b2 = then;
    n->c = other;
    return n;
}

// ---------------------------------------------------------------------------
// public API
// ---------------------------------------------------------------------------

void hmi_expr_free(hmi_expr_t *e)
{
    if (!e) return;
    node_free(e->root);
    for (size_t i = 0; i < e->ntags; i++) free(e->tags[i]);
    free(e);
}

hmi_expr_t *hmi_expr_compile(const char *text, char *err, size_t errlen)
{
    if (err && errlen) err[0] = '\0';
    if (!text) text = "";
    if (strlen(text) > MAX_LENGTH) {
        if (err && errlen) snprintf(err, errlen, "expression longer than %d characters", MAX_LENGTH);
        return NULL;
    }
    parser_t ps = {.text = text};
    ps.e = calloc(1, sizeof *ps.e);
    if (!ps.e) {
        if (err && errlen) snprintf(err, errlen, "out of memory");
        return NULL;
    }
    node_t *root = NULL;
    if (tokenize(&ps)) {
        root = parse_expr(&ps);
        if (root && cur(&ps)->kind != T_END) {
            fail_unexpected(&ps);
            node_free(root);
            root = NULL;
        }
    }
    for (size_t i = 0; i < ps.ntoks; i++) free(ps.toks[i].str);
    free(ps.toks);
    if (!root) {
        if (err && errlen) snprintf(err, errlen, "%s", ps.err[0] ? ps.err : "out of memory");
        hmi_expr_free(ps.e);
        return NULL;
    }
    ps.e->root = root;
    return ps.e;
}

size_t hmi_expr_tag_count(const hmi_expr_t *e)
{
    return e ? e->ntags : 0;
}

const char *hmi_expr_tag(const hmi_expr_t *e, size_t i)
{
    return (e && i < e->ntags) ? e->tags[i] : "";
}

// ---------------------------------------------------------------------------
// evaluator
// ---------------------------------------------------------------------------

typedef struct {
    const hmi_expr_t *e;
    hmi_expr_lookup_cb lookup;
    void *user;
} ctx_t;

// CONTRACT 13.1/13.2 truthy: null, false, 0, "", "false", "0" and an empty
// list are false.
static bool truthy(const hmi_value_t *v)
{
    switch (v->kind) {
    case HMI_V_BOOL: return v->b;
    case HMI_V_NUM: return v->n != 0.0;
    case HMI_V_STR: return v->s && *v->s && strcmp(v->s, "false") != 0 && strcmp(v->s, "0") != 0;
    case HMI_V_LIST: return v->count > 0;
    default: return false;
    }
}

// Arithmetic operand: numbers, and bools as 1/0; anything else is null.
static bool as_number(const hmi_value_t *v, double *out)
{
    if (v->kind == HMI_V_NUM) { *out = v->n; return true; }
    if (v->kind == HMI_V_BOOL) { *out = v->b ? 1.0 : 0.0; return true; }
    return false;
}

static hmi_value_t num_result(double x)
{
    return isfinite(x) ? hmi_value_num(x) : hmi_value_null();
}

static double round_half_away(double x)
{
    return x >= 0 ? floor(x + 0.5) : ceil(x - 0.5);
}

static hmi_value_t eval(const ctx_t *cx, const node_t *n);

static bool eval_truthy(const ctx_t *cx, const node_t *n)
{
    hmi_value_t v = eval(cx, n);
    bool t = truthy(&v);
    hmi_value_free(&v);
    return t;
}

static bool eval_number(const ctx_t *cx, const node_t *n, double *out)
{
    hmi_value_t v = eval(cx, n);
    bool ok = as_number(&v, out);
    hmi_value_free(&v);
    return ok;
}

static hmi_value_t eval_cmp(op_t op, const hmi_value_t *a, const hmi_value_t *b)
{
    if (a->kind == HMI_V_NULL || b->kind == HMI_V_NULL) return hmi_value_bool(false);
    bool as = a->kind == HMI_V_STR, bs = b->kind == HMI_V_STR;
    if (as || bs) {
        // Only two strings compare, and only for (in)equality; a string
        // against anything else is simply not equal.
        bool same = as && bs && strcmp(a->s ? a->s : "", b->s ? b->s : "") == 0;
        if (op == OP_EQ) return hmi_value_bool(same);
        if (op == OP_NE) return hmi_value_bool(!same);
        return hmi_value_bool(false);
    }
    double x, y;
    if (!as_number(a, &x) || !as_number(b, &y)) return hmi_value_bool(false);
    switch (op) {
    case OP_EQ: return hmi_value_bool(x == y);
    case OP_NE: return hmi_value_bool(x != y);
    case OP_LT: return hmi_value_bool(x < y);
    case OP_LE: return hmi_value_bool(x <= y);
    case OP_GT: return hmi_value_bool(x > y);
    case OP_GE: return hmi_value_bool(x >= y);
    default: return hmi_value_bool(false);
    }
}

static hmi_value_t eval_call(const ctx_t *cx, const node_t *n)
{
    double x[3];
    switch (n->fn) {
    case F_ABS: case F_FLOOR: case F_CEIL:
        if (!eval_number(cx, n->args[0], &x[0])) return hmi_value_null();
        return num_result(n->fn == F_ABS ? fabs(x[0]) : n->fn == F_FLOOR ? floor(x[0]) : ceil(x[0]));
    case F_ROUND: {
        if (!eval_number(cx, n->args[0], &x[0])) return hmi_value_null();
        if (n->nargs == 1) return num_result(round_half_away(x[0]));
        if (!eval_number(cx, n->args[1], &x[1])) return hmi_value_null();
        if (x[1] != floor(x[1]) || x[1] < 0 || x[1] > 6) return hmi_value_null();
        double f = pow(10.0, x[1]);
        return num_result(round_half_away(x[0] * f) / f);
    }
    case F_MIN: case F_MAX: {
        double best = 0.0;
        bool ok = true;
        // Every argument is evaluated, so a null anywhere is null.
        for (size_t i = 0; i < n->nargs; i++) {
            double v;
            if (!eval_number(cx, n->args[i], &v)) { ok = false; continue; }
            if (i == 0 || (n->fn == F_MIN ? v < best : v > best)) best = v;
        }
        return ok ? num_result(best) : hmi_value_null();
    }
    case F_CLAMP: {
        bool ok = true;
        for (size_t i = 0; i < 3; i++)
            if (!eval_number(cx, n->args[i], &x[i])) ok = false;
        if (!ok) return hmi_value_null();
        return num_result(fmax(x[1], fmin(x[0], x[2])));
    }
    }
    return hmi_value_null();
}

static hmi_value_t eval(const ctx_t *cx, const node_t *n)
{
    switch (n->kind) {
    case N_NUM: return num_result(n->d);
    case N_BOOL: return hmi_value_bool(n->b);
    case N_STR: return hmi_value_str(n->s);
    case N_TAG: {
        const hmi_value_t *v = cx->lookup ? cx->lookup(cx->e->tags[n->tag], cx->user) : NULL;
        return v ? hmi_value_copy(v) : hmi_value_null();
    }
    case N_UNARY: {
        if (n->op == OP_NOT) return hmi_value_bool(!eval_truthy(cx, n->a));
        double x;
        if (!eval_number(cx, n->a, &x)) return hmi_value_null();
        return num_result(-x);
    }
    case N_BIN: {
        double x, y;
        bool okx = eval_number(cx, n->a, &x);
        bool oky = eval_number(cx, n->b2, &y);
        if (!okx || !oky) return hmi_value_null();
        switch (n->op) {
        case OP_ADD: return num_result(x + y);
        case OP_SUB: return num_result(x - y);
        case OP_MUL: return num_result(x * y);
        case OP_DIV: return y == 0.0 ? hmi_value_null() : num_result(x / y);
        case OP_MOD: return y == 0.0 ? hmi_value_null() : num_result(fmod(x, y));
        default: return hmi_value_null();
        }
    }
    case N_CMP: {
        hmi_value_t a = eval(cx, n->a), b = eval(cx, n->b2);
        hmi_value_t r = eval_cmp(n->op, &a, &b);
        hmi_value_free(&a);
        hmi_value_free(&b);
        return r;
    }
    case N_AND: return hmi_value_bool(eval_truthy(cx, n->a) && eval_truthy(cx, n->b2));
    case N_OR: return hmi_value_bool(eval_truthy(cx, n->a) || eval_truthy(cx, n->b2));
    case N_TERN: return eval(cx, eval_truthy(cx, n->a) ? n->b2 : n->c);
    case N_CALL: return eval_call(cx, n);
    }
    return hmi_value_null();
}

hmi_value_t hmi_expr_eval(const hmi_expr_t *e, hmi_expr_lookup_cb lookup, void *user)
{
    if (!e || !e->root) return hmi_value_null();
    ctx_t cx = {e, lookup, user};
    return eval(&cx, e->root);
}
