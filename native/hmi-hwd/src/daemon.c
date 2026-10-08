/*
 * daemon.c -- sockets, the poll/publish loop, discovery, sd_notify, signals,
 * selftest (daemon.h). OWNER: A1.
 *
 * daemon/hmi_hwd.py HwDaemon + CommandProtocol + main are the reference.
 * One thread: ppoll() on the command and discovery sockets with a timeout to
 * the next poll tick or pulse release; SIGTERM/SIGINT are blocked except
 * inside ppoll, so the handler only sets a flag and the loop sees it at once.
 * Backends that block run their own threads (backend.h); they inherit the
 * blocked signal mask, so signals always land in the loop.
 */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE     /* ppoll; CMakeLists defines it too */
#endif
#include "daemon.h"
#include "backend.h"
#include "history.h"
#include "proto.h"
#include "subs.h"
#include "tagstore.h"

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <netdb.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#define SEQ_MASK 0x7FFFFFFFu            /* seq wraps at 2^31 */
#define MAX_BACKENDS 8
#define MAX_PULSES 256
#define RECV_BUF 65536
#define MAX_DGRAMS_PER_WAKE 256         /* bound command work between ticks */
#define LOG_RATE_LIMIT_S 5.0
/* Per-sender command rate limit (daemon.h): a token bucket. Generous -- it
 * only stops a flood from starving the poll loop. */
#define RATE_PER_S 500.0
#define RATE_BURST 1000.0
#define RATE_SLOTS 64

/* ---- CLI ---------------------------------------------------------------- */

static const char USAGE[] =
    "usage: hmi-hwd [-h] [--config CONFIG] [--sim] [--strict] [--selftest]\n"
    "               [--modbus-live] [--log-level {DEBUG,INFO,WARNING,ERROR}]\n";

static const char HELP[] =
    "\nHMI Hardware Abstraction Daemon (Layer 1), C port\n\n"
    "options:\n"
    "  -h, --help            show this help message and exit\n"
    "  --config CONFIG       Path to hwd.json config file (default: /etc/hmi/hwd.json)\n"
    "  --sim                 Force simulation backends, ignoring real hardware\n"
    "  --strict              Exit non-zero if hardware is unavailable (for target use)\n"
    "  --selftest            Init, poll once, print one JSON telemetry frame to stdout, exit 0\n"
    "  --modbus-live         Talk to the configured Modbus devices even with --sim\n"
    "  --log-level {DEBUG,INFO,WARNING,ERROR}\n"
    "                        Logging verbosity (default: INFO)\n";

static int usage_error(const char *what, const char *arg)
{
    fputs(USAGE, stderr);
    fprintf(stderr, "hmi-hwd: error: %s%s\n", what, arg ? arg : "");
    return 2;
}

int hwd_parse_args(int argc, char **argv, hwd_options *opt)
{
    static const char *const LONGS[] = {
        "--config", "--sim", "--strict", "--selftest", "--modbus-live", "--log-level", "--help",
    };
    static const char *const LEVELS[] = {"DEBUG", "INFO", "WARNING", "ERROR"};
    memset(opt, 0, sizeof *opt);
    opt->config_path = "/etc/hmi/hwd.json";
    opt->log_level = 1;

    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (strcmp(arg, "-h") == 0) arg = "--help";
        if (strncmp(arg, "--", 2) != 0 || strcmp(arg, "--") == 0)
            return usage_error("unrecognized arguments: ", argv[i]);

        /* --name or --name=value; argparse accepts unique prefixes. */
        const char *eq = strchr(arg, '=');
        size_t nlen = eq ? (size_t)(eq - arg) : strlen(arg);
        const char *name = NULL;
        int matches = 0;
        for (size_t k = 0; k < sizeof LONGS / sizeof LONGS[0]; k++) {
            if (strlen(LONGS[k]) == nlen && strncmp(LONGS[k], arg, nlen) == 0) {
                name = LONGS[k];
                matches = 1;
                break;
            }
            if (nlen > 2 && strncmp(LONGS[k], arg, nlen) == 0) {
                name = LONGS[k];
                matches++;
            }
        }
        if (matches > 1) return usage_error("ambiguous option: ", argv[i]);
        if (!name) return usage_error("unrecognized arguments: ", argv[i]);

        bool takes_value = strcmp(name, "--config") == 0 || strcmp(name, "--log-level") == 0;
        const char *value = NULL;
        if (takes_value) {
            if (eq) value = eq + 1;
            else if (i + 1 < argc) value = argv[++i];
            else return usage_error("expected one argument: ", name);
        } else if (eq) {
            return usage_error("ignored explicit argument: ", argv[i]);
        }

        if (strcmp(name, "--help") == 0) {
            fputs(USAGE, stdout);
            fputs(HELP, stdout);
            exit(0);
        } else if (strcmp(name, "--config") == 0) {
            opt->config_path = value;
        } else if (strcmp(name, "--sim") == 0) {
            opt->sim = true;
        } else if (strcmp(name, "--strict") == 0) {
            opt->strict = true;
        } else if (strcmp(name, "--selftest") == 0) {
            opt->selftest = true;
        } else if (strcmp(name, "--modbus-live") == 0) {
            opt->modbus_live = true;
        } else if (strcmp(name, "--log-level") == 0) {
            int lvl = -1;
            for (int k = 0; k < 4; k++)
                if (strcmp(value, LEVELS[k]) == 0) lvl = k;
            if (lvl < 0)
                return usage_error("argument --log-level: invalid choice (choose from "
                                   "DEBUG, INFO, WARNING, ERROR): ", value);
            opt->log_level = lvl;
        }
    }
    if (opt->sim && opt->strict) {
        hwd_log_level = opt->log_level;
        HWD_ERROR("--sim and --strict are mutually exclusive");
        return 1;
    }
    return 0;
}

