/*
 * io.c -- GPIO (uAPI v2, v1 fallback), IIO ADC and the native UART ("gpio", "adc",
 * "uart"; daemon/hmi_hwd.py GpioV1/GpioV2/GpioSim/IioAdc/IioSim/UartLink).
 * OWNER: A3. STUB written with the skeleton: every function compiles
 * and fails safe; the owner replaces the bodies (not the signatures).
 *
 * Backend contract: register every tag in create(), poll() within a few ms,
 * degraded reads store HWD_NULL + "bad"/"stale", sim mode follows the rules
 * below, strict mode treats a device that cannot be opened as fatal.
 */
#include "backend.h"

#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifdef __linux__
#include <termios.h>
#include <poll.h>
#endif

/* --- small cJSON helpers (backends read their own sections) ------------- */

static const cJSON *json_find(const cJSON *o, const char *name)
{
    return o ? cJSON_GetObjectItemCaseSensitive(o, name) : NULL;
}
static int json_int(const cJSON *o, const char *name, int def)
{
    const cJSON *v = json_find(o, name);
    return (v && v->type == cJSON_Number) ? (int)v->valuedouble : def;
}
static bool json_bool(const cJSON *o, const char *name, bool def)
{
    const cJSON *v = json_find(o, name);
    return (v && v->type == cJSON_True) ? true
         : (v && v->type == cJSON_False) ? false
         : def;
}
static double json_double(const cJSON *o, const char *name, double def)
{
    const cJSON *v = json_find(o, name);
    return (v && v->type == cJSON_Number) ? v->valuedouble : def;
}
static int json_str(const cJSON *o, const char *name, char *buf, size_t n)
{
    const cJSON *v = json_find(o, name);
    if (!v || v->type != cJSON_String || !v->valuestring) { if (n) buf[0] = '\0'; return 0; }
    snprintf(buf, n, "%s", v->valuestring);
    return 1;
}

/* --- configuration ------------------------------------------------------ */

typedef struct {
    char tag[HWD_MAX_TAG];
    int offset;
    bool active_low;
    bool is_output;
    bool writable;      /* an output tag is writable */
    int safe_state;
    int value;          /* logical 0/1 */
} line;

typedef struct {
    char tag[HWD_MAX_TAG];
    char channel_file[128];
    double gain;
    double transform_offset;
    int fd;             /* raw file descriptor, -1 until opened */
} chan;

typedef struct {
    hwd_backend_opts opts;
    hwd_tagstore *store;

    /* GPIO. */
    char chip[128];
    char consumer[64];
    line *outputs; size_t n_outputs;
    line *inputs;  size_t n_inputs;

    /* ADC. */
    chan *ads; size_t n_ads;
    bool adc_sim;     /* using the simulated ADC */

    /* UART. */
    char uart_port[128];
    int uart_fd;
    int uart_rx_count;

    /* Simulation state. */
    int sim_fail_count;
} iod_t;

/* ---- validate ---------------------------------------------------------- */

static int v_validate(const hwd_config *cfg, char *err, size_t errlen)
{
    const cJSON *gpio = cfg->gpio;
    if (gpio) {
        const cJSON *outputs = json_find(gpio, "outputs");
        if (outputs)
            for (cJSON *o = outputs->child; o; o = o->next) {
                if (json_int(o, "offset", -1) < 0) {
                    snprintf(err, errlen, "gpio outputs.%s: integer offset >= 0", o->string);
                    return -1;
                }
            }
        const cJSON *inputs = json_find(gpio, "inputs");
        if (inputs)
            for (cJSON *i = inputs->child; i; i = i->next) {
                if (json_int(i, "offset", -1) < 0) {
                    snprintf(err, errlen, "gpio inputs.%s: integer offset >= 0", i->string);
                    return -1;
                }
            }
    }

    const cJSON *adc = cfg->adc;
    if (adc) {
        const cJSON *channels = json_find(adc, "channels");
        if (channels)
            for (cJSON *c = channels->child; c; c = c->next) {
                if (!json_find(c, "channel_file")) {
                    snprintf(err, errlen, "adc channels.%s: needs channel_file", c->string);
                    return -1;
                }
            }
    }

    const cJSON *uart = cfg->uart;
    if (uart) {
        const cJSON *port = json_find(uart, "port");
        if (!port || port->type != cJSON_String || !port->valuestring || !*port->valuestring) {
            snprintf(err, errlen, "uart: needs port");
            return -1;
        }
        int baud = json_int(uart, "baudrate", 0);
        if (baud <= 0) {
            snprintf(err, errlen, "uart: baudrate must be positive");
            return -1;
        }
    }

    if (errlen) err[0] = '\0';
    return 0;
}

