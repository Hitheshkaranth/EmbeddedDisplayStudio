/*
 * daemon.c -- sockets, the poll/publish loop, discovery, sd_notify, signals, selftest (daemon.h).
 * OWNER: A1. STUB written with the skeleton: every function compiles
 * and fails safe; the owner replaces the bodies (not the signatures).
 */
#include "daemon.h"
#include "backend.h"
#include <stdio.h>
#include <string.h>

int hwd_parse_args(int argc, char **argv, hwd_options *opt)
{ (void)argc; (void)argv; memset(opt, 0, sizeof *opt); opt->config_path = "/etc/hmi/hwd.json"; return 0; }
int hwd_run(const hwd_options *opt) { (void)opt; fprintf(stderr, "hmi-hwd: not implemented\n"); return 1; }
