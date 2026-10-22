"""Control server of the P arm: the contract's Arm control API on 127.0.0.1.

Run: python -m harness.server --port 18341 [--ticket-who scail/bz_p_<run_id>]
With --ticket-who the server takes a compute ticket from the limits manager
before it listens and releases it when it stops. Never binds anything but
127.0.0.1.
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LIMITS_CLIENT = r"F:\REPS2\Meta_Orchestrator\tools\limits\client.py"
NO_WINDOW = 0x08000000


LOG = logging.getLogger("bz.server")


def setup_logging(path: str | None) -> None:
    handlers = [logging.FileHandler(path, encoding="utf-8")] if path else [logging.StreamHandler()]
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True,
                        format="%(asctime)s %(threadName)s %(name)s %(message)s")


def make_handler(arm, shutdown):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep logs quiet
            pass

        def handle_one_request(self):
            try:
                super().handle_one_request()
            except Exception:
                LOG.exception("request crashed")


        def _send(self, code: int, body) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            LOG.info("OUT %s %s %.1fs %s", code, self.path, time.time() - getattr(self, "_t0", time.time()),
                     data[:300].decode("utf-8", "replace"))
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

        def do_GET(self):
            self._t0 = time.time()
            if self.path != "/control/state":
                LOG.info("IN GET %s", self.path)
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
            self._t0 = time.time()
            try:
                data = self._body()
                route = self.path
                LOG.info("IN POST %s %s", route, json.dumps(data, ensure_ascii=False)[:300])
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
                if type(exc).__name__ == "BadRequest":  # harness.arm.BadRequest, imported lazily
                    LOG.info("bad request: %s", exc)
                    return self._send(400, {"error": str(exc)})
                LOG.exception("handler error")
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


def serve(port: int, arm=None, ticket_who: str | None = None, run_id: str | None = None) -> None:
    from harness.arm import Arm

    arm = arm or Arm()
    LOG.info("server boot port=%s ticket_who=%s", port, ticket_who)
    ticket = take_ticket(ticket_who, 1.0, 1.5) if ticket_who else None
    LOG.info("ticket %s", ticket)
    httpd = None
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(arm, lambda: httpd.shutdown()))
        httpd.daemon_threads = True
        LOG.info("listening")
        httpd.serve_forever()
    finally:
        LOG.info("server stopping")
        try:
            arm.stop()
        except Exception:
            pass
        if ticket:
            release_ticket(ticket)
        if run_id:
            from harness.launch import release_port
            release_port(port, run_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--ticket-who", default=None)
    parser.add_argument("--log-file", default=None)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()
    setup_logging(args.log_file)
    serve(args.port, ticket_who=args.ticket_who, run_id=args.run_id)


if __name__ == "__main__":
    main()