/* ---- helpers to register sections -------------------------------------- */

static void register_outputs(iod_t *t, hwd_tagstore *store, const cJSON *outputs, bool sim)
{
    if (!outputs) return;
    t->n_outputs = cJSON_GetArraySize(outputs);
t->outputs = calloc(t->n_outputs, sizeof *t->outputs);
    if (!t->outputs) return;
    size_t oi = 0;
    for (cJSON *o = outputs->child; o && oi < t->n_outputs; o = o->next) {
        line *L = &t->outputs[oi++];
        snprintf(L->tag, sizeof L->tag, "%s", o->string);
        L->offset = json_int(o, "offset", 0);
        L->active_low = json_bool(o, "active_low", false);
        L->safe_state = json_int(o, "safe_state", 0);
        bool initial = json_bool(o, "initial", false);
        L->value = sim ? (initial ? 1 : 0) : L->safe_state;
        L->is_output = true;
        L->writable = true;
        hwd_tagstore_register(store, L->tag, hwd_bool(initial), true);
    }
}

static void register_inputs(iod_t *t, hwd_tagstore *store, const cJSON *inputs)
{
    if (!inputs) return;
    t->n_inputs = cJSON_GetArraySize(inputs);
t->inputs = calloc(t->n_inputs, sizeof *t->inputs);
    if (!t->inputs) return;
    size_t ii = 0;
    for (cJSON *i = inputs->child; i && ii < t->n_inputs; i = i->next) {
        line *L = &t->inputs[ii++];
        snprintf(L->tag, sizeof L->tag, "%s", i->string);
        L->offset = json_int(i, "offset", 0);
        L->active_low = json_bool(i, "active_low", false);
        L->is_output = false;
        hwd_tagstore_register(store, L->tag, hwd_bool(false), false);
    }
}

static void register_ads(iod_t *t, hwd_tagstore *store, const cJSON *channels)
{
    if (!channels) return;
    t->n_ads = cJSON_GetArraySize(channels);
    t->ads = calloc(t->n_ads, sizeof *t->ads);
    if (!t->ads) return;
    size_t ai = 0;
    for (cJSON *c = channels->child; c && ai < t->n_ads; c = c->next) {
        chan *ch = &t->ads[ai++];
        snprintf(ch->tag, sizeof ch->tag, "%s", c->string);
        json_str(c, "channel_file", ch->channel_file, sizeof ch->channel_file);
        ch->gain = json_double(c, "gain", 1.0);
        ch->transform_offset = json_double(c, "transform_offset", 0.0);
        ch->fd = -1;
        hwd_tagstore_register(store, ch->tag, hwd_null(), false);
    }
}

/* ---- create ------------------------------------------------------------ */

static void *v_create(const hwd_config *cfg, hwd_tagstore *store, const hwd_backend_opts *opts,
                      char *err, size_t errlen)
{
    if (errlen) err[0] = '\0';

    iod_t *t = calloc(1, sizeof *t);
    if (!t) return NULL;
    t->opts = *opts;
    t->store = store;
    t->uart_fd = -1;
    t->uart_rx_count = 0;

    /* GPIO section (always present). */
    const cJSON *gpio = cfg->gpio;
    if (gpio) {
        json_str(gpio, "chip", t->chip, sizeof t->chip);
        if (!*t->chip) snprintf(t->chip, sizeof t->chip, "/dev/gpiochip0");
        json_str(gpio, "consumer", t->consumer, sizeof t->consumer);

        register_outputs(t, store, json_find(gpio, "outputs"), t->opts.sim);
        register_inputs(t, store, json_find(gpio, "inputs"));
    }

    /* ADC section (optional). */
    const cJSON *adc = cfg->adc;
    if (adc) {
        if (t->opts.sim) {
            register_ads(t, store, json_find(adc, "channels"));
            t->adc_sim = true;
        }
    }

    /* UART section (optional). */
    const cJSON *uart = cfg->uart;
    if (uart) {
        json_str(uart, "port", t->uart_port, sizeof t->uart_port);
        hwd_tagstore_register(store, "uart.rx", hwd_int(0), false);
    }

    return t;
}

