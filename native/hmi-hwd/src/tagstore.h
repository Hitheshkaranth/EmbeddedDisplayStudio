/*
 * tagstore.h -- every tag the daemon publishes, its value and whether a
 * client may write it. Thread-safe: the Modbus poll thread writes while the
 * main loop reads (one mutex inside; every call takes it).
 *
 * FROZEN.
 */
#ifndef HWD_TAGSTORE_H
#define HWD_TAGSTORE_H

#include "hwd.h"

typedef struct hwd_tagstore hwd_tagstore;

hwd_tagstore *hwd_tagstore_create(void);
void hwd_tagstore_destroy(hwd_tagstore *s);

/* Register a tag with its initial value (copied). false when the name is
 * invalid, already registered or the store is full. Registration order is
 * the order hwd_tagstore_names returns (the `list` ack sorts on its own). */
bool hwd_tagstore_register(hwd_tagstore *s, const char *tag, hwd_value initial, bool writable);

bool hwd_tagstore_exists(hwd_tagstore *s, const char *tag);
bool hwd_tagstore_writable(hwd_tagstore *s, const char *tag);

/* Copy of the current value (caller clears it); HWD_NULL when unknown. */
hwd_value hwd_tagstore_get(hwd_tagstore *s, const char *tag);

/* Store a copy of v; false when the tag is unknown. */
bool hwd_tagstore_set(hwd_tagstore *s, const char *tag, const hwd_value *v);

/* Names, in registration order; returns the count written (<= max). The
 * strings stay valid until the store is destroyed. */
size_t hwd_tagstore_names(hwd_tagstore *s, const char **out, size_t max);
size_t hwd_tagstore_count(hwd_tagstore *s);

/* Per-tag quality for CONTRACT 13.4 ("q" map): a tag whose last read
 * failed carries a short reason ("comm", "hw"); NULL/empty when good. */
void hwd_tagstore_set_quality(hwd_tagstore *s, const char *tag, const char *q);
/* Copy into buf; returns false when the tag is good. */
bool hwd_tagstore_quality(hwd_tagstore *s, const char *tag, char *buf, size_t n);

#endif
