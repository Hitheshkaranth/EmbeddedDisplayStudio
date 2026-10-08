/*
 * config.h -- hwd.json, loaded and validated exactly as daemon/hmi_hwd.py
 * load_config() does (same required sections, same ranges, same messages
 * where practical). A config error is a logged message and exit status 1.
 *
 * The core validates the "daemon" section and that "gpio" is present (as the
 * Python does); every other section is validated by the backend that owns
 * it (hwd_backend_ops.validate) and by hwd_history_validate. The parsed
 * cJSON tree is kept so backends read their own sections.
 *
 * FROZEN.
 */
#ifndef HWD_CONFIG_H
#define HWD_CONFIG_H

#include "hwd.h"
#include "cJSON.h"

typedef struct {
    cJSON *root;                 /* the whole document (owned) */
    double poll_interval_ms;     /* daemon.poll_interval_ms, > 0, default 100 */
    int cmd_port;                /* daemon.cmd_port, default 5000 */
    char sink_host[64];          /* daemon.telemetry_sink "host:port" */
    int sink_port;               /*   default 127.0.0.1:5001 */
    double subscriber_ttl_s;     /* daemon.subscriber_ttl_s, default 5 */
    bool discovery;              /* daemon.discovery, default true */
    int discovery_port;          /* daemon.discovery_port, default HWD_DISCOVERY_PORT */
    const cJSON *gpio;           /* required section */
    const cJSON *adc;            /* optional sections: NULL when absent */
    const cJSON *uart;
    const cJSON *modbus;         /* Modbus TCP */
    const cJSON *history;
    /* Wave 5 peripherals (docs/CONTRACT.md section 14). */
    const cJSON *serial;         /* USB / native serial ports */
    const cJSON *modbus_rtu;     /* Modbus RTU over a serial port */
    const cJSON *can;            /* SocketCAN */
    const cJSON *hid;            /* USB HID input (barcode scanners) */
    const cJSON *usb;            /* USB storage + device presence */
    const cJSON *i2c;            /* I2C sensors */
    const cJSON *spi;            /* SPI sensors */
} hwd_config;

/* Load and validate `path`. On failure returns false and writes a one-line
 * reason into err (the caller logs it and exits 1). */
bool hwd_config_load(const char *path, hwd_config *cfg, char *err, size_t errlen);
/* Same, from a string (tests). */
bool hwd_config_parse(const char *json, hwd_config *cfg, char *err, size_t errlen);
void hwd_config_free(hwd_config *cfg);

#endif
