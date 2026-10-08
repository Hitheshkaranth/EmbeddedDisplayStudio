/*
 * backend.h -- one interface for everything the daemon talks to.
 *
 * Each hwd.json section is served by one backend: gpio/adc/uart (io.c),
 * serial (USB and native serial ports, serial.c), modbus + modbus_rtu
 * (modbus.c), can (can.c), hid (hid.c), usb (usb.c, storage), i2c and spi
 * (sensors.c). daemon.c keeps the table below, creates every backend whose
 * section is present, routes set/pulse/commands to the backend that owns a
 * tag, and calls poll() every loop. Backends never call each other.
 *
 * Rules every backend keeps:
 *  - register all its tags in create() (hwd_tagstore_register), with the
 *    initial value it would publish before the first read (null when it
 *    cannot know);
 *  - poll() never blocks the loop for more than a few ms: slow I/O (TCP,
 *    serial request/response, I2C transactions at long periods) runs in the
 *    backend's own thread started by start(), writing results into the
 *    (thread-safe) store;
 *  - a failed read stores HWD_NULL and quality "bad"; a device that goes away
 *    (USB unplugged) does the same for its tags and its present-flag tag goes
 *    false; when it comes back the backend reopens it by itself (hotplug);
 *  - sim mode (--sim): no device is opened; values follow the simulation rules
 *    documented in the backend's .c and in docs/CONTRACT.md section 14, and
 *    HWD_SIM_FAIL="tag1,tag2" makes those tags read as failed;
 *  - strict mode (--strict): a configured device that cannot be opened at
 *    start is fatal (create returns NULL with err); otherwise the backend
 *    keeps running and retries.
 *
 * FROZEN.
 */
#ifndef HWD_BACKEND_H
#define HWD_BACKEND_H

#include "hwd.h"
#include "config.h"
#include "tagstore.h"
#include "cJSON.h"

typedef struct {
    bool sim;
    bool strict;
    bool modbus_live;     /* --modbus-live: Modbus TCP/RTU real even with --sim */
    double poll_interval_ms;
} hwd_backend_opts;

typedef struct hwd_backend_ops {
    const char *name;                       /* "io", "serial", "modbus", ... */
    /* Validate this backend's section(s) at load time: 0 ok, -1 + err
     * (load_config-style message; the daemon exits 1). Absent section: 0. */
    int (*validate)(const hwd_config *cfg, char *err, size_t errlen);
    /* NULL with err[0] == '\0': section absent, backend not used.
     * NULL with err set: fatal (only in strict mode, or a config the
     * validator could not catch). */
    void *(*create)(const hwd_config *cfg, hwd_tagstore *store,
                    const hwd_backend_opts *opts, char *err, size_t errlen);
    void (*start)(void *self);              /* may be NULL */
    void (*poll)(void *self, double now);   /* may be NULL */
    bool (*owns)(void *self, const char *tag);
    /* set: value as sent (bool/int/float/string). Returns not_writable,
     * bad_value, hw_error or OK. */
    hwd_err (*write)(void *self, const char *tag, const hwd_value *v);
    /* A command other than the CONTRACT 2.2 core ones (uart_tx, serial_tx,
     * can_tx, usb_export ...): HWD_ERR_UNKNOWN_CMD when not this backend's.
     * reply (an object) may receive extra fields for the ack. */
    hwd_err (*command)(void *self, const char *cmd, const cJSON *msg, cJSON *reply);
    void (*safe_state)(void *self);         /* may be NULL */
    uint64_t (*errors)(void *self);
    void (*destroy)(void *self);
} hwd_backend_ops;

/* The backends, in the order daemon.c creates them. */
extern const hwd_backend_ops hwd_backend_io;       /* gpio, adc, uart   (A3) */
extern const hwd_backend_ops hwd_backend_serial;   /* serial            (A3) */
extern const hwd_backend_ops hwd_backend_modbus;   /* modbus, modbus_rtu(A2) */
extern const hwd_backend_ops hwd_backend_can;      /* can               (A2) */
extern const hwd_backend_ops hwd_backend_hid;      /* hid               (A4) */
extern const hwd_backend_ops hwd_backend_usb;      /* usb               (A4) */
extern const hwd_backend_ops hwd_backend_sensors;  /* i2c, spi          (A4) */

/* Helpers every backend may use (implemented in util.c, not frozen to
 * workers' changes): HWD_SIM_FAIL lookup, and the shared sim ramp. */
bool hwd_sim_fails(const char *tag);
double hwd_sim_ramp(double now, double lo, double hi, double period_s);

#endif
