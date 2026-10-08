/*
 * io.c -- GPIO (uAPI v2, v1 fallback), IIO ADC and the native UART ("gpio", "adc",
 * "uart"; daemon/hmi_hwd.py GpioV1/GpioV2/GpioSim/IioAdc/IioSim/UartLink).
 * OWNER: A3.
 *
 * Backend contract: register every tag in create(), poll() within a few ms,
 * degraded reads store HWD_NULL + "bad"/"stale", sim mode follows the rules
 * below, strict mode treats a device that cannot be opened as fatal.
 *
 * GPIO. Outputs are driven at start to `initial` (default: `safe_state`,
 * default 0, as the Python drives safe_state). Real mode requests the lines
 * from the chip character device with GPIO_V2_GET_LINE_IOCTL (one request for
 * the outputs and one for the inputs, chunked at GPIO_V2_LINES_MAX, active_low
 * handled by the kernel through a per-line flags attribute); when the v2 ioctl
 * fails the v1 GPIO_GET_LINEHANDLE_IOCTL is used, one handle per line. A chip
 * that cannot be opened (or lines that cannot be claimed) is fatal in strict
 * mode, otherwise the GPIO part runs simulated with a warning.
 *
 * ADC. The IIO device is found by its `name` attribute under
 * <HWD_SYSFS_ROOT or /sys>/bus/iio/devices (key `iio_device_name`, or
 * `device_name`). Each channel's raw file stays open (seek + read per poll);
 * offset_file / scale_file are read once (missing: offset 0, scale 1).
 *   volts = ((raw + offset) * scale / 1000) * gain + transform_offset
 * (IIO voltage scale is mV per LSB; rounded to 6 decimals as IioAdc does).
 * A device that is not found is fatal in strict mode, else the ADC runs
 * simulated (IioSim fallback).
 *
 * UART. Opened non-blocking and raw at the configured format; poll() drains
 * whatever arrived and counts complete lines into `uart.rx` (the last line,
 * stripped, goes to `uart.last`; both always registered as the Python does).
 * A lost port is retried every 0.5 s. In --sim the UART is disabled
 * (uart_tx -> hw_error), as in the Python.
 *
 * Sim: outputs read back what was written, inputs read inactive (false), ADC
 * channels ramp 0..3.3 V (then gain / transform_offset), HWD_SIM_FAIL tags
 * read null + quality "bad" and count an error.
 */
#include "backend.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <termios.h>
#include <unistd.h>

#include <linux/gpio.h>

/* A lost UART is retried this often (back within 1 s of replug). */
#define RETRY_S 0.5

/* --- small cJSON helpers (backends read their own sections) ------------- */

static const cJSON *json_find(const cJSON *o, const char *name)
{
    return (o && cJSON_IsObject(o)) ? cJSON_GetObjectItemCaseSensitive(o, name) : NULL;
}
static double json_num(const cJSON *o, const char *name, double def)
{
    const cJSON *v = json_find(o, name);
    return (v && cJSON_IsNumber(v)) ? v->valuedouble : def;
}
/* 0/1 from a bool or a number (initial, safe_state, active_low). */
static int json_flag(const cJSON *o, const char *name, int def)
{
    const cJSON *v = json_find(o, name);
    if (!v) return def;
    if (cJSON_IsBool(v)) return cJSON_IsTrue(v) ? 1 : 0;
    if (cJSON_IsNumber(v)) return v->valuedouble != 0.0 ? 1 : 0;
    return def;
}
static bool json_flag_ok(const cJSON *o, const char *name)
{
    const cJSON *v = json_find(o, name);
    if (!v || cJSON_IsBool(v)) return true;
    return cJSON_IsNumber(v) && (v->valuedouble == 0.0 || v->valuedouble == 1.0);
}
static const char *json_s(const cJSON *o, const char *name)
{
    const cJSON *v = json_find(o, name);
    return (v && cJSON_IsString(v) && v->valuestring) ? v->valuestring : NULL;
}
static bool json_is_uint(const cJSON *v)
{
    return v && cJSON_IsNumber(v) && v->valuedouble >= 0 && v->valuedouble <= 1e9
        && v->valuedouble == floor(v->valuedouble);
}

/* --- state -------------------------------------------------------------- */

typedef struct {
    char tag[HWD_MAX_TAG];
    unsigned offset;
    bool active_low;
    int safe_state;
    int value;          /* logical 0/1 last driven (outputs) */
    int req;            /* index into the request table, -1 when unclaimed */
    int bit;            /* position inside that request */
} gline;

typedef struct {
    int fd;
    bool v2;
} greq;

typedef struct {
    char tag[HWD_MAX_TAG];
    char raw_path[1024];
    double offset, scale, gain, transform_offset;
    int fd;             /* raw file, -1 when missing */
    double next_try;    /* mono time of the next reopen attempt */
} chan;

