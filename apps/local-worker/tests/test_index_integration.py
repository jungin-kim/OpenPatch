"""Integration tests: the index-backed search tools keep their return shapes,
and the initial context pack routes query-relevant selection through the index.

Each test uses a unique temp repo (so the process-level index handle cache keys
on a fresh repo hash) and points the index storage at a temp home directory.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _write(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class IndexIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        self._patch = mock.patch(
            "repooperator_worker.services.common.get_repooperator_home_dir",
            return_value=self.home,
        )
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def test_find_file_candidates_shape(self) -> None:
        from repooperator_worker.agent_core.tools.builtin import find_file_candidates

        _write(self.repo, "pkg/payments.py", "def charge_card():\n    return True\n")
        results = find_file_candidates(self.repo, ["payments.py"], text_queries=[], max_results=5)
        self.assertTrue(results)
        top = results[0]
        self.assertEqual(set(top.keys()), {"path", "score", "reasons", "matched_queries"})
        self.assertEqual(top["path"], "pkg/payments.py")
        self.assertIsInstance(top["reasons"], list)
        self.assertIsInstance(top["matched_queries"], list)

    def test_search_text_matches_shape(self) -> None:
        from repooperator_worker.agent_core.tools.builtin import search_text_matches

        _write(self.repo, "svc.py", "alpha\ndef target():\n    return 2\n")
        matches, files_searched, truncated = search_text_matches(
            self.repo, query="def target", path_globs=[], max_results=10,
            case_sensitive=False, regex=False, context_lines=1,
        )
        self.assertIsInstance(files_searched, int)
        self.assertIsInstance(truncated, bool)
        self.assertTrue(matches)
        self.assertEqual(
            set(matches[0].keys()), {"path", "line", "column", "preview", "before", "after"}
        )
        self.assertEqual(matches[0]["path"], "svc.py")
        self.assertEqual(matches[0]["line"], 2)

    def test_search_text_invalid_regex_returns_error_shape(self) -> None:
        from repooperator_worker.agent_core.tools.builtin import search_text_matches

        _write(self.repo, "svc.py", "content\n")
        matches, files_searched, truncated = search_text_matches(
            self.repo, query="(unterminated", path_globs=[], max_results=10,
            case_sensitive=False, regex=True, context_lines=0,
        )
        self.assertEqual(files_searched, 0)
        self.assertFalse(truncated)
        self.assertTrue(matches and "Invalid regex" in matches[0]["preview"])

    def test_retrieve_context_general_routes_through_index(self) -> None:
        from repooperator_worker.services.retrieval_service import retrieve_context

        # A task-relevant file plus noise; a general (non-file-specific) query
        # should surface the relevant file via index ranking.
        _write(self.repo, "auth/session_manager.py", "def rotate_session_token():\n    return 'ok'\n")
        _write(self.repo, "misc/unrelated.py", "x = 1\n")
        _write(self.repo, "misc/other.py", "y = 2\n")

        result = retrieve_context(self.repo, "how does rotate_session_token work in the session manager")
        files = result.files_read
        self.assertTrue(files, "expected index-ranked files")
        self.assertIn("auth/session_manager.py", files)


if __name__ == "__main__":
    unittest.main()
