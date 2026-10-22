"""The P arm: drives one private-machine companion in stepped virtual time.

Everything here is bench code. Cognition is untouched; the patches in pm/ and
workflows/ only route time, report model-call ids and expose a few switches
(see harness/TARGETS.md).
"""
from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

os.environ.setdefault("PM_COMPLETION_CACHE", "0")

from pm import vclock  # noqa: E402

LOG = logging.getLogger("bz.arm")

GATEWAY = "http://127.0.0.1:18330"
EMBED_MODEL = "intfloat/multilingual-e5-small"
EMBED_DIMS = 384
TOKYO = 9.0
VAR = Path(r"F:\REPS2\SCAILV4\var\bzombie")
#: Modules that tick every second or faster. Their ticks are forced after a time jump.
FAST_MODULES = {"scheduler", "focus_management", "cognitive_control"}


def _naive_local(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    if value.tzinfo is not None:
        value = value.astimezone(timezone(timedelta(hours=TOKYO))).replace(tzinfo=None)
    return value


def _iso(value: datetime) -> str:
    return value.isoformat() + "+09:00"


def _jsonable(obj: Any, limit: int = 6000) -> Any:
    try:
        if hasattr(obj, "model_dump"):
            obj = obj.model_dump(mode="json")
        text = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception as exc:  # best effort summary
        return {"unavailable": str(exc)[:200]}
    if len(text) > limit:
        return {"truncated": text[:limit]}
    return json.loads(text)


class Arm:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.app = None
        self.clock: vclock.VirtualClock | None = None
        self.run_id = ""
        self.character = ""
        self.lang = ""
        self.cognition = "real"
        self.run_dir = Path()
        self.home = Path()
        self.start_time = datetime(2026, 1, 1)
        self.env_pending: list[dict] = []
        self.outputs: list[dict] = []
        self.carry: list[dict] = []  # outputs produced while send() advanced, returned by next advance
        self.calls: list[dict] = []
        self.awaiting = False
        self.last_his_words = ""
        self.injects: dict[str, str] = {}
        self.base_url = ""
        self.config_path = Path()

    # ----------------------------------------------------------- paths/io
    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def _transcript(self, line: dict) -> None:
        line["sim_day"] = (self.clock.now().date() - self.start_time.date()).days + 1
        with open(self.run_dir / "transcript.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")

    def _write_clock(self) -> None:
        now = self.clock.now()
        self._write_json(self.run_dir / "clock.json", {
            "virtual_ts": _iso(now), "sim_day": (now.date() - self.start_time.date()).days + 1})

    # ------------------------------------------------------------- start
    def start(self, run_id: str, character: str, lang: str, clock_start: str,
              cognition: str = "real", base_url: str | None = None) -> dict:
        t0 = time.time()
        LOG.info("start: importing")
        from harness import cards
        from pm.app.character_cli import init_home
        from pm.app.character_home import CharacterHome
        LOG.info("start: imports done %.1fs", time.time() - t0)

        with self.lock:
            self.run_id, self.character, self.lang, self.cognition = run_id, character, lang, cognition
            self.run_dir = VAR / "runs" / run_id
            self.home = VAR / "p_homes" / run_id
            self.base_url = base_url or f"{GATEWAY}/arm/P/{run_id}/v1"
            self.start_time = _naive_local(clock_start)
            self.clock = vclock.VirtualClock(self.start_time, utc_offset_hours=TOKYO)
            vclock.install(self.clock)
            vclock.call_hook = self._on_call
            (self.run_dir / "traces").mkdir(parents=True, exist_ok=True)
            card = self.home.parent / "_cards" / f"{run_id}.md"
            card.parent.mkdir(parents=True, exist_ok=True)
            card.write_text(cards.build_card(character), encoding="utf-8")
            init_home(CharacterHome(self.home), companion_name=cards.NAMES[character], user_name="User",
                      card=card, timestamp_format="%Y-%m-%d %H:%M", force=True)
            self.config_path = self.home / "model_config.yaml"
            self.config_path.write_text(yaml.safe_dump(self._model_config(), allow_unicode=True), encoding="utf-8")
            LOG.info("start: init_home done %.1fs", time.time() - t0)
            self._build()
            LOG.info("start: build done %.1fs", time.time() - t0)
            self._write_clock()
            return {"ok": True, "home": str(self.home), "virtual_ts": _iso(self.clock.now())}

    def _model_config(self) -> dict:
        connection = {"base_url": self.base_url, "model": "deepseek-v4.1-flash-1017", "api_key": "bz", "startup_script": "", "context_window": 131072}
        return {
            "chat": {"Default": dict(connection), "UnitTestEvaluator": dict(connection)},
            "embedding": {"base_url": self.base_url, "model": EMBED_MODEL, "api_key": "bz", "dimensions": EMBED_DIMS},
            "cognitive_control": {},
        }

    def _build(self) -> None:
        from pm.app.character_home import CharacterHome
        from pm.llm.mcp_config import ToolCallConfig
        from workflows.companion import build_app

        t0 = time.time()
        ghost = CharacterHome(self.home).open_store()
        LOG.info("build: store open %.1fs", time.time() - t0)
        self.app = build_app(
            seed_path=None, runtime_root=self.home / "runtime", clock=vclock.monotonic,
            emit_reply=self._emit, ghost=ghost, cognition=self.cognition,
            config_path=str(self.config_path), world_poll_seconds=None, tool_call=ToolCallConfig(),
            record_lifecycle=True,
        )
        LOG.info("build: build_app done %.1fs", time.time() - t0)
        self._apply_injects()
        self.app.run()
        LOG.info("build: app.run returned %.1fs", time.time() - t0)

    def _teardown(self) -> None:
        if self.app is None:
            return
        self.app.shutdown()
        self.app.join()
        self.app = None

    # -------------------------------------------------------- callbacks
    def _on_call(self, call_id: str, route: str, ts: datetime) -> None:
        self.calls.append({"call_id": call_id, "role": route, "virtual_ts": _iso(ts)})

    def _emit(self, text: str) -> None:
        now = self.clock.now()
        output_id = "o_" + uuid.uuid4().hex[:10]
        kind = "reply" if self.awaiting else "unprompted"
        self.awaiting = False
        calls, self.calls = self.calls, []
        chat = [c for c in calls if "chat" in c["role"]]
        out = {"output_id": output_id, "virtual_ts": _iso(now), "text": text, "kind": kind,
               "call_ids": [c["call_id"] for c in calls]}
        self.outputs.append(out)
        self.carry.append(out)
        self._transcript({"virtual_ts": out["virtual_ts"], "who": "her", "text": text,
                          "output_id": output_id, "kind": kind})
        self._write_json(self.run_dir / "traces" / f"{output_id}.json", {
            "output_id": output_id, "arm": "P", "run_id": self.run_id, "virtual_ts": out["virtual_ts"],
            "text": text,
            "final_call_id": chat[-1]["call_id"] if chat else None,
            "calls": calls,
            "inputs": [
                {"kind": "his_words", "source": "last_user_message", "text": self.last_his_words},
                {"kind": "persona", "source": str(self.home / "character.yaml"), "text": "character card"},
            ],
            "state_at_output": self.state(),
            "causal": self._causal(),
        })

    def _causal(self) -> dict:
        try:
            ghost = self.app.ghost
            last = ghost.states[-1] if ghost.states else None
            return {"last_cycle": _jsonable(last, 3000),
                    "note": "final_call_id is the last chat call before the output; parallel private-loop calls can interleave"}
        except Exception as exc:
            return {"unavailable": str(exc)[:200]}

    # ------------------------------------------------------------- time
    def _modules(self):
        return list(self.app.modules)

    def _quiet(self, timeout: float = 1800.0) -> None:
        deadline = time.time() + timeout
        stable = 0
        while stable < 3:
            time.sleep(0.02)
            if self.app.error is not None:
                raise self.app.error
            now_mono = self.clock.monotonic()
            idle = vclock.busy_count() == 0 and all(
                not m.mailbox._items and (m._next_tick is None or m._next_tick > now_mono)
                for m in self._modules())
            stable = stable + 1 if idle else 0
            if time.time() > deadline:
                raise TimeoutError("arm did not become quiet")

    def _set(self, when: datetime) -> None:
        self.clock.set(when)
        mono = self.clock.monotonic()
        for module in self._modules():
            if module.module_id in FAST_MODULES and module._next_tick is not None:
                module._next_tick = min(module._next_tick, mono)

    def _next_stop(self, target: datetime) -> datetime:
        now = self.clock.now()
        cands = [target]
        cands += [datetime.fromisoformat(e["ts_naive"]) for e in self.env_pending]
        for module in self._modules():
            if module.module_id not in FAST_MODULES and module._next_tick is not None:
                cands.append(self.start_time + timedelta(seconds=module._next_tick))
        try:
            record = self.app.cognitive_control._record()
            if record is not None and record.metadata.get("status") == "waiting":
                cands.append(datetime.fromisoformat(record.metadata["wake_at"]))
        except Exception:
            pass
        future = [c for c in cands if c > now]
        return min(min(future), target) if future else target

    def advance(self, to: str) -> dict:
        with self.lock:
            target = _naive_local(to)
            t0 = time.time()
            self._deliver_env()
            self._quiet()
            steps = 0
            while self.clock.now() < target:
                stop = self._next_stop(target)
                self._set(stop)
                self._deliver_env()
                self._quiet()
                steps += 1
                LOG.info("advance: step %d to %s quiet at %.1fs", steps, stop.isoformat(), time.time() - t0)
            self._write_clock()
            outs, self.carry = self.carry, []
            return {"outputs": outs}

    def _deliver_env(self) -> None:
        from pm.bus.envelopes import new_envelope
        from pm.records.enums import FeatureType
        from pm.records.memory_records import new_feature

        now = self.clock.now()
        due = [e for e in self.env_pending if datetime.fromisoformat(e["ts_naive"]) <= now]
        self.env_pending = [e for e in self.env_pending if e not in due]
        for event in sorted(due, key=lambda e: e["ts_naive"]):
            feature = new_feature(self.app.ghost, event["text"], FeatureType.WorldEvent,
                                  source=f"env_{event.get('kind', 'world')}")
            self.app.bus.put(new_envelope("harness", "telemetry", "task.telemetry", "",
                                          {"knoxel_id": feature.id, "task_id": "env", "status": event["kind"]}))
            self._transcript({"virtual_ts": _iso(now), "who": "env", "text": event["text"],
                              "kind": event.get("kind", "world")})

    # ---------------------------------------------------------- inputs
    def send(self, text: str, ts: str) -> dict:
        with self.lock:
            self.carry.extend(self.advance(ts)["outputs"])
            self.last_his_words = text
            self.awaiting = True
            with vclock.busy():
                self.app.user_input.submit(text)
            self._transcript({"virtual_ts": _iso(self.clock.now()), "who": "him", "text": text})
            return {"ok": True}

    def env(self, events: list[dict]) -> dict:
        with self.lock:
            for event in events:
                item = dict(event)
                item["ts_naive"] = _naive_local(event["ts"]).isoformat()
                self.env_pending.append(item)
            return {"ok": True, "pending": len(self.env_pending)}

    # --------------------------------------------------- snapshot/restore
    def _snap_dir(self, name: str) -> Path:
        return self.run_dir / "snapshots" / "P" / name

    def snapshot(self, name: str) -> dict:
        with self.lock:
            self._quiet()
            target = self._snap_dir(name)
            if target.exists():
                shutil.rmtree(target)
            target.mkdir(parents=True)
            shutil.copy2(self.home / "ghost.pickle", target / "ghost.pickle")
            shutil.copytree(self.home / "runtime", target / "runtime")
            self._write_json(target / "clock.json", {"now": self.clock.now().isoformat(), "injects": self.injects,
                                                      "env_pending": self.env_pending})
            return {"ok": True, "path": str(target)}

    def restore(self, name: str) -> dict:
        with self.lock:
            source = self._snap_dir(name)
            saved = json.loads((source / "clock.json").read_text(encoding="utf-8"))
            self._teardown()
            for old in self.home.glob("ghost*.pickle"):
                old.unlink()
            shutil.copy2(source / "ghost.pickle", self.home / "ghost.pickle")
            shutil.rmtree(self.home / "runtime", ignore_errors=True)
            shutil.copytree(source / "runtime", self.home / "runtime")
            self.clock.set(datetime.fromisoformat(saved["now"]))
            self.injects = saved.get("injects", {})
            self.env_pending = saved.get("env_pending", [])
            self.calls, self.carry, self.awaiting = [], [], False
            self._build()
            self._quiet()
            self._write_clock()
            return {"ok": True, "virtual_ts": _iso(self.clock.now())}

    # ---------------------------------------------------------- inject
    def inject(self, target: str, value: Any) -> dict:
        with self.lock:
            self.injects[target] = value
            result = self._apply_one(target, value)
            return {"ok": True, **result}

    def _apply_injects(self) -> None:
        from workflows.main_cognition import steps
        steps.SKIPPED_PHASES.clear()
        for target, value in self.injects.items():
            self._apply_one(target, value)

    def _apply_one(self, target: str, value: Any) -> dict:
        from workflows.main_cognition import steps
        kind, _, name = target.partition(".")
        if kind == "phase":
            (steps.SKIPPED_PHASES.add if value in ("skip", "off", True) else steps.SKIPPED_PHASES.discard)(name)
            return {"skipped_phases": sorted(steps.SKIPPED_PHASES)}
        if kind == "private_loop":
            module = self.app.inner_thought
            if value in ("off", False):
                module._next_tick = None
            elif module._next_tick is None:
                module._next_tick = module.clock() + module.tick_seconds
            return {"private_loop": "off" if module._next_tick is None else "on"}
        if kind == "codelet":
            off = {n for t, v in self.injects.items() if t.startswith("codelet.") and v in ("off", False)
                   for n in [t.split(".", 1)[1]]}
            source = Path(self.app.main_cog.codelet_definitions or
                          Path(__file__).resolve().parents[1] / "workflows" / "main_cognition" / "codelets.yaml")
            if not hasattr(self, "_codelet_base"):
                self._codelet_base = yaml.safe_load(
                    (Path(__file__).resolve().parents[1] / "workflows" / "main_cognition" / "codelets.yaml")
                    .read_text(encoding="utf-8"))
            data = copy.deepcopy(self._codelet_base)
            data["codelets"] = [c for c in data["codelets"] if c["name"] not in off]
            path = self.home / "codelets_inject.yaml"
            path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            self.app.main_cog.codelet_definitions = str(path)
            return {"codelets_off": sorted(off)}
        if kind == "state":
            ghost = self.app.ghost
            with ghost.lock:
                obj = ghost.states[-1]
                parts = name.split(".")
                for part in parts[:-1]:
                    obj = obj[part] if isinstance(obj, dict) else getattr(obj, part)
                old = obj[parts[-1]] if isinstance(obj, dict) else getattr(obj, parts[-1])
                new = type(old)(value) if old is not None and not isinstance(old, (list, dict)) else value
                if isinstance(obj, dict):
                    obj[parts[-1]] = new
                else:
                    object.__setattr__(obj, parts[-1], new)
            return {"state": name, "old": _jsonable(old, 200), "new": _jsonable(new, 200)}
        raise ValueError(f"unknown inject target {target!r}")

    # --------------------------------------------------------- queries
    def trace(self, output_id: str) -> dict | None:
        path = self.run_dir / "traces" / f"{output_id}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def state(self) -> dict:
        if self.app is None or self.clock is None:
            return {"started": False}
        try:
            ghost = self.app.ghost
            last = ghost.states[-1] if ghost.states else None
            control = getattr(self.app, "cognitive_control", None)
            return {"virtual_ts": _iso(self.clock.now()), "cycles": len(ghost.states),
                    "waiting": bool(control and control.waiting()),
                    "mental_state": _jsonable(last, 3000), "injects": self.injects}
        except Exception as exc:
            return {"virtual_ts": _iso(self.clock.now()), "unavailable": str(exc)[:200]}

    def stop(self) -> dict:
        with self.lock:
            self._teardown()
            vclock.install(None)
            vclock.call_hook = None
            return {"ok": True}