typedef struct {
    hwd_backend_opts opts;
    hwd_tagstore *store;
    uint64_t errors;

    /* GPIO. */
    char chip[256];
    char consumer[GPIO_MAX_NAME_SIZE];
    gline *outputs; size_t n_outputs;
    gline *inputs;  size_t n_inputs;
    greq *reqs;     size_t n_reqs, cap_reqs;
    bool gpio_sim;

    /* ADC. */
    chan *ads; size_t n_ads;
    bool adc_sim;

    /* UART. */
    bool uart_cfg;
    char uart_port[256];
    int uart_baud, uart_bytesize, uart_stopbits;
    char uart_parity;
    int uart_fd;
    double uart_next_try;
    int64_t uart_rx_count;
    char uart_line[1024];
    size_t uart_len;
    char uart_last[1024];
} iod_t;

/* ---- validate ---------------------------------------------------------- */

static int check_lines(const cJSON *gpio, const char *key, char *err, size_t errlen)
{
    const cJSON *sec = json_find(gpio, key);
    if (!sec) return 0;
    if (!cJSON_IsObject(sec)) {
        snprintf(err, errlen, "gpio.%s must be an object", key);
        return -1;
    }
    for (const cJSON *o = sec->child; o; o = o->next) {
        if (!hwd_tag_valid(o->string)) {
            snprintf(err, errlen, "Invalid tag name '%s' in gpio.%s", o->string, key);
            return -1;
        }
        if (!cJSON_IsObject(o)) {
            snprintf(err, errlen, "gpio.%s.%s must be an object", key, o->string);
            return -1;
        }
        if (!json_is_uint(json_find(o, "offset"))) {
            snprintf(err, errlen, "gpio.%s.%s: offset must be an integer >= 0", key, o->string);
            return -1;
        }
        if (!json_flag_ok(o, "active_low")) {
            snprintf(err, errlen, "gpio.%s.%s: active_low must be a bool", key, o->string);
            return -1;
        }
        if (!json_flag_ok(o, "initial") || !json_flag_ok(o, "safe_state")) {
            snprintf(err, errlen, "gpio.%s.%s: initial/safe_state must be 0 or 1", key, o->string);
            return -1;
        }
    }
    return 0;
}

static int v_validate(const hwd_config *cfg, char *err, size_t errlen)
{
    if (errlen) err[0] = '\0';
    const cJSON *gpio = cfg->gpio;
    if (gpio) {
        if (!cJSON_IsObject(gpio)) { snprintf(err, errlen, "gpio must be an object"); return -1; }
        const cJSON *chip = json_find(gpio, "chip");
        if (chip && (!cJSON_IsString(chip) || !chip->valuestring[0])) {
            snprintf(err, errlen, "gpio.chip must be a non-empty string");
            return -1;
        }
        if (check_lines(gpio, "outputs", err, errlen) < 0) return -1;
        if (check_lines(gpio, "inputs", err, errlen) < 0) return -1;
    }

    const cJSON *adc = cfg->adc;
    if (adc) {
        if (!cJSON_IsObject(adc)) { snprintf(err, errlen, "adc must be an object"); return -1; }
        const cJSON *channels = json_find(adc, "channels");
        if (channels && !cJSON_IsObject(channels)) {
            snprintf(err, errlen, "adc.channels must be an object");
            return -1;
        }
        for (const cJSON *c = channels ? channels->child : NULL; c; c = c->next) {
            if (!hwd_tag_valid(c->string)) {
                snprintf(err, errlen, "Invalid tag name '%s' in adc.channels", c->string);
                return -1;
            }
            const char *cf = json_s(c, "channel_file");
            if (!cf || !cf[0]) {
                snprintf(err, errlen, "adc.channels.%s: needs channel_file", c->string);
                return -1;
            }
            const cJSON *g = json_find(c, "gain"), *to = json_find(c, "transform_offset");
            if ((g && !cJSON_IsNumber(g)) || (to && !cJSON_IsNumber(to))) {
                snprintf(err, errlen, "adc.channels.%s: gain/transform_offset must be numbers",
                         c->string);
                return -1;
            }
        }
    }

    const cJSON *uart = cfg->uart;
    if (uart) {
        if (!cJSON_IsObject(uart)) { snprintf(err, errlen, "uart must be an object"); return -1; }
        const char *port = json_s(uart, "port");
        if (!port || !port[0]) {
            snprintf(err, errlen, "uart.port must be a non-empty string");
            return -1;
        }
        const cJSON *baud = json_find(uart, "baudrate");
        if (baud && (!json_is_uint(baud) || baud->valuedouble <= 0)) {
            snprintf(err, errlen, "uart.baudrate must be a positive integer");
            return -1;
        }
        int bs = (int)json_num(uart, "bytesize", 8);
        if (bs < 5 || bs > 8) { snprintf(err, errlen, "uart.bytesize must be 5..8"); return -1; }
        const cJSON *par = json_find(uart, "parity");
        if (par && (!cJSON_IsString(par) || strlen(par->valuestring) != 1
                    || !strchr("NEO", par->valuestring[0]))) {
            snprintf(err, errlen, "uart.parity must be N, E or O");
            return -1;
        }
        int sb = (int)json_num(uart, "stopbits", 1);
        if (sb != 1 && sb != 2) { snprintf(err, errlen, "uart.stopbits must be 1 or 2"); return -1; }
    }
    return 0;
}

