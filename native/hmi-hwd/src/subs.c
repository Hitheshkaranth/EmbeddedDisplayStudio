/*
 * subs.c -- static sink and TTL subscribers (subs.h).
 * OWNER: A1. STUB written with the skeleton: every function compiles
 * and fails safe; the owner replaces the bodies (not the signatures).
 */
#include "subs.h"

#include <stdlib.h>
#include <string.h>

typedef struct {
    struct sockaddr_in addr;
    double expiry;   /* monotonic seconds; 0 for the static sink (never expires) */
} sub_entry;

struct hwd_subs {
    struct sockaddr_in static_sink;
    double default_ttl;
    sub_entry items[HWD_MAX_SUBSCRIBERS];
    size_t count;
};

hwd_subs *hwd_subs_create(const struct sockaddr_in *static_sink, double default_ttl)
{
    hwd_subs *s = calloc(1, sizeof *s);
    if (!s) return NULL;
    if (static_sink)
        s->static_sink = *static_sink;
    else
        memset(&s->static_sink, 0, sizeof s->static_sink);
    s->default_ttl = default_ttl > 0.0 ? default_ttl : 5.0;
    return s;
}

void hwd_subs_destroy(hwd_subs *s) { free(s); }

void hwd_subs_subscribe(hwd_subs *s, const struct sockaddr_in *addr, double ttl, double now)
{
    if (!s || !addr) return;
    double exp = now + (ttl > 0.0 ? ttl : s->default_ttl);
    /* Replace an existing matching subscriber, else append. */
    for (size_t i = 0; i < s->count; i++) {
        if (memcmp(&s->items[i].addr, addr, sizeof *addr) == 0) {
            s->items[i].expiry = exp;
            return;
        }
    }
    if (s->count < HWD_MAX_SUBSCRIBERS) {
        s->items[s->count].addr = *addr;
        s->items[s->count].expiry = exp;
        s->count++;
    }
}

static bool same_addr(const struct sockaddr_in *a, const struct sockaddr_in *b)
{
    return a->sin_family == b->sin_family &&
           a->sin_addr.s_addr == b->sin_addr.s_addr &&
           a->sin_port == b->sin_port;
}

void hwd_subs_unsubscribe(hwd_subs *s, const struct sockaddr_in *addr)
{
    if (!s || !addr) return;
    for (size_t i = 0; i < s->count; i++) {
        if (same_addr(&s->items[i].addr, addr)) {
            /* shift remaining entries left to fill the gap */
            for (size_t j = i; j + 1 < s->count; j++)
                s->items[j] = s->items[j + 1];
            s->count--;
            return;
        }
    }
}

/* Drop expired dynamic subscribers; never expire the static sink. */
static void prune(hwd_subs *s, double now)
{
    size_t w = 0;
    for (size_t i = 0; i < s->count; i++) {
        if (s->items[i].expiry <= now)
            continue;   /* expired: drop */
        s->items[w++] = s->items[i];
    }
    s->count = w;
}

size_t hwd_subs_targets(hwd_subs *s, double now, struct sockaddr_in *out, size_t max)
{
    if (!s || !out) return 0;
    prune(s, now);

    size_t n = 0;
    /* static sink first, unless it is expired (it never is). */
    if (n < max) out[n++] = s->static_sink;
    for (size_t i = 0; i < s->count && n < max; i++) {
        if (!same_addr(&s->items[i].addr, &s->static_sink))
            out[n++] = s->items[i].addr;
    }
    return n;
}