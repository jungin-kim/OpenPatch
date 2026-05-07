import sys
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from repooperator_worker.agent_core import controller_graph  # noqa: E402
from repooperator_worker.agent_core.planner import TaskFrame, validate_model_next_action  # noqa: E402
from repooperator_worker.agent_core.steering import SteeringDecision  # noqa: E402
from repooperator_worker.agent_core.state import AgentCoreState, ClassifierResult  # noqa: E402
from repooperator_worker.schemas import AgentRunRequest  # noqa: E402


class PlannerSteeringModuleTests(unittest.TestCase):
    def test_direct_and_compat_imports_exist(self) -> None:
        frame = TaskFrame(user_goal="Explain README.md", mentioned_files=["README.md"])
        decision = SteeringDecision(steering_type="defer")
        self.assertEqual(frame.mentioned_files, ["README.md"])
        self.assertEqual(decision.steering_type, "defer")
        self.assertIs(controller_graph.TaskFrame, TaskFrame)
        self.assertIs(controller_graph.SteeringDecision, SteeringDecision)

    def test_planner_validates_search_text_action_directly(self) -> None:
        request = AgentRunRequest(project_path=".", git_provider="local", branch="main", task="search text")
        state = AgentCoreState(run_id="run-planner", thread_id=None, repo=".", branch="main", user_task=request.task)
        state.classifier_result = ClassifierResult(intent="read_only_question", confidence=0.8)
        action = validate_model_next_action(
            {
                "action_type": "search_text",
                "reason_summary": "Search text safely.",
                "query": "foo|bar",
                "regex": True,
                "confidence": 0.9,
            },
            request,
            state,
            TaskFrame(user_goal=request.task),
        )
        self.assertIsNotNone(action)
        self.assertEqual(action.type, "search_text")
        self.assertTrue(action.payload["regex"])


if __name__ == "__main__":
    unittest.main()
