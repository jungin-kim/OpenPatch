"""'Approve and don't ask again for this session' must actually stop re-prompting.

The session approval was stored by run_command_with_policy but the permission
gate (preview via _classify_command) never consulted it, so the approval card
reappeared for the same command every time. The preview now honors a matching
session approval.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from repooperator_worker.services import command_service as cs  # noqa: E402


class CommandSessionApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        cs._SESSION_APPROVALS.clear()
        self.repo = tempfile.mkdtemp()

    def tearDown(self) -> None:
        cs._SESSION_APPROVALS.clear()

    def _remember(self, preview: dict) -> None:
        cs._SESSION_APPROVALS[preview["approval_id"]] = {
            "id": preview["approval_id"],
            "repo": preview["cwd"],
            "pattern": preview["pattern"],
            "risk": preview["risk"],
            "created_at": 0,
        }

    def test_session_approval_suppresses_reprompt(self) -> None:
        first = cs.preview_command(["npm", "test"], project_path=self.repo)
        self.assertTrue(first["needs_approval"], "npm test should need approval initially")
        self._remember(first)  # user picked "don't ask again for this session"
        again = cs.preview_command(["npm", "test"], project_path=self.repo)
        self.assertFalse(again["needs_approval"], "remembered command must not re-prompt")

    def test_different_command_still_asks(self) -> None:
        first = cs.preview_command(["npm", "test"], project_path=self.repo)
        self._remember(first)
        other = cs.preview_command(["npm", "run", "build"], project_path=self.repo)
        self.assertTrue(other["needs_approval"], "a different command must still ask")


if __name__ == "__main__":
    unittest.main()
