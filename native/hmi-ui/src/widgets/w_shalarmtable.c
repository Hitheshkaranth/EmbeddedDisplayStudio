// widgets/w_shalarmtable.c -- kit widget ShAlarmTable (Industrial, "Alarm Table").
//
// Spec: ui/qml/Shadcn/ShAlarmTable.qml: a 36 px header (Theme.secondary,
// radiusSm) with the title (sm semibold, elided, width - 56) and a
// secondary ShBadge holding the alarm count at the right; below it a
// bordered Theme.background body that says "No active alarms" or lists one
// row per alarm (rowHeight tall, Theme.accent until acknowledged, 1 px
// border line at the bottom): an 8 px ShStatDot by severity, the message
// (sm, elided), "NEW"/"ACK" (10 px, brand/muted, 28 wide) and the
// timestamp (10 px, muted, 64 wide, right-aligned; hidden by showTimestamp).
// Tapping a row emits alarmActivated with the alarm's tag.
//
// The `alarms` property arrives from the runtime as the alarm engine's
// HMI_V_LIST of [tag, label, severity, value, message, timestamp,
// acknowledged] lists (alarms.h).
//
// Table view (`columns` or `sampleRows` set; both default "" = the list
// above, unchanged): a compact title bar clamp(round(0.17 H), 22, 36) tall,
// a column header row clamp(round(0.13 H), 16, 24) tall (Theme.secondary,
// mutedForeground) when `columns` ("Time,Tag,Description,Priority,Status")
// is set, and one row per alarm with a cell per column -- a column is
// filled from the alarm by its name (time, tag, description/message,
// priority/severity -> HIGH/MEDIUM/LOW, status -> ACTIVE/ACKED, value,
// label). While no live alarm exists the `sampleRows` ("a|b|c;d|e|f") are
// drawn instead of "No active alarms", so a design shows its picture's
// rows; they share the body's height (at most rowHeight each). A cell
// reading HIGH/CRITICAL, MEDIUM, LOW, ACTIVE or ACKED is a small pill (red,
// amber, blue; ACTIVE a red outline on a red tint, ACKED a grey outline); a
// row holding ACTIVE draws its other cells in Theme.destructive. Column
// widths are each column's widest text plus 2 x 8 px, scaled together to the
// width. Thin Theme.border lines separate the columns.
//
// headerColor ("" = Theme.secondary) colours the title bar; on it the title
// is white or near-black by its luminance. showCount (true) shows the badge.
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"
#include "text_util.h"

enum { HEADER_H = 36, SPACING = 8, DOT = 8, STATE_W = 28, TS_W = 64 };
enum { MAX_COLS = 8, MAX_SAMPLES = 16, CELL_LEN = 96, PAD = 8 };

typedef struct {
    hmi_value_t alarms;         // the last list delivered
    int maxVisible, rowHeight;
    bool showTimestamp, showCount;
    lv_obj_t *root, *header, *title, *badge, *badgeText, *body, *empty;
    char headerColour[32];
    char cols[MAX_COLS][32];
    int nCols;
    char samples[MAX_SAMPLES][MAX_COLS][CELL_LEN];
    int nSamples, sampleCols;
} state_t;

static const char *cell(const hmi_value_t *row, size_t i, const char *def)
{
    if (row->kind != HMI_V_LIST || i >= row->count) return def;
    return hmi_value_as_str(&row->items[i], def);
}

static bool cell_bool(const hmi_value_t *row, size_t i)
{
    if (row->kind != HMI_V_LIST || i >= row->count) return false;
    return hmi_value_as_bool(&row->items[i], false);
}

static void row_clicked(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    state_t *st = w->state;
    lv_obj_t *row = lv_event_get_current_target(e);
    // Each alarm row carries its index + 1 (0 = not an alarm row).
    uintptr_t index = (uintptr_t)lv_obj_get_user_data(row);
    if (index == 0 || index - 1 >= st->alarms.count) return;
    --index;
    hmi_value_t tag = hmi_value_str(cell(&st->alarms.items[index], 0, ""));
    hmi_widget_emit(w, "alarmActivated", &tag);
    hmi_value_free(&tag);
}

static lv_obj_t *plain(lv_obj_t *parent)
{
    lv_obj_t *o = lv_obj_create(parent);
    lv_obj_remove_style_all(o);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    return o;
}