/* ---- GPIO hardware ----------------------------------------------------- */

static int add_req(iod_t *t, int fd, bool v2)
{
    if (t->n_reqs == t->cap_reqs) {
        size_t cap = t->cap_reqs ? t->cap_reqs * 2 : 8;
        greq *n = realloc(t->reqs, cap * sizeof *n);
        if (!n) return -1;
        t->reqs = n;
        t->cap_reqs = cap;
    }
    t->reqs[t->n_reqs].fd = fd;
    t->reqs[t->n_reqs].v2 = v2;
    return (int)t->n_reqs++;
}

/* uAPI v2: lines[0..n) (n <= GPIO_V2_LINES_MAX) in one request. */
static int request_v2(iod_t *t, int chipfd, gline *lines, size_t n, bool output)
{
    struct gpio_v2_line_request req;
    memset(&req, 0, sizeof req);
    snprintf(req.consumer, sizeof req.consumer, "%s", t->consumer);
    req.num_lines = (uint32_t)n;
    uint64_t base = output ? GPIO_V2_LINE_FLAG_OUTPUT : GPIO_V2_LINE_FLAG_INPUT;
    req.config.flags = base;
    uint64_t low_mask = 0, all = 0, vals = 0;
    for (size_t i = 0; i < n; i++) {
        req.offsets[i] = lines[i].offset;
        all |= 1ULL << i;
        if (lines[i].active_low) low_mask |= 1ULL << i;
        if (lines[i].value) vals |= 1ULL << i;
    }
    uint32_t k = 0;
    if (low_mask) {
        req.config.attrs[k].attr.id = GPIO_V2_LINE_ATTR_ID_FLAGS;
        req.config.attrs[k].attr.flags = base | GPIO_V2_LINE_FLAG_ACTIVE_LOW;
        req.config.attrs[k].mask = low_mask;
        k++;
    }
    if (output) {
        req.config.attrs[k].attr.id = GPIO_V2_LINE_ATTR_ID_OUTPUT_VALUES;
        req.config.attrs[k].attr.values = vals;   /* logical: active_low applied by the kernel */
        req.config.attrs[k].mask = all;
        k++;
    }
    req.config.num_attrs = k;
    if (ioctl(chipfd, GPIO_V2_GET_LINE_IOCTL, &req) < 0) return -1;
    int r = add_req(t, req.fd, true);
    if (r < 0) { close(req.fd); errno = ENOMEM; return -1; }
    for (size_t i = 0; i < n; i++) { lines[i].req = r; lines[i].bit = (int)i; }
    return 0;
}

/* uAPI v1: one handle per line (a v1 handle's flags cover all of its lines,
 * and active_low differs per line). */
static int request_v1(iod_t *t, int chipfd, gline *L, bool output)
{
    struct gpiohandle_request hr;
    memset(&hr, 0, sizeof hr);
    hr.lineoffsets[0] = L->offset;
    hr.lines = 1;
    hr.flags = (output ? GPIOHANDLE_REQUEST_OUTPUT : GPIOHANDLE_REQUEST_INPUT)
             | (L->active_low ? GPIOHANDLE_REQUEST_ACTIVE_LOW : 0);
    hr.default_values[0] = (uint8_t)(L->value ? 1 : 0);
    snprintf(hr.consumer_label, sizeof hr.consumer_label, "%s", t->consumer);
    if (ioctl(chipfd, GPIO_GET_LINEHANDLE_IOCTL, &hr) < 0) return -1;
    int r = add_req(t, hr.fd, false);
    if (r < 0) { close(hr.fd); errno = ENOMEM; return -1; }
    L->req = r;
    L->bit = 0;
    return 0;
}

static void release_gpio(iod_t *t)
{
    for (size_t i = 0; i < t->n_reqs; i++)
        if (t->reqs[i].fd >= 0) close(t->reqs[i].fd);
    t->n_reqs = 0;
    for (size_t i = 0; i < t->n_outputs; i++) t->outputs[i].req = -1;
    for (size_t i = 0; i < t->n_inputs; i++) t->inputs[i].req = -1;
}

