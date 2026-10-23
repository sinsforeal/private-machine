"""The P arm must not write transcript.jsonl (the harness driver owns it; both writing doubled every event)."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from harness.arm import Arm


class ArmTranscriptTest(unittest.TestCase):
    def test_arm_events_go_to_its_own_log_not_transcript(self):
        with tempfile.TemporaryDirectory(dir=r"F:\temp") as tmp:
            run_dir = Path(tmp)
            stub = SimpleNamespace(
                run_dir=run_dir,
                clock=SimpleNamespace(now=lambda: datetime(2026, 10, 26, 7, 10)),
                start_time=datetime(2026, 10, 26, 7, 0),
            )
            Arm._transcript(stub, {"virtual_ts": "x", "who": "him", "text": "hi"})
            self.assertFalse((run_dir / "transcript.jsonl").exists())
            lines = (run_dir / "logs" / "arm_events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(json.loads(lines[0])["text"], "hi")
            self.assertEqual(json.loads(lines[0])["sim_day"], 1)


if __name__ == "__main__":
    unittest.main()
