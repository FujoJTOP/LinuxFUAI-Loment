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
tests/          14 regression cases + harness (+ optional l11b shim case)
adapters/       C LD_PRELOAD eye shim and a libc payload (MIT)
tools/          build.py, regress.py, model_server.py
```

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

**Older packages (0.1.4.x)** have a small per-unit string-literal table that a
unit this size overflows (`fujoc-s: cannot open …`). For those, `build.py`
falls back to the reference compiler and its `lomelf` twin in a Loment
checkout:

```bash
git clone https://github.com/Loment-Lang/Loment.git ~/Loment
export LOMENT_REPO=~/Loment
```

The product is a **freestanding static ELF** (`readelf -l` shows no
`INTERP`), so the supervisor runs on any Debian x86-64 kernel without glibc.
The two optional adapters are ordinary dynamic binaries and are built on the
target distribution.

## Verified

- **Debian GNU/Linux 13 (trixie) x86-64**: built from source and run natively
  — **14/14 PASS**, optional `l11b_shim` PASS. Two toolchains both verified:
  the packaged **0.1.5.1** Linux release, and the reference pair from Loment
  `main` at `0328abbc` (2026-11-09).
- Ubuntu 26.04 x86-64 (WSL): 14/14 PASS.

The supervisor binaries are statically linked (`readelf -l` shows no
`INTERP`), so no glibc is involved on the FUAI side.

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

## License

MIT. The C eye shim and the model-server protocol are derived from
[LinuxFUAI](https://github.com/FujoJTOP/LinuxFUAI) (MIT), same author.