/* Claim every line: v2 first, v1 when the v2 ioctl fails. 0, or -1 + why. */
static int open_gpio(iod_t *t, char *why, size_t n)
{
    int chipfd = open(t->chip, O_RDWR | O_CLOEXEC);
    if (chipfd < 0) {
        snprintf(why, n, "GPIO chip %s: %s", t->chip, strerror(errno));
        return -1;
    }
    gline *arr[2] = {t->outputs, t->inputs};
    size_t cnt[2] = {t->n_outputs, t->n_inputs};
    for (int v2 = 1; v2 >= 0; v2--) {
        int rc = 0;
        for (int k = 0; k < 2 && rc == 0; k++) {
            if (v2) {
                for (size_t i = 0; i < cnt[k] && rc == 0; i += GPIO_V2_LINES_MAX) {
                    size_t m = cnt[k] - i < GPIO_V2_LINES_MAX ? cnt[k] - i : GPIO_V2_LINES_MAX;
                    rc = request_v2(t, chipfd, arr[k] + i, m, k == 0);
                }
            } else {
                for (size_t i = 0; i < cnt[k] && rc == 0; i++)
                    rc = request_v1(t, chipfd, &arr[k][i], k == 0);
            }
        }
        if (rc == 0) {
            close(chipfd);
            HWD_INFO("GPIO %s: %zu output(s), %zu input(s) via uAPI %s", t->chip,
                     t->n_outputs, t->n_inputs, v2 ? "v2" : "v1");
            return 0;
        }
        int e = errno;
        release_gpio(t);
        if (v2) HWD_DEBUG("GPIO v2 line request failed (%s); trying v1", strerror(e));
        else snprintf(why, n, "GPIO %s: cannot claim lines: %s", t->chip, strerror(e));
    }
    close(chipfd);
    return -1;
}

/* Logical value of a claimed line: 0/1, or -1 on error. */
static int gpio_read(iod_t *t, const gline *L)
{
    if (L->req < 0) return -1;
    const greq *r = &t->reqs[L->req];
    if (r->v2) {
        struct gpio_v2_line_values lv = {.bits = 0, .mask = 1ULL << L->bit};
        if (ioctl(r->fd, GPIO_V2_LINE_GET_VALUES_IOCTL, &lv) < 0) return -1;
        return ((lv.bits >> L->bit) & 1ULL) ? 1 : 0;
    }
    struct gpiohandle_data d;
    memset(&d, 0, sizeof d);
    if (ioctl(r->fd, GPIOHANDLE_GET_LINE_VALUES_IOCTL, &d) < 0) return -1;
    return d.values[L->bit] ? 1 : 0;
}

static int gpio_drive(iod_t *t, const gline *L, int value)
{
    if (L->req < 0) { errno = ENODEV; return -1; }
    const greq *r = &t->reqs[L->req];
    if (r->v2) {
        struct gpio_v2_line_values lv = {.bits = value ? 1ULL << L->bit : 0,
                                         .mask = 1ULL << L->bit};
        return ioctl(r->fd, GPIO_V2_LINE_SET_VALUES_IOCTL, &lv) < 0 ? -1 : 0;
    }
    struct gpiohandle_data d;
    memset(&d, 0, sizeof d);
    d.values[L->bit] = (uint8_t)(value ? 1 : 0);
    return ioctl(r->fd, GPIOHANDLE_SET_LINE_VALUES_IOCTL, &d) < 0 ? -1 : 0;
}

/* ---- ADC hardware ------------------------------------------------------ */

static const char *sysfs_root(void)
{
    const char *r = getenv("HWD_SYSFS_ROOT");
    return (r && r[0]) ? r : "/sys";
}

static bool read_text(const char *path, char *buf, size_t n)
{
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return false;
    ssize_t got = read(fd, buf, n - 1);
    close(fd);
    if (got <= 0) return false;
    buf[got] = '\0';
    while (got > 0 && (buf[got - 1] == '\n' || buf[got - 1] == ' ' || buf[got - 1] == '\r'))
        buf[--got] = '\0';
    return true;
}

static bool parse_num(const char *s, double *out)
{
    char *end = NULL;
    errno = 0;
    double v = strtod(s, &end);
    if (end == s || errno == ERANGE) return false;
    while (*end == ' ' || *end == '\n' || *end == '\r' || *end == '\t') end++;
    if (*end) return false;
    *out = v;
    return true;
}

/* The IIO device directory whose `name` attribute is `want`. */
static bool find_iio(const char *want, char *dir, size_t n)
{
    char base[384];
    snprintf(base, sizeof base, "%s/bus/iio/devices", sysfs_root());
    DIR *d = opendir(base);
    if (!d) return false;
    bool found = false;
    struct dirent *e;
    while (!found && (e = readdir(d)) != NULL) {
        if (e->d_name[0] == '.') continue;
        char path[768], name[128];
        snprintf(path, sizeof path, "%s/%s/name", base, e->d_name);
        if (read_text(path, name, sizeof name) && strcmp(name, want) == 0) {
            snprintf(dir, n, "%s/%s", base, e->d_name);
            found = true;
        }
    }
    closedir(d);
    return found;
}

static bool adc_raw(chan *c, double *raw)
{
    if (c->fd < 0) return false;
    char buf[64];
    if (lseek(c->fd, 0, SEEK_SET) < 0) return false;
    ssize_t n = read(c->fd, buf, sizeof buf - 1);
    if (n <= 0) return false;
    buf[n] = '\0';
    return parse_num(buf, raw);
}

