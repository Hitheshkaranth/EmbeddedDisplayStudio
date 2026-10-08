/*
 * tagstore.c -- the thread-safe tag store (tagstore.h).
 * OWNER: A1. STUB written with the skeleton: every function compiles
 * and fails safe; the owner replaces the bodies (not the signatures).
 */
#include "tagstore.h"

hwd_tagstore *hwd_tagstore_create(void) { return NULL; }
void hwd_tagstore_destroy(hwd_tagstore *s) { (void)s; }
bool hwd_tagstore_register(hwd_tagstore *s, const char *tag, hwd_value initial, bool writable)
{ (void)s; (void)tag; hwd_value_clear(&initial); (void)writable; return false; }
bool hwd_tagstore_exists(hwd_tagstore *s, const char *tag) { (void)s; (void)tag; return false; }
bool hwd_tagstore_writable(hwd_tagstore *s, const char *tag) { (void)s; (void)tag; return false; }
hwd_value hwd_tagstore_get(hwd_tagstore *s, const char *tag) { (void)s; (void)tag; return hwd_null(); }
bool hwd_tagstore_set(hwd_tagstore *s, const char *tag, const hwd_value *v) { (void)s; (void)tag; (void)v; return false; }
size_t hwd_tagstore_names(hwd_tagstore *s, const char **out, size_t max) { (void)s; (void)out; (void)max; return 0; }
size_t hwd_tagstore_count(hwd_tagstore *s) { (void)s; return 0; }
void hwd_tagstore_set_quality(hwd_tagstore *s, const char *tag, const char *q) { (void)s; (void)tag; (void)q; }
bool hwd_tagstore_quality(hwd_tagstore *s, const char *tag, char *buf, size_t n)
{ (void)s; (void)tag; if (n) buf[0] = '\0'; return false; }
