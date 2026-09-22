// model.c -- see model.h. Mirrors designer/model.py's reader: unknown keys
// are ignored, missing ones take the same defaults the Designer uses.
#include "model.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"

static char *dupstr(const char *s) { return strdup(s ? s : ""); }

static const char *jstr(const cJSON *o, const char *key, const char *def)
{
    const cJSON *j = cJSON_GetObjectItemCaseSensitive(o, key);
    return cJSON_IsString(j) ? cJSON_GetStringValue(j) : def;
}

static double jnum(const cJSON *o, const char *key, double def)
{
    const cJSON *j = cJSON_GetObjectItemCaseSensitive(o, key);
    return cJSON_IsNumber(j) ? cJSON_GetNumberValue(j) : def;
}

static bool jbool(const cJSON *o, const char *key, bool def)
{
    const cJSON *j = cJSON_GetObjectItemCaseSensitive(o, key);
    return cJSON_IsBool(j) ? cJSON_IsTrue(j) : def;
}

static hmi_widget_t *load_widget(const cJSON *jw, hmi_widget_t *parent)
{
    hmi_widget_t *w = calloc(1, sizeof *w);
    w->type = dupstr(jstr(jw, "type", ""));
    w->id = dupstr(jstr(jw, "id", ""));
    w->parent = parent;
    const cJSON *g = cJSON_GetObjectItemCaseSensitive(jw, "geometry");
    w->x = jnum(g, "x", 0); w->y = jnum(g, "y", 0);
    w->width = jnum(g, "width", 0); w->height = jnum(g, "height", 0);
    w->z = (int)jnum(jw, "z", 0);
    w->locked = jbool(jw, "locked", false);

    const cJSON *props = cJSON_GetObjectItemCaseSensitive(jw, "properties");
    if (cJSON_IsObject(props)) {
        w->nprops = (size_t)cJSON_GetArraySize(props);
        w->props = w->nprops ? calloc(w->nprops, sizeof(hmi_prop_t)) : NULL;
        size_t i = 0;
        const cJSON *p;
        cJSON_ArrayForEach(p, props) {
            w->props[i].name = dupstr(p->string);
            w->props[i].value = hmi_value_from_json(p);
            ++i;
        }
    }
    const cJSON *binds = cJSON_GetObjectItemCaseSensitive(jw, "bindings");
    if (cJSON_IsObject(binds)) {
        w->nbindings = (size_t)cJSON_GetArraySize(binds);
        w->bindings = w->nbindings ? calloc(w->nbindings, sizeof(hmi_binding_t)) : NULL;
        size_t i = 0;
        const cJSON *b;
        cJSON_ArrayForEach(b, binds) {
            hmi_binding_t *bd = &w->bindings[i++];
            bd->prop = dupstr(b->string);
            if (cJSON_IsString(b)) {          // legacy short form: "prop": "tag"
                bd->tag = dupstr(cJSON_GetStringValue(b));
                bd->format = dupstr(""); bd->unit = dupstr("");
                bd->warning = dupstr(""); bd->critical = dupstr("");
                bd->multiplier = 1.0;
                continue;
            }
            bd->tag = dupstr(jstr(b, "tag", ""));
            bd->format = dupstr(jstr(b, "format", ""));
            bd->multiplier = jnum(b, "multiplier", 1.0);
            bd->offset = jnum(b, "offset", 0.0);
            bd->unit = dupstr(jstr(b, "unit", ""));
            bd->warning = dupstr(jstr(b, "warning", ""));
            bd->critical = dupstr(jstr(b, "critical", ""));
        }
    }
    const cJSON *acts = cJSON_GetObjectItemCaseSensitive(jw, "actions");
    if (cJSON_IsObject(acts)) {
        w->nactions = (size_t)cJSON_GetArraySize(acts);
        w->actions = w->nactions ? calloc(w->nactions, sizeof(hmi_action_t)) : NULL;
        size_t i = 0;
        const cJSON *a;
        cJSON_ArrayForEach(a, acts) {
            hmi_action_t *ac = &w->actions[i++];
            ac->signal = dupstr(a->string);
            ac->kind = dupstr(jstr(a, "kind", "write"));
            ac->tag = dupstr(jstr(a, "tag", ""));
            ac->value = hmi_value_from_json(cJSON_GetObjectItemCaseSensitive(a, "value"));
            ac->ms = (int)jnum(a, "ms", 250);
            ac->page = dupstr(jstr(a, "page", ""));
        }
    }
    const cJSON *kids = cJSON_GetObjectItemCaseSensitive(jw, "children");
    if (cJSON_IsArray(kids)) {
        w->nchildren = (size_t)cJSON_GetArraySize(kids);
        w->children = w->nchildren ? calloc(w->nchildren, sizeof(hmi_widget_t *)) : NULL;
        size_t i = 0;
        const cJSON *k;
        cJSON_ArrayForEach(k, kids) w->children[i++] = load_widget(k, w);
    }
    return w;
}

static void free_widget(hmi_widget_t *w)
{
    if (!w) return;
    for (size_t i = 0; i < w->nchildren; ++i) free_widget(w->children[i]);
    free(w->children);
    for (size_t i = 0; i < w->nprops; ++i) { free(w->props[i].name); hmi_value_free(&w->props[i].value); }
    free(w->props);
    for (size_t i = 0; i < w->nbindings; ++i) {
        hmi_binding_t *b = &w->bindings[i];
        free(b->prop); free(b->tag); free(b->format); free(b->unit); free(b->warning); free(b->critical);
    }
    free(w->bindings);
    for (size_t i = 0; i < w->nactions; ++i) {
        hmi_action_t *a = &w->actions[i];
        free(a->signal); free(a->kind); free(a->tag); free(a->page); hmi_value_free(&a->value);
    }
    free(w->actions);
    free(w->type); free(w->id);
    free(w);
}

