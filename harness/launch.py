"""Hidden launcher of one P arm control server.

    python -m harness.launch <run_id> [port]

Starts ``pythonw -m harness.server`` with no window (CREATE_NO_WINDOW). The
server takes the compute ticket (who scail/bz_p_<run_id>) itself and releases
it on /control/stop. Prints the port. Ports 18341-18349 only.

The port is claimed through a file per port (var/bzombie/ports/<port>.json),
same format as bzombie/harness/driver.py claim_port, so two launches never
get the same port and S and P claims never collide.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = Path(r"F:\REPS2\SCAILV4\var\bzombie\runs")
PORTS = Path(r"F:\REPS2\SCAILV4\var\bzombie\ports")
NO_WINDOW = 0x08000000
GRACE_S = 120  # a claim younger than this is not stale: the server is still booting (ticket wait, imports)


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _run_running(run_id: str) -> bool:
    for name in ("state.json", "config.json"):
        st = _read(RUNS / str(run_id) / name) or {}
        if st.get("status"):
            return st["status"] == "running"
    return False


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def claim_port(run_id: str, base: int = 18341, span: int = 9, ports_dir: Path | None = None,
               listening=_listening) -> int:
    """Ours when the claim's run_id matches. Stale when nothing listens and its run is not running (or the claim is
    past the boot grace). A fresh claim is created with O_EXCL so two launches cannot take the same port."""
    d = ports_dir or PORTS
    d.mkdir(parents=True, exist_ok=True)
    for p in range(base, base + span):
        f = d / f"{p}.json"
        held = _read(f)
        if held and held.get("run_id") == run_id:
            return p
        if held:
            age = time.time() - f.stat().st_mtime if f.exists() else 1e9
            if listening(p) or (_run_running(held.get("run_id", "?")) and age < GRACE_S):
                continue
            f.write_text(json.dumps({"run_id": run_id, "claimed": _now(), "took_over": held.get("run_id")}),
                         encoding="utf-8")
            if (_read(f) or {}).get("run_id") == run_id:
                return p
            continue
        if f.exists() or listening(p):  # unreadable claim (mid-write) or an unclaimed listener
            continue
        try:
            fd = os.open(str(f), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"run_id": run_id, "claimed": _now()}))
        return p
    raise SystemExit(f"no free P control port in {base}..{base + span - 1}")


def release_port(port: int, run_id: str, ports_dir: Path | None = None) -> bool:
    f = (ports_dir or PORTS) / f"{port}.json"
    if (_read(f) or {}).get("run_id") == run_id:
        try:
            f.unlink()
            return True
        except OSError:
            pass
    return False


def launch(run_id: str, port: int | None = None) -> int:
    port = port or claim_port(run_id)
    log_dir = RUNS / run_id / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    env = {**os.environ, "TEMP": r"F:\temp", "TMP": r"F:\temp", "PM_COMPLETION_CACHE": "0",
           "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1"}
    log = open(log_dir / "p_server.log", "ab")
    subprocess.Popen([str(pythonw), "-m", "harness.server", "--port", str(port),
                      "--ticket-who", f"scail/bz_p_{run_id}", "--run-id", run_id,
                      "--log-file", str(log_dir / "p_control.log")],
                     cwd=str(ROOT), env=env, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                     creationflags=NO_WINDOW)
    return port


if __name__ == "__main__":
    print(launch(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None))
