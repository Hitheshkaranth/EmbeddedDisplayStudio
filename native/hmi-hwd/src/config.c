/*
 * config.c -- hwd.json loading and core validation (config.h).
 * OWNER: A1. Mirrors daemon/hmi_hwd.py load_config for the "daemon" section,
 * the required "gpio" section and the gpio/adc tag names; every other section
 * is validated by its backend (hwd_backend_ops.validate, called by daemon.c).
 */
#include "config.h"
#include "hwd.h"

#include <ctype.h>
#include <errno.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void fail(char *err, size_t errlen, const char *fmt, ...)
{
    if (!err || !errlen) return;
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(err, errlen, fmt, ap);
    va_end(ap);
}

static cJSON *section(const cJSON *root, const char *name)
{
    cJSON *s = cJSON_GetObjectItemCaseSensitive(root, name);
    return cJSON_IsObject(s) ? s : NULL;
}

/* A JSON number with no fractional part (Python isinstance(x, int)). */
static bool is_int(const cJSON *j)
{
    return cJSON_IsNumber(j) && isfinite(j->valuedouble) && j->valuedouble == floor(j->valuedouble);
}

/* "host:port" split at the last colon; port all digits, 1..65535. */
static bool split_sink(const char *sink, char *host, size_t maxlen, int *port, char *err, size_t errlen)
{
    const char *colon = strrchr(sink, ':');
    if (!colon) {
        fail(err, errlen, "daemon.telemetry_sink must be 'host:port', got '%s'", sink);
        return false;
    }
    const char *ps = colon + 1;
    bool digits = *ps != '\0';
    for (const char *q = ps; *q; q++)
        if (!isdigit((unsigned char)*q)) digits = false;
    long v = digits && strlen(ps) <= 6 ? strtol(ps, NULL, 10) : 0;
    if (!digits || v < 1 || v > 65535) {
        fail(err, errlen, "daemon.telemetry_sink port must be 1..65535, got '%s'", ps);
        return false;
    }
    size_t hlen = (size_t)(colon - sink);
    if (hlen == 0 || hlen >= maxlen) {
        fail(err, errlen, "daemon.telemetry_sink must be 'host:port', got '%s'", sink);
        return false;
    }
    memcpy(host, sink, hlen);
    host[hlen] = '\0';
    *port = (int)v;
    return true;
}

static bool check_tag_names(const cJSON *obj, const char *where, char *err, size_t errlen)
{
    if (!cJSON_IsObject(obj)) return true;
    const cJSON *it;
    cJSON_ArrayForEach(it, obj) {
        if (!it->string || !hwd_tag_valid(it->string)) {
            fail(err, errlen, "Invalid tag name '%s' in %s", it->string ? it->string : "", where);
            return false;
        }
    }
    return true;
}

static bool parse_daemon(const cJSON *d, hwd_config *cfg, char *err, size_t errlen)
{
    const cJSON *j;

    cfg->poll_interval_ms = 100;
    if ((j = cJSON_GetObjectItemCaseSensitive(d, "poll_interval_ms"))) {
        if (!cJSON_IsNumber(j) || !isfinite(j->valuedouble) || j->valuedouble <= 0) {
            fail(err, errlen, "daemon.poll_interval_ms must be a positive number");
            return false;
        }
        cfg->poll_interval_ms = j->valuedouble;
    }

    cfg->cmd_port = 5000;
    if ((j = cJSON_GetObjectItemCaseSensitive(d, "cmd_port"))) {
        if (!is_int(j) || j->valuedouble < 1 || j->valuedouble > 65535) {
            fail(err, errlen, "daemon.cmd_port must be 1..65535");
            return false;
        }
        cfg->cmd_port = (int)j->valuedouble;
    }

    snprintf(cfg->sink_host, sizeof cfg->sink_host, "127.0.0.1");
    cfg->sink_port = 5001;
    if ((j = cJSON_GetObjectItemCaseSensitive(d, "telemetry_sink"))) {
        if (!cJSON_IsString(j) || !j->valuestring) {
            fail(err, errlen, "daemon.telemetry_sink must be 'host:port'");
            return false;
        }
        if (!split_sink(j->valuestring, cfg->sink_host, sizeof cfg->sink_host, &cfg->sink_port,
                        err, errlen))
            return false;
    }

    cfg->subscriber_ttl_s = 5;
    if ((j = cJSON_GetObjectItemCaseSensitive(d, "subscriber_ttl_s"))) {
        if (!cJSON_IsNumber(j) || !isfinite(j->valuedouble) || j->valuedouble <= 0) {
            fail(err, errlen, "daemon.subscriber_ttl_s must be a positive number");
            return false;
        }
        cfg->subscriber_ttl_s = j->valuedouble;
    }

    cfg->discovery = true;
    if ((j = cJSON_GetObjectItemCaseSensitive(d, "discovery"))) {
        if (cJSON_IsBool(j)) cfg->discovery = cJSON_IsTrue(j);
        else if (cJSON_IsNumber(j)) cfg->discovery = j->valuedouble != 0;
        else {
            fail(err, errlen, "daemon.discovery must be true or false");
            return false;
        }
    }

    cfg->discovery_port = HWD_DISCOVERY_PORT;
    if ((j = cJSON_GetObjectItemCaseSensitive(d, "discovery_port"))) {
        if (!is_int(j) || j->valuedouble < 1 || j->valuedouble > 65535) {
            fail(err, errlen, "daemon.discovery_port must be 1..65535");
            return false;
        }
        cfg->discovery_port = (int)j->valuedouble;
    }
    return true;
}

