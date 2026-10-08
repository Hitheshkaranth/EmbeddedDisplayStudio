/*
 * subs.c -- static sink and TTL subscribers (subs.h).
 * OWNER: A1. Same behaviour as daemon/hmi_hwd.py SubscriberRegistry: the
 * static sink always first and never expiring; dynamic subscribers keyed by
 * address, refreshed by a re-subscribe, dropped silently once expired.
 */
#include "subs.h"

#include <stdlib.h>
#include <string.h>

typedef struct {
    struct sockaddr_in addr;
    double expiry;   /* the caller's clock (the daemon passes monotonic seconds) */
} sub_entry;

struct hwd_subs {
    struct sockaddr_in static_sink;
    double default_ttl;
    sub_entry items[HWD_MAX_SUBSCRIBERS];
    size_t count;
};

static bool same_addr(const struct sockaddr_in *a, const struct sockaddr_in *b)
{
    return a->sin_family == b->sin_family &&
           a->sin_addr.s_addr == b->sin_addr.s_addr &&
           a->sin_port == b->sin_port;
}

/* Drop expired dynamic subscribers (Python: now >= expiry). */
static void prune(hwd_subs *s, double now)
{
    size_t w = 0;
    for (size_t i = 0; i < s->count; i++)
        if (now < s->items[i].expiry) s->items[w++] = s->items[i];
    s->count = w;
}

hwd_subs *hwd_subs_create(const struct sockaddr_in *static_sink, double default_ttl)
{
    hwd_subs *s = calloc(1, sizeof *s);
    if (!s) return NULL;
    if (static_sink) s->static_sink = *static_sink;
    s->default_ttl = default_ttl > 0.0 ? default_ttl : 5.0;
    return s;
}

void hwd_subs_destroy(hwd_subs *s) { free(s); }

void hwd_subs_subscribe(hwd_subs *s, const struct sockaddr_in *addr, double ttl, double now)
{
    if (!s || !addr) return;
    double exp = now + (ttl > 0.0 ? ttl : s->default_ttl);
    for (size_t i = 0; i < s->count; i++) {
        if (same_addr(&s->items[i].addr, addr)) {
            s->items[i].expiry = exp;
            return;
        }
    }
    if (s->count >= HWD_MAX_SUBSCRIBERS) prune(s, now);
    if (s->count >= HWD_MAX_SUBSCRIBERS) {
        /* Full: replace the one closest to expiry. */
        size_t victim = 0;
        for (size_t i = 1; i < s->count; i++)
            if (s->items[i].expiry < s->items[victim].expiry) victim = i;
        s->items[victim].addr = *addr;
        s->items[victim].expiry = exp;
        return;
    }
    memset(&s->items[s->count].addr, 0, sizeof s->items[s->count].addr);
    s->items[s->count].addr.sin_family = addr->sin_family;
    s->items[s->count].addr.sin_addr = addr->sin_addr;
    s->items[s->count].addr.sin_port = addr->sin_port;
    s->items[s->count].expiry = exp;
    s->count++;
}

void hwd_subs_unsubscribe(hwd_subs *s, const struct sockaddr_in *addr)
{
    if (!s || !addr) return;
    for (size_t i = 0; i < s->count; i++) {
        if (same_addr(&s->items[i].addr, addr)) {
            memmove(&s->items[i], &s->items[i + 1], (s->count - i - 1) * sizeof s->items[0]);
            s->count--;
            return;
        }
    }
}

size_t hwd_subs_targets(hwd_subs *s, double now, struct sockaddr_in *out, size_t max)
{
    if (!s || !out || max == 0) return 0;
    prune(s, now);
    size_t n = 0;
    out[n++] = s->static_sink;
    for (size_t i = 0; i < s->count && n < max; i++)
        if (!same_addr(&s->items[i].addr, &s->static_sink)) out[n++] = s->items[i].addr;
    return n;
}
