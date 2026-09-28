// runtime.c -- see runtime.h.
#include "runtime.h"

#include <stdlib.h>
#include <string.h>

#include "actions.h"
#include "alarms.h"
#include "journal.h"
#include "log.h"
#include "overlay.h"
#include "registry.h"
#include "theme.h"

#define BACK_DEPTH 16

struct hmi_runtime {
    hmi_project_t *project;
    lv_obj_t *screen;
    hmi_tags_t *tags;
    hmi_bind_t *bind;
    hmi_page_t *page;
    lv_obj_t *page_obj;     // container for the page's widgets
    hmi_page_t *pending;    // navigation requested, applied by hmi_runtime_tick
    bool pending_is_back;   // a back() does not push the page it leaves
    hmi_page_t *back[BACK_DEPTH];
    size_t nback;
    hmi_alarms_t *alarms;
    hmi_overlay_t *overlay;
};

// Deliver the active alarm list to every ShAlarmTable of the current page.
static void deliver_alarms_cb(hmi_widget_t *w, void *user)
{
    hmi_runtime_t *rt = user;
    if (strcmp(w->type, "ShAlarmTable") != 0 || !w->native) return;
    // No definitions: the engine has nothing to say; the model's own list stands.
    const hmi_widget_ops_t *ops = hmi_registry_find(w->type);
    if (!ops || !ops->set_prop) return;
    // 13.3 history mode: the journal's newest maxVisible events.
    if (strcmp(hmi_widget_str(w, "mode", "active"), "history") == 0) {
        hmi_journal_t *j = hmi_alarms_journal(rt->alarms);
        if (!j) return;
        hmi_value_t hist = hmi_journal_recent(j, (size_t)hmi_widget_num(w, "maxVisible", 6));
        ops->set_prop(w, "alarms", &hist);
        hmi_value_free(&hist);
        return;
    }
    if (hmi_alarms_tag_count(rt->alarms) == 0) return;
    hmi_value_t list = hmi_alarms_active_value(rt->alarms);
    ops->set_prop(w, "alarms", &list);
    hmi_value_free(&list);
}

static void alarms_changed(void *user)
{
    hmi_runtime_t *rt = user;
    if (rt->page) hmi_page_visit(rt->page, deliver_alarms_cb, rt);
}

// Every widget carries a pointer back to its runtime in state[0]? No: the
// model's `state` belongs to the widget implementation. The runtime keeps a
// flat map instead (few widgets, linear search is fine).
typedef struct { const hmi_widget_t *w; hmi_runtime_t *rt; } owner_t;
static owner_t g_owners[2048];
static size_t g_nowners;

static void own(const hmi_widget_t *w, hmi_runtime_t *rt)
{
    for (size_t i = 0; i < g_nowners; ++i)
        if (g_owners[i].w == w) { g_owners[i].rt = rt; return; }
    if (g_nowners < sizeof g_owners / sizeof g_owners[0])
        g_owners[g_nowners++] = (owner_t){w, rt};
}

hmi_runtime_t *hmi_runtime_of(const hmi_widget_t *w)
{
    for (size_t i = 0; i < g_nowners; ++i)
        if (g_owners[i].w == w) return g_owners[i].rt;
    return NULL;
}

hmi_tags_t *hmi_runtime_tags(const hmi_runtime_t *rt) { return rt ? rt->tags : NULL; }
const hmi_project_t *hmi_runtime_project(const hmi_runtime_t *rt) { return rt ? rt->project : NULL; }

// -- placeholder for a type without an implementation ---------------------
static lv_obj_t *placeholder_create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *box = lv_obj_create(parent);
    lv_obj_set_style_bg_color(box, hmi_colour("autoPanel"), 0);
    lv_obj_set_style_bg_opa(box, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(box, hmi_colour("destructive"), 0);
    lv_obj_set_style_border_width(box, 1, 0);
    lv_obj_set_style_radius(box, 6, 0);
    lv_obj_set_style_pad_all(box, 4, 0);
    lv_obj_t *lbl = lv_label_create(box);
    lv_label_set_text(lbl, w->type);
    lv_obj_set_style_text_color(lbl, hmi_colour("mutedForeground"), 0);
    lv_obj_set_style_text_font(lbl, hmi_font(12, 500), 0);
    lv_obj_center(lbl);
    return box;
}

static void build_widget(hmi_runtime_t *rt, hmi_widget_t *w, lv_obj_t *parent);

// LVGL paints children in creation order, so the Designer's z (which the
// QML preview honours, qml_generator.py) had no effect on the panel: a
// card sent behind an instrument still covered it, because it came later
// in the document. Build low z first, keeping document order within a z.
static void build_in_z_order(hmi_runtime_t *rt, hmi_widget_t **widgets, size_t n,
                             lv_obj_t *parent)
{
    if (n == 0) return;
    size_t *order = lv_malloc(n * sizeof *order);
    if (!order) {                       // no memory: document order still draws
        for (size_t i = 0; i < n; ++i) build_widget(rt, widgets[i], parent);
        return;
    }
    for (size_t i = 0; i < n; ++i) order[i] = i;
    // Insertion sort: a page holds tens of widgets, and it is stable, which
    // is what keeps two widgets at the same z in the order they were written.
    for (size_t i = 1; i < n; ++i) {
        size_t cur = order[i];
        size_t j = i;
        while (j > 0 && widgets[order[j - 1]]->z > widgets[cur]->z) {
            order[j] = order[j - 1];
            --j;
        }
        order[j] = cur;
    }
    for (size_t i = 0; i < n; ++i) build_widget(rt, widgets[order[i]], parent);
    lv_free(order);
}

