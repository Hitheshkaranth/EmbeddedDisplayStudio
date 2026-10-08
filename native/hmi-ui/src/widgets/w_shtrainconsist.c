// widgets/w_shtrainconsist.c -- kit widget ShTrainConsist (Rail, "Train Consist").
//
// Spec: ui/qml/Shadcn/ShTrainConsist.qml. A top-down metro consist standing
// vertically: the cars stacked with small gaps, cab cars at both ends with a
// rounded accent-trimmed nose, windscreen band and head/tail lights, two
// columns of seats per car, a lock on the car behind the leading cab, and two
// door bars on each long side coloured by doorsLeft / doorsRight. Car names
// read bottom-to-top on the right, the two door captions on the left (the
// part after the colon coloured by its door state).
//
// Geometry (shared with the QML and designer/canvas/rail/train_consist.py):
//   bodyW = 0.30 W centred; train from 0.015 H, 0.97 H tall; gap max(2, 0.007 H)
//   nose radius min(0.42 bodyW, 0.35 carH); doors max(3, 0.027 W) x 0.28 carH.
#include <ctype.h>
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "icons.h"
#include "registry.h"

#define MAX_CARS 16
#define NAME_LEN 24

typedef enum { DOOR_CLOSED, DOOR_OPEN, DOOR_DISABLED } door_t;

typedef struct {
    int n;
    char names[MAX_CARS][NAME_LEN];
    door_t left, right;
    char accent[16];
    char captions[2][128];                   // leftLabel, rightLabel
    lv_obj_t *face, *carLabels[MAX_CARS], *lock;
    lv_obj_t *capPrefix[2], *capStatus[2];   // [0] leftLabel, [1] rightLabel
} state_t;

typedef struct { double W, H, bw, bx, top, gap, carH, rN, rs; } geom_t;

static geom_t geometry(const hmi_widget_t *w, int n)
{
    geom_t g;
    g.W = fmax(1, w->width); g.H = fmax(1, w->height);
    g.bw = g.W * 0.30; g.bx = (g.W - g.bw) / 2;
    g.top = g.H * 0.015;
    g.gap = fmax(2, g.H * 0.007);
    double trainH = g.H * 0.97;
    g.carH = n > 0 ? (trainH - g.gap * (n - 1)) / n : trainH;
    g.rN = fmin(g.bw * 0.42, g.carH * 0.35);
    g.rs = fmax(2, g.bw * 0.07);
    return g;
}

// -- door state ---------------------------------------------------------------

static door_t door_from_str(const char *s)
{
    char b[16];
    size_t i = 0;
    while (*s && isspace((unsigned char)*s)) ++s;
    for (; s[i] && i < sizeof b - 1; ++i) b[i] = (char)tolower((unsigned char)s[i]);
    b[i] = 0;
    while (i > 0 && isspace((unsigned char)b[i - 1])) b[--i] = 0;
    if (!strcmp(b, "closed") || !strcmp(b, "true") || !strcmp(b, "1")) return DOOR_CLOSED;
    if (!strcmp(b, "open") || !strcmp(b, "false") || !strcmp(b, "0")) return DOOR_OPEN;
    return DOOR_DISABLED;
}

// A bound value may be a bool or number: true / non-zero -> closed, false / 0 -> open.
static door_t door_from_value(const hmi_value_t *v, door_t def)
{
    if (!v) return def;
    switch (v->kind) {
    case HMI_V_BOOL: return v->b ? DOOR_CLOSED : DOOR_OPEN;
    case HMI_V_NUM: return v->n != 0 ? DOOR_CLOSED : DOOR_OPEN;
    case HMI_V_STR: return door_from_str(v->s ? v->s : "");
    default: return def;
    }
}

static lv_color_t door_colour(door_t d)
{
    return hmi_colour_hex(d == DOOR_CLOSED ? "#4ade80" : d == DOOR_OPEN ? "#f59e0b" : "#3f3f46", NULL);
}

static lv_color_t caption_colour(door_t d)
{
    return hmi_colour_hex(d == DOOR_CLOSED ? "#4ade80" : d == DOOR_OPEN ? "#f59e0b" : "#71717a", NULL);
}

// -- cars -----------------------------------------------------------------------