static bool table_mode(const state_t *st) { return st->nCols > 0 || st->nSamples > 0; }

// -- parsing -------------------------------------------------------------------

static void copy_trim(char *dst, size_t n, const char *src, size_t len)
{
    while (len && (*src == ' ' || *src == '\t')) { ++src; --len; }
    while (len && (src[len - 1] == ' ' || src[len - 1] == '\t')) --len;
    if (len >= n) len = n - 1;
    memcpy(dst, src, len);
    dst[len] = '\0';
}

// Splits `spec` at `sep` into up to `max` trimmed fields of `width` chars.
static int split(const char *spec, char sep, char *out, int max, size_t width)
{
    int n = 0;
    const char *p = spec ? spec : "";
    if (!*p) return 0;
    while (n < max) {
        const char *end = strchr(p, sep);
        size_t len = end ? (size_t)(end - p) : strlen(p);
        copy_trim(out + (size_t)n * width, width, p, len);
        ++n;
        if (!end) break;
        p = end + 1;
    }
    return n;
}

static void parse_columns(state_t *st, const char *spec)
{
    st->nCols = split(spec, ',', &st->cols[0][0], MAX_COLS, sizeof st->cols[0]);
}

static void parse_samples(state_t *st, const char *spec)
{
    st->nSamples = 0;
    st->sampleCols = 0;
    const char *p = spec ? spec : "";
    while (*p && st->nSamples < MAX_SAMPLES) {
        const char *end = strchr(p, ';');
        size_t len = end ? (size_t)(end - p) : strlen(p);
        char row[MAX_COLS * CELL_LEN];
        copy_trim(row, sizeof row, p, len);
        if (row[0]) {
            int nc = split(row, '|', &st->samples[st->nSamples][0][0], MAX_COLS, CELL_LEN);
            for (int c = nc; c < MAX_COLS; ++c) st->samples[st->nSamples][c][0] = '\0';
            if (nc > st->sampleCols) st->sampleCols = nc;
            st->nSamples++;
        }
        if (!end) break;
        p = end + 1;
    }
}

// -- table cells -----------------------------------------------------------------

static bool ieq(const char *a, const char *b)
{
    for (; *a && *b; ++a, ++b) {
        char x = *a >= 'A' && *a <= 'Z' ? (char)(*a + 32) : *a;
        char y = *b >= 'A' && *b <= 'Z' ? (char)(*b + 32) : *b;
        if (x != y) return false;
    }
    return *a == *b;
}

// A live alarm's text for the column named `name`.
static const char *alarm_cell(const hmi_value_t *al, const char *name, char *buf, size_t n)
{
    if (ieq(name, "time") || ieq(name, "timestamp") || ieq(name, "date")) return cell(al, 5, "");
    if (ieq(name, "tag") || ieq(name, "id")) return cell(al, 0, "");
    if (ieq(name, "label") || ieq(name, "name")) return cell(al, 1, "");
    if (ieq(name, "description") || ieq(name, "message") || ieq(name, "alarm") || ieq(name, "text")
        || ieq(name, "event")) {
        const char *m = cell(al, 4, "");
        return m[0] ? m : "Alarm";
    }
    if (ieq(name, "priority") || ieq(name, "severity") || ieq(name, "level")) {
        const char *s = cell(al, 2, "");
        return strcmp(s, "fault") == 0 ? "HIGH"
             : (strcmp(s, "warning") == 0 || strcmp(s, "caution") == 0) ? "MEDIUM" : "LOW";
    }
    if (ieq(name, "status") || ieq(name, "state") || ieq(name, "ack")) return cell_bool(al, 6) ? "ACKED" : "ACTIVE";
    if (ieq(name, "value")) {
        if (al->kind == HMI_V_LIST && al->count > 3) return hmi_text_of(&al->items[3], buf, n, "");
        return "";
    }
    return "";
}

typedef enum { PILL_NONE, PILL_HIGH, PILL_MEDIUM, PILL_LOW, PILL_ACTIVE, PILL_ACKED } pill_t;

static pill_t pill_of(const char *text)
{
    if (ieq(text, "HIGH") || ieq(text, "CRITICAL")) return PILL_HIGH;
    if (ieq(text, "MEDIUM")) return PILL_MEDIUM;
    if (ieq(text, "LOW")) return PILL_LOW;
    if (ieq(text, "ACTIVE")) return PILL_ACTIVE;
    if (ieq(text, "ACKED")) return PILL_ACKED;
    return PILL_NONE;
}

