/* fuai_shim.c — FUAI eyes for unmodified Linux binaries (LD_PRELOAD).
 *
 * Interposes write()/exit() in payload processes and reports real events to
 * the supervisor through $FUAI_EV_FIFO as lines "EV <kind> <a> <b>":
 *   write to a regular file -> kind 2 (FUAI_EV_FILE, a = byte count)
 *   process exit            -> kind 4 (FUAI_EV_EXIT, a = exit status)
 * The supervisor's ev pump drains the FIFO into the 128-slot event ring —
 * the same eyes the FujoOS kernel fills from its own syscall path (0x8004).
 *
 * Build as a PIC shared object; see Makefile target libfuaieyes.so.
 * SPDX-License-Identifier: MIT
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int  ev_fd = -1;
static long ev_syscalls;

static void shim_init(void)
{
    if (ev_fd >= 0) return;
    const char *path = getenv("FUAI_EV_FIFO");
    if (!path || !*path) return;
    ev_fd = open(path, O_WRONLY | O_NONBLOCK);
}

static void ev_send(int kind, long a, long b)
{
    shim_init();
    if (ev_fd < 0) return;
    char line[64];
    int n = snprintf(line, sizeof(line), "EV %d %ld %ld\n", kind, a, b);
    ssize_t rc = write(ev_fd, line, (size_t)n);
    (void)rc;
}

/* ---- write(2): file events -------------------------------------------------- */

ssize_t write(int fd, const void *buf, size_t count)
{
    static ssize_t (*real_write)(int, const void *, size_t);
    if (!real_write)
        real_write = dlsym(RTLD_NEXT, "write");

    shim_init(); /* lazy: first write may precede any ev_send */
    ev_syscalls++;
    if (count > 0 && ev_fd >= 0 && fd != ev_fd) {
        struct stat st;
        if (fstat(fd, &st) == 0 && S_ISREG(st.st_mode))
            ev_send(2, (long)count, (long)fd); /* EV_FILE */
    }
    return real_write(fd, buf, count);
}

/* ---- exit(3): exit events ----------------------------------------------------- */

void exit(int status)
{
    static void (*real_exit)(int) __attribute__((noreturn));
    if (!real_exit)
        real_exit = dlsym(RTLD_NEXT, "exit");
    ev_send(4, status, 0); /* EV_EXIT */
    real_exit(status);
}