/* ---- the daemon ----------------------------------------------------------- */

typedef struct {
    const hwd_backend_ops *ops;
    void *self;
} backend;

typedef struct {
    char tag[HWD_MAX_TAG + 1];
    double due;                     /* monotonic */
} pulse_release;

typedef struct {
    struct sockaddr_in addr;
    double tokens, last;
    bool used;
} rate_slot;

typedef struct {
    hwd_config cfg;
    hwd_tagstore *store;
    backend be[MAX_BACKENDS];
    size_t nbe;
    hwd_history *hist;
    hwd_subs *subs;
    bool sink_ok;
    int cmd_fd, send_fd, disc_fd;
    uint64_t errors;                /* the daemon's own error count */
    uint32_t seq;
    double start_mono;
    pulse_release pulses[MAX_PULSES];
    size_t npulses;
    rate_slot rate[RATE_SLOTS];
    double log_last[16];
    char host[256];
    char model[256];
} hwd_daemon;

static volatile sig_atomic_t g_stop;

static void on_signal(int sig) { (void)sig; g_stop = 1; }

/* At most one log line per error class per LOG_RATE_LIMIT_S (Python _rl_log). */
static bool log_ok(hwd_daemon *d, hwd_err cls)
{
    size_t i = (size_t)cls < 16 ? (size_t)cls : 15;
    double now = hwd_mono();
    if (d->log_last[i] != 0 && now - d->log_last[i] < LOG_RATE_LIMIT_S) return false;
    d->log_last[i] = now;
    return true;
}

static const char *addr_str(const struct sockaddr_in *a, char *buf, size_t n)
{
    char ip[INET_ADDRSTRLEN] = "?";
    inet_ntop(AF_INET, &a->sin_addr, ip, sizeof ip);
    snprintf(buf, n, "%s:%u", ip, (unsigned)ntohs(a->sin_port));
    return buf;
}

/* ---- sd_notify (raw AF_UNIX, no libsystemd) ------------------------------ */

static int g_notify_fd = -1;

static void sd_notify(const char *state)
{
    const char *path = getenv("NOTIFY_SOCKET");
    if (!path || !*path) return;
    struct sockaddr_un sa;
    memset(&sa, 0, sizeof sa);
    sa.sun_family = AF_UNIX;
    size_t plen = strlen(path);
    if (plen >= sizeof sa.sun_path) return;
    memcpy(sa.sun_path, path, plen);
    if (sa.sun_path[0] == '@') sa.sun_path[0] = '\0';      /* abstract namespace */
    socklen_t salen = (socklen_t)(offsetof(struct sockaddr_un, sun_path) + plen);
    if (g_notify_fd < 0) g_notify_fd = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    if (g_notify_fd < 0) return;
    if (sendto(g_notify_fd, state, strlen(state), MSG_NOSIGNAL, (struct sockaddr *)&sa, salen) < 0) {
        close(g_notify_fd);         /* rebuild on the next call */
        g_notify_fd = -1;
    }
}

/* ---- sending ------------------------------------------------------------- */

static void send_text(int fd, const char *text, const struct sockaddr_in *to)
{
    if (!text || fd < 0) return;
    (void)sendto(fd, text, strlen(text), MSG_DONTWAIT | MSG_NOSIGNAL,
                 (const struct sockaddr *)to, sizeof *to);
}