// Table metrics for a body of height bodyH.
typedef struct {
    int headH, colH, rowH, px, pillH;
    int ncols;
    int x[MAX_COLS + 1];
} table_t;

static int pill_w(const char *text, int px) { return hmi_text_w(text, px - 1, 600) + 16; }

static void table_metrics(const state_t *st, double W, double H, int nrows, const char *(*cells)[MAX_COLS],
                          table_t *t)
{
    t->headH = (int)fmax(22, fmin(36, lround(H * 0.17)));
    t->colH = st->nCols > 0 ? (int)fmax(16, fmin(24, lround(H * 0.13))) : 0;
    int avail = (int)fmax(1, H - t->headH - t->colH);
    int rh = st->rowHeight > 0 ? st->rowHeight : 30;
    if (st->nSamples > 0) rh = (int)fmin(rh, fmax(14, avail / st->nSamples));
    t->rowH = rh;
    t->px = (int)fmax(9, fmin(13, lround(rh * 0.6)));
    t->pillH = (int)fmax(12, fmin(22, lround(rh * 0.64)));
    t->ncols = st->nCols > 0 ? st->nCols : st->sampleCols;
    if (t->ncols < 1) t->ncols = 1;
    int nat[MAX_COLS], sum = 0;
    for (int c = 0; c < t->ncols; ++c) {
        int m = st->nCols > 0 ? hmi_text_w(st->cols[c], (int)fmax(9, t->px - 1), 500) : 0;
        for (int r = 0; r < nrows; ++r) {
            const char *s = cells[r][c] ? cells[r][c] : "";
            int tw = pill_of(s) != PILL_NONE ? pill_w(s, t->px) : hmi_text_w(s, t->px, 400);
            if (tw > m) m = tw;
        }
        nat[c] = m + 2 * PAD;
        sum += nat[c];
    }
    // Room to spare: every column grows in proportion. Too narrow: the
    // columns that fit a fair share keep their width (times, pills) and the
    // wide ones share what is left in proportion (water-filling).
    double width[MAX_COLS];
    if (sum <= W) {
        for (int c = 0; c < t->ncols; ++c) width[c] = nat[c] * W / (sum > 0 ? sum : 1);
    } else {
        bool fixed[MAX_COLS] = {false};
        double left = W;
        for (int pass = 0; pass < MAX_COLS; ++pass) {
            int flex = 0;
            double flexSum = 0;
            for (int c = 0; c < t->ncols; ++c)
                if (!fixed[c]) { ++flex; flexSum += nat[c]; }
            if (flex == 0) break;
            bool changed = false;
            for (int c = 0; c < t->ncols; ++c)
                if (!fixed[c] && nat[c] <= left / flex) {
                    fixed[c] = true;
                    width[c] = nat[c];
                    left -= nat[c];
                    changed = true;
                }
            if (!changed) {
                for (int c = 0; c < t->ncols; ++c)
                    if (!fixed[c]) width[c] = nat[c] * fmax(0, left) / flexSum;
                break;
            }
        }
    }
    double x = 0;
    for (int c = 0; c < t->ncols; ++c) {
        t->x[c] = (int)lround(x);
        x += width[c];
    }
    t->x[t->ncols] = (int)lround(W);
}

static lv_obj_t *vline(lv_obj_t *parent, int x, int h)
{
    lv_obj_t *l = plain(parent);
    lv_obj_set_size(l, 1, h);
    lv_obj_set_pos(l, x, 0);
    lv_obj_set_style_bg_color(l, hmi_colour("border"), 0);
    lv_obj_set_style_bg_opa(l, LV_OPA_COVER, 0);
    return l;
}

