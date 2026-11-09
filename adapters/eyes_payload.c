/* eyes_payload.c — an unmodified libc payload for the eye-shim test.
 *
 * Writes a regular file three times and returns from main (exit()). With
 * LD_PRELOAD=libfuaieyes.so and FUAI_EV_FIFO set, the shim reports three
 * EV_FILE lines and one EV_EXIT line on the supervisor's eye FIFO. This is
 * the LinuxFUAI mechanism, exercised against the same pump/ring on the
 * Loment side.
 *
 * SPDX-License-Identifier: MIT
 */
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(void)
{
    int fd = open("/tmp/fuai-shim-demo.txt", O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd >= 0) {
        const char *msg = "shim eyes demo line\n";
        for (int i = 0; i < 3; i++) {
            ssize_t rc = write(fd, msg, strlen(msg));
            (void)rc;
        }
        close(fd);
    }
    exit(0); /* explicit: main-return goes through glibc internally */
}
