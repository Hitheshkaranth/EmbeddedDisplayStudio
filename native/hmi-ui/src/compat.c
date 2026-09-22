// compat.c -- see compat.h. The POSIX branch is what the runtime always did
// (readlink /proc/self/exe, access, localtime_r, mkstemp, usleep,
// CLOCK_MONOTONIC, BSD sockets); the Windows branch is the mingw-w64 build
// of the Studio's headless preview binary.
#include "compat.h"

#include <errno.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#include <ws2tcpip.h>
#else
#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

// -- files and paths ----------------------------------------------------------------

bool hmi_exe_dir(char *buf, size_t n)
{
    if (!buf || n < 2) return false;
#ifdef _WIN32
    DWORD len = GetModuleFileNameA(NULL, buf, (DWORD)n);
    if (len == 0 || len >= n) return false;
    for (char *p = buf; *p; ++p)
        if (*p == '\\') *p = '/';
#else
    ssize_t len = readlink("/proc/self/exe", buf, n - 1);
    if (len <= 0) return false;
    buf[len] = '\0';
#endif
    char *slash = strrchr(buf, '/');
    if (!slash) return false;
    // "/hmi-ui" lives in "/": keep the root slash rather than an empty string.
    if (slash == buf) slash[1] = '\0';
    else *slash = '\0';
    return true;
}

bool hmi_path_exists(const char *path)
{
    if (!path || !*path) return false;
#ifdef _WIN32
    return GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES;
#else
    return access(path, F_OK) == 0;
#endif
}

void hmi_localtime(time_t t, struct tm *out)
{
#ifdef _WIN32
    localtime_s(out, &t);
#else
    localtime_r(&t, out);
#endif
}

FILE *hmi_tmpfile(char *path_out, size_t n)
{
    if (!path_out || n == 0) return NULL;
#ifdef _WIN32
    char dir[MAX_PATH + 1], name[MAX_PATH + 1];
    DWORD len = GetTempPathA(sizeof dir, dir);
    if (len == 0 || len >= sizeof dir) return NULL;
    // GetTempFileNameA creates the (empty) file, so the name is ours.
    if (GetTempFileNameA(dir, "hmi", 0, name) == 0) return NULL;
    if (strlen(name) >= n) { DeleteFileA(name); return NULL; }
    strcpy(path_out, name);
    FILE *f = fopen(path_out, "w");
    if (!f) DeleteFileA(name);
    return f;
#else
    char path[] = "/tmp/hmi-ui-XXXXXX";
    if (sizeof path > n) return NULL;
    int fd = mkstemp(path);
    if (fd < 0) return NULL;
    strcpy(path_out, path);
    FILE *f = fdopen(fd, "w");
    if (!f) { close(fd); unlink(path); }
    return f;
#endif
}

int hmi_remove(const char *path)
{
    return remove(path);
}

// -- time -----------------------------------------------------------------------------

void hmi_sleep_ms(unsigned ms)
{
#ifdef _WIN32
    Sleep(ms);
#else
    usleep(ms * 1000u);
#endif
}

unsigned long hmi_millis(void)
{
#ifdef _WIN32
    return (unsigned long)GetTickCount64();
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (unsigned long)(ts.tv_sec * 1000 + ts.tv_nsec / 1000000);
#endif
}

// -- UDP ------------------------------------------------------------------------------

#ifdef _WIN32
// Winsock keeps its own error codes; the callers print strerror(errno), so
// map the ones a bind can plausibly hit and leave the rest as EIO.
static void set_errno_from_wsa(void)
{
    switch (WSAGetLastError()) {
    case WSAEADDRINUSE: errno = EADDRINUSE; break;
    case WSAEACCES: errno = EACCES; break;
    case WSAEWOULDBLOCK: errno = EAGAIN; break;
    case WSANOTINITIALISED: errno = ENOTSOCK; break;
    default: errno = EIO; break;
    }
}
#endif

static bool make_addr(struct sockaddr_in *addr, const char *host, unsigned short port)
{
    memset(addr, 0, sizeof *addr);
    addr->sin_family = AF_INET;
    addr->sin_port = htons(port);
    if (inet_pton(AF_INET, host ? host : "127.0.0.1", &addr->sin_addr) != 1)
        return inet_pton(AF_INET, "127.0.0.1", &addr->sin_addr) == 1;
    return true;
}

bool hmi_udp_init(void)
{
#ifdef _WIN32
    static bool started;
    if (started) return true;
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) return false;
    started = true;
#endif
    return true;
}

hmi_udp_t hmi_udp_open(unsigned short bind_port)
{
    if (!hmi_udp_init()) return HMI_UDP_INVALID;
    hmi_udp_t s = socket(AF_INET, SOCK_DGRAM, 0);
    if (s == HMI_UDP_INVALID) {
#ifdef _WIN32
        set_errno_from_wsa();
#endif
        return HMI_UDP_INVALID;
    }
    struct sockaddr_in addr;
    make_addr(&addr, "127.0.0.1", bind_port);
    if (bind(s, (struct sockaddr *)&addr, sizeof addr) != 0) {
#ifdef _WIN32
        set_errno_from_wsa();
#endif
        hmi_udp_close(s);
        return HMI_UDP_INVALID;
    }
#ifdef _WIN32
    u_long nonblock = 1;
    ioctlsocket(s, FIONBIO, &nonblock);
#else
    fcntl(s, F_SETFL, fcntl(s, F_GETFL, 0) | O_NONBLOCK);
#endif
    return s;
}

// Not in compat.h: tags.h promises hmi_tags_rx_port() reports the port the
// kernel picked when rx_port was 0, which the contract's hmi_udp_open cannot
// return. tags.c declares this itself.
unsigned short hmi_udp_bound_port(hmi_udp_t s)
{
    struct sockaddr_in addr;
    socklen_t len = sizeof addr;
    if (s == HMI_UDP_INVALID || getsockname(s, (struct sockaddr *)&addr, &len) != 0) return 0;
    return ntohs(addr.sin_port);
}

int hmi_udp_send(hmi_udp_t s, const char *host, unsigned short port, const void *data, size_t n)
{
    struct sockaddr_in addr;
    make_addr(&addr, host, port);
#ifdef _WIN32
    int r = sendto(s, (const char *)data, (int)n, 0, (struct sockaddr *)&addr, sizeof addr);
    if (r == SOCKET_ERROR) { set_errno_from_wsa(); return -1; }
    return r;
#else
    ssize_t r = sendto(s, data, n, 0, (struct sockaddr *)&addr, sizeof addr);
    return r < 0 ? -1 : (int)r;
#endif
}

int hmi_udp_recv(hmi_udp_t s, void *buf, size_t n)
{
#ifdef _WIN32
    int r = recvfrom(s, (char *)buf, (int)n, 0, NULL, NULL);
    if (r == SOCKET_ERROR) {
        int e = WSAGetLastError();
        if (e == WSAEWOULDBLOCK) return 0;
        // A previous send to a closed port surfaces here as ICMP unreachable.
        if (e == WSAECONNRESET) return 0;
        set_errno_from_wsa();
        return -1;
    }
    return r;
#else
    ssize_t r = recvfrom(s, buf, n, 0, NULL, NULL);
    if (r < 0) return (errno == EAGAIN || errno == EWOULDBLOCK) ? 0 : -1;
    return (int)r;
#endif
}

void hmi_udp_close(hmi_udp_t s)
{
    if (s == HMI_UDP_INVALID) return;
#ifdef _WIN32
    closesocket(s);
#else
    close(s);
#endif
}
