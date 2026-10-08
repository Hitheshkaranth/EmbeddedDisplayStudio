/*
 * history.h -- the historian (CONTRACT 13.4), the C port of
 * daemon/historian.py. SQLite, the SAME schema and file as the Python, so
 * `python3 daemon/historian.py export --db ...` still reads what this writes.
 *
 * period_ms 100..3600000 per tag ("*" for every numeric tag not listed),
 * deadband (default 0), a sample also when 60 * period_ms passed; commits
 * batched (at most every 5 s); retention_days 1..365 enforced at start and
 * hourly. Table `samples (tag TEXT, ts INTEGER ms, value REAL)` with index
 * idx_sample_ts (tag, ts). query(): samples [epoch_ms, number] in
 * (now - seconds, now], oldest first, buffered ones included; when more than
 * `points`, the WINDOW is split into `points` equal (lo, hi] buckets and each
 * non-empty bucket's LAST sample kept (historian.Historian.query exactly).
 *
 * FROZEN.
 */
#ifndef HWD_HISTORY_H
#define HWD_HISTORY_H

#include "hwd.h"
#include "cJSON.h"

typedef struct hwd_history hwd_history;

/* Validate the "history" section; 0 ok, else -1 with err. A malformed
 * section is logged by the caller and the daemon runs without a historian. */
int hwd_history_validate(const cJSON *hcfg, char *err, size_t errlen);
/* Open (creating) the database; NULL with err on failure. */
hwd_history *hwd_history_create(const cJSON *hcfg, char *err, size_t errlen);
void hwd_history_destroy(hwd_history *h);   /* flushes */

/* Does it log this tag ("*" covers numeric tags not listed)? */
bool hwd_history_logs(hwd_history *h, const char *tag);
/* Offer one value: finite numbers only (bools and strings are not logged,
 * as in historian.py); returns true when kept. */
bool hwd_history_observe(hwd_history *h, const char *tag, const hwd_value *v, double now);
/* Commit if due, prune if due. Called every poll. */
void hwd_history_tick(hwd_history *h, double now);
/* Samples as a cJSON array of [epoch_ms, value]; caller owns it. */
cJSON *hwd_history_query(hwd_history *h, const char *tag, int seconds, int points, double now);

#endif
