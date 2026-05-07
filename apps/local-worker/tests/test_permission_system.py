import sys
import tempfile
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from repooperator_worker.agent_core.permissions import PermissionMode, ToolPermissionContext  # noqa: E402
from repooperator_worker.agent_core.tools.builtin import GenerateEditTool, ReadFileTool, RunApprovedCommandTool  # noqa: E402
from repooperator_worker.schemas import AgentRunRequest  # noqa: E402


class PermissionSystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        (self.repo / "README.md").write_text("# Demo\n", encoding="utf-8")
        self.request = AgentRunRequest(project_path=str(self.repo), git_provider="local", branch="main", task="Test permissions")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _context(self, mode: PermissionMode = PermissionMode.DEFAULT) -> ToolPermissionContext:
        return ToolPermissionContext(request=self.request, run_id="run-permission", permission_mode=mode, active_repository=str(self.repo))

    def test_read_only_tool_allowed_in_plan_and_default(self) -> None:
        tool = ReadFileTool()
        self.assertEqual(tool.check_permission({}, self._context(PermissionMode.PLAN)).decision, "allow")
        self.assertEqual(tool.check_permission({}, self._context(PermissionMode.DEFAULT)).decision, "allow")

    def test_generate_edit_proposal_allowed_in_plan(self) -> None:
        decision = GenerateEditTool().check_permission({"target_files": ["README.md"]}, self._context(PermissionMode.PLAN))
        self.assertEqual(decision.decision, "allow")
        self.assertIn("proposal-only", decision.reason)

    def test_run_approved_command_allows_read_only_preview(self) -> None:
        decision = RunApprovedCommandTool().check_permission({"command": ["git", "status", "--short"]}, self._context())
        self.assertEqual(decision.decision, "allow")
        self.assertTrue(decision.metadata["command_preview"]["read_only"])

    def test_run_approved_command_asks_for_mutating_command(self) -> None:
        decision = RunApprovedCommandTool().check_permission({"command": ["git", "commit", "-m", "test"]}, self._context())
        self.assertEqual(decision.decision, "ask")
        self.assertTrue(decision.approval_id)
        self.assertTrue(decision.metadata["command_preview"]["needs_approval"])

    def test_bypass_mode_exists_but_does_not_bypass_command_policy(self) -> None:
        decision = RunApprovedCommandTool().check_permission({"command": ["git", "commit", "-m", "test"]}, self._context(PermissionMode.BYPASS))
        self.assertEqual(decision.decision, "ask")


if __name__ == "__main__":
    unittest.main()