static void send_owned(int fd, char *text, const struct sockaddr_in *to)
{
    send_text(fd, text, to);
    free(text);
}

/* The ack for c (positive when err is HWD_OK) -- only when it carried an id. */
static void reply(hwd_daemon *d, const hwd_cmd *c, hwd_err err, const struct sockaddr_in *from)
{
    if (c->has_id) send_owned(d->cmd_fd, hwd_proto_ack(c->id, err), from);
}

/* ---- tags and the tick --------------------------------------------------- */

static backend *owner_of(hwd_daemon *d, const char *tag)
{
    for (size_t i = 0; i < d->nbe; i++)
        if (d->be[i].ops->owns && d->be[i].ops->owns(d->be[i].self, tag)) return &d->be[i];
    return NULL;
}

static uint64_t total_errors(hwd_daemon *d)
{
    uint64_t n = d->errors;
    for (size_t i = 0; i < d->nbe; i++)
        if (d->be[i].ops->errors) n += d->be[i].ops->errors(d->be[i].self);
    return n;
}

static void poll_backends(hwd_daemon *d, double mono, double wall)
{
    for (size_t i = 0; i < d->nbe; i++)
        if (d->be[i].ops->poll) d->be[i].ops->poll(d->be[i].self, mono);

    hwd_value v = hwd_float(mono - d->start_mono);
    hwd_tagstore_set(d->store, "sys.uptime", &v);
    v = hwd_int((int64_t)total_errors(d));
    hwd_tagstore_set(d->store, "sys.errors", &v);

    if (d->hist) {
        const char *names[HWD_MAX_TAGS];
        size_t n = hwd_tagstore_names(d->store, names, HWD_MAX_TAGS);
        for (size_t i = 0; i < n; i++) {
            if (!hwd_history_logs(d->hist, names[i])) continue;
            hwd_value cur = hwd_tagstore_get(d->store, names[i]);
            hwd_history_observe(d->hist, names[i], &cur, wall);
            hwd_value_clear(&cur);
        }
        hwd_history_tick(d->hist, wall);
    }
}

static char *next_frame(hwd_daemon *d, double wall)
{
    char *frame = hwd_proto_frame(d->store, d->seq, wall);
    d->seq = (d->seq + 1) & SEQ_MASK;
    return frame;
}

static void tick(hwd_daemon *d)
{
    double mono = hwd_mono(), wall = hwd_now();
    poll_backends(d, mono, wall);
    char *frame = next_frame(d, wall);
    if (frame) {
        struct sockaddr_in targets[HWD_MAX_SUBSCRIBERS + 1];
        size_t n = hwd_subs_targets(d->subs, mono, targets, HWD_MAX_SUBSCRIBERS + 1);
        for (size_t i = d->sink_ok ? 0 : 1; i < n; i++) send_text(d->send_fd, frame, &targets[i]);
        free(frame);
    } else {
        d->errors++;
    }
    sd_notify("WATCHDOG=1");
}

/* ---- commands ------------------------------------------------------------ */

static bool rate_allow(hwd_daemon *d, const struct sockaddr_in *from)
{
    double now = hwd_mono();
    rate_slot *slot = NULL, *oldest = &d->rate[0];
    for (size_t i = 0; i < RATE_SLOTS; i++) {
        rate_slot *r = &d->rate[i];
        if (r->used && r->addr.sin_addr.s_addr == from->sin_addr.s_addr &&
            r->addr.sin_port == from->sin_port) {
            slot = r;
            break;
        }
        if (!r->used || (oldest->used && r->last < oldest->last)) oldest = r;
    }
    if (!slot) {
        slot = oldest;
        slot->used = true;
        slot->addr = *from;
        slot->tokens = RATE_BURST;
        slot->last = now;
    }
    slot->tokens += (now - slot->last) * RATE_PER_S;
    if (slot->tokens > RATE_BURST) slot->tokens = RATE_BURST;
    slot->last = now;
    if (slot->tokens < 1.0) return false;
    slot->tokens -= 1.0;
    return true;
}

/* Commands no core handler knows (uart_tx, serial_tx, can_tx, usb_export
 * ...): each backend's command() until one answers something other than
 * unknown_cmd. The ack carries the fields the backend put in `reply`. */
