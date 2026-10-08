#define _GNU_SOURCE
#include "proto.h"
#include "hwd.h"
#include <stdio.h>
#include <string.h>
int main(void) {
    const char *m = "{\"cmd\":\"list\"}";
    hwd_cmd c;
    memset(&c, 0, sizeof c);
    hwd_err e = hwd_proto_parse(m, strlen(m), &c);
    printf("e=%d kind=%d\n", (int)e, (int)c.kind);
    return 0;
}