static bool adc_read(chan *c, double *volts)
{
    double raw;
    if (!adc_raw(c, &raw)) {
        /* Reopen once (device re-enumerated), as IioAdc.read does; a file
         * that is missing is retried at most once a second. */
        if (c->fd >= 0) { close(c->fd); c->fd = -1; }
        double m = hwd_mono();
        if (m < c->next_try) return false;
        c->fd = open(c->raw_path, O_RDONLY | O_CLOEXEC);
        if (c->fd < 0) { c->next_try = m + 1.0; return false; }
        if (!adc_raw(c, &raw)) return false;
    }
    double v = ((raw + c->offset) * c->scale) / 1000.0;   /* IIO voltage scale: mV per LSB */
    v = v * c->gain + c->transform_offset;
    *volts = round(v * 1e6) / 1e6;
    return true;
}

/* ---- UART -------------------------------------------------------------- */

static speed_t baud_flag(int baud)
{
    switch (baud) {
    case 50: return B50;           case 75: return B75;
    case 110: return B110;         case 134: return B134;
    case 150: return B150;         case 200: return B200;
    case 300: return B300;         case 600: return B600;
    case 1200: return B1200;       case 1800: return B1800;
    case 2400: return B2400;       case 4800: return B4800;
    case 9600: return B9600;       case 19200: return B19200;
    case 38400: return B38400;     case 57600: return B57600;
    case 115200: return B115200;   case 230400: return B230400;
    case 460800: return B460800;   case 500000: return B500000;
    case 576000: return B576000;   case 921600: return B921600;
    case 1000000: return B1000000; case 1152000: return B1152000;
    case 1500000: return B1500000; case 2000000: return B2000000;
    case 2500000: return B2500000; case 3000000: return B3000000;
    case 3500000: return B3500000; case 4000000: return B4000000;
    default: return (speed_t)0;
    }
}

static int uart_open(iod_t *t)
{
    int fd = open(t->uart_port, O_RDWR | O_NOCTTY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) return -1;
    struct termios tio;
    if (tcgetattr(fd, &tio) == 0) {
        cfmakeraw(&tio);
        speed_t sp = baud_flag(t->uart_baud);
        if (sp) { cfsetispeed(&tio, sp); cfsetospeed(&tio, sp); }
        else HWD_WARN("UART %s: baudrate %d not in the termios table", t->uart_port, t->uart_baud);
        tio.c_cflag &= ~(tcflag_t)(CSIZE | CSTOPB | PARENB | PARODD | CRTSCTS);
        tio.c_cflag |= CLOCAL | CREAD;
        tio.c_cflag |= t->uart_bytesize == 5 ? CS5 : t->uart_bytesize == 6 ? CS6
                     : t->uart_bytesize == 7 ? CS7 : CS8;
        if (t->uart_stopbits == 2) tio.c_cflag |= CSTOPB;
        if (t->uart_parity == 'E') tio.c_cflag |= PARENB;
        if (t->uart_parity == 'O') tio.c_cflag |= PARENB | PARODD;
        tio.c_cc[VMIN] = 0;
        tio.c_cc[VTIME] = 0;
        tcsetattr(fd, TCSANOW, &tio);
    }
    t->uart_fd = fd;
    t->uart_len = 0;
    return 0;
}

static void uart_close(iod_t *t)
{
    if (t->uart_fd >= 0) close(t->uart_fd);
    t->uart_fd = -1;
    t->uart_len = 0;
}

/* Keep a line valid UTF-8 for the JSON frame: invalid bytes become '?'. */
static void sanitize_utf8(char *s)
{
    unsigned char *p = (unsigned char *)s;
    while (*p) {
        int n = *p < 0x80 ? 1 : (*p & 0xE0) == 0xC0 ? 2 : (*p & 0xF0) == 0xE0 ? 3
              : (*p & 0xF8) == 0xF0 ? 4 : 0;
        bool ok = n > 0;
        for (int i = 1; ok && i < n; i++) ok = (p[i] & 0xC0) == 0x80;
        if (!ok) { *p++ = '?'; continue; }
        p += n;
    }
}

static void uart_line_done(iod_t *t)
{
    t->uart_line[t->uart_len] = '\0';
    /* Python: raw.decode(...).strip() */
    char *s = t->uart_line;
    size_t len = t->uart_len;
    while (len && (s[len - 1] == '\r' || s[len - 1] == ' ' || s[len - 1] == '\t'))
        s[--len] = '\0';
    while (*s == ' ' || *s == '\t' || *s == '\r') s++;
    snprintf(t->uart_last, sizeof t->uart_last, "%s", s);
    sanitize_utf8(t->uart_last);
    t->uart_rx_count++;
    t->uart_len = 0;
}

