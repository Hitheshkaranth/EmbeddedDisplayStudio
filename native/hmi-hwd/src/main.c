/*
 * main.c -- hmi-hwd entry point. Written with the skeleton; daemon.c does
 * the work.
 */
#include "daemon.h"

int main(int argc, char **argv)
{
    hwd_options opt;
    int rc = hwd_parse_args(argc, argv, &opt);
    if (rc != 0) return rc;
    return hwd_run(&opt);
}
