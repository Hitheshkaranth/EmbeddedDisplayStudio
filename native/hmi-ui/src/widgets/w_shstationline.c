// widgets/w_shstationline.c -- kit widget ShStationLine (Rail, "Station Line").
//
// Spec: ui/qml/Shadcn/ShStationLine.qml -- a vertical route timeline. The
// stations (comma-separated `stations`, up to 8) sit at even steps from
// 0.09 h to 0.84 h on a 4 px line at x = 0.14 w: grey (#3f3f46) above the
// current station, `accent` from it down, a faint grey stub above the first
// node. Per station i, against `current`:
//   i <  current  a grey dot (#52525b, r 13), name and subtitle dim (#71717a);
//   i == current  a glow, a dark disc ringed in accent (r 38, 4 px) holding
//                 the white "train" icon (36 px); name bold white, subtitle accent;
//   i >  current  an accent dot (r 13), or a hollow accent ring (r 16) for the
//                 terminus; name semibold white, subtitle #a1a1aa.
// Names (34 px) start at x = 0.24 w, wrap to at most two lines, their first
// line centred on the node; the subtitle (22 px, from `details`, matched by
// position) sits under the name. Sizes scale by k = min(w / 520, h / 680).
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "icons.h"
#include "registry.h"

#define MAX_STATIONS 8
#define TEXT_LEN 128

typedef struct {
    lv_obj_t *face, *icon;
    lv_obj_t *name[MAX_STATIONS], *sub[MAX_STATIONS];
    char names[MAX_STATIONS][TEXT_LEN];
    char subs[MAX_STATIONS][TEXT_LEN];
    int count, current;
    lv_color_t accent;
    int nodeY[MAX_STATIONS];
} state_t;

// The geometry, shared by the draw callback and the layout (the QML's readonly properties).
typedef struct {
    double k;
    int lineX, lineW, top, bottom, textX, textW;
    int nameFs, subFs, nameLineH, gap;
    int dotR, ringR, ringW, termR, iconSz, stub;
} geom_t;

static geom_t geometry(const hmi_widget_t *w)
{
    geom_t g;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    g.k = fmin(W / 520.0, H / 680.0);
    g.lineX = (int)round(W * 0.14);
    g.lineW = hmi_px_min(4 * g.k, 2);
    g.top = (int)round(H * 0.09);
    g.bottom = (int)round(H * 0.84);
    g.textX = (int)round(W * 0.24);
    g.textW = (int)fmax(10, round(W - g.textX - W * 0.04));
    g.nameFs = hmi_px_min(34 * g.k, 8);
    g.subFs = hmi_px_min(22 * g.k, 7);
    g.nameLineH = (int)round(g.nameFs * 1.21);
    g.gap = (int)round(2 * g.k);
    g.dotR = hmi_px_min(13 * g.k, 3);
    g.ringR = hmi_px_min(38 * g.k, 6);
    g.ringW = hmi_px_min(4 * g.k, 2);
    g.termR = hmi_px_min(16 * g.k, 4);
    g.iconSz = hmi_px_min(36 * g.k, 6);
    g.stub = (int)round(H * 0.06);
    return g;
}

// Split a comma-separated list into trimmed fields. keep_empty keeps the
// field positions (details line up with stations by index).
static int split_list(const char *src, char out[][TEXT_LEN], int max, bool keep_empty)
{
    int n = 0;
    const char *p = src ? src : "";
    if (!*p) return 0;
    while (n < max) {
        const char *end = strchr(p, ',');
        size_t len = end ? (size_t)(end - p) : strlen(p);
        while (len > 0 && (*p == ' ' || *p == '\t')) { ++p; --len; }
        while (len > 0 && (p[len - 1] == ' ' || p[len - 1] == '\t')) --len;
        if (len >= TEXT_LEN) len = TEXT_LEN - 1;
        if (len > 0 || keep_empty) {
            memcpy(out[n], p, len);
            out[n][len] = '\0';
            ++n;
        }
        if (!end) break;
        p = end + 1;
    }
    return n;
}