static void route_to_backends(hwd_daemon *d, const hwd_cmd *c, const char *data, size_t len,
                              hwd_err fallback, const struct sockaddr_in *from)
{
    cJSON *msg = cJSON_ParseWithLength(data, len);
    const cJSON *jcmd = msg ? cJSON_GetObjectItemCaseSensitive(msg, "cmd") : NULL;
    char a[48];
    if (!cJSON_IsString(jcmd) || !jcmd->valuestring) {
        cJSON_Delete(msg);
        d->errors++;
        if (log_ok(d, HWD_ERR_UNKNOWN_CMD))
            HWD_WARN("Missing or non-string 'cmd' from %s", addr_str(from, a, sizeof a));
        reply(d, c, HWD_ERR_UNKNOWN_CMD, from);
        return;
    }
    hwd_err res = fallback;
    cJSON *extra = cJSON_CreateObject();
    bool handled = false;
    for (size_t i = 0; i < d->nbe && extra; i++) {
        if (!d->be[i].ops->command) continue;
        hwd_err r = d->be[i].ops->command(d->be[i].self, jcmd->valuestring, msg, extra);
        if (r != HWD_ERR_UNKNOWN_CMD) {
            res = r;
            handled = true;
            break;
        }
        /* not this backend's: drop anything it may have added */
        cJSON_Delete(extra);
        extra = cJSON_CreateObject();
    }
    if (res != HWD_OK) {
        d->errors++;
        if (!handled && log_ok(d, res))
            HWD_WARN("Command '%s' from %s: %s", jcmd->valuestring, addr_str(from, a, sizeof a),
                     hwd_err_name(res));
    }
    if (c->has_id) {
        cJSON *ack = cJSON_CreateObject();
        cJSON_AddStringToObject(ack, "t", "ack");
        cJSON_AddStringToObject(ack, "id", c->id);
        cJSON_AddBoolToObject(ack, "ok", res == HWD_OK);
        if (res != HWD_OK) cJSON_AddStringToObject(ack, "err", hwd_err_name(res));
        if (handled && extra) {
            cJSON *it = extra->child;
            while (it) {
                cJSON *next = it->next;
                if (it->string && !cJSON_GetObjectItemCaseSensitive(ack, it->string)) {
                    cJSON_DetachItemViaPointer(extra, it);
                    cJSON_AddItemToObject(ack, it->string, it);
                }
                it = next;
            }
        }
        char *text = cJSON_PrintUnformatted(ack);
        cJSON_Delete(ack);
        send_owned(d->cmd_fd, text, from);
    }
    cJSON_Delete(extra);
    cJSON_Delete(msg);
}

/* set / pulse: Python order -- unknown_tag, not_writable, bad_value, write. */
static backend *check_writable(hwd_daemon *d, const hwd_cmd *c, hwd_err parse_err,
                               const struct sockaddr_in *from)
{
    backend *b = c->tag[0] ? owner_of(d, c->tag) : NULL;
    bool exists = c->tag[0] && (hwd_tagstore_exists(d->store, c->tag) || b);
    hwd_err err = HWD_OK;
    if (!exists) err = HWD_ERR_UNKNOWN_TAG;
    else if (!hwd_tagstore_writable(d->store, c->tag) || !b) err = HWD_ERR_NOT_WRITABLE;
    else if (parse_err != HWD_OK) err = parse_err;
    if (err == HWD_OK) return b;
    d->errors++;
    reply(d, c, err, from);
    return NULL;
}

static void cmd_set(hwd_daemon *d, const hwd_cmd *c, hwd_err perr, const struct sockaddr_in *from)
{
    backend *b = check_writable(d, c, perr, from);
    if (!b) return;
    hwd_err r = b->ops->write ? b->ops->write(b->self, c->tag, &c->value) : HWD_ERR_NOT_WRITABLE;
    if (r != HWD_OK) {
        d->errors++;
        if (r == HWD_ERR_HW_ERROR && log_ok(d, r)) HWD_WARN("Write error for %s", c->tag);
    }
    reply(d, c, r, from);
}

static void cmd_pulse(hwd_daemon *d, const hwd_cmd *c, hwd_err perr, const struct sockaddr_in *from)
{
    backend *b = check_writable(d, c, perr, from);
    if (!b) return;
    if (d->npulses >= MAX_PULSES) {
        d->errors++;
        reply(d, c, HWD_ERR_HW_ERROR, from);
        return;
    }
    hwd_value one = hwd_int(1);
    hwd_err r = b->ops->write ? b->ops->write(b->self, c->tag, &one) : HWD_ERR_NOT_WRITABLE;
    if (r == HWD_OK) {
        pulse_release *p = &d->pulses[d->npulses++];
        snprintf(p->tag, sizeof p->tag, "%s", c->tag);
        p->due = hwd_mono() + c->ms / 1000.0;      /* released by the loop, never slept */
    } else {
        d->errors++;
        if (log_ok(d, HWD_ERR_HW_ERROR)) HWD_WARN("Pulse error for %s", c->tag);
    }
    reply(d, c, r, from);
}

