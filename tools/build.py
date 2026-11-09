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
        ROOT.parent / "Loment-DEV-wt-fuai",
        ROOT.parent / "Loment-DEV",
        Path.home() / "Loment",
        Path("/opt/Loment"),
    ]
    for c in candidates:
        if (c / "tools" / "lomentc.py").exists():
            return c.resolve()
    raise SystemExit("set LOMENT_REPO to a Loment checkout (tools/lomentc.py)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="build")
    ap.add_argument("src")
    ap.add_argument("-o", "--out")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--ir", action="store_true")
    a = ap.parse_args(argv)

    repo = loment_repo()
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