static void read_stations(state_t *st, const hmi_value_t *v)
{
    memset(st->names, 0, sizeof st->names);
    if (v && v->kind == HMI_V_LIST) {
        int n = 0;
        for (size_t i = 0; i < v->count && n < MAX_STATIONS; ++i) {
            const char *s = hmi_value_as_str(&v->items[i], NULL);
            if (!s || !*s) continue;
            snprintf(st->names[n++], TEXT_LEN, "%s", s);
        }
        st->count = n;
        return;
    }
    st->count = split_list(v ? hmi_value_as_str(v, "") : "", st->names, MAX_STATIONS, false);
}

static void read_details(state_t *st, const hmi_value_t *v)
{
    memset(st->subs, 0, sizeof st->subs);
    if (v && v->kind == HMI_V_LIST) {
        for (size_t i = 0; i < v->count && i < MAX_STATIONS; ++i) {
            const hmi_value_t *it = &v->items[i];
            if (it->kind == HMI_V_NUM) snprintf(st->subs[i], TEXT_LEN, "%s", hmi_value_debug(it));
            else snprintf(st->subs[i], TEXT_LEN, "%s", hmi_value_as_str(it, ""));
        }
        return;
    }
    split_list(v ? hmi_value_as_str(v, "") : "", st->subs, MAX_STATIONS, true);
}

static void fill_circle(const hmi_draw_t *d, double cx, double cy, int r, lv_color_t c, lv_opa_t opa,
                        int border, lv_color_t bc)
{
    lv_draw_rect_dsc_t dsc;
    lv_draw_rect_dsc_init(&dsc);
    dsc.bg_color = c;
    dsc.bg_opa = opa;
    dsc.radius = LV_RADIUS_CIRCLE;
    dsc.border_width = border;
    dsc.border_color = bc;
    dsc.border_opa = border > 0 ? LV_OPA_COVER : LV_OPA_TRANSP;
    int x0 = (int)lround(cx) - r, y0 = (int)lround(cy) - r;
    lv_area_t a = {d->coords.x1 + x0, d->coords.y1 + y0, d->coords.x1 + x0 + 2 * r - 1, d->coords.y1 + y0 + 2 * r - 1};
    lv_draw_rect(d->layer, &dsc, &a);
}

