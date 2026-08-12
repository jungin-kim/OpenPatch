"""upsert_thread must not 500 on a malformed on-disk record (0.22.0).

A top-level JSON list persisted at a thread path made ThreadSummary(**raw) raise
TypeError, which escaped the except tuple and 500'd POST /threads. upsert now
requires a mapping and swallows TypeError, overwriting the bad record.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from repooperator_worker.schemas.requests import ThreadUpsertRequest  # noqa: E402
from repooperator_worker.services import thread_service as ts  # noqa: E402


def _request(thread_id: str = "t-1") -> ThreadUpsertRequest:
    return ThreadUpsertRequest(
        id=thread_id,
        title="Test thread",
        repo={"project_path": "o/r", "git_provider": "github", "local_repo_path": "/tmp/o/r", "branch": "main"},
        messages=[],
        created_at="2026-08-12T00:00:00Z",
        updated_at="2026-08-12T00:00:00Z",
    )


class ThreadUpsertRobustnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        (self.home / "threads").mkdir()
        self._patch = mock.patch.object(ts, "get_repooperator_home_dir", return_value=self.home)
        self._patch.start()
        assert self.home in ts._thread_path("x").parents  # isolation guard

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def test_malformed_list_record_is_overwritten_not_500(self) -> None:
        req = _request("t-list")
        # Persist a malformed top-level JSON *list* at the thread path.
        ts._thread_path(req.id).write_text(json.dumps(["not", "a", "mapping"]), encoding="utf-8")
        result = ts.upsert_thread(req)  # must not raise
        self.assertEqual(result.id, "t-list")
        # File is now a valid mapping.
        on_disk = json.loads(ts._thread_path(req.id).read_text(encoding="utf-8"))
        self.assertIsInstance(on_disk, dict)
        self.assertEqual(on_disk["id"], "t-list")

    def test_valid_newer_existing_record_is_preserved(self) -> None:
        req = _request("t-keep")
        newer = req.model_dump()
        newer["updated_at"] = "2999-01-01T00:00:00Z"
        newer["title"] = "Newer title"
        ts._thread_path(req.id).write_text(json.dumps(newer), encoding="utf-8")
        result = ts.upsert_thread(req)
        self.assertEqual(result.title, "Newer title")  # existing newer record wins


if __name__ == "__main__":
    unittest.main()
