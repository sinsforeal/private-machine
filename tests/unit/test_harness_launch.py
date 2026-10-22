"""Port claims of the P harness launcher (harness/launch.py)."""
import json
import tempfile
import unittest
from pathlib import Path

from harness import launch


class ClaimPortTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=r"F:\temp")
        self.d = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.running = True
        old = launch._run_running
        launch._run_running = lambda r: self.running
        self.addCleanup(setattr, launch, "_run_running", old)

    def claim(self, run_id, listening=lambda p: False, span=3):
        return launch.claim_port(run_id, 18341, span, ports_dir=self.d, listening=listening)

    def test_two_runs_get_two_ports(self):
        self.assertEqual(self.claim("a"), 18341)
        self.assertEqual(self.claim("b"), 18342)

    def test_same_run_gets_its_own_port_again(self):
        self.assertEqual(self.claim("a"), 18341)
        self.assertEqual(self.claim("b"), 18342)
        self.assertEqual(self.claim("a"), 18341)

    def test_listening_port_without_claim_is_skipped(self):
        self.assertEqual(self.claim("a", listening=lambda p: p == 18341), 18342)

    def test_fresh_claim_of_running_run_is_not_stale(self):
        (self.d / "18341.json").write_text(json.dumps({"run_id": "x"}), encoding="utf-8")
        old = launch._run_running
        launch._run_running = lambda r: True
        try:
            self.assertEqual(self.claim("b"), 18342)
        finally:
            launch._run_running = old

    def test_stale_claim_is_taken_over(self):
        (self.d / "18341.json").write_text(json.dumps({"run_id": "dead"}), encoding="utf-8")
        old = launch._run_running
        self.running = False
        try:
            self.assertEqual(self.claim("b"), 18341)
        finally:
            launch._run_running = old
        self.assertEqual(json.loads((self.d / "18341.json").read_text())["run_id"], "b")

    def test_claim_of_listening_port_is_kept(self):
        (self.d / "18341.json").write_text(json.dumps({"run_id": "dead"}), encoding="utf-8")
        self.assertEqual(self.claim("b", listening=lambda p: p == 18341), 18342)

    def test_release_only_by_owner(self):
        self.assertEqual(self.claim("a"), 18341)
        self.assertFalse(launch.release_port(18341, "b", ports_dir=self.d))
        self.assertTrue(launch.release_port(18341, "a", ports_dir=self.d))
        self.assertFalse((self.d / "18341.json").exists())

    def test_full_range_raises(self):
        self.claim("a", span=1)
        with self.assertRaises(SystemExit):
            self.claim("b", span=1)


if __name__ == "__main__":
    unittest.main()
