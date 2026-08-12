"""Scale guards for the run store (0.20.0).

get_active_runs used to read and JSON-parse every historical run's meta.json on
each call — and it is polled by the UI — so as run history grew the endpoint
took tens of seconds and blew the web proxy timeout ("Worker unavailable"). It
now bounds the scan to the freshest runs, and prune_run_history keeps the dir
small. These tests lock in the bound + prune behaviour (correctness, not timing).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from repooperator_worker.services import event_service as es  # noqa: E402


def _write_run(runs_dir: Path, run_id: str, status: str, *, age_s: float = 0.0) -> Path:
    from datetime import datetime, timezone

    d = runs_dir / run_id
    d.mkdir(parents=True, exist_ok=True)
    # Recent started_at so waiting_approval runs are not TTL-expired by the scan.
    meta = {
        "id": run_id,
        "run_id": run_id,
        "status": status,
        "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    meta_path = d / "meta.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    if age_s:
        old = time.time() - age_s
        os.utime(meta_path, (old, old))
        os.utime(d, (old, old))
    return d


class RunStoreScaleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.runs = self.home / "runs"
        self.runs.mkdir()
        # Patch the exact function the store uses to locate the runs dir, so
        # get_active_runs/prune can NEVER touch the real ~/.repooperator/runs.
        self._patch = mock.patch.object(es, "_runs_dir", return_value=self.runs)
        self._patch.start()
        # Hard safety guard: refuse to run destructive tests unless the store is
        # provably the temp dir (a broken patch must fail loudly, never delete
        # real data).
        resolved = es._runs_dir().resolve()
        assert resolved == self.runs.resolve(), f"runs dir not isolated: {resolved}"
        assert str(resolved).startswith(tempfile.gettempdir()) or self._tmp.name in str(resolved)

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def test_get_active_runs_finds_fresh_active_among_many_completed(self) -> None:
        # Many old completed runs + a couple of fresh active/waiting ones.
        for i in range(400):
            _write_run(self.runs, f"run_done_{i:04d}", "completed", age_s=10_000 + i)
        _write_run(self.runs, "run_live_a", "running", age_s=1)
        _write_run(self.runs, "run_live_b", "waiting_approval", age_s=2)

        active = es.get_active_runs()
        ids = {r.get("id") for r in active}
        self.assertEqual(ids, {"run_live_a", "run_live_b"})

    def test_prune_keeps_recent_and_never_deletes_active(self) -> None:
        for i in range(300):
            _write_run(self.runs, f"run_done_{i:04d}", "completed", age_s=10_000 + i)
        # An old still-waiting run must survive pruning regardless of age.
        _write_run(self.runs, "run_old_waiting", "waiting_approval", age_s=999_999)

        pruned = es.prune_run_history(keep=50)
        self.assertGreater(pruned, 0)

        remaining = {p.parent.name for p in self.runs.glob("*/meta.json")}
        self.assertIn("run_old_waiting", remaining, "active/waiting run must never be pruned")
        # Dir is bounded: kept ~50 completed + the preserved waiting run.
        self.assertLessEqual(len(remaining), 60)

    def test_prune_noop_when_under_keep(self) -> None:
        for i in range(10):
            _write_run(self.runs, f"run_done_{i:04d}", "completed")
        self.assertEqual(es.prune_run_history(keep=200), 0)
        self.assertEqual(len(list(self.runs.glob("*/meta.json"))), 10)


if __name__ == "__main__":
    unittest.main()
