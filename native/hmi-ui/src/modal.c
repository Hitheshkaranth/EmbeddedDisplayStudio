// modal.c -- see modal.h. The runtime is single-threaded (LVGL's loop), so a
// plain pointer is the whole state.
#include "modal.h"

#include <stddef.h>
#include <string.h>

static const char *g_owner;

bool hmi_modal_claim(const char *owner)
{
    if (!owner) return false;
    if (g_owner && strcmp(g_owner, owner) != 0) return false;
    g_owner = owner;
    return true;
}

void hmi_modal_release(const char *owner)
{
    if (g_owner && owner && strcmp(g_owner, owner) == 0) g_owner = NULL;
}

const char *hmi_modal_owner(void) { return g_owner; }
