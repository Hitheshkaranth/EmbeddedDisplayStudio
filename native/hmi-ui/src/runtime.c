// runtime.c -- see runtime.h.
#include "runtime.h"

#include <stdlib.h>
#include <string.h>

#include "log.h"
#include "registry.h"
#include "theme.h"

struct hmi_runtime {
    hmi_project_t *project;
    lv_obj_t *screen;
    hmi_tags_t *tags;
    hmi_bind_t *bind;
    hmi_page_t *page;
    lv_obj_t *page_obj;     // container for the page's widgets
};

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
    // Children of a plain container are placed by the container's own
    // implementation when it is a positioner (Row/Column/Grid); otherwise
    // they are absolute inside the parent.
    for (size_t i = 0; i < w->nchildren; ++i)
        build_widget(rt, w->children[i], obj);
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
    for (size_t i = 0; i < page->nwidgets; ++i)
        build_widget(rt, page->widgets[i], rt->page_obj);
    hmi_bind_page(rt->bind, page);
    // Re-deliver every known tag so bound widgets start from live values.
    // (The bind engine asks the tag map through hmi_bind_page's fallbacks;
    // the values already received arrive through on_tag as they change.)
    hmi_log(HMI_LOG_DEBUG, "page %s shown (%zu widgets)", page->id, hmi_page_widget_count(page));
    return true;
}

hmi_runtime_t *hmi_runtime_create(hmi_project_t *project, lv_obj_t *screen, hmi_tags_t *tags)
{
    hmi_runtime_t *rt = calloc(1, sizeof *rt);
    rt->project = project;
    rt->screen = screen;
    rt->tags = tags;
    rt->bind = hmi_bind_create(bind_apply, rt);
    hmi_theme_set_dark(strcmp(project->theme, "light") != 0);
    show_page(rt, project->pages[0]);
    return rt;
}

void hmi_runtime_destroy(hmi_runtime_t *rt)
{
    if (!rt) return;
    teardown_page(rt);
    hmi_bind_destroy(rt->bind);
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
    return show_page(rt, page);
}

const char *hmi_runtime_current_page(const hmi_runtime_t *rt) { return rt->page ? rt->page->id : ""; }

void hmi_runtime_on_tag(hmi_runtime_t *rt, const char *tag, const hmi_value_t *value)
{
    hmi_bind_on_tag(rt->bind, tag, value);
}

void hmi_runtime_on_online(hmi_runtime_t *rt, bool online)
{
    (void)rt;
    hmi_log(HMI_LOG_INFO, "daemon link %s", online ? "online" : "lost");
}

void hmi_runtime_signal(hmi_widget_t *w, const char *signal, const hmi_value_t *arg)
{
    hmi_runtime_t *rt = hmi_runtime_of(w);
    if (!rt) return;
    for (size_t i = 0; i < w->nactions; ++i) {
        const hmi_action_t *a = &w->actions[i];
        if (strcmp(a->signal, signal) != 0) continue;
        if (strcmp(a->kind, "navigate") == 0) {
            hmi_runtime_navigate(rt, a->page);
        } else if (!rt->tags) {
            hmi_log(HMI_LOG_DEBUG, "action %s on %s ignored (no daemon link)", a->kind, w->id);
        } else if (strcmp(a->kind, "pulse") == 0) {
            hmi_tags_pulse(rt->tags, a->tag, a->ms);
        } else {   // write: the model's value, else the signal's argument, else true
            hmi_value_t v = a->value.kind != HMI_V_NULL ? hmi_value_copy(&a->value)
                          : arg ? hmi_value_copy(arg) : hmi_value_bool(true);
            hmi_tags_write(rt->tags, a->tag, &v);
            hmi_value_free(&v);
        }
    }
}