static void parse_cars(state_t *st, const char *s)
{
    st->n = 0;
    while (s && *s && st->n < MAX_CARS) {
        const char *e = strchr(s, ',');
        size_t len = e ? (size_t)(e - s) : strlen(s);
        while (len && isspace((unsigned char)*s)) { ++s; --len; }
        while (len && isspace((unsigned char)s[len - 1])) --len;
        if (len) {
            if (len >= NAME_LEN) len = NAME_LEN - 1;
            memcpy(st->names[st->n], s, len);
            st->names[st->n][len] = 0;
            st->n++;
        }
        s = e ? e + 1 : NULL;
    }
}

// The passenger section of car i (below the nose of the leading cab, above
// the nose of the trailing one).
static void section(const geom_t *g, int i, int n, double *sy, double *sh)
{
    double y = g->top + i * (g->carH + g->gap), h = g->carH;
    if (i == 0) { y += g->rN; h -= g->rN; }
    if (i == n - 1) h -= g->rN;
    *sy = y; *sh = h;
}

static void rect_at(const hmi_draw_t *d, lv_draw_rect_dsc_t *rd, double x, double y, double w, double h)
{
    lv_area_t a = {(int32_t)lround(d->coords.x1 + x), (int32_t)lround(d->coords.y1 + y),
                   (int32_t)lround(d->coords.x1 + x + w) - 1, (int32_t)lround(d->coords.y1 + y + h) - 1};
    lv_draw_rect(d->layer, rd, &a);
}

static void draw_door(const hmi_draw_t *d, double x, double y, double dw, double dh, door_t s)
{
    lv_color_t c = door_colour(s);
    if (s == DOOR_CLOSED) {   // soft glow
        double e = dw * 0.6;
        hmi_draw_fill(d, x - e, y - e, dw + 2 * e, dh + 2 * e, c, 56, (int)lround(dw));
    }
    hmi_draw_fill(d, x, y, dw, dh, c, LV_OPA_COVER, (int)lround(fmax(1, dw * 0.3)));
}

static void draw_cb(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    state_t *st = w->state;
    int n = st->n;
    if (n <= 0) return;
    hmi_draw_t d = hmi_draw_begin(e);
    geom_t g = geometry(w, n);
    lv_color_t body = hmi_colour_hex("#2a2a30", NULL), line = hmi_colour_hex("#3f3f46", NULL);
    lv_color_t seat = hmi_colour_hex("#3a3a42", NULL), glass = hmi_colour_hex("#0c0c10", NULL);
    lv_color_t accent = hmi_colour_hex(st->accent, NULL);
    int outline = (int)fmax(1, lround(g.W * 0.005));
    int trim = (int)fmax(2, lround(g.W * 0.013));
    double dw = fmax(3, g.W * 0.027), dh = g.carH * 0.28;

    for (int i = 0; i < n; ++i) {
        double y = g.top + i * (g.carH + g.gap);
        bool lead = i == 0, tail = i == n - 1;
        double sy, sh;
        section(&g, i, n, &sy, &sh);

        // Doors under the body (they stick out half their width).
        double gp = (sh - 2 * dh) / 3;
        for (int k = 0; k < 2; ++k) {
            double dy = sy + gp + k * (dh + gp);
            draw_door(&d, g.bx - dw * 0.55, dy, dw, dh, st->left);
            draw_door(&d, g.bx + g.bw - dw * 0.45, dy, dw, dh, st->right);
        }

        lv_draw_rect_dsc_t rd;
        lv_draw_rect_dsc_init(&rd);
        rd.bg_color = body; rd.bg_opa = LV_OPA_COVER;
        if (lead || tail) {
            // The nose: the whole car rounded by rN with the accent trim ...
            rd.radius = (int32_t)lround(g.rN);
            rd.border_color = accent; rd.border_opa = LV_OPA_COVER; rd.border_width = trim;
            rect_at(&d, &rd, g.bx, y, g.bw, g.carH);
            // ... then the passenger part over it, plain outline, open towards the nose.
            rd.radius = (int32_t)lround(g.rs);
            rd.border_color = line; rd.border_width = outline;
            if (lead && tail) {
                rd.border_side = LV_BORDER_SIDE_LEFT | LV_BORDER_SIDE_RIGHT;
                rd.radius = 0;
                rect_at(&d, &rd, g.bx, y + g.rN, g.bw, g.carH - 2 * g.rN);
            } else if (lead) {
                rd.border_side = LV_BORDER_SIDE_LEFT | LV_BORDER_SIDE_RIGHT | LV_BORDER_SIDE_BOTTOM;
                rect_at(&d, &rd, g.bx, y + g.rN, g.bw, g.carH - g.rN);
            } else {
                rd.border_side = LV_BORDER_SIDE_LEFT | LV_BORDER_SIDE_RIGHT | LV_BORDER_SIDE_TOP;
                rect_at(&d, &rd, g.bx, y, g.bw, g.carH - g.rN);
            }
            // Windscreen band and lights at the tip(s).
            double bh = fmax(3, g.rN * 0.32), lr = fmax(1.5, g.bw * 0.035);
            if (lead) {
                hmi_draw_fill(&d, g.bx + g.bw * 0.16, y + g.rN * 0.55, g.bw * 0.68, bh, glass, LV_OPA_COVER,
                              (int)lround(bh / 2));
                lv_color_t c = hmi_colour_hex("#f4f4f5", NULL);
                hmi_draw_disc(&d, g.bx + g.bw * 0.32, y + g.rN * 0.30, lr, c, LV_OPA_COVER);
                hmi_draw_disc(&d, g.bx + g.bw * 0.68, y + g.rN * 0.30, lr, c, LV_OPA_COVER);
            }
            if (tail) {
                double yb = y + g.carH;
                hmi_draw_fill(&d, g.bx + g.bw * 0.16, yb - g.rN * 0.55 - bh, g.bw * 0.68, bh, glass, LV_OPA_COVER,
                              (int)lround(bh / 2));
                lv_color_t c = hmi_colour_hex("#ef4444", NULL);
                hmi_draw_disc(&d, g.bx + g.bw * 0.32, yb - g.rN * 0.30, lr, c, LV_OPA_COVER);
                hmi_draw_disc(&d, g.bx + g.bw * 0.68, yb - g.rN * 0.30, lr, c, LV_OPA_COVER);
            }
        } else {
            rd.radius = (int32_t)lround(g.rs);
            rd.border_color = line; rd.border_opa = LV_OPA_COVER; rd.border_width = outline;
            rect_at(&d, &rd, g.bx, y, g.bw, g.carH);
        }

        // Seats: two columns of three.
        double ay = sy + sh * 0.12, pitch = sh * 0.76 / 3, seatH = pitch * 0.62, seatW = g.bw * 0.24;
        int sr = (int)lround(fmax(1, seatW * 0.18));
        for (int r = 0; r < 3; ++r) {
            double yy = ay + r * pitch + (pitch - seatH) / 2;
            hmi_draw_fill(&d, g.bx + g.bw * 0.14, yy, seatW, seatH, seat, LV_OPA_COVER, sr);
            hmi_draw_fill(&d, g.bx + g.bw * 0.62, yy, seatW, seatH, seat, LV_OPA_COVER, sr);
        }
    }
}