static void uart_poll(iod_t *t)
{
    if (!t->uart_cfg || t->opts.sim) return;
    if (t->uart_fd < 0) {
        double m = hwd_mono();
        if (m < t->uart_next_try) return;
        t->uart_next_try = m + RETRY_S;
        if (uart_open(t) < 0) return;
        HWD_INFO("UART %s reopened", t->uart_port);
    }
    for (int rounds = 0; rounds < 16; rounds++) {
        struct pollfd pfd = {.fd = t->uart_fd, .events = POLLIN};
        if (poll(&pfd, 1, 0) <= 0) return;
        if (pfd.revents & POLLIN) {
            char buf[512];
            ssize_t n = read(t->uart_fd, buf, sizeof buf);
            if (n > 0) {
                for (ssize_t i = 0; i < n; i++) {
                    if (buf[i] == '\n') uart_line_done(t);
                    else if (t->uart_len < sizeof t->uart_line - 1)
                        t->uart_line[t->uart_len++] = buf[i];
                }
                continue;
            }
            if (n < 0 && (errno == EAGAIN || errno == EINTR)) return;
        } else if (!(pfd.revents & (POLLHUP | POLLERR | POLLNVAL))) {
            return;
        }
        /* EOF, read error or hangup: the port went away; retry in a second. */
        t->errors++;
        HWD_WARN("UART %s lost; reopening", t->uart_port);
        uart_close(t);
        t->uart_next_try = hwd_mono() + RETRY_S;
        return;
    }
}

/* ---- create ------------------------------------------------------------ */

static gline *load_lines(const cJSON *sec, size_t *count, bool output)
{
    *count = 0;
    size_t n = sec ? (size_t)cJSON_GetArraySize(sec) : 0;
    if (!n) return NULL;
    gline *arr = calloc(n, sizeof *arr);
    if (!arr) return NULL;
    size_t i = 0;
    for (const cJSON *o = sec->child; o && i < n; o = o->next, i++) {
        gline *L = &arr[i];
        snprintf(L->tag, sizeof L->tag, "%s", o->string);
        L->offset = (unsigned)json_num(o, "offset", 0);
        L->active_low = json_flag(o, "active_low", 0) != 0;
        L->safe_state = json_flag(o, "safe_state", 0);
        L->value = output ? json_flag(o, "initial", L->safe_state) : 0;
        L->req = -1;
    }
    *count = i;
    return arr;
}

static void destroy_op(void *self);

static void *fail_create(iod_t *t, char *err, size_t errlen, const char *msg)
{
    snprintf(err, errlen, "%s", msg);
    destroy_op(t);
    return NULL;
}