// One table cell: plain text, or a pill.
static void table_cell(lv_obj_t *row, const table_t *t, int c, const char *text, lv_color_t ink)
{
    int cx = t->x[c], cw = t->x[c + 1] - t->x[c];
    pill_t pill = pill_of(text);
    if (pill == PILL_NONE) {
        int lh = hmi_text_line_h(t->px, 400);
        lv_obj_t *l = hmi_make_label(row, t->px, 400, ink, "");
        hmi_text_place(l, text, t->px, 400, 1.0, cx + PAD, (t->rowH - lh) / 2, cw - 2 * PAD, ink, LV_OPA_COVER,
                       LV_TEXT_ALIGN_LEFT);
        return;
    }
    int ppx = (int)fmax(8, t->px - 1);
    int pw = (int)fmin(cw - 2 * PAD + 4, fmax(pill_w(text, t->px), lround(cw * 0.62)));
    if (pw < 8) return;
    lv_color_t fill, fg, edge = lv_color_hex(0);
    lv_opa_t fillOpa = LV_OPA_COVER;
    int border = 0;
    switch (pill) {
    case PILL_HIGH: fill = hmi_colour("destructive"); fg = lv_color_hex(0xffffff); break;
    case PILL_MEDIUM: fill = hmi_colour("warning"); fg = lv_color_hex(0x1a1203); break;
    case PILL_LOW: fill = hmi_colour("info"); fg = lv_color_hex(0xffffff); break;
    case PILL_ACTIVE:
        fill = hmi_colour("destructive"); fillOpa = (lv_opa_t)56; fg = hmi_colour("destructive");
        edge = fg; border = 1; break;
    default:
        fill = hmi_colour("muted"); fillOpa = LV_OPA_TRANSP; fg = hmi_colour("mutedForeground");
        edge = fg; border = 1; break;
    }
    lv_obj_t *p = plain(row);
    lv_obj_set_pos(p, cx + PAD - 2, (t->rowH - t->pillH) / 2);
    lv_obj_set_size(p, pw, t->pillH);
    lv_obj_set_style_radius(p, 3, 0);
    lv_obj_set_style_bg_color(p, fill, 0);
    lv_obj_set_style_bg_opa(p, fillOpa, 0);
    if (border) {
        lv_obj_set_style_border_color(p, edge, 0);
        lv_obj_set_style_border_width(p, 1, 0);
    }
    int lh = hmi_text_line_h(ppx, 600);
    lv_obj_t *l = hmi_make_label(p, ppx, 600, fg, "");
    hmi_text_place(l, text, ppx, 600, 0.8, 2 - border, (t->pillH - lh) / 2 - border, pw - 4, fg, LV_OPA_COVER,
                   LV_TEXT_ALIGN_CENTER);
}

