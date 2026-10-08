/*
 * config.c -- hwd.json loading and core validation (config.h).
 * OWNER: A1. STUB written with the skeleton: every function compiles
 * and fails safe; the owner replaces the bodies (not the signatures).
 */
#include "config.h"
#include <stdio.h>
#include <string.h>

bool hwd_config_parse(const char *json, hwd_config *cfg, char *err, size_t errlen)
{ (void)json; memset(cfg, 0, sizeof *cfg); if (errlen) snprintf(err, errlen, "not implemented"); return false; }
bool hwd_config_load(const char *path, hwd_config *cfg, char *err, size_t errlen)
{ (void)path; memset(cfg, 0, sizeof *cfg); if (errlen) snprintf(err, errlen, "not implemented"); return false; }
void hwd_config_free(hwd_config *cfg) { if (cfg && cfg->root) cJSON_Delete(cfg->root); if (cfg) cfg->root = NULL; }
