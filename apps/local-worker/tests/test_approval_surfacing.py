"""Contract tests: every approval pause surfaces an actionable UI payload (0.21.0).

The network-approval bug was that a paused run carried a pending_approval the UI
could not render (no command_approval / git_approval, response_type unset), so
the user could neither approve nor deny. These tests lock the worker-side
contract that _workflow_response_updates emits a decision payload for each kind.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from repooperator_worker.agent_core.graph.nodes import finalization  # noqa: E402


def _updates_for(pending: dict) -> dict:
    return finalization._workflow_response_updates({"pending_approval": pending})


class ApprovalSurfacingTests(unittest.TestCase):
    def test_fetch_url_surfaces_command_approval_card(self) -> None:
        updates = _updates_for(
            {"kind": "fetch_url", "approval_payload": {"url": "https://github.com/o/r"}, "reason": "Network access requires approval."}
        )
        self.assertEqual(updates["response_type"], "command_approval")
        card = updates["command_approval"]
        self.assertTrue(card)
        self.assertTrue(card["needs_network"])
        self.assertIn("github.com/o/r", card["display_command"])
        self.assertEqual(card["options"], ["yes", "no_explain"])
        self.assertTrue(updates["response"])  # human-facing text present

    def test_search_web_surfaces_command_approval_card(self) -> None:
        updates = _updates_for({"kind": "search_web", "approval_payload": {"query": "langgraph interrupts"}})
        self.assertEqual(updates["response_type"], "command_approval")
        self.assertIn("langgraph interrupts", updates["command_approval"]["display_command"])

    def test_git_branch_create_now_surfaces_approval(self) -> None:
        updates = _updates_for({"kind": "git_branch_create", "branch": "feature/x"})
        self.assertEqual(updates["response_type"], "git_approval")
        self.assertTrue(updates["command_approval"])
        self.assertIn("feature/x", " ".join(updates["command_approval"]["command"]))

    def test_git_commit_still_surfaces(self) -> None:
        updates = _updates_for({"kind": "git_commit", "message": "fix: thing"})
        self.assertEqual(updates["response_type"], "git_approval")
        self.assertTrue(updates["command_approval"])

    def test_no_pending_no_approval_fields(self) -> None:
        updates = finalization._workflow_response_updates({})
        self.assertNotIn("command_approval", updates)
        self.assertNotIn("git_approval", updates)


if __name__ == "__main__":
    unittest.main()
