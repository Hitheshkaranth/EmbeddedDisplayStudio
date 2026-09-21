// log.h -- "LEVEL - hmi-ui - message" lines on stdout, flushed per line, the
// shape the loaders use (CONTRACT C5) so the same harness can read both.
#pragma once

typedef enum { HMI_LOG_DEBUG, HMI_LOG_INFO, HMI_LOG_WARNING, HMI_LOG_ERROR, HMI_LOG_CRITICAL } hmi_log_level_t;

void hmi_log_set_level(const char *name);   // "DEBUG" | "INFO" | "WARNING" | "ERROR"
void hmi_log(hmi_log_level_t level, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
