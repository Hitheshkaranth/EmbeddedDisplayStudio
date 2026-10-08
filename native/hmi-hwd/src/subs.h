/*
 * subs.h -- the static telemetry sink plus dynamic subscribers learned from
 * `subscribe` (TTL, default 5 s; CONTRACT 2.1). Same behaviour as
 * daemon/hmi_hwd.py SubscriberRegistry.
 *
 * FROZEN.
 */
#ifndef HWD_SUBS_H
#define HWD_SUBS_H

#include "hwd.h"
#include <netinet/in.h>

typedef struct hwd_subs hwd_subs;

hwd_subs *hwd_subs_create(const struct sockaddr_in *static_sink, double default_ttl);
void hwd_subs_destroy(hwd_subs *s);
/* ttl <= 0 means the default. Re-subscribing refreshes the expiry. */
void hwd_subs_subscribe(hwd_subs *s, const struct sockaddr_in *addr, double ttl, double now);
void hwd_subs_unsubscribe(hwd_subs *s, const struct sockaddr_in *addr);
/* Targets for this frame: the static sink first, then every live
 * subscriber not equal to it (expired ones are dropped). Returns count. */
size_t hwd_subs_targets(hwd_subs *s, double now, struct sockaddr_in *out, size_t max);

#endif
