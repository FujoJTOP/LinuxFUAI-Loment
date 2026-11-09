# fuai-linux-loment

FUAI (Fujo AI Architecture) implemented in **Loment** for **Debian / Linux
x86-64** user space — a complete port of the 14-case LinuxFUAI regression
suite.

FUAI is the supervisory-runtime architecture from
[FujoOS](https://github.com/FujoJTOP/FujoOS): a model channel, eyes (event
ring), hands (capability-gated actions), revocable domains, five duties and
offline axiom probes. This repository keeps that interface contract and
re-implements the mechanism in Loment, so the supervisor is a static ELF with
no libc and no Python runtime.

```
$ python3 tools/regress.py --build
==============================================================
  l1_inv             PASS
  ...
  l14_adversarial    PASS
  l15_capdom         PASS
  capdom_guard (E004) PASS
  l11b_shim (optional) PASS
==============================================================
  fujoregress(linux): 14/14 PASS
```

## Relationship to the two existing implementations

| | substrate | language |
|---|---|---|
| [FujoOS](https://github.com/FujoJTOP/FujoOS) | no_std kernel | Rust |
| [LinuxFUAI](https://github.com/FujoJTOP/LinuxFUAI) | Linux user space | C11 |
| **this repository** | Linux user space | **Loment** |

The interface names and wire formats are the LinuxFUAI ones; the byte layout
of the shm frame (v2), the FJRU v1 rulebook and the 88-byte AI audit entries
are unchanged, so the same Python model server answers all three.

## Layout

```
src/            the Loment implementation (~3.6k lines)
  fuai_byte      byte/string/number helpers
  fuai_sys       raw x86-64 Linux syscalls (no libc)
  fuai_state     the single state block and its layout
  fuai_ev        tick epoch, 128-slot event ring, eye FIFO pump
  fuai_ai        AI audit ring (16 x 88B)
  fuai_payload   payload registry by id + the --fuai-payload runner
  fuai_core      capability slots, audit, config, domains, tasks, cap_exec
  fuai_ctx       structural context text and event digest
  fuai_rules     deterministic rules + FJRU loader
  fuai_chan      shm frame file + FIFO trigger + R3 staleness
  fuai_duty      five duties, quality ledger, trust-adaptive domains
  fuai_probe     axiom self-check (0x830A) + R3 probe
  fuai           lifecycle facade
tests/          14 regression cases + harness, l15 capability-domain case,
                a negative E004 fixture, and the optional l11b shim case
adapters/       C LD_PRELOAD eye shim and a libc payload (MIT)
tools/          build.py, regress.py, model_server.py
```

## Requirements

### Target

- **Linux x86-64** (verified: Debian GNU/Linux 13 "trixie"). The supervisor is
  a **static ELF** (`ET_EXEC`, no `INTERP`); it does not use glibc, so the
  distribution's libc version is irrelevant.
- Kernel ABI used: `fork`/`execve`/`wait4`/`kill`, `openat`/`mkdirat`/
  `mknodat`/`unlinkat`, `pread64`/`pwrite64`, `poll`, `nanosleep`,
  `clock_gettime`, `readlink`, `uname`, `sched_getaffinity`, the
  `/proc/self/{exe,environ,cmdline}` files, `/proc/meminfo`, and FIFOs. All are
  in a stock Debian kernel.

### Build host

| component | version | why |
|---|---|---|
| Loment | **0.1.5.1+**, Linux x64 release (`loment-0.1.5.1-linux-x64.tar.gz`, SHA-256 `fc4e4f…`) | the self-hosted compiler; the first release that handles this 15-module unit and its capability domains |
| Python | 3.9+ | `tools/build.py`, `tools/regress.py`, the model server |
| make | any | `make build` / `make adapters` / `make regress` |
| gcc + libc headers | optional | only `adapters/` (the C `LD_PRELOAD` shim and its payload) |
| tar, sha256sum | any | unpack and verify the release |

`loment` must be the **Linux** build. The Windows install reached through WSL
interop emits PE and is rejected by `tools/build.py`. Point at the Linux
release explicitly if it is not on `PATH`:

```bash
export LOMENT_BIN=~/opt/loment-0.1.5.1-linux-x64/bin/loment
```

### Environment variables

| variable | default | meaning |
|---|---|---|
| `LOMENT_BIN` | `loment` on `PATH` | the packaged compiler `build.py` uses |
| `LOMENT_REPO` | — | a Loment checkout; only for the reference `--check` path (codegen is refused for capability units until PR #1526 ships) |
| `FUAI_HOME` | `/tmp/fuai-link-<test>` (set by `regress.py`) | link directory: `fuai.shm`, `req.fifo`, `rsp.fifo`, `ev.fifo`; the model server requires it under `/tmp` |
| `FUJO_BACKEND` | `stub` | `stub` (deterministic) or `ollama` |
| `FUJO_MODEL` | `qwen2.5:0.5b` | `ollama` model name |
| `FUJO_EVIL` | unset | `1` runs the l14 adversarial model server |
| `FUAI_LINK_TIMEOUT` | `600` ticks (6 s) | model-link timeout; the offline tests set `3` |

### Runtime footprint

- No network is needed for the `stub` backend: the model link is a FIFO pair
  plus a 0xE00-byte file. The optional `ollama` backend talks only to the fixed
  loopback endpoint `127.0.0.1:11434`.
- The supervisor state is one 40 KiB `alloc` block; each test binary is about
  270 KiB.
- `l11` spawns a child process. `l11b` (optional) needs `gcc` at build time and
  `LD_PRELOAD` at run time.

See [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) for the same matrix in more
detail, including the WSL invocation notes.

## Build (Debian)

**Preferred: the packaged toolchain, 0.1.5.1 or newer.** It builds this whole
multi-module unit directly. Download the Linux x64 tarball from the release
page, unpack it, and put its `bin/` on `PATH` (or point `LOMENT_BIN` at it):

```bash
mkdir -p ~/opt && tar -xzf loment-0.1.5.1-linux-x64.tar.gz -C ~/opt
export PATH=~/opt/loment-0.1.5.1-linux-x64/bin:$PATH
make build          # python3 tools/regress.py --build
make adapters       # optional: C shim + shim payload
make regress
```

`tools/build.py` picks a native Linux `loment` automatically (it rejects the
Windows install reached through WSL interop, which emits PE). To name it
explicitly:

```bash
export LOMENT_BIN=~/opt/loment-0.1.5.1-linux-x64/bin/loment
```

**0.1.5.1 or newer is required to build.** The port declares capability
domains, and the reference compiler resolves a dependency's `guard` against
the **entry unit's** table (Loment issue #1175): it silently emits `[0..0]`
and the resulting binary traps at the first in-range guard (measured: the
reference-built `l15_capdom` exits 132, SIGILL). The fix is in Loment
[PR #1526](https://github.com/Loment-Lang/Loment/pull/1526); until it lands in
a release, `tools/build.py` refuses to emit a binary from the reference path
for this unit and names #1175. The reference remains usable for `--check`.
0.1.4.x cannot build a unit with capability declarations at all.

The product is a **freestanding static ELF** (`readelf -l` shows no
`INTERP`), so the supervisor runs on any Debian x86-64 kernel without glibc.
The two optional adapters are ordinary dynamic binaries and are built on the
target distribution.

## Verified

- **Debian GNU/Linux 13 (trixie) x86-64**, packaged Loment **0.1.5.1**
  (commit `7bc9767b`): built from source and run natively — **14/14 PASS**,
  `l15_capdom` PASS, negative E004 PASS, optional `l11b_shim` PASS.
- Ubuntu 26.04 x86-64 (WSL): 14/14 PASS.
- The #1175 fix was verified on a Loment `main` branch (PR #1526): the
  issue's `app_silent` case went from SIGILL 132 to exit 3, and the same
  `l15_capdom` built by the reference passes the whole suite. This repository
  keeps the reference codegen refused until that fix is released.

The supervisor binaries are statically linked (`readelf -l` shows no
`INTERP`), so no glibc is involved on the FUAI side.

## Capability domains

The port declares FUAI's three index spaces as Loment capability domains
(`src/fuai_core.lomt`):

| domain | range | guards |
|---|---|---|
| `fuai_slots` | 0..7 | `cap_grant`, `cap_check` |
| `fuai_domains` | 0..4 | `dom_create`, `dom_bind`, `dom_revoke`, `dom_adjust`, `dom_info`, `task_bind_domain` |
| `fuai_actions` | 1..7 | `cap_exec` (after authorization) |

Every guard sits **after** the dynamic FUAI check, so the contract is
unchanged: an out-of-range slot or domain still returns `-22`, an
unauthorized action still returns `-1`, and none of them traps. What the
language adds is the declared shape (visible in `loment caps`) and a
compile-time E004 for a literal index that can never be valid
(`tests/negative/capdom_guard.lomt`).

`guard` is not the authorization. The gate remains `cap_exec` and the table
in `fuai_core`; a guard is an index invariant, not a permission check.

## Honest boundaries

- **The supervisor state is explicit.** Loment has no module-level mutable
  state and no mutable struct references, so the whole state lives in one
  block (`fuai_state`) passed as `ptr`. The behaviour, not the spelling, is
  what is compared.
- **Payloads are ids, not function pointers.** Loment has no function
  pointers; `fuai_payload_register(id)` and the `--fuai-payload <id>` runner
  preserve the public shape.
- **l11 reports from the payload itself.** The C suite's shim interposes libc
  `write`/`exit`; a freestanding Loment payload issues raw syscalls and never
  enters libc. The Loment payload therefore reports on the same FIFO itself.
  The ring, the pump and the supervisor side are identical. The original
  mechanism is still exercised by the optional `l11b_shim` case with
  `adapters/libfuaieyes.so`.
- **The shm frame is pwritten, not mmap'd.** The process has no libc `mmap`
  with six arguments; the supervisor writes the same 0xE00 bytes to the same
  file with `pwrite`. The Python server reads that file, so the wire format is
  unchanged.
- **The gate is `cap_exec`, not seccomp.** Like LinuxFUAI, domains bound
  model-originated actions; they are not a kernel sandbox.
- **`/proc` and FIFOs are the substrate.** Environment, argv and the machine
  digest are read from `/proc`; the model link is a FIFO pair.
- **Toolchain ceilings are real.** Under 0.1.5.1 a single source file must stay
  below 480 KiB (E999), and two name-form `use <module>` lines against the
  shipped store still fail when the store root is long (Loment issue #37).
  This port uses path-form `use "..."` only, which is why its 15 modules build.

## License

MIT. The C eye shim and the model-server protocol are derived from
[LinuxFUAI](https://github.com/FujoJTOP/LinuxFUAI) (MIT), same author.
