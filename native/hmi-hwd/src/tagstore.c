/*
 * tagstore.c -- the thread-safe tag store (tagstore.h). Written with the
 * skeleton so every backend's tests run from the start; workers use it and
 * do not change it.
 *
 * A flat array: a panel has tens to a few hundred tags, and a linear scan
 * over interned names is cheaper than a hash table at that size.
 */
#include "tagstore.h"

#include <pthread.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    char *name;
    hwd_value value;
    bool writable;
    char quality[16];
} entry;

struct hwd_tagstore {
    pthread_mutex_t lock;
    entry items[HWD_MAX_TAGS];
    size_t count;
};

hwd_tagstore *hwd_tagstore_create(void)
{
    hwd_tagstore *s = calloc(1, sizeof *s);
    if (!s) return NULL;
    pthread_mutex_init(&s->lock, NULL);
    return s;
}

void hwd_tagstore_destroy(hwd_tagstore *s)
{
    if (!s) return;
    for (size_t i = 0; i < s->count; i++) {
        free(s->items[i].name);
        hwd_value_clear(&s->items[i].value);
    }
    pthread_mutex_destroy(&s->lock);
    free(s);
}

static entry *find(hwd_tagstore *s, const char *tag)
{
    if (!tag) return NULL;
    for (size_t i = 0; i < s->count; i++)
        if (strcmp(s->items[i].name, tag) == 0) return &s->items[i];
    return NULL;
}

bool hwd_tagstore_register(hwd_tagstore *s, const char *tag, hwd_value initial, bool writable)
{
    bool ok = false;
    if (!s || !hwd_tag_valid(tag)) { hwd_value_clear(&initial); return false; }
    pthread_mutex_lock(&s->lock);
    if (!find(s, tag) && s->count < HWD_MAX_TAGS) {
        entry *e = &s->items[s->count];
        e->name = strdup(tag);
        if (e->name) {
            e->value = initial;               /* takes ownership */
            e->writable = writable;
            e->quality[0] = '\0';
            s->count++;
            ok = true;
        }
    }
    pthread_mutex_unlock(&s->lock);
    if (!ok) hwd_value_clear(&initial);
    return ok;
}

bool hwd_tagstore_exists(hwd_tagstore *s, const char *tag)
{
    if (!s) return false;
    pthread_mutex_lock(&s->lock);
    bool ok = find(s, tag) != NULL;
    pthread_mutex_unlock(&s->lock);
    return ok;
}

bool hwd_tagstore_writable(hwd_tagstore *s, const char *tag)
{
    if (!s) return false;
    pthread_mutex_lock(&s->lock);
    entry *e = find(s, tag);
    bool ok = e && e->writable;
    pthread_mutex_unlock(&s->lock);
    return ok;
}

hwd_value hwd_tagstore_get(hwd_tagstore *s, const char *tag)
{
    hwd_value v = hwd_null();
    if (!s) return v;
    pthread_mutex_lock(&s->lock);
    entry *e = find(s, tag);
    if (e) v = hwd_value_copy(&e->value);
    pthread_mutex_unlock(&s->lock);
    return v;
}

bool hwd_tagstore_set(hwd_tagstore *s, const char *tag, const hwd_value *v)
{
    if (!s || !v) return false;
    hwd_value copy = hwd_value_copy(v);
    pthread_mutex_lock(&s->lock);
    entry *e = find(s, tag);
    if (e) {
        hwd_value old = e->value;
        e->value = copy;
        pthread_mutex_unlock(&s->lock);
        hwd_value_clear(&old);
        return true;
    }
    pthread_mutex_unlock(&s->lock);
    hwd_value_clear(&copy);
    return false;
}

size_t hwd_tagstore_names(hwd_tagstore *s, const char **out, size_t max)
{
    if (!s) return 0;
    pthread_mutex_lock(&s->lock);
    size_t n = s->count < max ? s->count : max;
    for (size_t i = 0; i < n; i++) out[i] = s->items[i].name;
    pthread_mutex_unlock(&s->lock);
    return n;
}

size_t hwd_tagstore_count(hwd_tagstore *s)
{
    if (!s) return 0;
    pthread_mutex_lock(&s->lock);
    size_t n = s->count;
    pthread_mutex_unlock(&s->lock);
    return n;
}

void hwd_tagstore_set_quality(hwd_tagstore *s, const char *tag, const char *q)
{
    if (!s) return;
    pthread_mutex_lock(&s->lock);
    entry *e = find(s, tag);
    if (e) {
        if (q && *q) {
            strncpy(e->quality, q, sizeof e->quality - 1);
            e->quality[sizeof e->quality - 1] = '\0';
        } else {
            e->quality[0] = '\0';
        }
    }
    pthread_mutex_unlock(&s->lock);
}

bool hwd_tagstore_quality(hwd_tagstore *s, const char *tag, char *buf, size_t n)
{
    if (n) buf[0] = '\0';
    if (!s) return false;
    pthread_mutex_lock(&s->lock);
    entry *e = find(s, tag);
    bool bad = e && e->quality[0];
    if (bad && n) {
        strncpy(buf, e->quality, n - 1);
        buf[n - 1] = '\0';
    }
    pthread_mutex_unlock(&s->lock);
    return bad;
}
