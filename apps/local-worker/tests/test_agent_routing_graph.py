import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from repooperator_worker.schemas import (  # noqa: E402
    AgentProposeFileResponse,
    AgentRunRequest,
    AgentRunResponse,
    ConversationMessage,
)
from repooperator_worker.services.agent_orchestration_graph import run_agent_orchestration_graph  # noqa: E402
from repooperator_worker.services.agent_service import run_agent_task  # noqa: E402


class _ClassifierClient:
    response: dict

    @property
    def model_name(self) -> str:
        return "test-model"

    def generate_text(self, request):
        if "intent classifier" not in request.system_prompt.lower():
            raise RuntimeError("Only classifier calls are mocked in this test.")
        return json.dumps(self.response)


class AgentRoutingGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / "trim_videos.py").write_text(
            "def split_video(input_path):\n    return input_path\n",
            encoding="utf-8",
        )
        (self.repo / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
        nested = self.repo / "CosyVoice" / "runtime" / "triton_trtllm"
        nested.mkdir(parents=True)
        (nested / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
        (self.repo / "README.md").write_text("# Demo\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _request(self, task: str, history: list[ConversationMessage] | None = None) -> AgentRunRequest:
        return AgentRunRequest(
            project_path=str(self.repo),
            git_provider="local",
            branch="main",
            task=task,
            conversation_history=history or [],
        )

    def _run_with_classifier(self, payload: dict, request: AgentRunRequest):
        _ClassifierClient.response = payload
        with patch(
            "repooperator_worker.services.agent_orchestration_graph.OpenAICompatibleModelClient",
            return_value=_ClassifierClient(),
        ), patch(
            "repooperator_worker.services.agent_orchestration_graph.get_active_repository",
            return_value=None,
        ):
            return run_agent_orchestration_graph(request)

    def test_followup_change_confirmation_routes_to_previous_file(self) -> None:
        history = [
            ConversationMessage(role="user", content="trim_videos.py 코드 분석해줘"),
            ConversationMessage(
                role="assistant",
                content="Refactor split_video in trim_videos.py by validating inputs.",
                metadata={
                    "response_type": "assistant_answer",
                    "files_read": ["trim_videos.py"],
                    "thread_context_symbols": ["split_video"],
                },
            ),
        ]
        request = self._request("이 내용 그대로 적용해줘", history)

        with patch(
            "repooperator_worker.services.context_reference_service.OpenAICompatibleModelClient",
            return_value=_ClassifierClient(),
        ), patch(
            "repooperator_worker.services.agent_orchestration_graph.propose_file_edit",
            return_value=AgentProposeFileResponse(
                project_path=str(self.repo),
                relative_path="trim_videos.py",
                model="test-model",
                context_summary="test",
                original_content="def split_video(input_path):\n    return input_path\n",
                proposed_content="def split_video(input_path):\n    if not input_path:\n        raise ValueError('input_path required')\n    return input_path\n",
            ),
        ):
            result = self._run_with_classifier(
                {
                    "intent": "write_confirmation",
                    "confidence": 0.94,
                    "target_files": ["trim_videos.py"],
                    "target_symbols": ["split_video"],
                    "requested_action": "prepare_refactor",
                    "needs_tool": None,
                    "needs_clarification": False,
                    "clarification_question": None,
                },
                request,
            )

        self.assertEqual(result.response_type, "change_proposal")
        self.assertEqual(result.intent_classification, "write_confirmation")
        self.assertEqual(result.proposal_relative_path, "trim_videos.py")
        self.assertEqual(result.classifier, "llm")

    def test_read_followup_keeps_symbol_context(self) -> None:
        history = [
            ConversationMessage(role="user", content="trim_videos.py 코드 분석해줘"),
            ConversationMessage(
                role="assistant",
                content="split_video is defined in trim_videos.py.",
                metadata={
                    "response_type": "assistant_answer",
                    "files_read": ["trim_videos.py"],
                    "thread_context_symbols": ["split_video"],
                },
            ),
        ]
        request = self._request("split_video 함수 보고 고칠거 알려줘", history)
        with patch("repooperator_worker.services.agent_graph.run_agent_graph") as run_read_only:
            run_read_only.return_value = AgentRunResponse(
                project_path=str(self.repo),
                git_provider="local",
                active_repository_source="local",
                active_repository_path=str(self.repo),
                active_branch="main",
                task=request.task,
                model="test-model",
                branch="main",
                repo_root_name=Path(self.repo).name,
                context_summary="split_video is present in trim_videos.py.",
                top_level_entries=[],
                readme_included=False,
                diff_included=False,
                is_git_repository=True,
                files_read=["trim_videos.py"],
                response="split_video can validate inputs and return explicit outputs.",
                response_type="assistant_answer",
                thread_context_files=["trim_videos.py"],
                thread_context_symbols=["split_video"],
            )
            result = self._run_with_classifier(
                {
                    "intent": "read_only_question",
                    "confidence": 0.9,
                    "target_files": ["trim_videos.py"],
                    "target_symbols": ["split_video"],
                    "requested_action": "analyze_symbol",
                    "needs_tool": None,
                    "needs_clarification": False,
                    "clarification_question": None,
                },
                request,
            )
        self.assertEqual(result.intent_classification, "read_only_question")
        self.assertIn("split_video", result.thread_context_symbols)

    def test_commit_request_routes_to_git_workflow_not_proposal(self) -> None:
        request = self._request("방금 수정한 내용 커밋해줘")
        with patch("repooperator_worker.services.command_service.preview_command") as preview, patch(
            "repooperator_worker.services.command_service.run_command_with_policy"
        ) as run_command:
            preview.return_value = {
                "type": "command_approval",
                "approval_id": "cmd_test",
                "command": ["git", "status", "--short"],
                "display_command": "git status --short",
                "cwd": str(self.repo),
                "risk": "low",
                "read_only": True,
                "needs_network": False,
                "touches_outside_repo": False,
                "needs_approval": False,
                "blocked": False,
                "reason": "Check git status.",
            }
            run_command.return_value = {
                **preview.return_value,
                "status": "ok",
                "exit_code": 0,
                "stdout": " M README.md\n",
                "stderr": "",
            }
            result = self._run_with_classifier(
                {
                    "intent": "git_workflow_request",
                    "confidence": 0.95,
                    "target_files": [],
                    "target_symbols": [],
                    "requested_action": "commit",
                    "needs_tool": "git",
                    "needs_clarification": False,
                    "clarification_question": None,
                },
                request,
            )
        self.assertEqual(result.intent_classification, "git_workflow_request")
        self.assertEqual(result.response_type, "command_result")
        self.assertIsNone(result.proposal_relative_path)

    def test_mr_request_routes_to_gitlab_tool_flow(self) -> None:
        request = self._request("지금 레포 mr정보 알려줘")
        with patch("shutil.which", return_value=None):
            result = self._run_with_classifier(
                {
                    "intent": "gitlab_mr_request",
                    "confidence": 0.96,
                    "target_files": [],
                    "target_symbols": [],
                    "requested_action": "list_merge_requests",
                    "needs_tool": "glab",
                    "needs_clarification": False,
                    "clarification_question": None,
                },
                request,
            )
        self.assertEqual(result.intent_classification, "gitlab_mr_request")
        self.assertIn("glab", result.response)

    def test_recommend_files_request_does_not_require_target(self) -> None:
        result = self._run_with_classifier(
            {
                "intent": "recommend_change_targets",
                "confidence": 0.93,
                "target_files": [],
                "target_symbols": [],
                "requested_action": "recommend_files",
                "needs_tool": None,
                "needs_clarification": False,
                "clarification_question": None,
            },
            self._request("수정할 파일 추천해줘"),
        )
        self.assertEqual(result.intent_classification, "recommend_change_targets")
        self.assertIn("Here are concrete files", result.response)

    def test_candidate_answer_selects_previous_docker_compose_candidate(self) -> None:
        history = [
            ConversationMessage(role="user", content="docker-compose.yml 파일 검토해서 수정 제안해줘"),
            ConversationMessage(
                role="assistant",
                content="I found multiple possible targets.",
                metadata={
                    "response_type": "clarification",
                    "clarification_candidates": [
                        "docker-compose.yml",
                        "CosyVoice/runtime/triton_trtllm/docker-compose.yml",
                    ],
                },
            ),
        ]
        request = self._request("docker-compose.yml로 해줘", history)
        with patch(
            "repooperator_worker.services.agent_orchestration_graph.propose_file_edit",
            return_value=AgentProposeFileResponse(
                project_path=str(self.repo),
                relative_path="docker-compose.yml",
                model="test-model",
                context_summary="test",
                original_content="services: {}\n",
                proposed_content="services:\n  app:\n    image: alpine\n",
            ),
        ):
            result = self._run_with_classifier(
                {
                    "intent": "file_clarification_answer",
                    "confidence": 0.95,
                    "target_files": ["docker-compose.yml"],
                    "target_symbols": [],
                    "requested_action": "select_candidate",
                    "needs_tool": None,
                    "needs_clarification": False,
                    "clarification_question": None,
                },
                request,
            )
        self.assertEqual(result.response_type, "change_proposal")
        self.assertEqual(result.proposal_relative_path, "docker-compose.yml")

    def test_agent_service_returns_agent_error_without_legacy_fallback(self) -> None:
        request = self._request("tts_dockerfile 최적화해줘")
        with patch(
            "repooperator_worker.services.agent_orchestration_graph.run_agent_orchestration_graph",
            side_effect=KeyError("graph exploded"),
        ), patch(
            "repooperator_worker.services.agent_service.logger.exception",
        ):
            result = run_agent_task(request)
        self.assertEqual(result.response_type, "agent_error")
        self.assertEqual(result.graph_path, "agent_error")
        self.assertNotIn("Switch the permission mode", result.response)


if __name__ == "__main__":
    unittest.main()