static void release_due_pulses(hwd_daemon *d, double mono)
{
    size_t w = 0;
    for (size_t i = 0; i < d->npulses; i++) {
        pulse_release p = d->pulses[i];
        if (p.due > mono) {
            d->pulses[w++] = p;
            continue;
        }
        backend *b = owner_of(d, p.tag);
        hwd_value zero = hwd_int(0);
        if (!b || !b->ops->write || b->ops->write(b->self, p.tag, &zero) != HWD_OK) {
            d->errors++;
            HWD_WARN("Pulse release failed for %s", p.tag);
        }
    }
    d->npulses = w;
}

static void cmd_history(hwd_daemon *d, const hwd_cmd *c, hwd_err perr, const struct sockaddr_in *from)
{
    if (!d->hist) {
        reply(d, c, HWD_ERR_NO_HISTORY, from);
        return;
    }
    if (!c->tag[0] || !hwd_tagstore_exists(d->store, c->tag)) {
        d->errors++;
        reply(d, c, HWD_ERR_UNKNOWN_TAG, from);
        return;
    }
    if (!hwd_history_logs(d->hist, c->tag)) {
        reply(d, c, HWD_ERR_NO_HISTORY, from);
        return;
    }
    if (perr != HWD_OK) {
        reply(d, c, perr, from);
        return;
    }
    if (!c->has_id) return;
    cJSON *samples = hwd_history_query(d->hist, c->tag, (int)c->seconds, (int)c->points, hwd_now());
    if (!samples) samples = cJSON_CreateArray();
    send_owned(d->cmd_fd, hwd_proto_history_ack(c->id, c->tag, samples), from);
}

static void handle_command(hwd_daemon *d, const char *data, size_t len, const struct sockaddr_in *from)
{
    hwd_cmd c;
    hwd_err err = hwd_proto_parse(data, len, &c);
    char a[48];

    if (!rate_allow(d, from)) {
        d->errors++;
        if (log_ok(d, HWD_ERR_RATE_LIMITED))
            HWD_WARN("Rate limit exceeded by %s", addr_str(from, a, sizeof a));
        reply(d, &c, HWD_ERR_RATE_LIMITED, from);
        hwd_cmd_free(&c);
        return;
    }

    if (err == HWD_ERR_TOO_LARGE || err == HWD_ERR_BAD_JSON || err == HWD_ERR_NOT_AN_OBJECT) {
        d->errors++;
        if (log_ok(d, err)) {
            const char *what = err == HWD_ERR_TOO_LARGE ? "Oversized datagram"
                             : err == HWD_ERR_BAD_JSON ? "Malformed or non-UTF-8 datagram"
                             : "Non-object JSON";
            HWD_WARN("%s (%zu B) from %s", what, len, addr_str(from, a, sizeof a));
        }
        reply(d, &c, err, from);
        hwd_cmd_free(&c);
        return;
    }

    switch (c.kind) {
    case HWD_CMD_SET: cmd_set(d, &c, err, from); break;
    case HWD_CMD_PULSE: cmd_pulse(d, &c, err, from); break;
    case HWD_CMD_UART_TX:
        /* the io backend owns the UART: no backend answering = no link */
        route_to_backends(d, &c, data, len, HWD_ERR_HW_ERROR, from);
        break;
    case HWD_CMD_SUBSCRIBE:
        hwd_subs_subscribe(d->subs, from, c.ttl, hwd_mono());
        reply(d, &c, HWD_OK, from);
        break;
    case HWD_CMD_UNSUBSCRIBE:
        hwd_subs_unsubscribe(d->subs, from);
        reply(d, &c, HWD_OK, from);
        break;
    case HWD_CMD_LIST:      /* ping/list always answer */
        send_owned(d->cmd_fd, hwd_proto_list_ack(c.has_id ? c.id : NULL, d->store), from);
        break;
    case HWD_CMD_PING:
        send_owned(d->cmd_fd, hwd_proto_ping_ack(c.has_id ? c.id : NULL), from);
        break;
    case HWD_CMD_HISTORY: cmd_history(d, &c, err, from); break;
    case HWD_CMD_DISCOVER:  /* only on the discovery socket */
    case HWD_CMD_NONE:
    default:
        route_to_backends(d, &c, data, len, HWD_ERR_UNKNOWN_CMD, from);
        break;
    }
    hwd_cmd_free(&c);
}

