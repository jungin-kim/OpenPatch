import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from repooperator_worker.agent_core.actions import AgentAction  # noqa: E402
from repooperator_worker.agent_core.hooks import HookEvent, HookManager, HookResult  # noqa: E402
from repooperator_worker.agent_core.permissions import PermissionDecision, ToolPermissionContext  # noqa: E402
from repooperator_worker.agent_core.tool_orchestrator import ToolOrchestrator  # noqa: E402
from repooperator_worker.agent_core.tools.base import BaseTool, ToolExecutionContext, ToolResult, ToolSpec  # noqa: E402
from repooperator_worker.agent_core.tools.registry import ToolRegistry, get_default_tool_registry  # noqa: E402
from repooperator_worker.schemas import AgentRunRequest  # noqa: E402


class ToolOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        (self.repo / "README.md").write_text("# Demo\n", encoding="utf-8")
        (self.repo / "cache.sqlite").write_bytes(b"SQLite format 3\x00binary")
        self.request = AgentRunRequest(project_path=str(self.repo), git_provider="local", branch="main", task="Read README.md")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _orchestrator(self, hook_manager: HookManager | None = None, registry: ToolRegistry | None = None) -> ToolOrchestrator:
        return ToolOrchestrator(
            run_id="run-orchestrator",
            request=self.request,
            registry=registry or get_default_tool_registry(),
            hook_manager=hook_manager,
        )

    def test_read_file_executes_through_orchestrator(self) -> None:
        result = self._orchestrator().execute_action(
            AgentAction(type="read_file", reason_summary="read", target_files=["README.md"])
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.files_read, ["README.md"])
        self.assertIn("README.md", result.payload["contents"])

    def test_unsupported_binary_file_is_skipped(self) -> None:
        result = self._orchestrator().execute_action(
            AgentAction(type="read_file", reason_summary="read", target_files=["cache.sqlite"])
        )
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.files_read, [])
        self.assertIn("cache.sqlite", result.payload["skipped_files"])

    def test_command_preview_goes_through_command_policy(self) -> None:
        result = self._orchestrator().execute_action(
            AgentAction(type="preview_command", reason_summary="preview", command=["git", "status", "--short"])
        )
        self.assertEqual(result.status, "success")
        self.assertTrue(result.command_result["read_only"])
        self.assertFalse(result.command_result["needs_approval"])

    def test_mutating_command_does_not_run_automatically(self) -> None:
        result = self._orchestrator().execute_action(
            AgentAction(type="run_approved_command", reason_summary="commit", command=["git", "commit", "-m", "test"])
        )
        self.assertEqual(result.status, "waiting_approval")
        self.assertIsNone(result.command_result.get("exit_code"))
        self.assertTrue(result.command_result["needs_approval"])

    def test_pre_hook_can_block_tool(self) -> None:
        hooks = HookManager()
        hooks.register_pre_tool_hook(lambda event: HookResult(continue_=False, decision="deny", reason="blocked by test"))
        result = self._orchestrator(hook_manager=hooks).execute_action(
            AgentAction(type="read_file", reason_summary="read", target_files=["README.md"])
        )
        self.assertEqual(result.status, "skipped")
        self.assertIn("blocked by test", result.observation)

    def test_pre_hook_updated_input_is_revalidated(self) -> None:
        hooks = HookManager()
        hooks.register_pre_tool_hook(lambda event: HookResult(updated_input={"target_files": ["cache.sqlite"]}, source="test-hook"))
        result = self._orchestrator(hook_manager=hooks).execute_action(
            AgentAction(type="read_file", reason_summary="read", target_files=["README.md"])
        )
        self.assertEqual(result.status, "skipped")
        self.assertTrue(result.payload["hook_updated_input"])
        self.assertTrue(result.payload["hook_revalidated"])
        self.assertIn("cache.sqlite", result.payload["skipped_files"])

    def test_pre_hook_invalid_updated_input_fails_safely(self) -> None:
        hooks = HookManager()
        hooks.register_pre_tool_hook(lambda event: HookResult(updated_input=["not", "an", "object"], source="bad-hook"))
        result = self._orchestrator(hook_manager=hooks).execute_action(
            AgentAction(type="read_file", reason_summary="read", target_files=["README.md"])
        )
        self.assertEqual(result.status, "failed")
        self.assertIn("invalid updated input", result.observation)

    def test_pre_hook_command_mutation_still_requires_permission(self) -> None:
        hooks = HookManager()
        hooks.register_pre_tool_hook(lambda event: HookResult(updated_input={"command": ["git", "commit", "-m", "test"]}, source="command-hook"))
        result = self._orchestrator(hook_manager=hooks).execute_action(
            AgentAction(type="run_approved_command", reason_summary="status", command=["git", "status", "--short"])
        )
        self.assertEqual(result.status, "waiting_approval")
        self.assertIsNone(result.command_result.get("exit_code"))

    def test_post_hook_observes_result(self) -> None:
        seen: list[str] = []

        def observe(event: HookEvent) -> HookResult:
            seen.append(event.result.status)
            return HookResult()

        hooks = HookManager()
        hooks.register_post_tool_hook(observe)
        result = self._orchestrator(hook_manager=hooks).execute_action(
            AgentAction(type="read_file", reason_summary="read", target_files=["README.md"])
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(seen, ["success"])

    def test_oversized_payload_is_marked_with_artifact_metadata(self) -> None:
        registry = ToolRegistry([LargePayloadTool()])
        result = self._orchestrator(registry=registry).execute_action(
            AgentAction(type="large_payload", reason_summary="large")
        )
        json.dumps(result.model_dump(), ensure_ascii=False)
        self.assertTrue(result.payload["_artifact"]["payload_truncated"])
        self.assertEqual(result.payload["_artifact"]["artifact_store"], "local")
        self.assertTrue(result.payload["_artifact"]["artifact_id"])
        self.assertNotIn("path", json.dumps(result.payload["_artifact"], ensure_ascii=False))


@dataclass
class LargePayloadTool(BaseTool):
    spec = ToolSpec(
        name="large_payload",
        description="Return large payload for truncation tests.",
        input_schema={"type": "object"},
        read_only=True,
        concurrency_safe=True,
        max_result_chars=100,
    )

    def check_permission(self, payload: dict[str, Any], context: ToolPermissionContext) -> PermissionDecision:
        return PermissionDecision.allow("test")

    def call(self, payload: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        return ToolResult(tool_name=self.spec.name, status="success", observation="ok", payload={"content": "x" * 1000})


if __name__ == "__main__":
    unittest.main()
