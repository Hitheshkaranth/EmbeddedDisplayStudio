// journal.h -- CONTRACT 13.3 alarm journal on the panel. FROZEN (wave 1, W3).
//
// One JSON object per line, appended and flushed at once:
//   {"ts":<epoch ms>,"event":"raise"|"clear"|"ack"|"shelve"|"unshelve",
//    "tag":...,"label":...,"severity":...,"priority":<int>,"value":<JSON>}
// fsync at most once a second (the next append after a second has passed
// syncs). When the file passes max_bytes after an append it is renamed
// PATH.1 (replacing any PATH.1) and the next append starts a new PATH.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "value.h"

typedef struct hmi_journal hmi_journal_t;

#define HMI_JOURNAL_MAX_BYTES (1024u * 1024u)
#define HMI_JOURNAL_PATH_MAX 600
#define HMI_JOURNAL_STR_MAX  160
#define HMI_JOURNAL_VALUE_MAX 48
#define HMI_JOURNAL_LINE_MAX 512

// Open (create if missing) for append. NULL for a NULL/empty path or when the
// file cannot be opened (logged at warning): callers treat NULL as "off".
hmi_journal_t *hmi_journal_open(const char *path, size_t max_bytes);
void hmi_journal_close(hmi_journal_t *j);   // NULL is fine

// Append one event. false (and logged once) on a write error; NULL j is a no-op
// returning false.
bool hmi_journal_append(hmi_journal_t *j, int64_t ts_ms, const char *event, const char *tag,
                        const char *label, const char *severity, int priority,
                        const hmi_value_t *value);

// The newest `n` events (PATH, then PATH.1 when PATH has fewer), newest first,
// as an HMI_V_LIST of ShAlarmTable history items (CONTRACT 13.3):
//   [tag, label, severity, value, event, timestamp "YYYY-MM-DDTHH:MM:SS" local,
//    true, priority, "cleared"]
// Unparseable lines are skipped. Caller frees. Empty list when j is NULL.
hmi_value_t hmi_journal_recent(hmi_journal_t *j, size_t n);
