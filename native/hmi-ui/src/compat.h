// compat.h -- the runtime's few operating-system seams.
//
// compat.c (POSIX and Windows branches under #ifdef _WIN32) puts every
// direct use of unistd/readlink/mkstemp/localtime_r/usleep/
// clock_gettime/BSD sockets in src/*.c behind these calls (getopt_long
// stays: mingw-w64 provides it), so that the same sources build
// for the Linux panel (gcc) and for the Studio's headless preview binary
// (x86_64-w64-mingw32-gcc, HMI_UI_WITH_DRM=OFF). Nothing here changes
// behaviour on Linux.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <time.h>

// Directory of the running executable, without a trailing slash, with '/'
// separators on every platform. False when it cannot be determined.
bool hmi_exe_dir(char *buf, size_t n);

// True when `path` exists (file or directory).
bool hmi_path_exists(const char *path);

// Local time, thread-safe on every platform (localtime_r / localtime_s).
void hmi_localtime(time_t t, struct tm *out);

// A fresh temporary file opened for writing; `path_out` receives its path
// (the caller deletes it with hmi_remove when done). NULL on failure.
FILE *hmi_tmpfile(char *path_out, size_t n);
int hmi_remove(const char *path);

// Millisecond sleep and monotonic milliseconds (LVGL's tick source).
void hmi_sleep_ms(unsigned ms);
unsigned long hmi_millis(void);

// Minimal UDP socket abstraction for tags.c: an IPv4 datagram socket bound
// to `port` on 127.0.0.1 (0 = any), non-blocking. hmi_udp_t is a plain int
// on POSIX and a SOCKET on Windows; HMI_UDP_INVALID marks none.
#ifdef _WIN32
#include <winsock2.h>
typedef SOCKET hmi_udp_t;
#define HMI_UDP_INVALID INVALID_SOCKET
#else
typedef int hmi_udp_t;
#define HMI_UDP_INVALID (-1)
#endif
bool hmi_udp_init(void);                                   // WSAStartup on Windows; no-op elsewhere
hmi_udp_t hmi_udp_open(unsigned short bind_port);          // HMI_UDP_INVALID on failure
int hmi_udp_send(hmi_udp_t s, const char *host, unsigned short port, const void *data, size_t n);
// Returns bytes received, 0 when nothing is waiting (EAGAIN/EWOULDBLOCK), -1 on error.
int hmi_udp_recv(hmi_udp_t s, void *buf, size_t n);
void hmi_udp_close(hmi_udp_t s);
// The port the socket is bound to (what the kernel chose for bind_port 0).
unsigned short hmi_udp_bound_port(hmi_udp_t s);
