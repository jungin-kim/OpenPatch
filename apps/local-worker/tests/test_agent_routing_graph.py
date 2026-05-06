import inspect
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from repooperator_worker.agent_core.controller_graph import _existing_target_files, _answer_with_model, run_controller_graph, stream_controller_graph  # noqa: E402
from repooperator_worker.agent_core.state import ClassifierResult  # noqa: E402
from repooperator_worker.agent_core.repository_review import review_single_file  # noqa: E402
from repooperator_worker.schemas import AgentRunRequest, AgentRunResponse  # noqa: E402
from repooperator_worker.services.agent_orchestration_graph import (  # noqa: E402
    run_agent_orchestration_graph,
    stream_agent_orchestration_graph,
)
from repooperator_worker.services.agent_run_coordinator import start_run, stream_run  # noqa: E402
from repooperator_worker.services.agent_service import run_agent_task  # noqa: E402
from repooperator_worker.services.event_service import list_run_events  # noqa: E402


class _StreamingReviewClient:
    @property
    def model_name(self) -> str:
        return "test-model"

    def stream_text(self, _request):
        yield {"type": "assistant_delta", "delta": "Purpose: checks the fixture. "}
        yield {"type": "assistant_delta", "delta": "Confirmed issues: none."}

    def generate_text(self, _request):
        raise AssertionError("review_single_file should prefer stream_text")


class _LoopClient:
    @property
    def model_name(self) -> str:
        return "test-model"

    def stream_text(self, _request):
        yield {"type": "assistant_delta", "delta": "README.md evidence reached the final answer."}

    def generate_text(self, _request):
        return "README.md evidence reached the final answer."


class ActivePathMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = tempfile.TemporaryDirectory()
        self.repo_base = Path(self.tmp.name) / "repos"
        self.repo = self.repo_base / "jungin-kim" / "EldersNiceShot"
        self.repo.mkdir(parents=True)
        (self.repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
        (self.repo / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
        self.config = Path(self.tmp.name) / "config.json"
        self.config.write_text(
            json.dumps(
                {
                    "repooperatorHomeDir": self.home.name,
                    "localRepoBaseDir": str(self.repo_base),
                    "openai": {"baseUrl": "http://127.0.0.1:11434/v1", "apiKey": "test", "model": "test-model"},
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.home.cleanup()
        self.tmp.cleanup()

    def _request(self, project_path: str | None = None) -> AgentRunRequest:
        return AgentRunRequest(
            project_path=project_path or str(self.repo),
            git_provider="local",
            branch="main",
            thread_id="thread-active-path",
            task="Explain README.md",
            conversation_history=[],
        )

    def _response(self, request: AgentRunRequest, run_id: str | None = None) -> AgentRunResponse:
        return AgentRunResponse(
            project_path=request.project_path,
            git_provider=request.git_provider,
            active_repository_source=request.git_provider,
            active_repository_path=request.project_path,
            active_branch=request.branch,
            task=request.task,
            model="test-model",
            branch=request.branch,
            repo_root_name="EldersNiceShot",
            context_summary="",
            top_level_entries=[],
            readme_included=False,
            diff_included=False,
            is_git_repository=True,
            files_read=["README.md"],
            response="README.md describes the fixture.",
            response_type="assistant_answer",
            intent_classification="read_only_question",
            graph_path="agent_core:test",
            agent_flow="agent_core_controller",
            run_id=run_id,
        )

    def test_agent_service_calls_agent_core_controller(self) -> None:
        request = self._request()
        called: list[str] = []

        def fake_controller(req):
            called.append(req.task)
            return self._response(req)

        with patch(
            "repooperator_worker.agent_core.controller_graph.run_controller_graph",
            side_effect=fake_controller,
        ), patch(
            "repooperator_worker.services.agent_orchestration_graph.run_agent_orchestration_graph",
            side_effect=AssertionError("old orchestration graph must not run"),
        ):
            result = run_agent_task(request)

        self.assertEqual(called, [request.task])
        self.assertEqual(result.agent_flow, "agent_core_controller")

    def test_agent_run_coordinator_sync_calls_agent_core_controller(self) -> None:
        request = self._request()
        called: list[str] = []

        def fake_controller(req, *, run_id=None):
            called.append(str(run_id))
            return self._response(req, run_id)

        with patch.dict(os.environ, {"REPOOPERATOR_CONFIG_PATH": str(self.config)}, clear=False), patch(
            "repooperator_worker.agent_core.controller_graph.run_controller_graph",
            side_effect=fake_controller,
        ), patch(
            "repooperator_worker.services.agent_service.run_agent_task",
            side_effect=AssertionError("agent_service must not be on coordinator sync path"),
        ):
            result = start_run(request)

        self.assertEqual(len(called), 1)
        self.assertEqual(result.run_id, called[0])

    def test_agent_run_coordinator_stream_calls_agent_core_stream(self) -> None:
        request = self._request()
        called: list[str] = []

        def fake_stream(req, *, run_id=None):
            called.append(str(run_id))
            yield {"type": "progress_delta", "run_id": run_id, "activity_id": "test", "label": "Working", "status": "completed"}
            yield {"type": "assistant_delta", "delta": "Done."}
            yield {"type": "final_message", "result": self._response(req, run_id).model_dump(mode="json")}

        with patch.dict(os.environ, {"REPOOPERATOR_CONFIG_PATH": str(self.config)}, clear=False), patch(
            "repooperator_worker.agent_core.controller_graph.stream_controller_graph",
            side_effect=fake_stream,
        ), patch(
            "repooperator_worker.services.agent_orchestration_graph.stream_agent_orchestration_graph",
            side_effect=AssertionError("old stream graph must not run"),
        ):
            run_id, stream = stream_run(request)
            chunks: list[str] = []
            deadline = time.time() + 3
            while time.time() < deadline:
                chunk = next(stream)
                chunks.append(chunk)
                if "[DONE]" in chunk:
                    break
            sequences = [event["sequence"] for event in list_run_events(run_id)]

        self.assertEqual(called, [run_id])
        self.assertTrue(any("progress_delta" in chunk for chunk in chunks))
        self.assertEqual(sequences, sorted(set(sequences)))

    def test_agent_orchestration_graph_is_adapter(self) -> None:
        request = self._request()
        with patch(
            "repooperator_worker.services.agent_orchestration_graph.run_controller_graph",
            return_value=self._response(request),
        ) as run_controller:
            result = run_agent_orchestration_graph(request)
        self.assertTrue(run_controller.called)
        self.assertEqual(result.graph_path, "agent_core:test")

        with patch(
            "repooperator_worker.services.agent_orchestration_graph.stream_controller_graph",
            return_value=iter([{"type": "final_message", "result": self._response(request).model_dump(mode="json")}]),
        ) as stream_controller:
            events = list(stream_agent_orchestration_graph(request, run_id="run-adapter"))
        self.assertTrue(stream_controller.called)
        self.assertEqual(events[0]["type"], "final_message")

    def test_old_agent_graph_is_not_imported_by_active_services(self) -> None:
        import repooperator_worker.services.agent_run_coordinator as coordinator
        import repooperator_worker.services.agent_service as service

        combined = inspect.getsource(coordinator) + "\n" + inspect.getsource(service)
        self.assertNotIn("agent_graph", combined)
        self.assertNotIn("run_agent_graph", combined)

    def test_existing_target_files_resolves_provider_style_project_path(self) -> None:
        request = self._request("jungin-kim/EldersNiceShot")
        with patch.dict(
            os.environ,
            {"REPOOPERATOR_CONFIG_PATH": str(self.config), "LOCAL_REPO_BASE_DIR": str(self.repo_base)},
            clear=False,
        ), patch(
            "pathlib.Path.cwd",
            side_effect=AssertionError("current working directory must not be used"),
        ):
            self.assertEqual(_existing_target_files(request, ["README.md", "../outside.py"]), ["README.md"])

    def test_visible_reasoning_is_removed_from_final_answer(self) -> None:
        request = self._request()

        class _Client:
            def stream_text(self, _prompt):
                yield {"type": "assistant_delta", "delta": "<think>private notes</think>\nFinal answer"}

            def generate_text(self, _prompt):
                raise AssertionError("stream result should be used")

        with patch("repooperator_worker.agent_core.controller_graph.OpenAICompatibleModelClient", return_value=_Client()):
            answer = _answer_with_model(request, {"README.md": "# Fixture\n"})
        self.assertEqual(answer, "Final answer")
        self.assertNotIn("<think>", answer)
        self.assertNotIn("private notes", answer)

    def test_repository_review_streams_file_deltas_on_same_activity(self) -> None:
        deltas: list[str] = []
        result = review_single_file(
            request=self._request(),
            relative_path="app.py",
            content="def main():\n    return 1\n",
            truncated=False,
            client=_StreamingReviewClient(),
            on_delta=deltas.append,
        )
        self.assertIn("Confirmed issues", result["summary"])
        self.assertEqual(deltas, ["Purpose: checks the fixture. ", "Confirmed issues: none."])

    def test_repository_review_streaming_honors_cancellation(self) -> None:
        deltas: list[str] = []
        result = review_single_file(
            request=self._request(),
            relative_path="app.py",
            content="def main():\n    return 1\n",
            truncated=False,
            client=_StreamingReviewClient(),
            on_delta=deltas.append,
            should_cancel=lambda: bool(deltas),
        )
        self.assertTrue(result["cancelled"])
        self.assertEqual(deltas, ["Purpose: checks the fixture. "])

    def test_controller_loop_reads_target_file_then_answers(self) -> None:
        request = self._request()
        classifier = ClassifierResult(
            intent="read_only_question",
            confidence=0.9,
            analysis_scope="single_file",
            requested_workflow="file_review",
            target_files=["README.md"],
        )
        with patch("repooperator_worker.agent_core.controller_graph.classify_intent", return_value=classifier), patch(
            "repooperator_worker.agent_core.controller_graph.OpenAICompatibleModelClient",
            return_value=_LoopClient(),
        ), patch(
            "repooperator_worker.agent_core.controller_graph.get_active_repository",
            return_value=None,
        ):
            result = run_controller_graph(request, run_id="loop-target-file")
        self.assertGreater(result.loop_iteration, 1)
        self.assertEqual(result.files_read, ["README.md"])
        self.assertEqual(result.graph_path, "agent_core:read_file_answer")
        self.assertIn("README.md evidence", result.response)

    def test_stream_final_message_omits_streamed_activity_metadata(self) -> None:
        request = self._request()
        classifier = ClassifierResult(
            intent="read_only_question",
            confidence=0.9,
            analysis_scope="single_file",
            requested_workflow="file_review",
            target_files=["README.md"],
        )
        with patch.dict(os.environ, {"REPOOPERATOR_CONFIG_PATH": str(self.config)}, clear=False), patch(
            "repooperator_worker.agent_core.controller_graph.classify_intent",
            return_value=classifier,
        ), patch(
            "repooperator_worker.agent_core.controller_graph.OpenAICompatibleModelClient",
            return_value=_LoopClient(),
        ), patch(
            "repooperator_worker.agent_core.controller_graph.get_active_repository",
            return_value=None,
        ):
            events = list(stream_controller_graph(request, run_id="stream-no-duplicate"))
        final = next(event for event in events if event.get("type") == "final_message")
        self.assertEqual(final["result"]["activity_events"], [])

    def test_agent_service_error_uses_agent_core_metadata(self) -> None:
        request = self._request()
        with patch(
            "repooperator_worker.agent_core.controller_graph.run_controller_graph",
            side_effect=RuntimeError("boom"),
        ), patch(
            "repooperator_worker.services.agent_service.logger.exception",
        ):
            result = run_agent_task(request)
        self.assertEqual(result.response_type, "agent_error")
        self.assertEqual(result.agent_flow, "agent_core_controller")
        self.assertEqual(result.graph_path, "agent_core:error")


if __name__ == "__main__":
    unittest.main()
