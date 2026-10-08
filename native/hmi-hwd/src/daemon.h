/*
 * daemon.h -- the daemon: sockets, the poll/publish loop and its lifecycle
 * (daemon/hmi_hwd.py HwDaemon is the reference).
 *
 *  - command socket on 127.0.0.1:cmd_port; every datagram parsed with
 *    proto.c and answered per CONTRACT 2.3 (acks only when an id is present,
 *    or for ping/list); set/pulse go to io or modbus by tag; pulse is
 *    non-blocking (the release is scheduled on the loop, not slept);
 *  - every poll_interval_ms: io poll -> store, sys.uptime/sys.errors,
 *    history observe/tick, one frame to the static sink and each subscriber;
 *  - "stale" quality for a tag whose value is older than 5 poll periods;
 *  - per-sender rate limit (rate_limited), oversized datagrams counted and
 *    dropped (too_large nack when an id is recoverable);
 *  - discovery socket (0.0.0.0:discovery_port) answering
 *    {"cmd":"discover"} with
 *    {"t":"hello","host":<hostname>,"model":<device-tree model or "">,
 *     "hwd":HWD_VERSION,"cmd_port":N,"tags":count}
 *    unicast to the sender;
 *  - systemd: READY=1 after init, WATCHDOG=1 every loop (sd_notify via
 *    $NOTIFY_SOCKET, no libsystemd);
 *  - SIGTERM/SIGINT: io and modbus to safe state, history flushed, exit 0;
 *  - --selftest: init, poll once, print ONE frame (compact JSON + newline)
 *    to stdout, exit 0.
 *
 * FROZEN.
 */
#ifndef HWD_DAEMON_H
#define HWD_DAEMON_H

#include "hwd.h"
#include "config.h"

typedef struct {
    const char *config_path;   /* --config, default /etc/hmi/hwd.json */
    bool sim;                  /* --sim */
    bool strict;               /* --strict (exclusive with --sim) */
    bool selftest;             /* --selftest */
    bool modbus_live;          /* --modbus-live: real Modbus even with --sim */
    int log_level;             /* --log-level DEBUG|INFO|WARNING|ERROR */
} hwd_options;

/* Parse argv the way the Python argparse does (same flags; unknown flag or
 * --sim with --strict: message and exit status 1/2). */
int hwd_parse_args(int argc, char **argv, hwd_options *opt);
/* Run until signalled (or once for selftest). Returns the exit status. */
int hwd_run(const hwd_options *opt);

#endif