static void draw_cb(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    state_t *st = w->state;
    if (!st || st->count == 0) return;
    hmi_draw_t d = hmi_draw_begin(e);
    geom_t g = geometry(w);
    lv_color_t grey = hmi_colour_hex("#3f3f46", NULL), passed = hmi_colour_hex("#52525b", NULL);
    lv_color_t dark = hmi_colour_hex("#18181b", NULL);
    int n = st->count, last = n - 1;
    int cur = st->current;
    int x = g.lineX - g.lineW / 2;

    // the line: a faint stub above the first node, grey to the train, accent after it
    hmi_draw_fill(&d, x, st->nodeY[0] - g.stub, g.lineW, g.stub, grey, LV_OPA_50, 0);
    if (n > 1) {
        int split = cur <= 0 ? st->nodeY[0] : (cur >= last ? st->nodeY[last] : st->nodeY[cur]);
        hmi_draw_fill(&d, x, st->nodeY[0], g.lineW, split - st->nodeY[0], grey, LV_OPA_COVER, 0);
        hmi_draw_fill(&d, x, split, g.lineW, st->nodeY[last] - split, st->accent, LV_OPA_COVER, 0);
    }

    for (int i = 0; i < n; ++i) {
        double cy = st->nodeY[i];
        if (i < cur) {
            fill_circle(&d, g.lineX, cy, g.dotR, passed, LV_OPA_COVER, 0, passed);
        } else if (i == cur) {
            // the halo: three soft accent discs, then the dark disc and its ring
            fill_circle(&d, g.lineX, cy, g.ringR + (int)round(22 * g.k), st->accent, (lv_opa_t)(0.07 * 255), 0, dark);
            fill_circle(&d, g.lineX, cy, g.ringR + (int)round(14 * g.k), st->accent, (lv_opa_t)(0.10 * 255), 0, dark);
            fill_circle(&d, g.lineX, cy, g.ringR + (int)round(7 * g.k), st->accent, (lv_opa_t)(0.16 * 255), 0, dark);
            fill_circle(&d, g.lineX, cy, g.ringR, dark, LV_OPA_COVER, g.ringW, st->accent);
        } else if (i == last) {
            fill_circle(&d, g.lineX, cy, g.termR, dark, LV_OPA_COVER, g.ringW, st->accent);
        } else {
            fill_circle(&d, g.lineX, cy, g.dotR, st->accent, LV_OPA_COVER, 0, st->accent);
        }
    }
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    geom_t g = geometry(w);
    int n = st->count;
    lv_color_t white = hmi_colour_hex("#fafafa", NULL), dim = hmi_colour_hex("#71717a", NULL);
    lv_color_t muted = hmi_colour_hex("#a1a1aa", NULL);

    for (int i = 0; i < MAX_STATIONS; ++i) {
        if (i >= n) {
            lv_obj_add_flag(st->name[i], LV_OBJ_FLAG_HIDDEN);
            lv_obj_add_flag(st->sub[i], LV_OBJ_FLAG_HIDDEN);
            continue;
        }
        st->nodeY[i] = n > 1 ? (int)round(g.top + i * (double)(g.bottom - g.top) / (n - 1)) : g.top;
        bool isPassed = i < st->current, isCurrent = i == st->current;
        lv_obj_t *nm = st->name[i], *sb = st->sub[i];
        lv_obj_remove_flag(nm, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_text_font(nm, hmi_font(g.nameFs, isCurrent ? 700 : 600), 0);
        lv_obj_set_style_text_color(nm, isPassed ? dim : white, 0);
        lv_obj_set_style_text_line_space(nm, g.nameLineH - lv_font_get_line_height(hmi_font(g.nameFs, 600)), 0);
        lv_obj_set_width(nm, g.textW);
        lv_obj_set_height(nm, LV_SIZE_CONTENT);
        lv_obj_set_style_max_height(nm, 2 * g.nameLineH, 0);
        lv_label_set_long_mode(nm, LV_LABEL_LONG_DOT);
        lv_label_set_text(nm, st->names[i]);
        int nameY = st->nodeY[i] - (int)round(g.nameFs * 0.6);
        lv_obj_set_pos(nm, g.textX, nameY);
        lv_obj_update_layout(nm);
        int lines = lv_obj_get_height(nm) > g.nameLineH + g.nameLineH / 2 ? 2 : 1;

        if (st->subs[i][0]) lv_obj_remove_flag(sb, LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(sb, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_text_font(sb, hmi_font(g.subFs, 400), 0);
        lv_obj_set_style_text_color(sb, isPassed ? dim : (isCurrent ? st->accent : muted), 0);
        lv_obj_set_width(sb, g.textW);
        lv_label_set_text(sb, st->subs[i]);
        lv_obj_set_pos(sb, g.textX, nameY + lines * g.nameLineH + g.gap);
    }

    if (st->current >= 0 && st->current < n) {
        hmi_icon_set(st->icon, "train", g.iconSz, white);
        lv_obj_set_pos(st->icon, g.lineX - g.iconSz / 2, st->nodeY[st->current] - g.iconSz / 2);
        lv_obj_remove_flag(st->icon, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(st->icon, LV_OBJ_FLAG_HIDDEN);
    }
    lv_obj_invalidate(st->face);
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
    for (int i = 0; i < MAX_STATIONS; ++i) {
        st->name[i] = hmi_make_label(face, 12, 600, hmi_colour_hex("#fafafa", NULL), "");
        st->sub[i] = hmi_make_label(face, 12, 400, hmi_colour_hex("#a1a1aa", NULL), "");
    }
    st->icon = hmi_icon_create(face, "train", 36, hmi_colour_hex("#fafafa", NULL));
    read_stations(st, hmi_widget_get(w, "stations"));
    read_details(st, hmi_widget_get(w, "details"));
    st->current = (int)lround(hmi_widget_num(w, "current", 1));
    st->accent = hmi_colour_hex(hmi_widget_str(w, "accent", "#a855f7"), NULL);
    lv_obj_add_event_cb(face, draw_cb, LV_EVENT_DRAW_MAIN, w);
    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "stations") == 0) read_stations(st, value);
    else if (strcmp(prop, "details") == 0) read_details(st, value);
    else if (strcmp(prop, "current") == 0) st->current = (int)lround(hmi_value_as_num(value, st->current));
    else if (strcmp(prop, "accent") == 0) st->accent = hmi_colour_hex(hmi_value_as_str(value, "#a855f7"), NULL);
    else return;
    layout(w);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shstationline = {"ShStationLine", create, set_prop, destroy};
