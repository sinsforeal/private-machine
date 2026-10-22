"""End-to-end check through the control API.

    python -m harness.e2e dummy        # dummy cognition, no model calls
    python -m harness.e2e live         # real cognition through the gateway, cap 0.20 USD

Sequence: start Tomoe at a virtual time, send a message, advance until a
reply, fetch its trace, snapshot, advance, restore, check the clock.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

from harness.launch import RUNS, launch


def call(port: int, method: str, path: str, body: dict | None = None, timeout: float = 60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main(mode: str) -> int:
    run_id = f"bz_p_e2e_{mode}_{int(time.time()) % 100000}"
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(json.dumps({
        "run_id": run_id, "arm": "P", "character": "tomoe", "lang": "en", "model": "deepseek-v4.1-flash-1017",
        "cap_usd": 0.20, "sim_days": 1, "clock_start": "2026-10-23T09:00:00+09:00", "seed": 1,
        "status": "running"}), encoding="utf-8")
    port = launch(run_id)
    try:
        return run(mode, run_id, run_dir, port)
    finally:
        try:
            call(port, "POST", "/control/stop", {}, timeout=30)
        except Exception:
            pass


def run(mode: str, run_id: str, run_dir: Path, port: int) -> int:
    for _ in range(120):
        try:
            call(port, "GET", "/control/state", timeout=2)
            break
        except Exception:
            time.sleep(1)
    wall = time.time()
    print("start", call(port, "POST", "/control/start", {
        "run_id": run_id, "character": "tomoe", "lang": "en", "clock_start": "2026-10-23T09:00:00+09:00",
        "cognition": "dummy" if mode == "dummy" else "real"}))
    print("advance", call(port, "POST", "/control/advance", {"to": "2026-10-23T09:05:00+09:00"})["outputs"][:1])
    call(port, "POST", "/control/env", {"events": [{"ts": "2026-10-23T09:06:00+09:00", "kind": "world",
                                                    "text": "Her first lecture ends and she walks to the cafeteria.",
                                                    "source": "env_script/1"}]})
    call(port, "POST", "/control/send", {"text": "hey, how was your morning?", "ts": "2026-10-23T09:10:00+09:00"})
    reply = None
    now = 10
    send_wall = time.time()
    while reply is None and now < 120:
        now += 5
        outs = call(port, "POST", "/control/advance", {"to": f"2026-10-23T{9 + now // 60:02d}:{now % 60:02d}:00+09:00"})["outputs"]
        replies = [o for o in outs if o["kind"] == "reply"]
        reply = replies[0] if replies else None
    print("reply", reply)
    if reply is None:
        return 1
    reply_wall = time.time() - send_wall
    trace = call(port, "GET", f"/control/trace/{reply['output_id']}")
    print("trace keys", sorted(trace), "calls", len(trace["calls"]))
    call(port, "POST", "/control/snapshot", {"name": "s1"})
    before = json.loads((run_dir / "clock.json").read_text())["virtual_ts"]
    call(port, "POST", "/control/advance", {"to": "2026-10-23T12:00:00+09:00"}, timeout=900)
    mid = json.loads((run_dir / "clock.json").read_text())["virtual_ts"]
    call(port, "POST", "/control/restore", {"name": "s1"})
    after = json.loads((run_dir / "clock.json").read_text())["virtual_ts"]
    print("clock before/mid/after", before, mid, after, "restore_ok", before == after and mid != after)
    print("inject", call(port, "POST", "/control/inject", {"target": "phase.attention", "value": "skip"}))
    print("inject", call(port, "POST", "/control/inject", {"target": "private_loop", "value": "off"}))
    call(port, "POST", "/control/stop", {})
    print("wall_total_s", round(time.time() - wall, 1), "reply_wall_s", round(reply_wall, 1),
          "calls_per_reply", len(trace["calls"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "dummy"))
