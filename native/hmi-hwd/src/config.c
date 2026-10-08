/*
 * config.c -- hwd.json loading and core validation (config.h).
 * OWNER: A1. STUB written with the skeleton: every function compiles
 * and fails safe; the owner replaces the bodies (not the signatures).
 */
#include "config.h"
#include "hwd.h"

#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Parse "host:port" (host up to maxlen-1 chars, port 1..65535). */
static bool split_host_port(const char *sink, char *host, size_t maxlen, int *port)
{
    if (!sink || !*sink) return false;
    const char *colon = strrchr(sink, ':');
    if (!colon || colon == sink) return false;
    size_t hlen = (size_t)(colon - sink);
    if (hlen >= maxlen) return false;
    memcpy(host, sink, hlen);
    host[hlen] = '\0';
    if (host[0] == '\0') return false;
    const char *colonp = colon + 1;
    if (*colonp == '\0') return false;
    for (const char *q = colonp; *q; q++)
        if (!isdigit((unsigned char)*q)) return false;
    long v = strtol(colonp, NULL, 10);
    if (v < 1 || v > 65535) return false;
    *port = (int)v;
    return true;
}

static cJSON *section(const cJSON *root, const char *name)
{
    cJSON *s = cJSON_GetObjectItemCaseSensitive(root, name);
    return cJSON_IsObject(s) ? s : NULL;
}