static void handle_discovery(hwd_daemon *d, const char *data, size_t len, const struct sockaddr_in *from)
{
    hwd_cmd c;
    hwd_err err = hwd_proto_parse(data, len, &c);
    hwd_cmd_kind kind = c.kind;
    hwd_cmd_free(&c);
    if (err != HWD_OK || kind != HWD_CMD_DISCOVER) return;   /* never answer noise */
    if (!rate_allow(d, from)) return;
    cJSON *h = cJSON_CreateObject();
    cJSON_AddStringToObject(h, "t", "hello");
    cJSON_AddStringToObject(h, "host", d->host);
    cJSON_AddStringToObject(h, "model", d->model);
    cJSON_AddStringToObject(h, "hwd", HWD_VERSION);
    cJSON_AddNumberToObject(h, "cmd_port", d->cfg.cmd_port);
    cJSON_AddNumberToObject(h, "tags", (double)hwd_tagstore_count(d->store));
    char *text = cJSON_PrintUnformatted(h);
    cJSON_Delete(h);
    send_owned(d->disc_fd, text, from);
}

static void drain(hwd_daemon *d, int fd, bool discovery)
{
    static char buf[RECV_BUF + 1];
    for (int i = 0; i < MAX_DGRAMS_PER_WAKE; i++) {
        struct sockaddr_in from;
        socklen_t flen = sizeof from;
        /* MSG_TRUNC: n is the datagram's real length even when it did not
         * fit; an oversized one is too_large whatever it holds, and its head
         * (where the id is looked for) is in buf. */
        ssize_t n = recvfrom(fd, buf, RECV_BUF, MSG_DONTWAIT | MSG_TRUNC,
                             (struct sockaddr *)&from, &flen);
        if (n < 0) {
            if (errno == EINTR) continue;
            return;     /* EAGAIN, or an ICMP error reported on the socket */
        }
        if (flen < sizeof from || from.sin_family != AF_INET) continue;
        size_t len = (size_t)n;
        if (discovery) {
            if (len <= HWD_MAX_DGRAM) handle_discovery(d, buf, len, &from);
        } else {
            handle_command(d, buf, len, &from);
        }
    }
}

/* ---- setup and teardown -------------------------------------------------- */

static int udp_socket(const char *ip, int port, bool reuse, char *err, size_t errlen)
{
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    if (fd < 0) {
        snprintf(err, errlen, "socket: %s", strerror(errno));
        return -1;
    }
    if (reuse) {
        int one = 1;
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    }
    struct sockaddr_in sa;
    memset(&sa, 0, sizeof sa);
    sa.sin_family = AF_INET;
    sa.sin_port = htons((uint16_t)port);
    inet_pton(AF_INET, ip, &sa.sin_addr);
    if (bind(fd, (struct sockaddr *)&sa, sizeof sa) < 0) {
        snprintf(err, errlen, "cannot bind %s:%d: %s", ip, port, strerror(errno));
        close(fd);
        return -1;
    }
    return fd;
}

static bool resolve_ipv4(const char *host, int port, struct sockaddr_in *out)
{
    memset(out, 0, sizeof *out);
    out->sin_family = AF_INET;
    out->sin_port = htons((uint16_t)port);
    if (inet_pton(AF_INET, host, &out->sin_addr) == 1) return true;
    struct addrinfo hints, *res = NULL;
    memset(&hints, 0, sizeof hints);
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_DGRAM;
    if (getaddrinfo(host, NULL, &hints, &res) != 0 || !res) return false;
    out->sin_addr = ((struct sockaddr_in *)res->ai_addr)->sin_addr;
    freeaddrinfo(res);
    return true;
}

static void read_identity(hwd_daemon *d)
{
    if (gethostname(d->host, sizeof d->host - 1) != 0) snprintf(d->host, sizeof d->host, "unknown");
    d->host[sizeof d->host - 1] = '\0';
    d->model[0] = '\0';
    FILE *f = fopen("/proc/device-tree/model", "rb");
    if (!f) return;
    size_t n = fread(d->model, 1, sizeof d->model - 1, f);
    fclose(f);
    d->model[n] = '\0';
    n = strlen(d->model);                          /* the file ends in a NUL */
    while (n > 0 && (d->model[n - 1] == '\n' || d->model[n - 1] == ' ')) d->model[--n] = '\0';
}

