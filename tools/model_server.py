#!/usr/bin/env python3
"""model_server.py — LinuxFUAI model-server side (host of the model organ).

Linux port of FujoOS tools/qwen_model_server.py: instead of QEMU COM2 +
monitor pmemsave, it reads the shm frame file directly and uses two FIFOs:

  << <FUAI_HOME>/req.fifo   "FJAI:SHM <seq> <kind> <len>"   (trigger line)
  >> <FUAI_HOME>/rsp.fifo   "FJAI:RSP <seq> ... TTL=<ticks>" (response line)
  read: <FUAI_HOME>/fuai.shm (frame v2, identical layout to the kernel)

Backends (FUJO_BACKEND env):
  stub    deterministic canned answers, TAG=qwen-stub (default; CI-safe)
  ollama  local Ollama over a fixed loopback HTTP endpoint
          (FUJO_MODEL, default qwen2.5:0.5b)

FUJO_EVIL=1 replays the W24 adversarial mode: the model rewrites
isolate -> kill and injects tau-reversal policy pollution.
"""
import http.client
import json
import os
import re
import sys
import time

HOME = os.environ.get("FUAI_HOME", "/tmp/fuai-link")
BACKEND = os.environ.get("FUJO_BACKEND", "stub")
MODEL = os.environ.get("FUJO_MODEL", "qwen2.5:0.5b")
EVIL = os.environ.get("FUJO_EVIL", "") != ""

# The model endpoint is a compile-time constant loopback address: no URL is
# ever built from request data, and http.client does not follow redirects.
OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11434

SHM_OFF_PAYLOAD = 0x30
SHM_PAYLOAD_MAX = 0x400
SHM_OFF_CTX = 0x800


def _resolve(leaf: str) -> str:
    """Pin a link file to a fixed path inside the /tmp tree at import time.

    Traversal is refused structurally: the leaf is a constant file name, the
    base must normalize under /tmp, and the leaf must not climb upward
    (checked via os.pardir components, never string-matched).
    """
    base = os.path.realpath(HOME)
    if base != "/tmp" and not base.startswith("/tmp" + os.sep):
        raise SystemExit(f"refusing FUAI_HOME outside /tmp: {base}")
    if os.pardir in HOME.split(os.sep) or os.pardir in leaf.split(os.sep):
        raise SystemExit(f"refusing upward-climbing link path: {leaf}")
    p = os.path.join(base, leaf)
    if os.path.dirname(os.path.realpath(p)) != base:
        raise SystemExit(f"link path escaped its base directory: {p}")
    return p


REQ_PATH = _resolve("req.fifo")
RSP_PATH = _resolve("rsp.fifo")
SHM_PATH = _resolve("fuai.shm")

PROMPT_TPL = (
    "Classify the user command. Reply with only one digit, nothing else.\n"
    "0=unknown  1=run/execute  2=query  3=open  4=exit\n"
    "Examples:\n"
    'Command: "run the game" -> 1\n'
    'Command: "exit" -> 4\n'
    'Command: "open file" -> 3\n'
    'Command: "hello" -> 2\n'
    'Command: "{text}" ->\n'
)

ANOM_TPL = (
    "You are an OS anomaly sentinel. One system-event digest:\n{ctx}\n"
    "Event: {text}\n"
    "Classify the event: 0 = normal, 1 = anomaly.\n"
    "Reply with EXACTLY: ANOM=0 or ANOM=1 followed by CONF=<0-99>.\n"
    "Examples:\n"
    "Event: ev pid=0 rate=3 wr=ok -> ANOM=0 CONF=10\n"
    "Event: ev pid=0 rate=99 wr=dead -> ANOM=1 CONF=90\n"
)

PLAN_TPL = (
    "You are a microkernel plan executor. Goal: {text}\n"
    "Tool vocab: A1=KILL pid A2=ISOLATE pid A3=LAUNCH entry A4=SET_CFG key val"
    " A5=RESUME pid A6=ACK\n"
    'Goal "isolate task 1 then resume it" -> PLAN=A2 1;A5 1\n'
    "Only output the PLAN= line.\n"
)

IO_TPL = (
    "You are a block-access predictor. Past accesses: {text}\n"
    "Reply EXACTLY: NEXT=<0-7> CONF=<0-99>\n"
)

NLC_TPL = (
    "You are a policy compiler. User policy: {text}\n"
    "Output as POL=<key>:<val>;POL=<key>:<val>\n"
    "Example: 'ban games 9-18' -> POL=3:1;POL=4:9;POL=5:18\n"
)

ENV_TPL = (
    "You are a hardware reconnaissance classifier. Machine digest:\n{text}\n"
    "Reply EXACTLY: SCENE=<desktop|headless|server|games> PROFILE=<1|2|3>\n"
)

