// journal.c -- see journal.h (CONTRACT 13.3). STUB: wave 1 W3 implements.
#include "journal.h"

hmi_journal_t *hmi_journal_open(const char *path, size_t max_bytes)
{
    (void)path; (void)max_bytes;
    return NULL;
}

void hmi_journal_close(hmi_journal_t *j) { (void)j; }

bool hmi_journal_append(hmi_journal_t *j, int64_t ts_ms, const char *event, const char *tag,
                        const char *label, const char *severity, int priority,
                        const hmi_value_t *value)
{
    (void)j; (void)ts_ms; (void)event; (void)tag; (void)label; (void)severity; (void)priority; (void)value;
    return false;
}

hmi_value_t hmi_journal_recent(hmi_journal_t *j, size_t n)
{
    (void)j; (void)n;
    hmi_value_t out = hmi_value_null();
    out.kind = HMI_V_LIST;
    return out;
}
