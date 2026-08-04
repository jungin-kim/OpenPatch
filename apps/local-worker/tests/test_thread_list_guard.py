"""P0: list_threads must not 500 on non-thread JSON in the threads dir."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


class ListThreadsGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name)
        (home / "config.json").write_text("{}", encoding="utf-8")
        self._prev = os.environ.get("REPOOPERATOR_CONFIG_PATH")
        os.environ["REPOOPERATOR_CONFIG_PATH"] = str(home / "config.json")
        self.addCleanup(self._restore_env)
        self.threads = home / "threads"
        self.threads.mkdir(parents=True, exist_ok=True)

    def _restore_env(self) -> None:
        if self._prev is None:
            os.environ.pop("REPOOPERATOR_CONFIG_PATH", None)
        else:
            os.environ["REPOOPERATOR_CONFIG_PATH"] = self._prev

    def _write(self, name: str, payload: object) -> None:
        (self.threads / name).write_text(json.dumps(payload), encoding="utf-8")

    def test_skips_queue_and_non_dict_json(self) -> None:
        from repooperator_worker.services.thread_service import list_threads

        # A valid thread.
        self._write(
            "t1.json",
            {
                "id": "t1",
                "title": "Chat one",
                "repo": {"project_path": "o/r", "git_provider": "github", "local_repo_path": "/tmp/o/r", "branch": "main"},
                "messages": [],
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        )
        # The coordinator's queue.json is a LIST and previously caused a 500.
        self._write("queue.json", [{"id": "q1", "status": "queued"}])
        # A context sidecar (dict, but not a ThreadSummary).
        self._write("t1.context.json", {"context": "stuff"})
        # A stray non-dict json.
        self._write("weird.json", ["not", "a", "thread"])

        result = list_threads()
        ids = [t.id for t in result.threads]
        self.assertEqual(ids, ["t1"])  # only the real thread, no crash


if __name__ == "__main__":
    unittest.main()