// -- labels ---------------------------------------------------------------------

static void place_rotated(lv_obj_t *l, double cx, double cy)
{
    lv_obj_update_layout(l);
    int lw = lv_obj_get_width(l), lh = lv_obj_get_height(l);
    lv_obj_set_style_transform_pivot_x(l, lw / 2, 0);
    lv_obj_set_style_transform_pivot_y(l, lh / 2, 0);
    lv_obj_set_style_transform_rotation(l, -900, 0);
    lv_obj_set_pos(l, (int32_t)lround(cx - lw / 2.0), (int32_t)lround(cy - lh / 2.0));
}

static void layout_caption(hmi_widget_t *w, int which, const geom_t *g)
{
    state_t *st = w->state;
    const char *text = st->captions[which];
    door_t s = which ? st->right : st->left;
    char prefix[128], status[128];
    const char *colon = strchr(text, ':');
    if (colon) {
        size_t pl = (size_t)(colon - text) + 1;
        if (pl >= sizeof prefix) pl = sizeof prefix - 1;
        memcpy(prefix, text, pl); prefix[pl] = 0;
        const char *r = colon + 1;
        while (*r && isspace((unsigned char)*r)) ++r;
        snprintf(status, sizeof status, "%s", r);
    } else {
        snprintf(prefix, sizeof prefix, "%s", text);
        status[0] = 0;
    }
    int fs = (int)fmax(8, lround(fmin(g->H * 0.0227, g->W * 0.067)));
    lv_obj_t *p = st->capPrefix[which], *q = st->capStatus[which];
    lv_obj_set_style_text_font(p, hmi_font(fs, 600), 0);
    lv_obj_set_style_text_font(q, hmi_font(fs, 600), 0);
    lv_obj_set_style_text_color(q, caption_colour(s), 0);
    lv_label_set_text(p, prefix);
    lv_label_set_text(q, status);
    lv_obj_update_layout(p);
    lv_obj_update_layout(q);
    double pw = lv_obj_get_width(p), sw = status[0] ? lv_obj_get_width(q) : 0;
    double sep = status[0] ? fs * 0.3 : 0, L = pw + sep + sw;
    double cx = g->bx - g->W * 0.12, cy = g->H * (which ? 0.75 : 0.25);
    // Reads bottom-to-top: the prefix at the bottom, the status above it.
    place_rotated(p, cx, cy + L / 2 - pw / 2);
    place_rotated(q, cx, cy - L / 2 + sw / 2);
    if (status[0]) lv_obj_remove_flag(q, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(q, LV_OBJ_FLAG_HIDDEN);
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    geom_t g = geometry(w, st->n);
    int fs = (int)fmax(8, lround(fmin(g.H * 0.025, g.W * 0.075)));
    for (int i = 0; i < MAX_CARS; ++i) {
        lv_obj_t *l = st->carLabels[i];
        if (i >= st->n) { lv_obj_add_flag(l, LV_OBJ_FLAG_HIDDEN); continue; }
        lv_obj_remove_flag(l, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_text_font(l, hmi_font(fs, 500), 0);
        lv_label_set_text(l, st->names[i]);
        place_rotated(l, g.bx + g.bw + g.W * 0.12, g.top + i * (g.carH + g.gap) + g.carH / 2);
    }
    layout_caption(w, 0, &g);
    layout_caption(w, 1, &g);
    if (st->n >= 3) {
        double sy, sh, size = fmax(8, g.bw * 0.24);
        section(&g, 1, st->n, &sy, &sh);
        hmi_icon_set(st->lock, "lock", (int)lround(size), hmi_colour_hex("#d4d4d8", NULL));
        lv_obj_set_pos(st->lock, (int32_t)lround(g.bx + g.bw / 2 - size / 2), (int32_t)lround(sy + sh / 2 - size / 2));
        lv_obj_remove_flag(st->lock, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(st->lock, LV_OBJ_FLAG_HIDDEN);
    }
}

static void read_model(hmi_widget_t *w)
{
    state_t *st = w->state;
    parse_cars(st, hmi_widget_str(w, "cars", "MC1,M1,T1,T2,M2,MC2"));
    st->left = door_from_value(hmi_widget_get(w, "doorsLeft"), DOOR_CLOSED);
    st->right = door_from_value(hmi_widget_get(w, "doorsRight"), DOOR_DISABLED);
    snprintf(st->accent, sizeof st->accent, "%s", hmi_widget_str(w, "accent", "#a855f7"));
    snprintf(st->captions[0], sizeof st->captions[0], "%s", hmi_widget_str(w, "leftLabel", ""));
    snprintf(st->captions[1], sizeof st->captions[1], "%s", hmi_widget_str(w, "rightLabel", ""));
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *face = lv_obj_create(parent);
    lv_obj_remove_style_all(face);
    lv_obj_set_size(face, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(face, LV_OBJ_FLAG_SCROLLABLE);
    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;
    st->face = face;
    lv_color_t muted = hmi_colour_hex("#a1a1aa", NULL), white = hmi_colour_hex("#fafafa", NULL);
    for (int i = 0; i < MAX_CARS; ++i) st->carLabels[i] = hmi_make_label(face, 20, 500, muted, "");
    for (int k = 0; k < 2; ++k) {
        st->capPrefix[k] = hmi_make_label(face, 20, 600, white, "");
        st->capStatus[k] = hmi_make_label(face, 20, 600, muted, "");
    }
    st->lock = hmi_icon_create(face, "lock", 20, muted);
    lv_obj_add_event_cb(face, draw_cb, LV_EVENT_DRAW_MAIN, w);
    read_model(w);
    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "doorsLeft") == 0) st->left = door_from_value(value, st->left);
    else if (strcmp(prop, "doorsRight") == 0) st->right = door_from_value(value, st->right);
    else if (strcmp(prop, "cars") == 0) parse_cars(st, hmi_value_as_str(value, ""));
    else if (strcmp(prop, "accent") == 0) snprintf(st->accent, sizeof st->accent, "%s", hmi_value_as_str(value, "#a855f7"));
    else if (strcmp(prop, "leftLabel") == 0 || strcmp(prop, "rightLabel") == 0) {
        const char *t = hmi_value_as_str(value, NULL);
        int k = prop[0] == 'r';
        if (!t) return;
        snprintf(st->captions[k], sizeof st->captions[k], "%s", t);
    } else return;
    layout(w);
    lv_obj_invalidate(st->face);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shtrainconsist = {"ShTrainConsist", create, set_prop, destroy};
