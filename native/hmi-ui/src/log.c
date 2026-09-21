// log.c -- see log.h.
#include "log.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

static hmi_log_level_t g_level = HMI_LOG_INFO;
static const char *const names[] = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"};

void hmi_log_set_level(const char *name)
{
    for (int i = 0; i < 5; ++i)
        if (name && strcmp(name, names[i]) == 0) { g_level = (hmi_log_level_t)i; return; }
    g_level = HMI_LOG_INFO;
}

void hmi_log(hmi_log_level_t level, const char *fmt, ...)
{
    if (level < g_level)
        return;
    va_list ap;
    va_start(ap, fmt);
    fprintf(stdout, "%s - hmi-ui - ", names[level]);
    vfprintf(stdout, fmt, ap);
    fputc('\n', stdout);
    fflush(stdout);
    va_end(ap);
}