bool hwd_config_parse(const char *json, hwd_config *cfg, char *err, size_t errlen)
{
    if (errlen) err[0] = '\0';
    if (!json) { if (errlen) snprintf(err, errlen, "no config"); return false; }

    cJSON *root = cJSON_Parse(json);
    if (!root) { if (errlen) snprintf(err, errlen, "invalid JSON"); return false; }

    /* daemon section required. */
    cJSON *dcfg = section(root, "daemon");
    if (!dcfg) { cJSON_Delete(root); if (errlen) snprintf(err, errlen, "missing section 'daemon'"); return false; }

    /* gpio section required. */
    cJSON *gpio = section(root, "gpio");
    if (!gpio) { cJSON_Delete(root); if (errlen) snprintf(err, errlen, "missing section 'gpio'"); return false; }

    /* poll_interval_ms: positive number, default 100. */
    cJSON *pm = cJSON_GetObjectItemCaseSensitive(dcfg, "poll_interval_ms");
    double poll_ms;
    if (cJSON_IsNumber(pm)) {
        poll_ms = pm->valuedouble;
        if (!isfinite(poll_ms) || poll_ms <= 0.0) {
            cJSON_Delete(root);
            if (errlen) snprintf(err, errlen, "daemon.poll_interval_ms must be positive");
            return false;
        }
    } else {
        poll_ms = 100.0;
    }

    /* cmd_port: integer 1..65535, default 5000. */
    cJSON *cp = cJSON_GetObjectItemCaseSensitive(dcfg, "cmd_port");
    int cmd_port;
    if (cJSON_IsNumber(cp) && !cJSON_IsBool(cp)) {
        long v = (long)cp->valuedouble;
        if (v < 1 || v > 65535) {
            cJSON_Delete(root);
            if (errlen) snprintf(err, errlen, "daemon.cmd_port must be 1..65535");
            return false;
        }
        cmd_port = (int)v;
    } else {
        cmd_port = 5000;
    }

    /* telemetry_sink: "host:port", default 127.0.0.1:5001. */
    char sink_host[64];
    int sink_port;
    cJSON *ts = cJSON_GetObjectItemCaseSensitive(dcfg, "telemetry_sink");
    if (cJSON_IsString(ts)) {
        if (!split_host_port(ts->valuestring, sink_host, sizeof sink_host, &sink_port)) {
            cJSON_Delete(root);
            if (errlen) snprintf(err, errlen, "daemon.telemetry_sink must be 'host:port' with port 1..65535");
            return false;
        }
    } else {
        snprintf(sink_host, sizeof sink_host, "127.0.0.1");
        sink_port = 5001;
    }

    /* subscriber_ttl_s: positive, default 5. */
    cJSON *tt = cJSON_GetObjectItemCaseSensitive(dcfg, "subscriber_ttl_s");
    double ttl;
    if (cJSON_IsNumber(tt)) {
        ttl = tt->valuedouble;
        if (!isfinite(ttl) || ttl <= 0.0) {
            cJSON_Delete(root);
            if (errlen) snprintf(err, errlen, "daemon.subscriber_ttl_s must be positive");
            return false;
        }
    } else {
        ttl = 5.0;
    }

    /* discovery: default true. */
    cJSON *disc = cJSON_GetObjectItemCaseSensitive(dcfg, "discovery");
    bool discovery;
    if (cJSON_IsBool(disc)) {
        discovery = cJSON_IsTrue(disc);
    } else if (cJSON_IsNumber(disc)) {
        discovery = !cJSON_IsTrue(disc);
    } else {
        discovery = true;
    }

    /* gpio outputs/inputs tag names. */
    const char *const field[] = {"outputs", "inputs", NULL};
    for (size_t fi = 0; field[fi]; fi++) {
        const char *fld = field[fi];
        cJSON *g = cJSON_GetObjectItemCaseSensitive(gpio, fld);
        if (!cJSON_IsObject(g)) continue;
        cJSON *it;
        cJSON_ArrayForEach(it, g) {
            if (!(cJSON_IsString(it) && it->string) || !hwd_tag_valid(it->string)) {
                cJSON_Delete(root);
                if (errlen) snprintf(err, errlen, "invalid tag name '%s' in gpio.%s", it->string, fld);
                return false;
            }
        }
    }

    /* adc channels tag names. */
    cJSON *adc = section(root, "adc");
    if (adc) {
        cJSON *channels = cJSON_GetObjectItemCaseSensitive(adc, "channels");
        if (cJSON_IsObject(channels)) {
            cJSON *it;
cJSON_ArrayForEach(it, channels) {
            if (!(cJSON_IsString(it) && it->string) || !hwd_tag_valid(it->string)) {
                cJSON_Delete(root);
                if (errlen) snprintf(err, errlen, "invalid tag name '%s' in adc.channels", it->string);
                return false;
            }
        }
        }
    }

    memset(cfg, 0, sizeof *cfg);
    cfg->root = root;
    cfg->poll_interval_ms = poll_ms;
    cfg->cmd_port = cmd_port;
    snprintf(cfg->sink_host, sizeof cfg->sink_host, "%s", sink_host);
    cfg->sink_port = sink_port;
    cfg->subscriber_ttl_s = ttl;
    cfg->discovery = discovery;
    cfg->discovery_port = HWD_DISCOVERY_PORT;
    cfg->gpio = gpio;
    cfg->adc = adc;
    cfg->uart = section(root, "uart");
    cfg->modbus = section(root, "modbus");
    cfg->history = section(root, "history");
    cfg->serial = section(root, "serial");
    cfg->modbus_rtu = section(root, "modbus_rtu");
    cfg->can = section(root, "can");
    cfg->hid = section(root, "hid");
    cfg->usb = section(root, "usb");
    cfg->i2c = section(root, "i2c");
    cfg->spi = section(root, "spi");
    return true;
}

bool hwd_config_load(const char *path, hwd_config *cfg, char *err, size_t errlen)
{
    if (errlen) err[0] = '\0';
    FILE *f = fopen(path, "r");
    if (!f) { if (errlen) snprintf(err, errlen, "config file not found: %s", path); return false; }
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); if (errlen) snprintf(err, errlen, "cannot seek config"); return false; }
    long sz = ftell(f);
    if (sz < 0) { fclose(f); if (errlen) snprintf(err, errlen, "cannot size config"); return false; }
    rewind(f);
    char *buf = malloc((size_t)sz + 1);
    if (!buf) { fclose(f); if (errlen) snprintf(err, errlen, "out of memory"); return false; }
    size_t rd = fread(buf, 1, (size_t)sz, f);
    fclose(f);
    buf[rd] = '\0';
    bool ok = hwd_config_parse(buf, cfg, err, errlen);
    free(buf);
    return ok;
}

void hwd_config_free(hwd_config *cfg)
{
    if (!cfg) return;
    if (cfg->root) cJSON_Delete(cfg->root);
    cfg->root = NULL;
}