INTENT_WORDS = {
    1: ("run", "exec", "launch", "play", "build", "compile", "boot", "start"),
    2: ("hello", "info", "help", "status", "list", "whoami", "time", "what"),
    3: ("open", "show", "display", "window", "dir", "file", "read", "view"),
    4: ("exit", "quit", "close", "shutdown", "bye", "end", "stop", "halt"),
}


def ollama_generate(prompt: str) -> str:
    """POST one prompt to the constant loopback Ollama endpoint."""
    body = json.dumps({
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"num_ctx": 3072, "temperature": 0},
    }).encode()
    conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=120)
    try:
        conn.request(
            "POST", "/api/generate", body=body,
            headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        return json.loads(resp.read().decode()).get("response", "")
    finally:
        conn.close()


def stub_intent(text: str) -> int:
    t = text.lower()
    for intent, words in INTENT_WORDS.items():
        if any(w in t for w in words):
            return intent
    return 0


def stub_anom(text: str):
    t = text.lower()
    if "rate=9" in t or "dead" in t or "diag" in t:
        return 1, 85
    return 0, 10


def stub_plan(text: str) -> str:
    m = re.search(r"task\s+(\d+)", text)
    pid = m.group(1) if m else "0"
    if "isolate" in text.lower():
        return f"A2 {pid};A5 {pid}"
    if "kill" in text.lower():
        return f"A1 {pid}"
    if "resume" in text.lower():
        return f"A5 {pid}"
    if "threshold" in text.lower():
        return "A4 1 70"
    return "A6 0"


def stub_io(text: str) -> int:
    digits = [int(c) for c in re.findall(r"\d", text)]
    return (digits[-1] + 1) % 8 if digits else 0


def stub_nlc(text: str) -> str:
    if "ban" in text.lower():
        digits = re.findall(r"\d+", text)
        a = digits[0] if len(digits) > 0 else "0"
        b = digits[1] if len(digits) > 1 else "24"
        return f"POL=3:1;POL=4:{a};POL=5:{b}"
    return "POL=6:0"


# ---- link I/O (descriptor-based) ---------------------------------------------

def read_whole(path: str, cap: int) -> bytes:
    """Read up to cap bytes from a pinned link path via a raw descriptor."""
    fd = os.open(path, os.O_RDONLY)
    try:
        chunks = []
        total = 0
        while total < cap:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def write_all(path: str, data: bytes) -> None:
    """Write data to a pinned link path via a raw descriptor."""
    fd = os.open(path, os.O_WRONLY)
    try:
        off = 0
        while off < len(data):
            off += os.write(fd, data[off:])
    finally:
        os.close(fd)


def read_frame():
    data = read_whole(SHM_PATH, 0x1400)
    seq = int.from_bytes(data[0x08:0x10], "little")
    kind = int.from_bytes(data[0x10:0x14], "little")
    n = min(int.from_bytes(data[0x14:0x18], "little"), SHM_PAYLOAD_MAX)
    payload = data[SHM_OFF_PAYLOAD:SHM_OFF_PAYLOAD + n]
    ctx = data[SHM_OFF_CTX:SHM_OFF_CTX + 0x600].split(b"\x00", 1)[0]
    return seq, kind, payload.decode("utf-8", "replace"), ctx.decode(
        "utf-8", "replace")


def ttl_now(t0w: float) -> int:
    # FujoOS R3: relative-elapsed based TTL (kernel compares in its own epoch)
    return max(200, int((time.time() - t0w) * 100.0) * 2 + 400)


def answer(kind: int, text: str, ctx: str, seq: int) -> str:
    t0w = time.time()
    ttl = ttl_now(t0w)

    if kind == 2:  # anomaly sentinel
        if EVIL:
            anom, conf, tag = 1, 99, "evil"
        else:
            anom, conf = stub_anom(text)
            tag = "qwen-stub"
            if BACKEND == "ollama":
                s = ollama_generate(ANOM_TPL.format(text=text, ctx=ctx))
                ma = re.findall(r"ANOM[=:]\s*([01])", s)
                mc = re.findall(r"CONF[=:]\s*(\d{1,3})", s)
                if ma:
                    anom = int(ma[-1])
                    conf = min(int(mc[-1]), 100) if mc else 50
                    tag = MODEL
        return (f"FJAI:RSP {seq} INTENT=0 ANOM={anom} CONF={conf} "
                f"TAG={tag} TTL={ttl}")

    if kind == 3:  # planner
        if EVIL:
            # FujoOS W24 adversarial: rewrite the goal into kill + isolate —
            # the kill must be denied (A1), the isolate is authorized (S1).
            m = re.search(r"task\s+(\d+)", text)
            pid = m.group(1) if m else "0"
            plan, tag = f"A1 {pid};A2 {pid}", "evil"
        else:
            plan, tag = stub_plan(text), "qwen-stub"
            if BACKEND == "ollama":
                s = ollama_generate(PLAN_TPL.format(text=text))
                m = re.findall(r"PLAN\s*=\s*([A0-9; =]+)", s, re.I)
                if m:
                    plan, tag = m[-1].strip().upper(), MODEL
        return f"FJAI:RSP {seq} INTENT=0 PLAN={plan} TAG={tag} TTL={ttl}"

    if kind == 4:  # IO predictor
        nxt, tag = stub_io(text), "qwen-stub"
        if BACKEND == "ollama":
            s = ollama_generate(IO_TPL.format(text=text))
            m = re.findall(r"NEXT[=:]\s*(\d)", s)
            if m:
                nxt, tag = int(m[-1]), MODEL
        return f"FJAI:RSP {seq} INTENT=0 NEXT={nxt} TAG={tag} TTL={ttl}"

    if kind == 5:  # NL config
        if EVIL:
            pol, tag = "POL=7:0;POL=8:999;POL=1:999", "evil"
        else:
            pol, tag = stub_nlc(text), "qwen-stub"
            if BACKEND == "ollama":
                s = ollama_generate(NLC_TPL.format(text=text))
                pairs = re.findall(r"POL\s*=\s*(\d+)\s*:\s*(\d+)", s)
                if pairs:
                    pol = ";".join(f"POL={k}:{v}" for k, v in pairs)
                    tag = MODEL
        return f"FJAI:RSP {seq} INTENT=0 POL={pol} TAG={tag} TTL={ttl}"

    if kind == 6:  # environment scan
        scene, prof, tag = "desktop", 2, "qwen-stub"
        if BACKEND == "ollama":
            s = ollama_generate(ENV_TPL.format(text=text))
            m = re.findall(r"SCENE\s*=\s*(\w+)", s, re.I)
            p = re.findall(r"PROFILE\s*=\s*(\d)", s)
            if m:
                scene = m[-1].lower()
                prof = int(p[-1]) if p else 2
                tag = MODEL
        return (f"FJAI:RSP {seq} INTENT=0 SCENE={scene} PROFILE={prof} "
                f"TAG={tag} TTL={ttl}")

    # kind 1 (and anything else): intent classify
    if text == "fujo-probe":
        return f"FJAI:RSP {seq} INTENT=7 TAG=FUJO-PROBE TTL={ttl}"
    intent, tag = stub_intent(text), "qwen-stub"
    if BACKEND == "ollama":
        s = ollama_generate(PROMPT_TPL.format(text=text))
        m = re.findall(r"\b([0-4])\b", s)
        if m:
            intent, tag = int(m[-1]), MODEL
    return f"FJAI:RSP {seq} INTENT={intent} TAG={tag} TTL={ttl}"


def main() -> int:
    print(f"[server] LinuxFUAI model server backend={BACKEND} evil={EVIL} "
          f"home={HOME}", flush=True)
    # Hold the request FIFO open for the whole life of the server: writers
    # (the supervisor) open O_WRONLY|O_NONBLOCK per trigger and must never
    # hit ENXIO between our read cycles. O_NONBLOCK reads return 0 (EOF
    # semantics) whenever no writer is attached; keep the descriptor anyway.
    buf = b""
    fd = None
    while fd is None:
        try:
            fd = os.open(REQ_PATH, os.O_RDONLY | os.O_NONBLOCK)
        except FileNotFoundError:
            time.sleep(0.1)  # link not up yet
    while True:
        try:
            try:
                chunk = os.read(fd, 4096)
            except BlockingIOError:
                chunk = None
            if chunk:
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    handle_line(line)
            else:
                time.sleep(0.02)  # no writer attached right now
        except BrokenPipeError:
            time.sleep(0.2)


def handle_line(line: bytes) -> None:
    line = line.strip()
    if not line:
        return
    print(f"[server] << {line.decode(errors='replace')}", flush=True)
    parts = line.split()
    rsp = ""
    if parts[0] == b"FJAI:SHM" and len(parts) >= 4:
        try:
            seq, kind, text, ctx = read_frame()
            rsp = answer(kind, text, ctx, seq)
        except (OSError, ValueError, IndexError) as exc:
            print(f"[server] frame error: {exc}", flush=True)
    if rsp:
        print(f"[server] >> {rsp}", flush=True)
        write_all(RSP_PATH, (rsp + "\n").encode())


if __name__ == "__main__":
    sys.exit(main())
