import sys
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from repooperator_worker.agent_core import controller_graph  # noqa: E402
from repooperator_worker.agent_core.planner import TaskFrame  # noqa: E402
from repooperator_worker.agent_core.steering import SteeringDecision  # noqa: E402


class PlannerSteeringModuleTests(unittest.TestCase):
    def test_direct_and_compat_imports_exist(self) -> None:
        frame = TaskFrame(user_goal="Explain README.md", mentioned_files=["README.md"])
        decision = SteeringDecision(steering_type="defer")
        self.assertEqual(frame.mentioned_files, ["README.md"])
        self.assertEqual(decision.steering_type, "defer")
        self.assertIs(controller_graph.TaskFrame, TaskFrame)
        self.assertIs(controller_graph.SteeringDecision, SteeringDecision)


if __name__ == "__main__":
    unittest.main()