// The table view's rows (children of body after the empty label).
static void build_table(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    size_t live = st->alarms.kind == HMI_V_LIST ? st->alarms.count : 0;
    bool sample = live == 0 && st->nSamples > 0;
    int nrows = sample ? st->nSamples : (st->nCols > 0 ? (int)(live > MAX_SAMPLES ? MAX_SAMPLES : live) : 0);
    static char buf[MAX_SAMPLES][MAX_COLS][32];
    const char *cells[MAX_SAMPLES][MAX_COLS];
    for (int r = 0; r < nrows; ++r)
        for (int c = 0; c < MAX_COLS; ++c) {
            if (sample) cells[r][c] = st->samples[r][c];
            else cells[r][c] = c < st->nCols ? alarm_cell(&st->alarms.items[r], st->cols[c], buf[r][c], sizeof buf[0][0])
                                             : "";
        }
    table_t t;
    table_metrics(st, W, H, nrows, cells, &t);
    int bodyH = (int)fmax(1, H - t.headH);

    if (st->nCols > 0) {
        lv_obj_t *hr = plain(st->body);
        lv_obj_set_pos(hr, -1, -1);
        lv_obj_set_size(hr, (int)W, t.colH);
        lv_obj_set_style_bg_color(hr, hmi_colour("secondary"), 0);
        lv_obj_set_style_bg_opa(hr, LV_OPA_COVER, 0);
        int hpx = (int)fmax(9, t.px - 1);
        int lh = hmi_text_line_h(hpx, 500);
        for (int c = 0; c < t.ncols; ++c) {
            lv_obj_t *l = hmi_make_label(hr, hpx, 500, hmi_colour("mutedForeground"), "");
            hmi_text_place(l, st->cols[c], hpx, 500, 0.8, t.x[c] + PAD, (t.colH - lh) / 2,
                           t.x[c + 1] - t.x[c] - 2 * PAD, hmi_colour("mutedForeground"), LV_OPA_COVER,
                           LV_TEXT_ALIGN_LEFT);
            if (c > 0) vline(hr, t.x[c], t.colH);
        }
        lv_obj_t *line = plain(hr);
        lv_obj_set_size(line, (int)W, 1);
        lv_obj_set_pos(line, 0, t.colH - 1);
        lv_obj_set_style_bg_color(line, hmi_colour("border"), 0);
        lv_obj_set_style_bg_opa(line, LV_OPA_COVER, 0);
    }
    // Rows below the body's bottom edge are never seen; only build those that fit.
    int fit = (int)((bodyH - t.colH) / (t.rowH > 0 ? t.rowH : 1)) + 1;
    int shown = nrows < fit ? nrows : fit;
    for (int r = 0; r < shown; ++r) {
        bool active = false;
        for (int c = 0; c < t.ncols; ++c)
            if (pill_of(cells[r][c]) == PILL_ACTIVE) active = true;
        lv_color_t ink = active ? hmi_colour("destructive") : hmi_colour("foreground");
        lv_obj_t *row = plain(st->body);
        lv_obj_set_size(row, (int)W, t.rowH);
        lv_obj_set_pos(row, -1, -1 + t.colH + r * t.rowH);
        if (!sample) {
            lv_obj_add_flag(row, LV_OBJ_FLAG_CLICKABLE);
            lv_obj_set_user_data(row, (void *)(uintptr_t)(r + 1));
            lv_obj_add_event_cb(row, row_clicked, LV_EVENT_CLICKED, w);
            bool ack = cell_bool(&st->alarms.items[r], 6);
            lv_obj_set_style_bg_color(row, hmi_colour("accent"), 0);
            lv_obj_set_style_bg_opa(row, ack ? LV_OPA_TRANSP : (lv_opa_t)90, 0);
        }
        for (int c = 0; c < t.ncols; ++c) {
            table_cell(row, &t, c, cells[r][c], ink);
            if (c > 0) vline(row, t.x[c], t.rowH);
        }
        lv_obj_t *line = plain(row);
        lv_obj_set_size(line, (int)W, 1);
        lv_obj_set_pos(line, 0, t.rowH - 1);
        lv_obj_set_style_bg_color(line, hmi_colour("border"), 0);
        lv_obj_set_style_bg_opa(line, LV_OPA_COVER, 0);
    }
    if (nrows == 0) {
        lv_obj_remove_flag(st->empty, LV_OBJ_FLAG_HIDDEN);
        lv_obj_align(st->empty, LV_ALIGN_CENTER, 0, t.colH / 2);
    } else {
        lv_obj_add_flag(st->empty, LV_OBJ_FLAG_HIDDEN);
    }
}

