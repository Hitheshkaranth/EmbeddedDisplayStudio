// tags.c -- STUB. Owner: W1. See tags.h for the contract; the specification
// is gui/hmi_loader/tagengine.py (TagEngine) and native/hmi-gui/src/tagengine.cpp,
// and tests/ui/test_conformance_ui.py is the acceptance test.
#include "tags.h"

#include <stdlib.h>

#include "log.h"

struct hmi_tags {
    hmi_tags_options_t opt;
    hmi_tag_change_cb on_tag;
    hmi_online_cb on_online;
    hmi_ack_cb on_ack;
    void *user;
};

hmi_tags_t *hmi_tags_create(const hmi_tags_options_t *opt)
{
    hmi_tags_t *t = calloc(1, sizeof *t);
    t->opt = *opt;
    hmi_log(HMI_LOG_WARNING, "tag engine not implemented (TODO W1); UI will run offline");
    return t;
}

void hmi_tags_destroy(hmi_tags_t *t) { free(t); }

void hmi_tags_set_callbacks(hmi_tags_t *t, hmi_tag_change_cb on_tag, hmi_online_cb on_online,
                            hmi_ack_cb on_ack, void *user)
{
    t->on_tag = on_tag; t->on_online = on_online; t->on_ack = on_ack; t->user = user;
}

void hmi_tags_poll(hmi_tags_t *t) { (void)t; }
const hmi_value_t *hmi_tags_value(const hmi_tags_t *t, const char *tag) { (void)t; (void)tag; return NULL; }
hmi_value_t hmi_tags_history(const hmi_tags_t *t, const char *tag, size_t count) { (void)t; (void)tag; (void)count; hmi_value_t v = hmi_value_null(); v.kind = HMI_V_LIST; return v; }
bool hmi_tags_online(const hmi_tags_t *t) { (void)t; return false; }
uint32_t hmi_tags_rx_errors(const hmi_tags_t *t) { (void)t; return 0; }
uint16_t hmi_tags_rx_port(const hmi_tags_t *t) { (void)t; return 0; }
const char *hmi_tags_write(hmi_tags_t *t, const char *tag, const hmi_value_t *value) { (void)t; (void)tag; (void)value; return ""; }
const char *hmi_tags_pulse(hmi_tags_t *t, const char *tag, int ms) { (void)t; (void)tag; (void)ms; return ""; }
const char *hmi_tags_uart_tx(hmi_tags_t *t, const char *data) { (void)t; (void)data; return ""; }
const char *hmi_tags_list(hmi_tags_t *t) { (void)t; return ""; }
void hmi_tags_ping(hmi_tags_t *t) { (void)t; }
