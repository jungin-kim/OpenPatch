import sys
import tempfile
import unittest
import inspect
import json
from pathlib import Path
from unittest.mock import patch


TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from repooperator_worker.schemas import AgentRunRequest  # noqa: E402
from repooperator_worker.services.agent_orchestration_graph import (  # noqa: E402
    REPOSITORY_REVIEW_BINARY_SUFFIXES,
    REPOSITORY_REVIEW_SUFFIXES,
    MAX_REPOSITORY_REVIEW_BYTES,
    _classify_intent,
    _repository_wide_review,
    _should_use_repository_wide_review,
)


class _ReviewClient:
    @property
    def model_name(self) -> str:
        return "review-test-model"

    def generate_text(self, request):
        if "slow_module.py" in request.user_prompt:
            raise RuntimeError("Model API request timed out after 120 seconds")
        if "server.py" in request.user_prompt:
            return "Purpose: exposes a small server helper. Confirmed issues: none from the shown code."
        if "Client.kt" in request.user_prompt:
            return "Purpose: contains a client entry point. Improvement: add error handling around network calls if present."
        return "Purpose: documentation or configuration. Confirmed issues: none from the shown content."


class _ClassifierClient:
    payload: dict = {}

    @property
    def model_name(self) -> str:
        return "classifier-test-model"

    def generate_text(self, request):
        return json.dumps(self.payload)


class RepositoryReviewProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "fixture"
        self.repo.mkdir()
        (self.repo / "README.md").write_text("# Fixture\n\nSmall mixed repository.\n", encoding="utf-8")
        (self.repo / "server.py").write_text("def handle():\n    return {'ok': True}\n", encoding="utf-8")
        (self.repo / "slow_module.py").write_text("def slow():\n    return 'needs review'\n", encoding="utf-8")
        (self.repo / "Client.kt").write_text("fun main() { println(\"hi\") }\n", encoding="utf-8")
        (self.repo / "diagram.pdf").write_bytes(b"%PDF-1.4\x00binary")
        node_modules = self.repo / "node_modules" / "pkg"
        node_modules.mkdir(parents=True)
        (node_modules / "index.js").write_text("console.log('generated')\n", encoding="utf-8")
        self.home = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.home.cleanup()
        self.tmp.cleanup()

    def _request(self, task: str) -> AgentRunRequest:
        return AgentRunRequest(
            project_path=str(self.repo),
            git_provider="local",
            branch="main",
            thread_id="thread-review",
            task=task,
            conversation_history=[],
        )

    def _run_review(self, task: str):
        request = self._request(task)
        with patch(
            "repooperator_worker.services.agent_orchestration_graph.OpenAICompatibleModelClient",
            return_value=_ReviewClient(),
        ), patch(
            "repooperator_worker.services.event_service.get_repooperator_home_dir",
            return_value=Path(self.home.name),
        ):
            return _repository_wide_review(
                {
                    "request": request,
                    "intent": "repo_analysis",
                    "classifier": "llm",
                    "confidence": 0.9,
                    "run_id": "run_review_test",
                }
            )["result"]

    def test_repository_review_uses_per_file_progress_events(self) -> None:
        result = self._run_review("Please review the whole repository and summarize confirmed file-level findings.")

        event_types = [event.get("event_type") for event in result.activity_events]
        self.assertIn("narrative_summary", event_types)
        self.assertIn("file_search", event_types)
        self.assertIn("file_selected", event_types)
        self.assertIn("file_read", event_types)
        self.assertIn("step_completed", event_types)
        self.assertIn("aggregate_summary", event_types)
        self.assertTrue(any(event.get("files") for event in result.activity_events))
        self.assertNotIn("context", " ".join(str(event.get("label", "")) for event in result.activity_events).lower())

    def test_per_file_timeout_is_partial_and_not_confirmed(self) -> None:
        result = self._run_review("Perform a repository-wide file review.")

        self.assertIn("slow_module.py", result.response)
        self.assertIn("timed out", result.response.lower())
        self.assertNotIn("slow_module.py` was read successfully", result.response)
        self.assertIn("server.py", result.response)
        self.assertIn("Confirmed File-Level Results", result.response)
        timeout_events = [event for event in result.activity_events if event.get("event_type") == "timeout"]
        self.assertEqual(len(timeout_events), 1)
        self.assertEqual(timeout_events[0].get("files"), ["slow_module.py"])

    def test_unsupported_files_are_skipped_with_reason(self) -> None:
        result = self._run_review("Assess every readable file in this project.")

        skipped_event = next(event for event in result.activity_events if event.get("event_type") == "aggregate_summary")
        aggregate = skipped_event.get("aggregate") or {}
        self.assertGreaterEqual(int(aggregate.get("files_skipped_count") or 0), 1)
        self.assertIn("diagram.pdf", result.response)
        self.assertNotIn("node_modules/pkg/index.js", result.files_read)

    def test_progress_events_do_not_expose_hidden_reasoning(self) -> None:
        result = self._run_review("Review the repository.")

        serialized = "\n".join(str(event) for event in result.activity_events)
        self.assertNotIn("<think>", serialized)
        self.assertNotIn("system_prompt", serialized)
        self.assertNotIn("raw model prompt", serialized.lower())

    def test_no_completed_summary_when_no_file_review_succeeds(self) -> None:
        class _TimeoutClient(_ReviewClient):
            def generate_text(self, request):
                raise RuntimeError("request timed out")

        request = self._request("Review the entire codebase.")
        with patch(
            "repooperator_worker.services.agent_orchestration_graph.OpenAICompatibleModelClient",
            return_value=_TimeoutClient(),
        ), patch(
            "repooperator_worker.services.event_service.get_repooperator_home_dir",
            return_value=Path(self.home.name),
        ):
            result = _repository_wide_review(
                {
                    "request": request,
                    "intent": "repo_analysis",
                    "classifier": "llm",
                    "confidence": 0.9,
                    "run_id": "run_review_timeout",
                }
            )["result"]

        self.assertIn("did not complete", result.response)
        self.assertNotIn("Confirmed File-Level Results", result.response)
        self.assertEqual(result.files_read, [])

    def test_repository_wide_review_selection_uses_classifier_fields(self) -> None:
        request = AgentRunRequest(project_path=str(self.repo), git_provider="local", branch="main", task="Look across this workspace.")
        state = {
            "request": request,
            "target_files": [],
            "file_hints": [],
            "requires_repository_wide_review": True,
            "analysis_scope": "unknown",
            "requested_workflow": "other",
        }
        self.assertTrue(_should_use_repository_wide_review(state))

    def test_selected_files_override_repository_wide_classifier_fields(self) -> None:
        request = AgentRunRequest(project_path=str(self.repo), git_provider="local", branch="main", task="Focus this pass.")
        state = {
            "request": request,
            "target_files": ["server.py"],
            "file_hints": [],
            "requires_repository_wide_review": True,
            "analysis_scope": "repository_wide",
            "requested_workflow": "repository_review",
        }
        self.assertFalse(_should_use_repository_wide_review(state))

    def test_unknown_classifier_scope_does_not_select_repository_wide_review(self) -> None:
        request = AgentRunRequest(project_path=str(self.repo), git_provider="local", branch="main", task="Please help.")
        state = {
            "request": request,
            "target_files": [],
            "file_hints": [],
            "requires_repository_wide_review": False,
            "analysis_scope": "unknown",
            "requested_workflow": "other",
        }
        self.assertFalse(_should_use_repository_wide_review(state))

    def test_korean_paraphrase_uses_mocked_classifier_scope_not_keywords(self) -> None:
        request = AgentRunRequest(project_path=str(self.repo), git_provider="local", branch="main", task="코드베이스를 한 바퀴 훑어줘")
        _ClassifierClient.payload = {
            "intent": "repo_analysis",
            "confidence": 0.91,
            "analysis_scope": "repository_wide",
            "requested_workflow": "repository_review",
            "requires_repository_wide_review": True,
            "target_files": [],
            "target_symbols": [],
            "requested_action": "broad_quality_pass",
            "needs_clarification": False,
        }
        with patch(
            "repooperator_worker.services.agent_orchestration_graph.OpenAICompatibleModelClient",
            return_value=_ClassifierClient(),
        ):
            classified = _classify_intent({"request": request, "pending": {}})
        self.assertEqual(classified["analysis_scope"], "repository_wide")
        self.assertTrue(_should_use_repository_wide_review({**classified, "request": request}))

    def test_english_paraphrase_uses_mocked_classifier_scope_not_keywords(self) -> None:
        request = AgentRunRequest(project_path=str(self.repo), git_provider="local", branch="main", task="Give this codebase a quality pass.")
        _ClassifierClient.payload = {
            "intent": "repo_analysis",
            "confidence": 0.89,
            "analysis_scope": "repository_wide",
            "requested_workflow": "repository_review",
            "requires_repository_wide_review": True,
            "target_files": [],
            "target_symbols": [],
            "requested_action": "broad_quality_pass",
            "needs_clarification": False,
        }
        with patch(
            "repooperator_worker.services.agent_orchestration_graph.OpenAICompatibleModelClient",
            return_value=_ClassifierClient(),
        ):
            classified = _classify_intent({"request": request, "pending": {}})
        self.assertEqual(classified["requested_workflow"], "repository_review")
        self.assertTrue(_should_use_repository_wide_review({**classified, "request": request}))

    def test_repository_wide_review_gate_has_no_natural_language_phrase_lists(self) -> None:
        source = inspect.getsource(_should_use_repository_wide_review)
        self.assertNotIn("review" + "_signals", source)
        self.assertNotIn("broad" + "_scope_signals", source)
        self.assertNotIn("request.task", source)
        self.assertNotIn(".lower()", source)

    def test_repository_review_safety_constants_remain(self) -> None:
        self.assertIn(".py", REPOSITORY_REVIEW_SUFFIXES)
        self.assertIn(".pdf", REPOSITORY_REVIEW_BINARY_SUFFIXES)
        self.assertGreater(MAX_REPOSITORY_REVIEW_BYTES, 0)


if __name__ == "__main__":
    unittest.main()