// Rebuild the rows from st->alarms (children of body after the empty label).
static void build_rows(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width);
    while (lv_obj_get_child_count(st->body) > 1) lv_obj_delete(lv_obj_get_child(st->body, 1));
    if (table_mode(st)) {
        build_table(w);
        return;
    }
    size_t n = st->alarms.kind == HMI_V_LIST ? st->alarms.count : 0;
    if (n == 0) lv_obj_remove_flag(st->empty, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(st->empty, LV_OBJ_FLAG_HIDDEN);
    int rowH = st->rowHeight > 0 ? st->rowHeight : 30;
    int tsW = st->showTimestamp ? TS_W : 0;
    // The row's text columns, right to left: timestamp, state, message.
    int tsX = (int)W - SPACING - tsW;
    int stateX = tsX - SPACING - STATE_W;
    int msgX = SPACING + DOT + SPACING;
    int msgW = stateX - SPACING - msgX;
    // The body does not scroll: rows below its bottom edge are never seen,
    // so only build the ones that fit (a long alarm list stays cheap).
    size_t fit = (size_t)(fmax(1, w->height - HEADER_H) / rowH) + 1;
    if (n > fit) n = fit;
    int smH = lv_font_get_line_height(hmi_font(hmi_font_size("fontSizeSm"), 400));
    int xsH = lv_font_get_line_height(hmi_font(10, 400));
    for (size_t i = 0; i < n; ++i) {
        const hmi_value_t *al = &st->alarms.items[i];
        bool ack = cell_bool(al, 6);
        const char *severity = cell(al, 2, "");
        lv_obj_t *row = plain(st->body);
        // The list fills the body (over its border): rows start at -1, -1.
        lv_obj_set_size(row, (int)W, rowH);
        lv_obj_set_pos(row, -1, -1 + (int)i * rowH);
        lv_obj_add_flag(row, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_set_user_data(row, (void *)(uintptr_t)(i + 1));
        lv_obj_set_style_bg_color(row, hmi_colour("accent"), 0);
        lv_obj_set_style_bg_opa(row, ack ? LV_OPA_TRANSP : LV_OPA_COVER, 0);
        lv_obj_add_event_cb(row, row_clicked, LV_EVENT_CLICKED, w);
        lv_obj_t *line = plain(row);
        lv_obj_set_size(line, (int)W, 1);
        lv_obj_set_pos(line, 0, rowH - 1);
        lv_obj_set_style_bg_color(line, hmi_colour("border"), 0);
        lv_obj_set_style_bg_opa(line, LV_OPA_COVER, 0);
        // ShStatDot: fault -> destructive, warning/caution -> warning, else ok
        const char *dotTok = strcmp(severity, "fault") == 0 ? "destructive"
                           : (strcmp(severity, "warning") == 0 || strcmp(severity, "caution") == 0) ? "warning" : "success";
        lv_obj_t *dot = plain(row);
        lv_obj_set_size(dot, DOT, DOT);
        lv_obj_set_pos(dot, SPACING, (rowH - DOT) / 2);
        lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_bg_color(dot, hmi_colour(dotTok), 0);
        lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
        const char *msg = cell(al, 4, "");
        lv_obj_t *message = hmi_make_label(row, hmi_font_size("fontSizeSm"), 400,
                                           hmi_colour(ack ? "mutedForeground" : "foreground"), msg[0] ? msg : "Alarm");
        lv_label_set_long_mode(message, LV_LABEL_LONG_DOT);
        lv_obj_set_size(message, msgW > 0 ? msgW : 1, smH);
        lv_obj_set_pos(message, msgX, (rowH - smH) / 2);
        lv_obj_t *state = hmi_make_label(row, 10, 400, hmi_colour(ack ? "mutedForeground" : "brand"), ack ? "ACK" : "NEW");
        lv_obj_set_width(state, STATE_W);
        lv_obj_set_pos(state, stateX, (rowH - xsH) / 2);
        if (st->showTimestamp) {
            lv_obj_t *ts = hmi_make_label(row, 10, 400, hmi_colour("mutedForeground"), cell(al, 5, ""));
            lv_label_set_long_mode(ts, LV_LABEL_LONG_DOT);
            lv_obj_set_size(ts, TS_W, xsH);
            lv_obj_set_style_text_align(ts, LV_TEXT_ALIGN_RIGHT, 0);
            lv_obj_set_pos(ts, tsX, (rowH - xsH) / 2);
        }
    }
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    bool table = table_mode(st);
    int headH = table ? (int)fmax(22, fmin(36, lround(H * 0.17))) : HEADER_H;
    lv_color_t headFill = hmi_colour("secondary"), titleInk = hmi_colour("foreground");
    lv_opa_t headOpa = LV_OPA_COVER;
    if (st->headerColour[0] == '#') {
        headFill = hmi_colour_hex(st->headerColour, &headOpa);
        titleInk = hmi_ink_on(headFill);
    }
    lv_obj_set_style_bg_color(st->header, headFill, 0);
    lv_obj_set_style_bg_opa(st->header, headOpa, 0);
    lv_obj_set_style_text_color(st->title, titleInk, 0);
    lv_obj_set_size(st->header, (int)W, headH);
    lv_label_set_text(st->title, hmi_widget_str(w, "title", "Active Alarms"));
    lv_obj_set_size(st->title, (int)fmax(1, W - (st->showCount ? 56 : 16)), lv_font_get_line_height(hmi_font(hmi_font_size("fontSizeSm"), 600)));
    lv_obj_set_pos(st->title, SPACING, (headH - lv_font_get_line_height(hmi_font(hmi_font_size("fontSizeSm"), 600))) / 2);
    size_t n = st->alarms.kind == HMI_V_LIST ? st->alarms.count : 0;
    // A design preview counts the sample rows it shows.
    if (n == 0 && table && st->nSamples > 0) n = (size_t)st->nSamples;
    lv_label_set_text_fmt(st->badgeText, "%u", (unsigned)n);
    lv_obj_update_layout(st->badgeText);
    int badgeW = lv_obj_get_width(st->badgeText) + 20;
    int badgeH = headH < 28 ? headH - 6 : 20;
    lv_obj_set_size(st->badge, badgeW, badgeH);
    lv_obj_set_pos(st->badge, (int)W - SPACING - badgeW, (headH - badgeH) / 2);
    lv_obj_center(st->badgeText);
    if (st->showCount) lv_obj_remove_flag(st->badge, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(st->badge, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_size(st->body, (int)W, (int)fmax(1, H - headH));
    lv_obj_set_pos(st->body, 0, headH);
    lv_obj_center(st->empty);
    build_rows(w);
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *root = plain(parent);
    lv_obj_set_size(root, (int32_t)w->width, (int32_t)w->height);
    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;
    st->root = root;
    st->alarms = hmi_value_null();
    st->alarms.kind = HMI_V_LIST;
    st->header = plain(root);
    lv_obj_set_style_bg_color(st->header, hmi_colour("secondary"), 0);
    lv_obj_set_style_bg_opa(st->header, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(st->header, hmi_radius("radiusSm"), 0);
    st->title = hmi_make_label(st->header, hmi_font_size("fontSizeSm"), 600, hmi_colour("foreground"), "");
    lv_label_set_long_mode(st->title, LV_LABEL_LONG_DOT);
    st->badge = plain(st->header);
    lv_obj_set_style_radius(st->badge, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(st->badge, hmi_colour("secondary"), 0);
    lv_obj_set_style_bg_opa(st->badge, LV_OPA_COVER, 0);
    st->badgeText = hmi_make_label(st->badge, hmi_font_size("fontSizeXs"), 600, hmi_colour("secondaryForeground"), "0");
    st->body = plain(root);
    lv_obj_set_style_bg_color(st->body, hmi_colour("background"), 0);
    lv_obj_set_style_bg_opa(st->body, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(st->body, hmi_colour("border"), 0);
    lv_obj_set_style_border_width(st->body, 1, 0);
    st->empty = hmi_make_label(st->body, hmi_font_size("fontSizeSm"), 400, hmi_colour("mutedForeground"), "No active alarms");

    st->maxVisible = (int)hmi_widget_num(w, "maxVisible", 6);
    st->rowHeight = (int)hmi_widget_num(w, "rowHeight", 30);
    st->showTimestamp = hmi_widget_bool(w, "showTimestamp", true);
    st->showCount = hmi_widget_bool(w, "showCount", true);
    snprintf(st->headerColour, sizeof st->headerColour, "%s", hmi_widget_str(w, "headerColor", ""));
    parse_columns(st, hmi_widget_str(w, "columns", ""));
    parse_samples(st, hmi_widget_str(w, "sampleRows", ""));
    const hmi_value_t *initial = hmi_widget_get(w, "alarms");
    if (initial && initial->kind == HMI_V_LIST) st->alarms = hmi_value_copy(initial);
    layout(w);
    return root;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "alarms") == 0) {
        hmi_value_free(&st->alarms);
        if (value->kind == HMI_V_LIST) st->alarms = hmi_value_copy(value);
        else { st->alarms = hmi_value_null(); st->alarms.kind = HMI_V_LIST; }
    } else if (strcmp(prop, "maxVisible") == 0) st->maxVisible = (int)hmi_value_as_num(value, st->maxVisible);
    else if (strcmp(prop, "rowHeight") == 0) st->rowHeight = (int)hmi_value_as_num(value, st->rowHeight);
    else if (strcmp(prop, "showTimestamp") == 0) st->showTimestamp = hmi_value_as_bool(value, st->showTimestamp);
    else if (strcmp(prop, "showCount") == 0) st->showCount = hmi_value_as_bool(value, st->showCount);
    else if (strcmp(prop, "headerColor") == 0)
        snprintf(st->headerColour, sizeof st->headerColour, "%s", hmi_value_as_str(value, ""));
    else if (strcmp(prop, "columns") == 0) parse_columns(st, hmi_value_as_str(value, ""));
    else if (strcmp(prop, "sampleRows") == 0) parse_samples(st, hmi_value_as_str(value, ""));
    else if (strcmp(prop, "title") != 0) return;
    layout(w);
}

static void destroy(hmi_widget_t *w)
{
    state_t *st = w->state;
    if (!st) return;
    hmi_value_free(&st->alarms);
    lv_free(st);
}

const hmi_widget_ops_t hmi_widget_shalarmtable = {"ShAlarmTable", create, set_prop, destroy};
