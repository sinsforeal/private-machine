"""Control server of the P arm: the contract's Arm control API on 127.0.0.1.

Run: python -m harness.server --port 18341 [--ticket-who scail/bz_p_<run_id>]
With --ticket-who the server takes a compute ticket from the limits manager
before it listens and releases it when it stops. Never binds anything but
127.0.0.1.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LIMITS_CLIENT = r"F:\REPS2\Meta_Orchestrator\tools\limits\client.py"
NO_WINDOW = 0x08000000


def make_handler(arm, shutdown):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep logs quiet
            pass

        def _send(self, code: int, body) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

        def do_GET(self):
            try:
                if self.path == "/control/state":
                    return self._send(200, arm.state())
                if self.path.startswith("/control/trace/"):
                    trace = arm.trace(self.path.rsplit("/", 1)[1])
                    return self._send(200 if trace else 404, trace or {"error": "no such output"})
                self._send(404, {"error": "not found"})
            except Exception as exc:
                self._send(500, {"error": str(exc)})

        def do_POST(self):
            try:
                data = self._body()
                route = self.path
                if route == "/control/start":
                    return self._send(200, arm.start(
                        data["run_id"], data["character"], data["lang"], data["clock_start"],
                        cognition=data.get("cognition", "real"), base_url=data.get("base_url")))
                if route == "/control/advance":
                    return self._send(200, arm.advance(data["to"]))
                if route == "/control/send":
                    return self._send(200, arm.send(data["text"], data["ts"]))
                if route == "/control/env":
                    return self._send(200, arm.env(data["events"]))
                if route == "/control/snapshot":
                    return self._send(200, arm.snapshot(data["name"]))
                if route == "/control/restore":
                    return self._send(200, arm.restore(data["name"]))
                if route == "/control/inject":
                    return self._send(200, arm.inject(data["target"], data["value"]))
                if route == "/control/stop":
                    result = arm.stop()
                    self._send(200, result)
                    threading.Thread(target=shutdown, daemon=True).start()
                    return None
                self._send(404, {"error": "not found"})
            except Exception as exc:
                traceback.print_exc()
                self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

    return Handler


def take_ticket(who: str, cpu: float, mem_gb: float) -> str:
    out = subprocess.run(
        [sys.executable, LIMITS_CLIENT, "wait", "--who", who, "--cpu", str(cpu), "--mem-gb", str(mem_gb),
         "--vram-mb", "0", "--host", "here", "--prio", "high", "--timeout", "3600"],
        capture_output=True, text=True, creationflags=NO_WINDOW)
    if out.returncode != 0:
        raise SystemExit(f"limits ticket failed rc={out.returncode}")
    return out.stdout.strip().split()[-1]


def release_ticket(ticket: str) -> None:
    subprocess.run([sys.executable, LIMITS_CLIENT, "release", ticket], capture_output=True,
                   creationflags=NO_WINDOW)


def serve(port: int, arm=None, ticket_who: str | None = None) -> None:
    from harness.arm import Arm

    arm = arm or Arm()
    ticket = take_ticket(ticket_who, 1.0, 1.5) if ticket_who else None
    httpd = None
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(arm, lambda: httpd.shutdown()))
        httpd.serve_forever()
    finally:
        try:
            arm.stop()
        except Exception:
            pass
        if ticket:
            release_ticket(ticket)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--ticket-who", default=None)
    args = parser.parse_args()
    serve(args.port, ticket_who=args.ticket_who)


if __name__ == "__main__":
    main()
