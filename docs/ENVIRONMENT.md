# Environment

What this repository needs to build and run, and why.

## Supported target

- **Linux x86-64.** Verified on Debian GNU/Linux 13 ("trixie") and Ubuntu
  26.04 (WSL).
- The supervisor is a **freestanding static ELF**: `readelf -l` shows no
  `INTERP`, and nothing links glibc. The distribution's libc version does not
  matter for the FUAI side.
- The two optional adapters (`adapters/libfuaieyes.so`,
  `adapters/fuai_eyes_payload`) are ordinary dynamic binaries; build them on
  the target distribution.

### Kernel surface used

`fork`, `execve`, `wait4`, `kill` (`SIGKILL`/`SIGSTOP`/`SIGCONT`), `openat`,
`mkdirat`, `mknodat` (FIFO), `unlinkat`, `pread64`, `pwrite64`, `poll`,
`nanosleep`, `clock_gettime`, `readlink`, `uname`, `sched_getaffinity`, and
these files:

```
/proc/self/exe
/proc/self/environ
/proc/self/cmdline
/proc/meminfo
```

All of them are in a stock Debian kernel; no module or capability beyond the
normal user is required.

## Build host

| component | version | notes |
|---|---|---|
| Loment | **0.1.5.1 or newer**, Linux x64 | the release asset `loment-0.1.5.1-linux-x64.tar.gz` from [Loment releases](https://github.com/Loment-Lang/Loment/releases); SHA-256 `fc4e4fb0…` |
| Python | 3.9+ | `tools/build.py`, `tools/regress.py`, `tools/model_server.py` |
| make | any | thin wrapper around the Python entry points |
| gcc + libc headers | optional | `make adapters` only |
| tar, sha256sum | any | unpack/verify the release |
| git | any | only to fetch this repository |

On Debian, the non-Loment parts are:

```bash
apt-get update
apt-get install -y python3 make gcc libc6-dev tar coreutils
```

### Install the toolchain

```bash
mkdir -p ~/opt
tar -xzf loment-0.1.5.1-linux-x64.tar.gz -C ~/opt
export PATH=~/opt/loment-0.1.5.1-linux-x64/bin:$PATH
loment version          # Loment 0.1.5.1 ... commit 7bc9767b
```

If it is not on `PATH`, name it explicitly:

```bash
export LOMENT_BIN=~/opt/loment-0.1.5.1-linux-x64/bin/loment
```

`tools/build.py` accepts a packaged `loment` only if the sibling
`loment-driver` starts with the ELF magic. The Windows install reached through
WSL interop (`/mnt/c/.../Loment/bin/loment`) is rejected on purpose: it emits
PE, and its diagnostics path does not work from WSL (Loment issue #1522).

## Environment variables

| variable | default | meaning |
|---|---|---|
| `LOMENT_BIN` | `loment` on `PATH` | packaged compiler used by `tools/build.py` |
| `LOMENT_REPO` | — | a Loment checkout; only for the reference `--check` path. Codegen is refused for capability units until Loment PR #1526 ships |
| `FUAI_HOME` | `/tmp/fuai-link-<test>` | link directory holding `fuai.shm`, `req.fifo`, `rsp.fifo`, `ev.fifo`. `regress.py` sets one per test; the model server refuses a path outside `/tmp` |
| `FUJO_BACKEND` | `stub` | `stub` = deterministic answers; `ollama` = local model |
| `FUJO_MODEL` | `qwen2.5:0.5b` | model name for the `ollama` backend |
| `FUJO_EVIL` | unset | `1` makes the l14 server adversarial |
| `FUAI_LINK_TIMEOUT` | `600` ticks (6 s) | model-link timeout; offline tests set `3` |
| `FUAI_EYES_LIB` | unset | `l11b_shim` only: path to `libfuaieyes.so` |
| `FUAI_SHIM_PAYLOAD` | unset | `l11b_shim` only: path to `fuai_eyes_payload` |

## Runtime footprint

- **No listening ports.** The model link is a file plus a FIFO pair. The
  optional `ollama` backend connects only to the fixed loopback endpoint
  `127.0.0.1:11434`; it does not accept connections.
- Supervisor state: one 40 KiB `alloc` block. Each test binary is ~270 KiB.
- `l11_eyes` spawns a child process; `l11b_shim` additionally needs `gcc` at
  build time and `LD_PRELOAD` at run time.
- No GPU, no CUDA, no database.

## Commands

```bash
# check only (does not emit)
python3 tools/build.py tests/l1_inv.lomt --check

# build one test
python3 tools/build.py tests/l1_inv.lomt -o build/l1_inv

# build everything and run the whole suite
python3 tools/regress.py --build

# or through make
make build      # = python3 tools/regress.py --build
make adapters   # optional C shim + payload
make regress    # run what is already in build/
```

To run a single case by hand:

```bash
FUAI_HOME=/tmp/fuai-link-l1 ./build/l1_inv
```

For the online cases, start the stub server first (the driver does this
automatically):

```bash
FUAI_HOME=/tmp/fuai-link-l13 FUJO_BACKEND=stub python3 tools/model_server.py &
FUAI_HOME=/tmp/fuai-link-l13 ./build/l13_model
```

## WSL notes

- Use the **Linux** release. The Windows package is the wrong artifact for
  every step after `loment version`.
- Invoking WSL from Git Bash: prefix the command with `MSYS_NO_PATHCONV=1`, or
  the `/mnt/...` path is rewritten to a Windows path.
- Executing from `/mnt/d` works, but the WSL `/tmp` copy is faster and avoids
  stale-file visibility; `tools/verify_debian.sh` copies the binaries to
  `/tmp` and runs the suite.
- A freshly built ELF on `/mnt/d` may need `chmod +x` (the compiler writes the
  file without the executable bit in some releases).

## Toolchain limits that shape the build

| limit | effect | workaround |
|---|---|---|
| 0.1.4.x per-unit literal table | a multi-module unit dies with `fujoc-s: cannot open …` | 0.1.5.1+ (this repository) |
| 480 KiB per source file (E999) | a larger file is refused with a diagnostic | split the file |
| two name-form `use <module>` lines against a long store root (#37) | E031 with a truncated path | use path-form `use "..."` (this repository does) |
| reference `[0..0]` for a dependency's guard (#1175) | the binary traps at the first in-range guard | use 0.1.5.1+, or Loment PR #1526 once released |
| `icmp == ptr` (#205) | the reference emits IR lomelf rejects | do not compare pointers; pass an integer address |

## What "verified" means here

The suite is the **LinuxFUAI** 14-case contract (`l1`–`l14`) plus this port's
own `l15_capdom` and a negative E004 fixture. The model server is the
LinuxFUAI one (MIT); the wire format (shm frame v2, FJRU v1, 88-byte AI audit
entries) is byte-identical.