static void shutdown_daemon(hwd_daemon *d)
{
    for (size_t i = 0; i < d->nbe; i++)
        if (d->be[i].ops->safe_state) d->be[i].ops->safe_state(d->be[i].self);
    for (size_t i = d->nbe; i-- > 0;)
        if (d->be[i].ops->destroy) d->be[i].ops->destroy(d->be[i].self);
    d->nbe = 0;
    if (d->hist) hwd_history_destroy(d->hist);      /* flushes */
    d->hist = NULL;
    if (d->cmd_fd >= 0) close(d->cmd_fd);
    if (d->send_fd >= 0) close(d->send_fd);
    if (d->disc_fd >= 0) close(d->disc_fd);
    d->cmd_fd = d->send_fd = d->disc_fd = -1;
    hwd_subs_destroy(d->subs);
    d->subs = NULL;
    hwd_tagstore_destroy(d->store);
    d->store = NULL;
    hwd_config_free(&d->cfg);
    if (g_notify_fd >= 0) close(g_notify_fd);
    g_notify_fd = -1;
}

static const hwd_backend_ops *const BACKENDS[] = {
    &hwd_backend_io, &hwd_backend_serial, &hwd_backend_modbus, &hwd_backend_can,
    &hwd_backend_hid, &hwd_backend_usb, &hwd_backend_sensors,
};
#define NBACKENDS (sizeof BACKENDS / sizeof BACKENDS[0])

static double next_deadline(const hwd_daemon *d, double next_tick)
{
    double t = next_tick;
    for (size_t i = 0; i < d->npulses; i++)
        if (d->pulses[i].due < t) t = d->pulses[i].due;
    return t;
}

