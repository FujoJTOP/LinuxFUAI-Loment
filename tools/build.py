#!/usr/bin/env python3
"""build.py — compile one Loment test with the reference toolchain.

The self-hosted compiler (0.1.4 package) has a small per-unit string-literal
table; a unit that pulls in several modules overflows it ("fujoc-s: cannot
open <fragment>"). The reference compiler in the Loment checkout has no such
limit and its lomelf twin emits the same static ELF, so this build script uses
that pair. Set LOMENT_REPO to the checkout (or clone it from GitHub).

  LOMENT_REPO=~/Loment python3 tools/build.py tests/l1_inv.lomt -o build/l1_inv
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def loment_repo() -> Path:
    env = os.environ.get("LOMENT_REPO")
    if env:
        return Path(env).resolve()
    candidates = [
        ROOT.parent / "loment-base-origin-main",
        ROOT.parent / "Loment",
        Path.home() / "Loment",
        Path("/opt/Loment"),
        ROOT.parent / "Loment-DEV",
    ]
    for c in candidates:
        if (c / "tools" / "lomentc.py").exists():
            return c.resolve()
    raise SystemExit("set LOMENT_REPO to a Loment checkout (tools/lomentc.py)")


def packaged_loment() -> str | None:
    """The packaged toolchain, if it is new enough for multi-module units."""
    if os.name == "nt":
        return None  # the Windows package emits PE; we need a Linux ELF
    import re
    import shutil
    import subprocess
    exe = os.environ.get("LOMENT_BIN") or shutil.which("loment")
    if not exe:
        return None
    # A Windows install reached through WSL interop has loment-driver.exe and
    # emits PE / a shimmed artifact; only a native Linux package has the ELF.
    drv = Path(exe).resolve().parent / "loment-driver"
    try:
        if drv.read_bytes()[:4] != b"\x7fELF":
            return None
    except OSError:
        return None
    try:
        out = subprocess.run([exe, "version"], capture_output=True, text=True,
                             timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"Loment (\d+)\.(\d+)\.(\d+)(?:\.(\d+))?", out)
    if not m:
        return None
    ver = tuple(int(x or 0) for x in m.groups())
    return exe if ver >= (0, 1, 5, 1) else None


def build_with_loment(exe: str, src: Path, out: Path | None) -> int:
    import subprocess
    if out is None:
        raise SystemExit("-o is required unless --check")
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([exe, "build", str(src), "-o", str(out)])
    if r.returncode != 0:
        return r.returncode
    os.chmod(out, 0o755)
    print(f"{out} ({out.stat().st_size} bytes) [packaged loment]")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="build")
    ap.add_argument("src")
    ap.add_argument("-o", "--out")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--ir", action="store_true")
    ap.add_argument("--toolchain", choices=["auto", "loment", "reference"],
                    default="auto")
    a = ap.parse_args(argv)

    src0 = Path(a.src).resolve()
    if not a.ir and not a.check:
        exe = packaged_loment()
        if a.toolchain in ("auto", "loment") and exe is not None:
            print(f"[toolchain] {exe} (packaged)")
            return build_with_loment(exe, src0, Path(a.out) if a.out else None)
        if a.toolchain == "loment":
            raise SystemExit("no packaged loment >= 0.1.5.1 on PATH")

    repo = loment_repo()
    print(f"[toolchain] {repo}")
    sys.path.insert(0, str(repo / "tools"))
    import lomentc  # noqa: E402
    import lomelf  # noqa: E402

    src = Path(a.src).resolve()
    mod = lomentc.load(src)
    deps = lomentc.resolve_deps(mod, repo, src.parent, entry=src)
    errs = lomentc.check(mod, deps=deps)
    if errs:
        for e in errs:
            print(e)
        return 1
    ll = lomentc.emit_llvm(mod, repo, deps)
    if a.ir:
        print(ll)
    if a.check:
        return 0
    if not a.out:
        raise SystemExit("-o is required unless --check")
    blob, info = lomelf.compile_ll(ll)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    os.chmod(out, 0o755)
    print(f"{out} ({len(blob)} bytes) entry={info.get('entry')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
