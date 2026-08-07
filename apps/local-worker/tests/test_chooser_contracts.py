"""Contract tests for the deterministic chooser chain in graph_routes.

The chain has grown past fifteen choosers whose ORDER and individual firing
conditions carry behavioral contracts that live QA kept re-discovering the
hard way. These tests pin the contracts at the unit level.
"""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import repooperator_worker.agent_core.graph  # noqa: F401  (break circular import: graph package must load first)
from repooperator_worker.agent_core import graph_routes
from repooperator_worker.agent_core.actions import ActionResult, AgentAction
from repooperator_worker.agent_core.planner import (
    build_task_frame,
    command_needed_for_text,
    edit_requested_text,
)
from repooperator_worker.agent_core.state import AgentCoreState
from repooperator_worker.schemas import AgentRunRequest


def _request(task: str, repo: str) -> AgentRunRequest:
    return AgentRunRequest(project_path=repo, git_provider="local", branch="main", task=task)


def _state(request: AgentRunRequest) -> AgentCoreState:
    return AgentCoreState(
        run_id="test-run",
        thread_id=None,
        repo=request.project_path,
        branch="main",
        user_task=request.task,
    )


class ChooserChainOrderTests(unittest.TestCase):
    """The relative order of choosers is a contract: deterministic intent
    handlers must run before model-driven ones."""

    def setUp(self) -> None:
        self.source = inspect.getsource(graph_routes.choose_graph_next_action)

    def _index(self, name: str) -> int:
        idx = self.source.find(name)
        self.assertGreaterEqual(idx, 0, f"{name} missing from chooser chain")
        return idx

    def test_command_chooser_precedes_model_choosers(self) -> None:
        # "python calc.py 실행해줘" must reach the command flow before any
        # model path can answer or edit instead.
        self.assertLess(self._index("_next_command_action"), self._index("_next_tool_calling_action"))
        self.assertLess(self._index("_next_command_action"), self._index("_next_model_planner_action"))

    def test_approved_write_wrapup_runs_first(self) -> None:
        # After an approved direct write succeeds, nothing may preempt the
        # wrap-up (the loop used to wander into a redundant change-set).
        self.assertLess(self._index("_next_approved_write_done_action"), self._index("_next_off_topic_answer_action"))

    def test_web_fetch_precedes_missing_file(self) -> None:
        # URL path segments look like filenames; fetch must win.
        self.assertLess(self._index("_next_web_fetch_action"), self._index("_next_missing_file_action"))

    def test_git_intent_choosers_precede_wrapup(self) -> None:
        self.assertLess(self._index("_next_git_commit_action"), self._index("_next_mentioned_files_covered_action"))
        self.assertLess(self._index("_next_git_branch_action"), self._index("_next_mentioned_files_covered_action"))


class IntentTextContractTests(unittest.TestCase):
    def test_run_request_maps_to_command(self) -> None:
        self.assertEqual(command_needed_for_text("python calc.py를 실행해서 에러가 없는지 확인해줘"), ["python", "calc.py"])
        self.assertEqual(command_needed_for_text("run pytest please"), ["pytest"])

    def test_non_run_text_maps_to_no_command(self) -> None:
        self.assertIsNone(command_needed_for_text("calc.py에 어떤 함수가 있는지 알려줘"))

    def test_edit_verbs_recognized(self) -> None:
        for text in (
            "add 함수에 docstring을 추가해줘",
            "subtract 함수를 삭제해줘",
            "이 함수 지워줘",
            "이름을 plus로 바꿔줘",
            "utils.py 파일을 만들어줘",
        ):
            self.assertTrue(edit_requested_text(text), text)

    def test_read_only_text_not_edit(self) -> None:
        self.assertFalse(edit_requested_text("calc.py를 설명해줘"))


class ChooserBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        (self.repo / "big_module.py").write_text("VALUE = 1\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _frame(self, task: str):
        request = _request(task, str(self.repo))
        state = _state(request)
        return request, state, build_task_frame(request, state)

    def test_branch_chooser_extracts_slashed_name(self) -> None:
        request, state, frame = self._frame("feature/qa-test 라는 이름으로 새 브랜치를 만들어줘")
        action = graph_routes._next_git_branch_action(state, request, frame)
        self.assertIsNotNone(action)
        self.assertEqual(action.type, "git_branch_create")
        self.assertEqual(action.payload.get("branch"), "feature/qa-test")

    def test_branch_chooser_skips_without_branch_word(self) -> None:
        request, state, frame = self._frame("calc.py를 설명해줘")
        self.assertIsNone(graph_routes._next_git_branch_action(state, request, frame))

    def test_missing_file_chooser_skips_creation_intent(self) -> None:
        request, state, frame = self._frame("utils.py 파일을 새로 만들어서 clamp 함수를 추가해줘")
        self.assertIsNone(graph_routes._next_missing_file_action(state, request, frame))

    def test_missing_file_chooser_skips_urls(self) -> None:
        request, state, frame = self._frame("https://example.com/peps/pep-0020.rst 요약해줘")
        self.assertIsNone(graph_routes._next_missing_file_action(state, request, frame))

    def test_web_fetch_fires_once(self) -> None:
        request, state, frame = self._frame("https://example.com/page 내용을 요약해줘")
        first = graph_routes._next_web_fetch_action(state, request, frame)
        self.assertIsNotNone(first)
        self.assertEqual(first.type, "fetch_url")
        state.actions_taken.append(AgentAction(type="fetch_url", reason_summary="done"))
        self.assertIsNone(graph_routes._next_web_fetch_action(state, request, frame))

    def test_edit_target_filler_overrides_empty_payload_list(self) -> None:
        # The model often sends an explicit empty target_files list — it must
        # be OVERWRITTEN, not setdefault'ed (the multi-file edit flake).
        request, state, frame = self._frame("calc.py와 big_module.py 두 파일 맨 위에 주석을 추가해줘")
        state.files_read = ["calc.py", "big_module.py"]
        action = AgentAction(type="generate_edit", reason_summary="model call", payload={"target_files": []})
        filled = graph_routes._with_edit_targets_filled(action, state, request, frame)
        self.assertTrue(filled.target_files)
        self.assertTrue(filled.payload.get("target_files"))

    def test_approved_write_triggers_wrapup(self) -> None:
        request, state, frame = self._frame("utils.py 파일을 만들어줘")
        state.actions_taken.append(AgentAction(type="create_file", reason_summary="write"))
        state.action_results.append(
            ActionResult(action_id="a1", status="success", payload={"approved": True, "path": "utils.py"})
        )
        action = graph_routes._next_approved_write_done_action(state, request, frame)
        self.assertIsNotNone(action)
        self.assertEqual(action.type, "final_answer")

    def test_commit_chooser_extracts_quoted_message(self) -> None:
        request, state, frame = self._frame("'docs: add docstring' 메시지로 커밋해줘")
        action = graph_routes._next_git_commit_action(state, request, frame)
        self.assertIsNotNone(action)
        self.assertEqual(action.payload.get("message"), "docs: add docstring")

    def test_commit_chooser_never_uses_request_sentence_as_message(self) -> None:
        request, state, frame = self._frame("방금 변경사항을 적당한 메시지로 커밋해줘")
        action = graph_routes._next_git_commit_action(state, request, frame)
        self.assertIsNotNone(action)
        self.assertNotIn("커밋해줘", str(action.payload.get("message")))


if __name__ == "__main__":
    unittest.main()