static void *v_create(const hwd_config *cfg, hwd_tagstore *store, const hwd_backend_opts *opts,
                      char *err, size_t errlen)
{
    if (errlen) err[0] = '\0';
    if (!cfg->gpio && !cfg->adc && !cfg->uart) return NULL;

    iod_t *t = calloc(1, sizeof *t);
    if (!t) { snprintf(err, errlen, "io: out of memory"); return NULL; }
    t->opts = *opts;
    t->store = store;
    t->uart_fd = -1;
    char msg[1536];

    /* GPIO. */
    const cJSON *gpio = cfg->gpio;
    const char *chip = json_s(gpio, "chip");
    snprintf(t->chip, sizeof t->chip, "%s", chip ? chip : "/dev/gpiochip0");
    const char *consumer = json_s(gpio, "consumer");
    snprintf(t->consumer, sizeof t->consumer, "%s", consumer ? consumer : "hmi-hwd");
    t->outputs = load_lines(json_find(gpio, "outputs"), &t->n_outputs, true);
    t->inputs = load_lines(json_find(gpio, "inputs"), &t->n_inputs, false);
    t->gpio_sim = opts->sim;
    if (!opts->sim && (t->n_outputs || t->n_inputs)) {
        if (open_gpio(t, msg, sizeof msg) < 0) {
            if (opts->strict) return fail_create(t, err, errlen, msg);
            HWD_WARN("%s; engaging GPIO simulation", msg);
            t->gpio_sim = true;
        }
    }
    for (size_t i = 0; i < t->n_outputs; i++)
        hwd_tagstore_register(store, t->outputs[i].tag, hwd_bool(t->outputs[i].value != 0), true);
    for (size_t i = 0; i < t->n_inputs; i++)
        hwd_tagstore_register(store, t->inputs[i].tag, hwd_bool(false), false);

    /* ADC. */
    const cJSON *adc = cfg->adc;
    const cJSON *channels = json_find(adc, "channels");
    size_t nch = channels ? (size_t)cJSON_GetArraySize(channels) : 0;
    if (nch) {
        t->ads = calloc(nch, sizeof *t->ads);
        if (!t->ads) return fail_create(t, err, errlen, "io: out of memory");
    }
    char devdir[700] = "";
    const char *dev = json_s(adc, "iio_device_name");
    if (!dev) dev = json_s(adc, "device_name");
    t->adc_sim = opts->sim;
    if (!opts->sim && nch) {
        if (!dev || !find_iio(dev, devdir, sizeof devdir)) {
            snprintf(msg, sizeof msg, "No IIO device named '%s' under %s/bus/iio/devices",
                     dev ? dev : "", sysfs_root());
            if (opts->strict) return fail_create(t, err, errlen, msg);
            HWD_WARN("IIO ADC not available (%s); using simulated ADC", msg);
            t->adc_sim = true;
        } else {
            HWD_INFO("IIO device '%s' found at %s", dev, devdir);
        }
    }
    for (const cJSON *c = channels ? channels->child : NULL; c && t->n_ads < nch; c = c->next) {
        chan *ch = &t->ads[t->n_ads++];
        snprintf(ch->tag, sizeof ch->tag, "%s", c->string);
        ch->gain = json_num(c, "gain", 1.0);
        ch->transform_offset = json_num(c, "transform_offset", 0.0);
        ch->offset = 0.0;
        ch->scale = 1.0;
        ch->fd = -1;
        hwd_tagstore_register(store, ch->tag, hwd_null(), false);
        if (t->adc_sim) continue;
        const char *cf = json_s(c, "channel_file");
        snprintf(ch->raw_path, sizeof ch->raw_path, "%s/%s", devdir, cf ? cf : "");
        char path[1024], txt[64];
        double v;
        const char *of = json_s(c, "offset_file"), *sf = json_s(c, "scale_file");
        if (of && of[0]) {
            snprintf(path, sizeof path, "%s/%s", devdir, of);
            if (read_text(path, txt, sizeof txt) && parse_num(txt, &v)) ch->offset = v;
        }
        if (sf && sf[0]) {
            snprintf(path, sizeof path, "%s/%s", devdir, sf);
            if (read_text(path, txt, sizeof txt) && parse_num(txt, &v)) ch->scale = v;
            else HWD_WARN("Cannot read IIO scale for %s, defaulting to 1.0 mV", ch->tag);
        }
        ch->fd = open(ch->raw_path, O_RDONLY | O_CLOEXEC);
        if (ch->fd < 0) {
            snprintf(msg, sizeof msg, "ADC channel %s: %s: %s", ch->tag, ch->raw_path,
                     strerror(errno));
            if (opts->strict) return fail_create(t, err, errlen, msg);
            HWD_WARN("%s", msg);
            ch->next_try = hwd_mono() + 1.0;
        }
    }

    /* UART (tags always registered so the tag map is stable, as the Python). */
    const cJSON *uart = cfg->uart;
    if (uart) {
        t->uart_cfg = true;
        const char *port = json_s(uart, "port");
        snprintf(t->uart_port, sizeof t->uart_port, "%s", port ? port : "");
        t->uart_baud = (int)json_num(uart, "baudrate", 115200);
        t->uart_bytesize = (int)json_num(uart, "bytesize", 8);
        t->uart_stopbits = (int)json_num(uart, "stopbits", 1);
        const char *par = json_s(uart, "parity");
        t->uart_parity = par && par[0] ? par[0] : 'N';
        if (opts->sim) {
            HWD_INFO("UART disabled in simulation mode");
        } else if (uart_open(t) < 0) {
            snprintf(msg, sizeof msg, "UART port %s: %s", t->uart_port, strerror(errno));
            if (opts->strict) return fail_create(t, err, errlen, msg);
            HWD_WARN("%s; retrying", msg);
            t->uart_next_try = hwd_mono() + RETRY_S;
        }
    }
    hwd_tagstore_register(store, "uart.rx", hwd_int(0), false);
    /* register takes ownership of the initial value (tagstore.c). */
    hwd_tagstore_register(store, "uart.last", hwd_str(""), false);
    return t;
}

/* ---- owns -------------------------------------------------------------- */

static bool owns(void *self, const char *tag)
{
    iod_t *t = self;
    if (!t || !tag) return false;
    for (size_t i = 0; i < t->n_outputs; i++)
        if (strcmp(t->outputs[i].tag, tag) == 0) return true;
    for (size_t i = 0; i < t->n_inputs; i++)
        if (strcmp(t->inputs[i].tag, tag) == 0) return true;
    for (size_t i = 0; i < t->n_ads; i++)
        if (strcmp(t->ads[i].tag, tag) == 0) return true;
    return strcmp(tag, "uart.rx") == 0 || strcmp(tag, "uart.last") == 0;
}

/* ---- poll -------------------------------------------------------------- */

/* Store a read: the value + quality cleared, or null + "bad" + an error. */
static void put(iod_t *t, const char *tag, hwd_value v, bool ok)
{
    if (!ok) {
        hwd_value_clear(&v);
        v = hwd_null();
        t->errors++;
    }
    hwd_tagstore_set(t->store, tag, &v);
    hwd_tagstore_set_quality(t->store, tag, ok ? NULL : "bad");
    hwd_value_clear(&v);
}

static void poll_gpio(iod_t *t, const gline *arr, size_t n, bool output)
{
    for (size_t i = 0; i < n; i++) {
        const gline *L = &arr[i];
        if (t->gpio_sim) {
            put(t, L->tag, hwd_bool(output && L->value != 0), !hwd_sim_fails(L->tag));
        } else {
            int v = gpio_read(t, L);
            put(t, L->tag, hwd_bool(v == 1), v >= 0);
        }
    }
}