bool hwd_config_parse(const char *json, hwd_config *cfg, char *err, size_t errlen)
{
    if (err && errlen) err[0] = '\0';
    if (!cfg) return false;
    memset(cfg, 0, sizeof *cfg);
    if (!json) { fail(err, errlen, "no config"); return false; }

    const char *end = NULL;
    cJSON *root = cJSON_ParseWithOpts(json, &end, true);
    if (!root) {
        fail(err, errlen, "Invalid JSON in config near offset %ld",
             end ? (long)(end - json) : 0L);
        return false;
    }
    if (!cJSON_IsObject(root)) {
        cJSON_Delete(root);
        fail(err, errlen, "Config must be a JSON object");
        return false;
    }

    static const char *const required[] = {"daemon", "gpio"};
    for (size_t i = 0; i < 2; i++) {
        if (!cJSON_GetObjectItemCaseSensitive(root, required[i])) {
            cJSON_Delete(root);
            fail(err, errlen, "Config missing required section '%s'", required[i]);
            return false;
        }
        if (!section(root, required[i])) {
            cJSON_Delete(root);
            fail(err, errlen, "Config section '%s' must be an object", required[i]);
            return false;
        }
    }

    if (!parse_daemon(section(root, "daemon"), cfg, err, errlen)) {
        cJSON_Delete(root);
        memset(cfg, 0, sizeof *cfg);
        return false;
    }

    const cJSON *gpio = section(root, "gpio");
    const cJSON *adc = section(root, "adc");
    if (!check_tag_names(cJSON_GetObjectItemCaseSensitive(gpio, "outputs"), "gpio.outputs", err, errlen) ||
        !check_tag_names(cJSON_GetObjectItemCaseSensitive(gpio, "inputs"), "gpio.inputs", err, errlen) ||
        (adc && !check_tag_names(cJSON_GetObjectItemCaseSensitive(adc, "channels"), "adc.channels",
                                 err, errlen))) {
        cJSON_Delete(root);
        memset(cfg, 0, sizeof *cfg);
        return false;
    }

    cfg->root = root;
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
    if (err && errlen) err[0] = '\0';
    if (cfg) memset(cfg, 0, sizeof *cfg);
    FILE *f = fopen(path, "rb");
    if (!f) {
        if (errno == ENOENT) fail(err, errlen, "Config file not found: %s", path);
        else fail(err, errlen, "Cannot read config %s: %s", path, strerror(errno));
        return false;
    }
    size_t cap = 4096, len = 0;
    char *buf = malloc(cap);
    while (buf) {
        if (len + 1 >= cap) {
            char *nb = realloc(buf, cap * 2);
            if (!nb) { free(buf); buf = NULL; break; }
            buf = nb;
            cap *= 2;
        }
        size_t rd = fread(buf + len, 1, cap - len - 1, f);
        len += rd;
        if (rd == 0) break;
    }
    bool rerr = ferror(f);
    fclose(f);
    if (!buf || rerr) {
        free(buf);
        fail(err, errlen, "Cannot read config %s", path);
        return false;
    }
    buf[len] = '\0';
    if (strlen(buf) != len) {
        free(buf);
        fail(err, errlen, "Invalid JSON in config %s: NUL byte", path);
        return false;
    }
    bool ok = hwd_config_parse(buf, cfg, err, errlen);
    free(buf);
    if (!ok && err && errlen && strncmp(err, "Invalid JSON", 12) == 0) {
        char tmp[256];
        snprintf(tmp, sizeof tmp, "%s", err);
        fail(err, errlen, "%s (%s)", tmp, path);
    }
    return ok;
}

void hwd_config_free(hwd_config *cfg)
{
    if (!cfg) return;
    cJSON_Delete(cfg->root);
    memset(cfg, 0, sizeof *cfg);
}
