"""Permission-mode routing contracts for the edit graph.

These pin the exact seams that made accept_edits/full_access behave like
default: the validate node must dispatch a pre-approved apply (instead of
stopping for approval), and the router must send that pre-approved apply to
the apply node (instead of the approval interrupt).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import repooperator_worker.agent_core.graph  # noqa: F401
from repooperator_worker.agent_core.graph.nodes import edit as edit_nodes
from repooperator_worker.agent_core.graph.routes import route_after_change_plan
from repooperator_worker.agent_core.graph_state import action_to_snapshot, request_to_snapshot
from repooperator_worker.agent_core.actions import AgentAction
from repooperator_worker.schemas import AgentRunRequest


def _proposal_for(repo: Path) -> dict:
    original = (repo / "app.py").read_text(encoding="utf-8")
    proposed = original + "\n# trailer\n"
    return {
        "proposal_id": "proposal:test123",
        "plan": {"summary": "Add trailer comment", "target_files": ["app.py"], "operations": ["modify"]},
        "changes": [
            {
                "path": "app.py",
                "operation": "modify",
                "summary": "Add trailer",
                "original_content": original,
                "proposed_content": proposed,
            }
        ],
        "status": "valid",
    }


class ValidateNodeModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
        self.request = AgentRunRequest(project_path=str(self.repo), git_provider="local", branch="main", task="app.py에 주석 추가해줘")
        self.state = {
            "repo": str(self.repo),
            "branch": "main",
            "run_id": "run-mode-test",
            "request_snapshot": request_to_snapshot(self.request),
            "change_set_proposal": _proposal_for(self.repo),
            "action_results": [],
            "actions_taken": [],
            "user_task": self.request.task,
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_auto_mode_dispatches_preapproved_apply(self) -> None:
        with patch.object(edit_nodes, "_mode_auto_applies_edits", return_value=True):
            update = edit_nodes.validate_change_set_node(dict(self.state))
        self.assertIsNone(update.get("pending_approval"))
        self.assertNotEqual(update.get("stop_reason"), "waiting_approval")
        pending = update.get("pending_action") or {}
        self.assertEqual(pending.get("type"), "apply_change_set")
        decision = (pending.get("payload") or {}).get("approval_decision") or {}
        self.assertEqual(str(decision.get("decision")).lower(), "allow")

    def test_default_mode_stops_for_approval(self) -> None:
        with patch.object(edit_nodes, "_mode_auto_applies_edits", return_value=False):
            update = edit_nodes.validate_change_set_node(dict(self.state))
        self.assertEqual(update.get("stop_reason"), "waiting_approval")
        self.assertEqual((update.get("pending_approval") or {}).get("kind"), "change_set_apply")


class RouteAfterChangePlanTests(unittest.TestCase):
    def _state(self, pending_action: dict | None) -> dict:
        proposal = {
            "proposal_id": "proposal:test123",
            "changes": [{"path": "app.py", "operation": "modify"}],
            "status": "valid",
            "applied": False,
        }
        return {
            "change_set_proposal": proposal,
            "action_results": [],
            "proposal_errors": [],
            "repair_attempts": 0,
            "pending_action": pending_action,
        }

    def test_preapproved_apply_skips_interrupt(self) -> None:
        action = AgentAction(
            type="apply_change_set",
            reason_summary="mode-approved",
            payload={"proposal_id": "proposal:test123", "approval_decision": {"decision": "allow"}},
        )
        self.assertEqual(route_after_change_plan(self._state(action_to_snapshot(action))), "apply_change_set")

    def test_unapproved_proposal_goes_to_interrupt(self) -> None:
        self.assertEqual(route_after_change_plan(self._state(None)), "await_change_approval")


if __name__ == "__main__":
    unittest.main()
