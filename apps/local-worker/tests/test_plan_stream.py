"""Phase 4: structured live-plan items for the UI todo checklist."""

from __future__ import annotations

import unittest

from repooperator_worker.agent_core.graph.observation_support import _structured_plan_items
from repooperator_worker.agent_core.state import AgentCoreState, AgentSubtask


def _state(**overrides) -> AgentCoreState:
    state = AgentCoreState(run_id="r1", thread_id="t1", repo="/tmp/repo", branch=None, user_task="do it")
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


class StructuredPlanTests(unittest.TestCase):
    def test_uses_subtasks_with_status(self) -> None:
        state = _state(
            subtasks=[
                AgentSubtask(id="s1", title="Gather evidence", goal="read files", status="completed"),
                AgentSubtask(id="s2", title="Propose edit", goal="patch", status="running"),
                AgentSubtask(id="s3", title="Validate", goal="check", status="pending"),
            ]
        )
        plan = _structured_plan_items(state)
        self.assertEqual([p["status"] for p in plan], ["completed", "running", "pending"])
        self.assertEqual(plan[0]["title"], "Gather evidence")
        self.assertEqual(plan[1]["id"], "s2")

    def test_falls_back_to_plan_strings(self) -> None:
        state = _state(plan=["Completed: read_file", "Inspect repository tree"])
        plan = _structured_plan_items(state)
        self.assertEqual(plan[0]["status"], "completed")
        self.assertEqual(plan[1]["status"], "pending")
        self.assertEqual(plan[1]["title"], "Inspect repository tree")

    def test_empty_when_no_plan(self) -> None:
        self.assertEqual(_structured_plan_items(_state()), [])


if __name__ == "__main__":
    unittest.main()