static void build_widget(hmi_runtime_t *rt, hmi_widget_t *w, lv_obj_t *parent)
{
    own(w, rt);
    const hmi_widget_ops_t *ops = hmi_registry_find(w->type);
    lv_obj_t *obj = ops ? ops->create(w, parent) : NULL;
    if (!obj) {
        // Both "unknown type" and "stub returned NULL" are visible in the log
        // so the parity gate can tell a stub from a wrong render.
        hmi_log(HMI_LOG_WARNING, "widget type %s not implemented (%s): placeholder", w->type, w->id);
        obj = placeholder_create(w, parent);
    }
    w->native = obj;
    hmi_widget_apply_common(w);
    // Belt and braces for contract C1: after create, every property the
    // model declares is also pushed through set_prop, so a widget whose
    // create() only built the tree still shows the model's values.
    if (ops && ops->set_prop) {
        for (size_t i = 0; i < w->nprops; ++i)
            if (w->props[i].value.kind != HMI_V_NULL)
                ops->set_prop(w, w->props[i].name, &w->props[i].value);
    }
    // Children of a plain container are placed by the container's own
    // implementation when it is a positioner (Row/Column/Grid); otherwise
    // they are absolute inside the parent.
    build_in_z_order(rt, w->children, w->nchildren, obj);
}

static void destroy_widget(hmi_widget_t *w)
{
    for (size_t i = 0; i < w->nchildren; ++i)
        destroy_widget(w->children[i]);
    const hmi_widget_ops_t *ops = hmi_registry_find(w->type);
    if (ops && ops->destroy)
        ops->destroy(w);
    w->native = NULL;
    w->state = NULL;
}