/* ---- owns -------------------------------------------------------------- */

static bool owns(void *self, const char *tag)
{
    iod_t *t = self;
    if (!t) return false;
    for (size_t i = 0; i < t->n_outputs; i++)
        if (strcmp(t->outputs[i].tag, tag) == 0) return true;
    for (size_t i = 0; i < t->n_inputs; i++)
        if (strcmp(t->inputs[i].tag, tag) == 0) return true;
    for (size_t i = 0; i < t->n_ads; i++)
        if (strcmp(t->ads[i].tag, tag) == 0) return true;
    return strcmp(tag, "uart.rx") == 0;
}

/* ---- poll -------------------------------------------------------------- */

static void poll_sim(iod_t *t, double now)
{
    /* Outputs read back the driven state. */
    for (size_t i = 0; i < t->n_outputs; i++) {
        line *L = &t->outputs[i];
        hwd_value v = hwd_bool(L->value != 0);
        hwd_tagstore_set(t->store, L->tag, &v);
        hwd_value_clear(&v);
    }
    /* Inputs read inactive. */
    for (size_t i = 0; i < t->n_inputs; i++) {
        line *L = &t->inputs[i];
        hwd_value v = hwd_bool(false);
        hwd_tagstore_set(t->store, L->tag, &v);
        hwd_value_clear(&v);
    }
    /* ADC channels ramp; HWD_SIM_FAIL makes a channel fail (null + "bad"). */
    for (size_t i = 0; i < t->n_ads; i++) {
        chan *c = &t->ads[i];
        hwd_value v;
        if (hwd_sim_fails(c->tag)) {
            t->sim_fail_count++;
            v = hwd_null();
            hwd_tagstore_set_quality(t->store, c->tag, "bad");
        } else {
            v = hwd_float(hwd_sim_ramp(now, 0.0, 3.3, 10.0));
        }
        hwd_tagstore_set(t->store, c->tag, &v);
        hwd_value_clear(&v);
    }
}

static void poll_real(iod_t *t)
{
    for (size_t i = 0; i < t->n_inputs; i++) {
        line *L = &t->inputs[i];
        hwd_value v = hwd_bool(L->value != 0);
        hwd_tagstore_set(t->store, L->tag, &v);
        hwd_value_clear(&v);
    }
    for (size_t i = 0; i < t->n_outputs; i++) {
        line *L = &t->outputs[i];
        hwd_value v = hwd_bool(L->value != 0);
        hwd_tagstore_set(t->store, L->tag, &v);
        hwd_value_clear(&v);
    }
    for (size_t i = 0; i < t->n_ads; i++) {
        chan *c = &t->ads[i];
        if (c->fd < 0) continue;
        if (lseek(c->fd, 0, SEEK_SET) < 0) continue;
        char buf[64];
        ssize_t n = read(c->fd, buf, sizeof buf - 1);
        if (n <= 0) continue;
        buf[n] = '\0';
        char *end = NULL;
        errno = 0;
        long raw = strtol(buf, &end, 10);
        if (end == buf) continue;
        double volts = (double)raw * c->gain / 1000.0 + c->transform_offset;
        hwd_value v = hwd_float(volts);
        hwd_tagstore_set(t->store, c->tag, &v);
        hwd_value_clear(&v);
    }
}

