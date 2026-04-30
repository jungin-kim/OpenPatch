import json
import subprocess
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
from repooperator_worker.services.agent_orchestration_graph import (  # noqa: E402
    run_agent_orchestration_graph,
    stream_agent_orchestration_graph,
)
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
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "RepoOperator Test"], cwd=self.repo, check=True)
        subprocess.run(["git", "add", "README.md"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.repo, check=True, capture_output=True)

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
        request = self._request("please turn that prior recommendation into a patch", history)

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
        self.assertEqual(result.stop_reason, "waiting_for_apply")
        self.assertGreaterEqual(result.loop_iteration, 1)
        self.assertEqual(result.edit_archive[0]["file_path"], "trim_videos.py")
        self.assertEqual(result.edit_archive[0]["status"], "proposed")
        self.assertGreater(result.edit_archive[0]["additions"], 0)

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
        request = self._request("review the previously discussed split_video function for improvements", history)
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
        (self.repo / "README.md").write_text("# Demo\n\nChanged\n", encoding="utf-8")
        request = self._request("prepare a local commit for the current working tree changes")
        result = self._run_with_classifier(
            {
                "intent": "git_workflow_request",
                "confidence": 0.95,
                "target_files": [],
                "target_symbols": [],
                "requested_action": "commit",
                "git_action": "git_commit_plan",
                "needs_tool": "git",
                "needs_clarification": False,
                "clarification_question": None,
            },
            request,
        )
        self.assertEqual(result.intent_classification, "git_workflow_request")
        self.assertEqual(result.response_type, "command_approval")
        self.assertEqual(result.git_action, "git_commit_plan")
        self.assertIn("git status --short", result.commands_run)
        self.assertIn("git add --all", result.commands_planned)
        self.assertIn("next_command_approval", result.command_approval)
        self.assertEqual(result.command_approval["next_command_approval"]["command"][:3], ["git", "commit", "-m"])
        self.assertIsNone(result.proposal_relative_path)

    def test_recent_commit_uses_git_log_not_status(self) -> None:
        result = self._run_with_classifier(
            {
                "intent": "git_workflow_request",
                "confidence": 0.95,
                "target_files": [],
                "target_symbols": [],
                "requested_action": "recent_commit",
                "git_action": "git_recent_commit",
                "needs_tool": "git",
                "needs_clarification": False,
                "clarification_question": None,
            },
            self._request("show the newest commit details for this branch"),
        )
        self.assertEqual(result.response_type, "assistant_answer")
        self.assertEqual(result.git_action, "git_recent_commit")
        self.assertIn("git log -1", result.commands_run[0])
        self.assertIn("Initial commit", result.response)

    def test_review_recommendation_does_not_generate_proposal(self) -> None:
        request = self._request("suggest improvements for the split_video function")
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
                context_summary="split_video is present.",
                top_level_entries=[],
                readme_included=False,
                diff_included=False,
                is_git_repository=True,
                files_read=["trim_videos.py"],
                response="Suggestions only: validate input and return output paths.",
                response_type="assistant_answer",
                thread_context_files=["trim_videos.py"],
                thread_context_symbols=["split_video"],
            )
            result = self._run_with_classifier(
                {
                    "intent": "review_recommendation",
                    "confidence": 0.94,
                    "target_files": ["trim_videos.py"],
                    "target_symbols": ["split_video"],
                    "requested_action": "review_symbol",
                    "needs_tool": None,
                    "needs_clarification": False,
                    "clarification_question": None,
                },
                request,
            )
        self.assertEqual(result.intent_classification, "review_recommendation")
        self.assertEqual(result.response_type, "assistant_answer")
        self.assertIsNone(result.proposal_relative_path)

    def test_mr_request_routes_to_gitlab_tool_flow(self) -> None:
        request = self._request("summarize merge request status for this repository")
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
            self._request("recommend the next files worth improving"),
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
        request = self._request("use the root compose file from those options", history)
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

    def test_recommendation_followup_uses_structured_context(self) -> None:
        recommendation_context = {
            "recommendation_id": "rec_test",
            "repo": str(self.repo),
            "branch": "main",
            "recommended_files": ["trim_videos.py"],
            "items": [
                {
                    "id": "rec_test_1",
                    "files": ["trim_videos.py"],
                    "symbols": ["split_video"],
                    "suggested_changes": ["Add validation and explicit return values."],
                    "rationale": "confirmed from file review",
                    "risk_level": "medium",
                    "category": "code",
                    "needs_more_inspection": False,
                }
            ],
        }
        history = [
            ConversationMessage(
                role="assistant",
                content="I recommend a focused validation refactor.",
                metadata={
                    "response_type": "assistant_answer",
                    "recommendation_context": recommendation_context,
                    "recommendation_context_loaded": True,
                    "files_read": ["trim_videos.py"],
                },
            )
        ]
        request = self._request("continue by preparing the recommended code change", history)

        class _RecommendationResolver:
            @property
            def model_name(self) -> str:
                return "test-model"

            def generate_text(self, request):
                return json.dumps(
                    {
                        "refers_to_previous_recommendation": True,
                        "selected_recommendation_ids": ["rec_test_1"],
                        "selected_files": ["trim_videos.py"],
                        "requested_action": "generate_proposal",
                        "confidence": 0.91,
                        "needs_clarification": False,
                        "clarification_question": None,
                    }
                )

        with patch(
            "repooperator_worker.services.recommendation_context_service.OpenAICompatibleModelClient",
            return_value=_RecommendationResolver(),
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
                    "confidence": 0.9,
                    "target_files": [],
                    "target_symbols": [],
                    "requested_action": "continue_previous_recommendation",
                    "needs_tool": None,
                    "needs_clarification": False,
                    "clarification_question": None,
                },
                request,
            )

        self.assertEqual(result.response_type, "change_proposal")
        self.assertTrue(result.recommendation_context_loaded)
        self.assertEqual(result.proposal_relative_path, "trim_videos.py")

    def test_multi_file_recommendation_followup_asks_for_scope(self) -> None:
        recommendation_context = {
            "recommendation_id": "rec_multi",
            "repo": str(self.repo),
            "branch": "main",
            "recommended_files": ["trim_videos.py", "README.md"],
            "items": [
                {"id": "rec_multi_1", "files": ["trim_videos.py"], "suggested_changes": ["Improve validation."]},
                {"id": "rec_multi_2", "files": ["README.md"], "suggested_changes": ["Document usage."]},
            ],
        }
        request = self._request(
            "prepare the suggested improvements",
            [
                ConversationMessage(
                    role="assistant",
                    content="Two areas are worth improving.",
                    metadata={"response_type": "assistant_answer", "recommendation_context": recommendation_context},
                )
            ],
        )

        class _MultiResolver:
            @property
            def model_name(self) -> str:
                return "test-model"

            def generate_text(self, request):
                return json.dumps(
                    {
                        "refers_to_previous_recommendation": True,
                        "selected_recommendation_ids": ["rec_multi_1", "rec_multi_2"],
                        "selected_files": ["trim_videos.py", "README.md"],
                        "requested_action": "generate_proposal",
                        "confidence": 0.86,
                        "needs_clarification": False,
                        "clarification_question": None,
                    }
                )

        with patch(
            "repooperator_worker.services.recommendation_context_service.OpenAICompatibleModelClient",
            return_value=_MultiResolver(),
        ):
            result = self._run_with_classifier(
                {
                    "intent": "write_confirmation",
                    "confidence": 0.9,
                    "target_files": [],
                    "target_symbols": [],
                    "requested_action": "continue_previous_recommendation",
                    "needs_tool": None,
                    "needs_clarification": False,
                    "clarification_question": None,
                },
                request,
            )
        self.assertEqual(result.response_type, "clarification")
        self.assertCountEqual(result.clarification_candidates, ["trim_videos.py", "README.md"])

    def test_pasted_spec_without_apply_does_not_select_repo_file(self) -> None:
        request = self._request(
            "Here is a structured implementation brief with constraints, verification, and final report sections."
        )
        result = self._run_with_classifier(
            {
                "intent": "pasted_prompt_or_spec",
                "confidence": 0.92,
                "target_files": ["README.md"],
                "target_symbols": [],
                "requested_action": "summarize_external_spec",
                "needs_tool": None,
                "needs_clarification": False,
                "clarification_question": None,
            },
            request,
        )
        self.assertEqual(result.intent_classification, "pasted_prompt_or_spec")
        self.assertEqual(result.response_type, "assistant_answer")
        self.assertTrue(result.pasted_prompt_or_spec)
        self.assertIsNone(result.proposal_relative_path)

    def test_explicit_apply_spec_returns_plan_before_edits(self) -> None:
        request = self._request(
            "Apply the attached implementation brief to this repository after planning the affected areas."
        )
        result = self._run_with_classifier(
            {
                "intent": "apply_spec_to_repo",
                "confidence": 0.91,
                "target_files": ["README.md", "trim_videos.py"],
                "target_symbols": [],
                "requested_action": "plan_spec_application",
                "needs_tool": None,
                "needs_clarification": False,
                "clarification_question": None,
            },
            request,
        )
        self.assertEqual(result.intent_classification, "apply_spec_to_repo")
        self.assertEqual(result.response_type, "assistant_answer")
        self.assertTrue(result.apply_spec_to_repo)
        self.assertGreaterEqual(len(result.plan_steps), 3)
        self.assertIsNone(result.proposal_relative_path)

    def test_agent_service_returns_agent_error_without_legacy_fallback(self) -> None:
        request = self._request("optimize the container build file")
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

    def test_stream_activity_uses_product_labels_not_internal_nodes(self) -> None:
        request = self._request("summarize the most recent commit")
        _ClassifierClient.response = {
            "intent": "git_workflow_request",
            "confidence": 0.95,
            "target_files": [],
            "target_symbols": [],
            "requested_action": "recent_commit",
            "git_action": "git_recent_commit",
            "needs_tool": "git",
            "needs_clarification": False,
            "clarification_question": None,
        }
        with patch(
            "repooperator_worker.services.agent_orchestration_graph.OpenAICompatibleModelClient",
            return_value=_ClassifierClient(),
        ), patch(
            "repooperator_worker.services.agent_orchestration_graph.get_active_repository",
            return_value=None,
        ):
            events = [json.loads(item) for item in stream_agent_orchestration_graph(request)]

        activity = [event for event in events if event.get("type") == "progress_delta"]
        labels = [event.get("label", "") for event in activity]
        serialized_labels = " ".join(labels)
        self.assertTrue(any(label == "Prepared Git workflow" for label in labels))
        self.assertNotIn("load_context", serialized_labels)
        self.assertNotIn("classify_intent", serialized_labels)
        self.assertNotIn("final_answer", serialized_labels)
        final = next(event for event in events if event.get("type") == "final_message")
        self.assertGreaterEqual(len(final["result"]["activity_events"]), 3)
        self.assertEqual(final["result"]["stop_reason"], "completed")


if __name__ == "__main__":
    unittest.main()
