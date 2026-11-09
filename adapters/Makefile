# adapters/Makefile — the two native adapters the port keeps:
#   libfuaieyes.so   the LD_PRELOAD eye shim (interposes libc write/exit)
#   fuai_eyes_payload  an unmodified libc payload used by l11b_shim
CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra

all: libfuaieyes.so fuai_eyes_payload

libfuaieyes.so: fuai_shim.c
	$(CC) $(CFLAGS) -fPIC -shared -o $@ $< -ldl

fuai_eyes_payload: eyes_payload.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f libfuaieyes.so fuai_eyes_payload

.PHONY: all clean