int hwd_run(const hwd_options *opt)
{
    static hwd_daemon dd;           /* large (pulse/rate tables): not on the stack */
    hwd_daemon *d = &dd;
    memset(d, 0, sizeof *d);
    d->cmd_fd = d->send_fd = d->disc_fd = -1;
    d->start_mono = hwd_mono();
    hwd_log_level = opt->log_level;
    char err[512];

    /* 1. config: the core sections here, the rest by their backends */
    if (!hwd_config_load(opt->config_path, &d->cfg, err, sizeof err)) {
        HWD_ERROR("%s", err);
        return 1;
    }
    for (size_t i = 0; i < NBACKENDS; i++) {
        err[0] = '\0';
        if (BACKENDS[i]->validate && BACKENDS[i]->validate(&d->cfg, err, sizeof err) != 0) {
            HWD_ERROR("%s", err[0] ? err : "invalid config");
            hwd_config_free(&d->cfg);
            return 1;
        }
    }
    bool history_ok = false;
    if (d->cfg.history) {
        err[0] = '\0';
        if (hwd_history_validate(d->cfg.history, err, sizeof err) != 0)
            HWD_ERROR("history config error: %s", err[0] ? err : "invalid");
        else
            history_ok = true;
    }

    /* Signals: blocked everywhere (backend threads inherit this) except
     * inside ppoll() below, where the handler only sets g_stop. */
    sigset_t block, orig;
    sigemptyset(&block);
    sigaddset(&block, SIGTERM);
    sigaddset(&block, SIGINT);
    sigprocmask(SIG_BLOCK, &block, &orig);
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_signal;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);
    signal(SIGPIPE, SIG_IGN);
    g_stop = 0;

    /* 2. tag store with the system tags */
    d->store = hwd_tagstore_create();
    if (!d->store) {
        HWD_ERROR("out of memory");
        hwd_config_free(&d->cfg);
        sigprocmask(SIG_SETMASK, &orig, NULL);
        return 1;
    }
    hwd_tagstore_register(d->store, "sys.uptime", hwd_float(0.0), false);
    hwd_tagstore_register(d->store, "sys.errors", hwd_int(0), false);

    /* 3. backends, in backend.h order */
    hwd_backend_opts bopts = {opt->sim, opt->strict, opt->modbus_live, d->cfg.poll_interval_ms};
    for (size_t i = 0; i < NBACKENDS; i++) {
        err[0] = '\0';
        void *self = BACKENDS[i]->create(&d->cfg, d->store, &bopts, err, sizeof err);
        if (!self) {
            if (err[0]) {
                HWD_ERROR("%s: %s", BACKENDS[i]->name, err);
                shutdown_daemon(d);
                sigprocmask(SIG_SETMASK, &orig, NULL);
                return 1;
            }
            continue;
        }
        d->be[d->nbe].ops = BACKENDS[i];
        d->be[d->nbe].self = self;
        d->nbe++;
        HWD_DEBUG("backend %s ready", BACKENDS[i]->name);
    }
    for (size_t i = 0; i < d->nbe; i++)
        if (d->be[i].ops->start) d->be[i].ops->start(d->be[i].self);

    /* 4. historian: a failure is logged, the I/O runs on without it */
    if (history_ok) {
        err[0] = '\0';
        d->hist = hwd_history_create(d->cfg.history, err, sizeof err);
        if (!d->hist) HWD_ERROR("history: %s", err[0] ? err : "cannot open the database");
    }

    /* 5. sockets */
    struct sockaddr_in sink;
    d->sink_ok = resolve_ipv4(d->cfg.sink_host, d->cfg.sink_port, &sink);
    if (!d->sink_ok) HWD_WARN("cannot resolve telemetry sink %s", d->cfg.sink_host);
    d->subs = hwd_subs_create(&sink, d->cfg.subscriber_ttl_s);
    err[0] = '\0';
    d->cmd_fd = d->subs ? udp_socket("127.0.0.1", d->cfg.cmd_port, false, err, sizeof err) : -1;
    if (d->cmd_fd < 0) {
        HWD_ERROR("command socket: %s", err[0] ? err : "out of memory");
        shutdown_daemon(d);
        sigprocmask(SIG_SETMASK, &orig, NULL);
        return 1;
    }
    d->send_fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    if (d->send_fd < 0) {
        HWD_ERROR("telemetry socket: %s", strerror(errno));
        shutdown_daemon(d);
        sigprocmask(SIG_SETMASK, &orig, NULL);
        return 1;
    }
    if (d->cfg.discovery && !opt->selftest) {
        d->disc_fd = udp_socket("0.0.0.0", d->cfg.discovery_port, true, err, sizeof err);
        if (d->disc_fd < 0) HWD_WARN("discovery disabled: %s", err);
    }
    read_identity(d);

    /* 6. selftest: one poll, one frame on stdout */
    if (opt->selftest) {
        double wall = hwd_now();
        poll_backends(d, hwd_mono(), wall);
        char *frame = next_frame(d, wall);
        int rc = 0;
        if (frame) {
            fputs(frame, stdout);
            fputc('\n', stdout);
            fflush(stdout);
            free(frame);
        } else {
            rc = 1;
        }
        shutdown_daemon(d);
        sigprocmask(SIG_SETMASK, &orig, NULL);
        return rc;
    }

    /* 7. the loop */
    sd_notify("READY=1");
    HWD_INFO("Hardware daemon ready -- cmd=127.0.0.1:%d, sink=%s:%d, poll=%dms, backends=%zu%s",
             d->cfg.cmd_port, d->cfg.sink_host, d->cfg.sink_port, (int)d->cfg.poll_interval_ms,
             d->nbe, d->hist ? ", history" : "");
    double period = d->cfg.poll_interval_ms / 1000.0;
    double next_tick = hwd_mono();
    sigset_t waitmask = orig;
    sigdelset(&waitmask, SIGTERM);
    sigdelset(&waitmask, SIGINT);

    while (!g_stop) {
        double now = hwd_mono();
        release_due_pulses(d, now);
        if (now >= next_tick) {
            tick(d);
            next_tick += period;
            now = hwd_mono();
            if (next_tick <= now) next_tick = now + period;   /* fell behind: no burst */
        }
        double wait = next_deadline(d, next_tick) - now;
        if (wait < 0) wait = 0;
        struct timespec ts;
        ts.tv_sec = (time_t)wait;
        ts.tv_nsec = (long)((wait - (double)ts.tv_sec) * 1e9);
        if (ts.tv_nsec >= 1000000000L) ts.tv_nsec = 999999999L;

        struct pollfd pfd[2];
        nfds_t nfd = 0;
        pfd[nfd].fd = d->cmd_fd;
        pfd[nfd].events = POLLIN;
        pfd[nfd++].revents = 0;
        if (d->disc_fd >= 0) {
            pfd[nfd].fd = d->disc_fd;
            pfd[nfd].events = POLLIN;
            pfd[nfd++].revents = 0;
        }
        int rc = ppoll(pfd, nfd, &ts, &waitmask);
        if (rc < 0) {
            if (errno == EINTR) continue;
            d->errors++;
            if (log_ok(d, HWD_ERR_HW_ERROR)) HWD_WARN("poll: %s", strerror(errno));
            continue;
        }
        if (rc == 0) continue;
        if (pfd[0].revents) drain(d, d->cmd_fd, false);
        if (nfd > 1 && pfd[1].revents) drain(d, d->disc_fd, true);
    }

    /* 8. shutdown: safe states, historian flushed */
    HWD_INFO("Driving outputs to safe states and releasing resources");
    shutdown_daemon(d);
    sigprocmask(SIG_SETMASK, &orig, NULL);
    HWD_INFO("Shutdown complete");
    return 0;
}
