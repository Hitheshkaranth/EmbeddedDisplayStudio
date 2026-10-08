/*
 * history.c -- the historian, SQLite, same schema as daemon/historian.py (CONTRACT 13.4).
 * OWNER: A4. STUB written with the skeleton: every function compiles
 * and fails safe; the owner replaces the bodies (not the signatures).
 */
#include "history.h"

int hwd_history_validate(const cJSON *hcfg, char *err, size_t errlen)
{ (void)hcfg; if (errlen) err[0] = '\0'; return 0; }
hwd_history *hwd_history_create(const cJSON *hcfg, char *err, size_t errlen)
{ (void)hcfg; if (errlen) err[0] = '\0'; return NULL; }
void hwd_history_destroy(hwd_history *h) { (void)h; }
bool hwd_history_logs(hwd_history *h, const char *tag) { (void)h; (void)tag; return false; }
bool hwd_history_observe(hwd_history *h, const char *tag, const hwd_value *v, double now)
{ (void)h; (void)tag; (void)v; (void)now; return false; }
void hwd_history_tick(hwd_history *h, double now) { (void)h; (void)now; }
cJSON *hwd_history_query(hwd_history *h, const char *tag, int seconds, int points, double now)
{ (void)h; (void)tag; (void)seconds; (void)points; (void)now; return cJSON_CreateArray(); }
