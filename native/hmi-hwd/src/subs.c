/*
 * subs.c -- static sink and TTL subscribers (subs.h).
 * OWNER: A1. STUB written with the skeleton: every function compiles
 * and fails safe; the owner replaces the bodies (not the signatures).
 */
#include "subs.h"

hwd_subs *hwd_subs_create(const struct sockaddr_in *static_sink, double default_ttl)
{ (void)static_sink; (void)default_ttl; return NULL; }
void hwd_subs_destroy(hwd_subs *s) { (void)s; }
void hwd_subs_subscribe(hwd_subs *s, const struct sockaddr_in *addr, double ttl, double now)
{ (void)s; (void)addr; (void)ttl; (void)now; }
void hwd_subs_unsubscribe(hwd_subs *s, const struct sockaddr_in *addr) { (void)s; (void)addr; }
size_t hwd_subs_targets(hwd_subs *s, double now, struct sockaddr_in *out, size_t max)
{ (void)s; (void)now; (void)out; (void)max; return 0; }