static void bind_apply(hmi_widget_t *w, const char *prop, const hmi_value_t *value, void *user)
{
    (void)user;
    if (!w->native) return;
    if (strcmp(prop, "visible") == 0 || strcmp(prop, "opacity") == 0) {
        // Common properties are the runtime's: mirror into the model-free path.
        lv_obj_t *obj = (lv_obj_t *)w->native;
        if (strcmp(prop, "visible") == 0) {
            if (hmi_value_as_bool(value, true)) lv_obj_remove_flag(obj, LV_OBJ_FLAG_HIDDEN);
            else lv_obj_add_flag(obj, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_set_style_opa(obj, (lv_opa_t)(hmi_value_as_num(value, 1.0) * 255.0), 0);
        }
        return;
    }
    const hmi_widget_ops_t *ops = hmi_registry_find(w->type);
    if (ops && ops->set_prop)
        ops->set_prop(w, prop, value);
}

static void teardown_page(hmi_runtime_t *rt)
{
    if (!rt->page) return;
    for (size_t i = 0; i < rt->page->nwidgets; ++i)
        destroy_widget(rt->page->widgets[i]);
    if (rt->page_obj) lv_obj_delete(rt->page_obj);
    rt->page_obj = NULL;
    rt->page = NULL;
}

static void request_backfill_cb(hmi_widget_t *w, void *user);

static bool show_page(hmi_runtime_t *rt, hmi_page_t *page)
{
    teardown_page(rt);
    rt->page = page;
    rt->page_obj = lv_obj_create(rt->screen);
    lv_obj_remove_style_all(rt->page_obj);
    lv_obj_set_size(rt->page_obj, rt->project->width, rt->project->height);
    lv_obj_set_pos(rt->page_obj, 0, 0);
    lv_obj_remove_flag(rt->page_obj, LV_OBJ_FLAG_SCROLLABLE);
    lv_opa_t opa;
    lv_obj_set_style_bg_color(rt->page_obj, hmi_colour_hex(rt->project->background, &opa), 0);
    lv_obj_set_style_bg_opa(rt->page_obj, opa, 0);
    build_in_z_order(rt, page->widgets, page->nwidgets, rt->page_obj);
    hmi_bind_page(rt->bind, page);
    hmi_page_visit(page, deliver_alarms_cb, rt);
    if (rt->tags) hmi_page_visit(page, request_backfill_cb, rt);
    // Re-deliver every known tag so bound widgets start from live values.
    // (The bind engine asks the tag map through hmi_bind_page's fallbacks;
    // the values already received arrive through on_tag as they change.)
    hmi_log(HMI_LOG_DEBUG, "page %s shown (%zu widgets)", page->id, hmi_page_widget_count(page));
    return true;
}

// 13.4 backfill: ask the daemon's historian for every scalar tag a trend
// chart on this page draws; tags.c merges the answer and on_history redraws.
static void request_backfill_cb(hmi_widget_t *w, void *user)
{
    hmi_runtime_t *rt = user;
    if (strcmp(w->type, "ShTrendChart") != 0) return;
    const hmi_binding_t *bd = hmi_widget_binding(w, "data");
    if (!bd || !bd->tag[0] || strncmp(bd->tag, "sim.", 4) == 0) return;
    int points = (int)hmi_widget_num(w, "maxPoints", 100);
    hmi_tags_request_history(rt->tags, bd->tag, 3600, points > 200 ? 200 : points);
}

static void on_history(const char *tag, void *user)
{
    hmi_runtime_t *rt = user;
    hmi_bind_refresh_series(rt->bind, tag);
}

static hmi_value_t tag_history(const char *tag, size_t count, void *user)
{
    hmi_runtime_t *rt = user;
    return hmi_tags_history(rt->tags, tag, count);
}

hmi_runtime_t *hmi_runtime_create(hmi_project_t *project, lv_obj_t *screen, hmi_tags_t *tags, const char *apps_dir)
{
    hmi_runtime_t *rt = calloc(1, sizeof *rt);
    rt->project = project;
    rt->screen = screen;
    rt->tags = tags;
    rt->bind = hmi_bind_create(bind_apply, rt);
    if (tags) {
        hmi_bind_set_history(rt->bind, tag_history, rt);
        hmi_tags_set_history_callback(tags, on_history, rt);
    }
    rt->alarms = hmi_alarms_create(apps_dir);
    hmi_alarms_set_callback(rt->alarms, alarms_changed, rt);
    rt->overlay = hmi_overlay_create(project, tags != NULL);
    hmi_theme_set_dark(strcmp(project->theme, "light") != 0);
    show_page(rt, project->pages[0]);
    return rt;
}

void hmi_runtime_destroy(hmi_runtime_t *rt)
{
    if (!rt) return;
    teardown_page(rt);
    hmi_overlay_destroy(rt->overlay);
    hmi_bind_destroy(rt->bind);
    hmi_alarms_destroy(rt->alarms);
    free(rt);
}

bool hmi_runtime_navigate(hmi_runtime_t *rt, const char *id)
{
    hmi_page_t *page = hmi_project_page(rt->project, id);
    if (!page) {
        hmi_log(HMI_LOG_WARNING, "navigate: no page '%s'", id);
        return false;
    }
    if (page == rt->page) return true;
    hmi_log(HMI_LOG_INFO, "navigate to page %s", id);
    rt->pending = page;   // a binding delivery or a widget event may be on the stack
    rt->pending_is_back = false;
    return true;
}

bool hmi_runtime_back(hmi_runtime_t *rt)
{
    if (!rt || rt->nback == 0) return false;
    rt->pending = rt->back[--rt->nback];
    rt->pending_is_back = true;
    hmi_log(HMI_LOG_INFO, "back to page %s", rt->pending->id);
    return true;
}

hmi_alarms_t *hmi_runtime_alarms(const hmi_runtime_t *rt) { return rt ? rt->alarms : NULL; }

void hmi_runtime_alarms_changed(hmi_runtime_t *rt) { if (rt) alarms_changed(rt); }

void hmi_runtime_set_journal(hmi_runtime_t *rt, hmi_journal_t *j)
{
    if (rt) hmi_alarms_set_journal(rt->alarms, j);
}

void hmi_runtime_tick(hmi_runtime_t *rt)
{
    if (!rt) return;
    hmi_alarms_tick(rt->alarms);
    hmi_overlay_tick(rt->overlay, lv_tick_get(), lv_display_get_inactive_time(NULL));
    if (!rt->pending) return;
    hmi_page_t *page = rt->pending;
    rt->pending = NULL;
    if (page == rt->page) return;
    if (!rt->pending_is_back && rt->page) {
        if (rt->nback == BACK_DEPTH) {          // oldest dropped
            memmove(rt->back, rt->back + 1, (BACK_DEPTH - 1) * sizeof rt->back[0]);
            rt->nback--;
        }
        rt->back[rt->nback++] = rt->page;
    }
    rt->pending_is_back = false;
    show_page(rt, page);
}

const char *hmi_runtime_current_page(const hmi_runtime_t *rt) { return rt->page ? rt->page->id : ""; }

void hmi_runtime_on_tag(hmi_runtime_t *rt, const char *tag, const hmi_value_t *value)
{
    hmi_bind_on_tag(rt->bind, tag, value);
    const char *tags[1] = {tag};
    hmi_alarms_evaluate(rt->alarms, tags, value, 1);   // fires alarms_changed when the set changes
}

void hmi_runtime_on_online(hmi_runtime_t *rt, bool online)
{
    hmi_log(HMI_LOG_INFO, "daemon link %s", online ? "online" : "lost");
    if (rt) hmi_overlay_link(rt->overlay, online);
}

void hmi_runtime_signal(hmi_widget_t *w, const char *signal, const hmi_value_t *arg)
{
    hmi_runtime_t *rt = hmi_runtime_of(w);
    if (rt) hmi_actions_run(rt, w, signal, arg);
}
