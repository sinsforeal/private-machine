"""End-to-end check through the control API.

    python -m harness.e2e dummy        # dummy cognition, no model calls
    python -m harness.e2e live         # real cognition through the gateway, cap 0.20 USD

Sequence: start Tomoe at a virtual time, send a message, advance until a
reply, fetch its trace, snapshot, advance, restore, check the clock.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from harness.launch import RUNS, launch


def call(port: int, method: str, path: str, body: dict | None = None, timeout: float = 60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


STAMP = re.compile(r"^\s*\[[A-Z][a-z]{2}[ ,]+\d{1,2}:\d{2}\]", re.M)


def run_live(run_id: str, run_dir: Path, port: int) -> int:
    """Momoka, Japanese, real cognition through the gateway: per-reply numbers."""
    for _ in range(120):
        try:
            call(port, "GET", "/control/state", timeout=2)
            break
        except Exception:
            time.sleep(1)
    t = time.time()
    print("start", call(port, "POST", "/control/start", {
        "run_id": run_id, "character": "momoka", "lang": "ja", "clock_start": "2026-10-23T21:30:00+09:00",
        "cognition": "real"}, timeout=300), "wall", round(time.time() - t, 1))
    call(port, "POST", "/control/env", {"events": [{
        "ts": "2026-10-23T21:30:30+09:00", "kind": "pc", "text": "Window title: YouTube - Google Chrome",
        "source": "env_script/1"}]})

    def gateway_calls() -> list[dict]:
        path = run_dir / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

    summary = []
    turns = [("2026-10-23T21:31:00+09:00", "ただいま。バイト長引いてさ、疲れた"),
             ("2026-10-23T21:50:00+09:00", "今日の夜ごはん何にしようかな")]
    for ts, text in turns:
        n_before = len(gateway_calls())
        wall0 = time.time()
        call(port, "POST", "/control/send", {"text": text, "ts": ts}, timeout=1700)
        base = datetime.fromisoformat(ts)
        reply = None
        minutes = 0
        while reply is None and minutes < 10:
            minutes += 1
            to = (base + timedelta(minutes=minutes)).isoformat()
            outs = call(port, "POST", "/control/advance", {"to": to}, timeout=1700)["outputs"]
            reply = next((o for o in outs if o["kind"] == "reply"), None)
        wall = time.time() - wall0
        row = {"him": text, "send_ts": ts, "wall_s": round(wall, 1)}
        if reply:
            by_id = {c["call_id"]: c for c in gateway_calls()}
            mine = [by_id[i] for i in reply["call_ids"] if i in by_id]
            row.update(reply_ts=reply["virtual_ts"], text=reply["text"],
                       virtual_s=(datetime.fromisoformat(reply["virtual_ts"]) - base).total_seconds(),
                       calls_linked=len(reply["call_ids"]),
                       gateway_calls_since_send=len(gateway_calls()) - n_before,
                       cost_usd_linked=round(sum(c.get("cost_micro") or 0 for c in mine) / 1e6, 6),
                       cost_usd_since_send=round(sum(c.get("cost_micro") or 0
                                                     for c in gateway_calls()[n_before:]) / 1e6, 6),
                       stamp_line=bool(STAMP.search(reply["text"])))
        else:
            row["reply"] = None
        summary.append(row)
        print("ROW", json.dumps(row, ensure_ascii=False))
        if not reply:
            break
    status = call(18330, "GET", "/status", timeout=10)["runs"].get(run_id, {})
    print("gateway run", json.dumps(status, ensure_ascii=False)[:400])
    print("replies", len(summary))
    return 0 if all("text" in r for r in summary) else 1


def main(mode: str) -> int:
    run_id = f"bz_p_e2e_{mode}_{int(time.time()) % 100000}"
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    live = mode == "live"
    (run_dir / "config.json").write_text(json.dumps({
        "run_id": run_id, "arm": "P", "character": "momoka" if live else "tomoe", "lang": "ja" if live else "en",
        "model": "deepseek-v4.1-flash-1017",
        "cap_usd": 0.20, "sim_days": 1, "clock_start": "2026-10-23T09:00:00+09:00", "seed": 1,
        "status": "running"}), encoding="utf-8")
    port = launch(run_id)
    try:
        if live:
            return run_live(run_id, run_dir, port)
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
