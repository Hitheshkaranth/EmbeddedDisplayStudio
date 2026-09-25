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
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

enum { HEADER_H = 36, SPACING = 8, DOT = 8, STATE_W = 28, TS_W = 64 };

typedef struct {
    hmi_value_t alarms;         // the last list delivered
    int maxVisible, rowHeight;
    bool showTimestamp;
    lv_obj_t *root, *header, *title, *badge, *badgeText, *body, *empty;
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
    uint32_t index = lv_obj_get_index(row);   // child 0 of the body is the empty-state label
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

// Rebuild the rows from st->alarms (children of body after the empty label).
static void build_rows(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width);
    while (lv_obj_get_child_count(st->body) > 1) lv_obj_delete(lv_obj_get_child(st->body, 1));
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
    lv_obj_set_size(st->header, (int)W, HEADER_H);
    lv_label_set_text(st->title, hmi_widget_str(w, "title", "Active Alarms"));
    lv_obj_set_size(st->title, (int)fmax(1, W - 56), lv_font_get_line_height(hmi_font(hmi_font_size("fontSizeSm"), 600)));
    lv_obj_set_pos(st->title, SPACING, (HEADER_H - lv_font_get_line_height(hmi_font(hmi_font_size("fontSizeSm"), 600))) / 2);
    size_t n = st->alarms.kind == HMI_V_LIST ? st->alarms.count : 0;
    lv_label_set_text_fmt(st->badgeText, "%u", (unsigned)n);
    lv_obj_update_layout(st->badgeText);
    int badgeW = lv_obj_get_width(st->badgeText) + 20;
    lv_obj_set_size(st->badge, badgeW, 20);
    lv_obj_set_pos(st->badge, (int)W - SPACING - badgeW, (HEADER_H - 20) / 2);
    lv_obj_center(st->badgeText);
    lv_obj_set_size(st->body, (int)W, (int)fmax(1, H - HEADER_H));
    lv_obj_set_pos(st->body, 0, HEADER_H);
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
