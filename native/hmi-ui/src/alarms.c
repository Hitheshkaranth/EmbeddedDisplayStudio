// alarms.c -- STUB. Owner: W4. See alarms.h; the specification is
// native/hmi-gui/src/alarmengine.cpp (a direct port) and its tests
// native/hmi-gui/tests/tst_alarms.cpp (27 cases to mirror in tests/test_alarms.c).
#include "alarms.h"

#include <stdlib.h>

struct hmi_alarms { hmi_alarms_changed_cb cb; void *user; };

hmi_alarms_t *hmi_alarms_create(const char *apps_dir) { (void)apps_dir; return calloc(1, sizeof(hmi_alarms_t)); }
void hmi_alarms_destroy(hmi_alarms_t *a) { free(a); }
void hmi_alarms_set_callback(hmi_alarms_t *a, hmi_alarms_changed_cb cb, void *user) { a->cb = cb; a->user = user; }
size_t hmi_alarms_tag_count(const hmi_alarms_t *a) { (void)a; return 0; }
const char *hmi_alarms_tag(const hmi_alarms_t *a, size_t i) { (void)a; (void)i; return ""; }
bool hmi_alarms_evaluate(hmi_alarms_t *a, const char *const *tags, const hmi_value_t *values, size_t n) { (void)a; (void)tags; (void)values; (void)n; return false; }
const hmi_alarm_t *hmi_alarms_active(const hmi_alarms_t *a, size_t *count) { (void)a; if (count) *count = 0; return NULL; }
hmi_value_t hmi_alarms_active_value(const hmi_alarms_t *a) { (void)a; hmi_value_t v = hmi_value_null(); v.kind = HMI_V_LIST; return v; }
bool hmi_alarms_acknowledge(hmi_alarms_t *a, const char *tag) { (void)a; (void)tag; return false; }
