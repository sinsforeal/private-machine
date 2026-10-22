"""Hidden launcher of one P arm control server.

    python -m harness.launch <run_id> [port]

Starts ``pythonw -m harness.server`` with no window (CREATE_NO_WINDOW). The
server takes the compute ticket (who scail/bz_p_<run_id>) itself and releases
it on /control/stop. Prints the port. Ports 18341-18349 only.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = Path(r"F:\REPS2\SCAILV4\var\bzombie\runs")
NO_WINDOW = 0x08000000


def free_port() -> int:
    for port in range(18341, 18350):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit("no free P control port in 18341-18349")


def launch(run_id: str, port: int | None = None) -> int:
    port = port or free_port()
    log_dir = RUNS / run_id / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    env = {**os.environ, "TEMP": r"F:\temp", "TMP": r"F:\temp", "PM_COMPLETION_CACHE": "0",
           "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1"}
    log = open(log_dir / "p_server.log", "ab")
    subprocess.Popen([str(pythonw), "-m", "harness.server", "--port", str(port),
                      "--ticket-who", f"scail/bz_p_{run_id}"],
                     cwd=str(ROOT), env=env, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                     creationflags=NO_WINDOW)
    return port


if __name__ == "__main__":
    print(launch(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None))