static void poll_op(void *self, double now)
{
    iod_t *t = self;
    if (!t) return;
    poll_gpio(t, t->inputs, t->n_inputs, false);
    poll_gpio(t, t->outputs, t->n_outputs, true);
    for (size_t i = 0; i < t->n_ads; i++) {
        chan *c = &t->ads[i];
        double v = 0.0;
        bool ok;
        if (t->adc_sim) {
            ok = !hwd_sim_fails(c->tag);
            v = hwd_sim_ramp(now, 0.0, 3.3, 10.0) * c->gain + c->transform_offset;
            v = round(v * 1e6) / 1e6;
        } else {
            ok = adc_read(c, &v);
        }
        put(t, c->tag, hwd_float(v), ok);
    }
    if (t->uart_cfg) {
        uart_poll(t);
        hwd_value rx = hwd_int(t->uart_rx_count);
        hwd_tagstore_set(t->store, "uart.rx", &rx);
        hwd_value last = hwd_str(t->uart_last);
        hwd_tagstore_set(t->store, "uart.last", &last);
        hwd_value_clear(&last);
    }
}

/* ---- write ------------------------------------------------------------- */

static hwd_err drive(iod_t *t, gline *L, int val)
{
    if (!t->gpio_sim && gpio_drive(t, L, val) < 0) {
        t->errors++;
        HWD_WARN("GPIO write error for %s: %s", L->tag, strerror(errno));
        return HWD_ERR_HW_ERROR;
    }
    L->value = val;
    hwd_value vb = hwd_bool(val != 0);
    hwd_tagstore_set(t->store, L->tag, &vb);
    return HWD_OK;
}

static hwd_err write_op(void *self, const char *tag, const hwd_value *v)
{
    iod_t *t = self;
    if (!t || !tag || !v) return HWD_ERR_NOT_WRITABLE;
    for (size_t i = 0; i < t->n_outputs; i++) {
        gline *L = &t->outputs[i];
        if (strcmp(L->tag, tag) != 0) continue;
        int val;
        switch (v->kind) {
        case HWD_BOOL:  val = v->u.b ? 1 : 0; break;
        case HWD_INT:   val = v->u.i ? 1 : 0; break;
        case HWD_FLOAT: val = v->u.f != 0.0 ? 1 : 0; break;
        default: return HWD_ERR_BAD_VALUE;
        }
        return drive(t, L, val);
    }
    return HWD_ERR_NOT_WRITABLE;
}

/* ---- command ----------------------------------------------------------- */

static hwd_err command_op(void *self, const char *cmd, const cJSON *msg, cJSON *reply)
{
    (void)reply;
    if (!cmd || strcmp(cmd, "uart_tx") != 0) return HWD_ERR_UNKNOWN_CMD;
    iod_t *t = self;
    if (!t) return HWD_ERR_HW_ERROR;
    if (t->uart_fd < 0) { t->errors++; return HWD_ERR_HW_ERROR; }
    const char *data = json_s(msg, "data");
    if (!data) { t->errors++; return HWD_ERR_BAD_VALUE; }
    size_t len = strlen(data), off = 0;
    double deadline = hwd_mono() + 0.5;
    while (off < len) {
        ssize_t rc = write(t->uart_fd, data + off, len - off);
        if (rc > 0) { off += (size_t)rc; continue; }
        if (rc < 0 && (errno == EAGAIN || errno == EINTR) && hwd_mono() < deadline) {
            struct pollfd pfd = {.fd = t->uart_fd, .events = POLLOUT};
            poll(&pfd, 1, 20);
            continue;
        }
        t->errors++;
        HWD_WARN("UART write error on %s", t->uart_port);
        return HWD_ERR_HW_ERROR;
    }
    return HWD_OK;
}

/* ---- errors ------------------------------------------------------------ */

static uint64_t errors_op(void *self)
{
    iod_t *t = self;
    return t ? t->errors : 0;
}

/* ---- safe_state -------------------------------------------------------- */

static void safe_state_op(void *self)
{
    iod_t *t = self;
    if (!t) return;
    for (size_t i = 0; i < t->n_outputs; i++)
        if (drive(t, &t->outputs[i], t->outputs[i].safe_state) != HWD_OK)
            HWD_WARN("Failed to set safe state for %s", t->outputs[i].tag);
}

/* ---- destroy ----------------------------------------------------------- */

static void destroy_op(void *self)
{
    iod_t *t = self;
    if (!t) return;
    release_gpio(t);
    for (size_t i = 0; i < t->n_ads; i++)
        if (t->ads[i].fd >= 0) close(t->ads[i].fd);
    uart_close(t);
    free(t->reqs);
    free(t->outputs);
    free(t->inputs);
    free(t->ads);
    free(t);
}

const hwd_backend_ops hwd_backend_io = {
    "io", v_validate, v_create, NULL, poll_op, owns, write_op, command_op,
    safe_state_op, errors_op, destroy_op,
};