hmi_project_t *hmi_project_load(const char *path, char *err, size_t errlen)
{
    if (err && errlen) err[0] = '\0';
    FILE *f = fopen(path, "rb");
    if (!f) { if (err) snprintf(err, errlen, "cannot open %s", path); return NULL; }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *text = malloc((size_t)n + 1);
    if (fread(text, 1, (size_t)n, f) != (size_t)n) { fclose(f); free(text); if (err) snprintf(err, errlen, "cannot read %s", path); return NULL; }
    fclose(f);
    text[n] = '\0';
    cJSON *root = cJSON_Parse(text);
    free(text);
    if (!root) { if (err) snprintf(err, errlen, "%s: invalid JSON near '%.30s'", path, cJSON_GetErrorPtr() ? cJSON_GetErrorPtr() : ""); return NULL; }

    hmi_project_t *p = calloc(1, sizeof *p);
    p->name = dupstr(jstr(root, "name", "project"));
    const cJSON *screen = cJSON_GetObjectItemCaseSensitive(root, "screen");
    p->width = (int)jnum(screen, "width", 1024);
    p->height = (int)jnum(screen, "height", 768);
    p->background = dupstr(jstr(screen, "background", "#09090b"));
    p->theme = dupstr(jstr(screen, "theme", "dark"));
    const char *slash = strrchr(path, '/');
#ifdef _WIN32
    const char *bslash = strrchr(path, '\\');
    if (bslash && (!slash || bslash > slash)) slash = bslash;
#endif
    if (slash) {   // strndup is POSIX; mingw-w64 has none
        size_t n = (size_t)(slash - path);
        p->dir = malloc(n + 1);
        memcpy(p->dir, path, n);
        p->dir[n] = '\0';
    } else {
        p->dir = dupstr(".");
    }

    const cJSON *pages = cJSON_GetObjectItemCaseSensitive(root, "pages");
    if (cJSON_IsArray(pages)) {
        p->npages = (size_t)cJSON_GetArraySize(pages);
        p->pages = p->npages ? calloc(p->npages, sizeof(hmi_page_t *)) : NULL;
        size_t i = 0;
        const cJSON *jp;
        cJSON_ArrayForEach(jp, pages) {
            hmi_page_t *pg = calloc(1, sizeof *pg);
            pg->id = dupstr(jstr(jp, "id", "main"));
            pg->name = dupstr(jstr(jp, "name", pg->id));
            const cJSON *ws = cJSON_GetObjectItemCaseSensitive(jp, "widgets");
            if (cJSON_IsArray(ws)) {
                pg->nwidgets = (size_t)cJSON_GetArraySize(ws);
                pg->widgets = pg->nwidgets ? calloc(pg->nwidgets, sizeof(hmi_widget_t *)) : NULL;
                size_t k = 0;
                const cJSON *jw;
                cJSON_ArrayForEach(jw, ws) pg->widgets[k++] = load_widget(jw, NULL);
            }
            p->pages[i++] = pg;
        }
    }
    cJSON_Delete(root);
    if (p->npages == 0) {
        hmi_project_free(p);
        if (err) snprintf(err, errlen, "%s: no pages", path);
        return NULL;
    }
    return p;
}

void hmi_project_free(hmi_project_t *p)
{
    if (!p) return;
    for (size_t i = 0; i < p->npages; ++i) {
        hmi_page_t *pg = p->pages[i];
        for (size_t k = 0; k < pg->nwidgets; ++k) free_widget(pg->widgets[k]);
        free(pg->widgets); free(pg->id); free(pg->name); free(pg);
    }
    free(p->pages); free(p->name); free(p->background); free(p->theme); free(p->dir);
    free(p);
}

const hmi_value_t *hmi_widget_prop(const hmi_widget_t *w, const char *name)
{
    for (size_t i = 0; w && i < w->nprops; ++i)
        if (strcmp(w->props[i].name, name) == 0)
            return &w->props[i].value;
    return NULL;
}

const hmi_binding_t *hmi_widget_binding(const hmi_widget_t *w, const char *prop)
{
    for (size_t i = 0; w && i < w->nbindings; ++i)
        if (strcmp(w->bindings[i].prop, prop) == 0)
            return &w->bindings[i];
    return NULL;
}

hmi_page_t *hmi_project_page(const hmi_project_t *p, const char *id)
{
    for (size_t i = 0; p && i < p->npages; ++i)
        if (strcmp(p->pages[i]->id, id) == 0)
            return p->pages[i];
    return NULL;
}

static void visit(hmi_widget_t *w, hmi_widget_visitor_t fn, void *user)
{
    fn(w, user);
    for (size_t i = 0; i < w->nchildren; ++i)
        visit(w->children[i], fn, user);
}

void hmi_page_visit(hmi_page_t *page, hmi_widget_visitor_t fn, void *user)
{
    for (size_t i = 0; page && i < page->nwidgets; ++i)
        visit(page->widgets[i], fn, user);
}

static void count_cb(hmi_widget_t *w, void *user) { (void)w; ++*(size_t *)user; }

size_t hmi_page_widget_count(const hmi_page_t *page)
{
    size_t n = 0;
    hmi_page_visit((hmi_page_t *)page, count_cb, &n);
    return n;
}
