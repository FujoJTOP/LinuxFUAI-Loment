#!/usr/bin/env python3
"""regress.py — the FUAI-on-Debian regression driver (fujoregress convention).

Builds nothing by default: run tools/build.py for each test first (or pass
--build). Offline tests l1..l12 run with FUAI_HOME per test; l13/l14 start the
stub model server (l14 with FUJO_EVIL=1), then run the binary. Exit code 0 iff
every case prints "RESULT: PASS" and exits 0.

  python3 tools/build.py tests/l1_inv.lomt -o build/l1_inv   # once per test
  python3 tools/regress.py --build
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
SERVER = ROOT / "tools" / "model_server.py"

OFFLINE = [
    "l1_inv", "l2_cap", "l3_domain", "l4_classify", "l5_anom", "l6_plan",
    "l7_io", "l8_nlc", "l9_env", "l10_trust", "l11_eyes", "l12_link",
]
ONLINE = [("l13_model", {}), ("l14_adversarial", {"FUJO_EVIL": "1"})]


def run_case(name: str, bindir: Path, env: dict, timeout: float):
    exe = bindir / name
    if not exe.exists():
        return False, f"missing binary {exe}"
    e = os.environ.copy()
    e.update(env)
    try:
        p = subprocess.run([str(exe)], capture_output=True, text=True,
                           timeout=timeout, env=e, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode == 0 and "RESULT: PASS" in out, out


def start_server(env: dict):
    e = os.environ.copy()
    e.update(env)
    e["FUJO_BACKEND"] = "stub"
    p = subprocess.Popen([sys.executable, str(SERVER)], env=e,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, cwd=str(ROOT))
    banner = p.stdout.readline().strip()
    if "model server" not in banner:
        p.kill()
        raise RuntimeError(f"model server failed to start: {banner}")
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="regress")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--bin", default=str(BUILD))
    ap.add_argument("--timeout", type=float, default=120.0)
    a = ap.parse_args(argv)
    bindir = Path(a.bin).resolve()

    if a.build:
        for name in OFFLINE + [n for n, _ in ONLINE] + ["l11b_shim"]:
            cmd = [sys.executable, str(ROOT / "tools" / "build.py"),
                   str(ROOT / "tests" / f"{name}.lomt"),
                   "-o", str(bindir / name)]
            r = subprocess.run(cmd, cwd=str(ROOT))
            if r.returncode != 0:
                print(f"[build] {name} FAILED")
                return 1

    results = []
    failures = 0
    for name in OFFLINE:
        home = f"/tmp/fuai-link-{name}"
        env = {"FUAI_HOME": home,
               "FUAI_EYES_LIB": str(bindir / "libfuaieyes.so")}
        ok, out = run_case(name, bindir, env, a.timeout)
        results.append((name, ok, out))
        failures += 0 if ok else 1

    for name, extra in ONLINE:
        home = f"/tmp/fuai-link-{name}"
        srv = start_server({**extra, "FUAI_HOME": home})
        try:
            ok, out = run_case(name, bindir, {"FUAI_HOME": home},
                               max(a.timeout, 180.0))
        finally:
            srv.terminate()
            try:
                srv.wait(timeout=5)
            except subprocess.TimeoutExpired:
                srv.kill()
        results.append((name, ok, out))
        failures += 0 if ok else 1

    # Optional: the C LD_PRELOAD shim path (adapters/ built with make).
    opt = []
    lib = ROOT / "adapters" / "libfuaieyes.so"
    pay = ROOT / "adapters" / "fuai_eyes_payload"
    if (bindir / "l11b_shim").exists() and lib.exists() and pay.exists():
        env = {"FUAI_HOME": "/tmp/fuai-link-l11b",
               "FUAI_EYES_LIB": str(lib),
               "FUAI_SHIM_PAYLOAD": str(pay)}
        ok, out = run_case("l11b_shim", bindir, env, a.timeout)
        opt.append(("l11b_shim (optional)", ok, out))

    print()
    print("=" * 62)
    for name, ok, out in results:
        print(f"  {name:<18} {'PASS' if ok else 'FAIL'}")
        if not ok:
            tail = "\n".join(out.strip().splitlines()[-15:])
            print("    ---- tail ----")
            for line in tail.splitlines():
                print(f"    {line}")
    for name, ok, out in opt:
        print(f"  {name:<18} {'PASS' if ok else 'FAIL'}")
        if not ok:
            tail = "\n".join(out.strip().splitlines()[-15:])
            print("    ---- tail ----")
            for line in tail.splitlines():
                print(f"    {line}")
    total = len(results)
    print("=" * 62)
    print(f"  fujoregress(linux): {total - failures}/{total} PASS")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