/* Count complete lines in the UART input so far. */
static void uart_poll(iod_t *t)
{
    if (t->uart_fd < 0) return;
    struct pollfd pfd = { .fd = t->uart_fd, .events = POLLIN };
    if (poll(&pfd, 1, 0) <= 0) return;
    if (!(pfd.revents & POLLIN)) return;
    char buf[256];
    while (true) {
        ssize_t n = read(t->uart_fd, buf, sizeof buf);
        if (n <= 0) break;
        for (ssize_t i = 0; i < n; i++)
            if (buf[i] == '\n') t->uart_rx_count++;
        if (n < (ssize_t)sizeof buf) break;
    }
}

static void poll_op(void *self, double now)
{
    iod_t *t = self;
    if (!t) return;
    if (t->opts.sim) poll_sim(t, now);
    else poll_real(t);
    uart_poll(t);
    hwd_value rx = hwd_int(t->uart_rx_count);
    hwd_tagstore_set(t->store, "uart.rx", &rx);
    hwd_value_clear(&rx);
}

/* ---- write ------------------------------------------------------------- */

static hwd_err write_op(void *self, const char *tag, const hwd_value *v)
{
    iod_t *t = self;
    if (!t) return HWD_ERR_NOT_WRITABLE;
    for (size_t i = 0; i < t->n_outputs; i++) {
        line *L = &t->outputs[i];
        if (strcmp(L->tag, tag) != 0) continue;
        if (v->kind != HWD_BOOL && v->kind != HWD_INT && v->kind != HWD_FLOAT)
            return HWD_ERR_BAD_VALUE;
        int val = 0;
        switch (v->kind) {
        case HWD_BOOL: val = v->u.b ? 1 : 0; break;
        case HWD_INT:  val = v->u.i ? 1 : 0; break;
        case HWD_FLOAT: val = v->u.f ? 1 : 0; break;
        default: return HWD_ERR_NOT_WRITABLE;
        }
        L->value = val;
        /* A real write would drive the line through the chip handle. */
        hwd_value vb = hwd_bool(L->value != 0);
        hwd_tagstore_set(t->store, tag, &vb);
        hwd_value_clear(&vb);
        return HWD_OK;
    }
    return HWD_ERR_NOT_WRITABLE;
}

/* ---- command ----------------------------------------------------------- */

static hwd_err command_op(void *self, const char *cmd, const cJSON *msg, cJSON *reply)
{
    (void)reply;
    if (strcmp(cmd, "uart_tx") != 0) return HWD_ERR_UNKNOWN_CMD;
    iod_t *t = self;
    if (!t || t->uart_fd < 0) return HWD_ERR_HW_ERROR;
    const cJSON *data = json_find(msg, "data");
    if (!data || data->type != cJSON_String) return HWD_ERR_BAD_VALUE;
    size_t len = strlen(data->valuestring);
    if (len == 0) return HWD_OK;
    ssize_t rc = write(t->uart_fd, data->valuestring, len);
    if (rc < 0) return HWD_ERR_HW_ERROR;
    return HWD_OK;
}

/* ---- errors ------------------------------------------------------------ */

static uint64_t errors_op(void *self)
{
    iod_t *t = self;
    return t ? t->sim_fail_count : 0;
}

/* ---- safe_state -------------------------------------------------------- */

static void safe_state_op(void *self)
{
    iod_t *t = self;
    if (!t) return;
    for (size_t i = 0; i < t->n_outputs; i++) {
        line *L = &t->outputs[i];
        L->value = L->safe_state;
        hwd_value v = hwd_bool(L->value != 0);
        hwd_tagstore_set(t->store, L->tag, &v);
        hwd_value_clear(&v);
    }
}

/* ---- destroy ----------------------------------------------------------- */

static void destroy_op(void *self)
{
    iod_t *t = self;
    if (!t) return;
    for (size_t i = 0; i < t->n_ads; i++)
        if (t->ads[i].fd >= 0) { close(t->ads[i].fd); t->ads[i].fd = -1; }
    if (t->uart_fd >= 0) { close(t->uart_fd); t->uart_fd = -1; }
    free(t->outputs);
    free(t->inputs);
    free(t->ads);
    free(t);
}

const hwd_backend_ops hwd_backend_io = {
    "io", v_validate, v_create, NULL, poll_op, owns, write_op, command_op,
    safe_state_op, errors_op, destroy_op,
};