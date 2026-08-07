"""Phase 1: model-driven native tool-calling planner."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from repooperator_worker.agent_core import agentic_loop
from repooperator_worker.agent_core.planner import TaskFrame
from repooperator_worker.services.model_tools import ToolCall, ToolCallResponse
from repooperator_worker.schemas import AgentRunRequest


def _settings(*, agentic=True, base_url="http://127.0.0.1:11434/v1", model="llama3", provider="ollama", api_key=None):
    return SimpleNamespace(
        agentic_tool_calling=agentic,
        openai_base_url=base_url,
        openai_model=model,
        openai_api_key=api_key,
        configured_model_provider=provider,
        configured_model_name=model,
        configured_model_connection_mode="local-runtime",
        model_request_timeout_seconds=30,
    )


def _state(**overrides):
    base = dict(
        context_packet={},
        files_read=[],
        max_file_reads=10,
        max_commands=5,
        loop_iteration=0,
        actions_taken=[],
        action_results=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _request():
    return AgentRunRequest(project_path="/tmp/repo", task="Explain what read_file does")


def _frame():
    return TaskFrame(user_goal="explain", likely_needed_tools=["read_file"], likely_capabilities=[])


class FakeClient:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def generate_with_tools(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class ToolCallingAvailabilityTests(unittest.TestCase):
    def test_disabled_when_flag_off(self) -> None:
        self.assertFalse(agentic_loop.tool_calling_available(_settings(agentic=False)))

    def test_disabled_when_no_endpoint(self) -> None:
        self.assertFalse(agentic_loop.tool_calling_available(_settings(base_url=None, provider="openai-compatible")))

    def test_enabled_when_configured(self) -> None:
        self.assertTrue(agentic_loop.tool_calling_available(_settings()))

    def test_anthropic_endpoint_uses_api_key(self) -> None:
        self.assertTrue(
            agentic_loop.tool_calling_available(
                _settings(provider="anthropic", base_url=None, api_key="k", model="claude-3.5")
            )
        )


class ActionMappingTests(unittest.TestCase):
    def test_tool_call_maps_to_action(self) -> None:
        response = ToolCallResponse(
            text="reading the file",
            tool_calls=(ToolCall(id="c1", name="read_file", arguments={"target_files": ["src/a.py"], "reason_summary": "look at a"}),),
        )
        client = FakeClient(response)
        action = agentic_loop.propose_next_action_with_tool_calling(
            _request(), _state(), _frame(), client_factory=lambda s: client, settings=_settings()
        )
        self.assertIsNotNone(action)
        self.assertEqual(action.type, "read_file")
        self.assertEqual(action.target_files, ["src/a.py"])
        self.assertEqual(action.reason_summary, "look at a")
        self.assertEqual(action.payload["target_files"], ["src/a.py"])
        # Tools were actually offered to the model.
        self.assertTrue(client.calls[0]["tools"])

    def test_path_alias_maps_to_target_files(self) -> None:
        response = ToolCallResponse(
            tool_calls=(ToolCall(id="c1", name="delete_file", arguments={"path": "/x/y.py", "justification": "dead"}),),
        )
        # An edit-shaped request: the read-only inverse gate must not block the
        # edit action whose alias mapping this test exercises.
        edit_request = AgentRunRequest(project_path="/tmp/repo", task="delete the dead file y.py")
        edit_frame = TaskFrame(user_goal="delete the dead file y.py", likely_needed_tools=["delete_file"], likely_capabilities=[])
        action = agentic_loop.propose_next_action_with_tool_calling(
            edit_request, _state(), edit_frame, client_factory=lambda s: FakeClient(response), settings=_settings()
        )
        self.assertEqual(action.type, "delete_file")
        self.assertEqual(action.target_files, ["x/y.py"])  # leading slash stripped

    def test_unknown_tool_returns_none(self) -> None:
        response = ToolCallResponse(tool_calls=(ToolCall(id="c1", name="not_a_real_tool", arguments={}),))
        action = agentic_loop.propose_next_action_with_tool_calling(
            _request(), _state(), _frame(), client_factory=lambda s: FakeClient(response), settings=_settings()
        )
        self.assertIsNone(action)

    def test_text_only_response_becomes_final_answer(self) -> None:
        # Text-only reply becomes final_answer once evidence exists.
        response = ToolCallResponse(text="It reads a repository file.")
        state = _state(files_read=["a.py"])
        action = agentic_loop.propose_next_action_with_tool_calling(
            _request(), state, _frame(), client_factory=lambda s: FakeClient(response), settings=_settings()
        )
        self.assertEqual(action.type, "final_answer")
        self.assertEqual(action.payload["model_answer"], "It reads a repository file.")

    def test_final_answer_blocked_without_evidence(self) -> None:
        # Model tries to answer immediately with no files read -> must defer.
        response = ToolCallResponse(text="This is a local-first coding agent.")
        action = agentic_loop.propose_next_action_with_tool_calling(
            _request(), _state(), _frame(), client_factory=lambda s: FakeClient(response), settings=_settings()
        )
        self.assertIsNone(action)

    def test_final_answer_allowed_with_evidence(self) -> None:
        response = ToolCallResponse(text="It reads repository files and answers questions.")
        state = _state(files_read=["README.md"])
        action = agentic_loop.propose_next_action_with_tool_calling(
            _request(), state, _frame(), client_factory=lambda s: FakeClient(response), settings=_settings()
        )
        self.assertIsNotNone(action)
        self.assertEqual(action.type, "final_answer")

    def test_tool_call_allowed_without_evidence(self) -> None:
        # A tool call (evidence gathering) is always fine even with no evidence yet.
        response = ToolCallResponse(tool_calls=(ToolCall(id="c1", name="inspect_repo_tree", arguments={}),))
        action = agentic_loop.propose_next_action_with_tool_calling(
            _request(), _state(), _frame(), client_factory=lambda s: FakeClient(response), settings=_settings()
        )
        self.assertEqual(action.type, "inspect_repo_tree")

    def test_empty_response_returns_none(self) -> None:
        response = ToolCallResponse()
        action = agentic_loop.propose_next_action_with_tool_calling(
            _request(), _state(), _frame(), client_factory=lambda s: FakeClient(response), settings=_settings()
        )
        self.assertIsNone(action)

    def test_disabled_flag_returns_none_without_calling_model(self) -> None:
        called = {"n": 0}

        def factory(_s):
            called["n"] += 1
            return FakeClient(ToolCallResponse(text="x"))

        action = agentic_loop.propose_next_action_with_tool_calling(
            _request(), _state(), _frame(), client_factory=factory, settings=_settings(agentic=False)
        )
        self.assertIsNone(action)
        self.assertEqual(called["n"], 0)

    def test_model_exception_falls_back_to_none(self) -> None:
        class Boom:
            def generate_with_tools(self, **kwargs):
                raise RuntimeError("network down")

        action = agentic_loop.propose_next_action_with_tool_calling(
            _request(), _state(), _frame(), client_factory=lambda s: Boom(), settings=_settings()
        )
        self.assertIsNone(action)


class TranscriptTests(unittest.TestCase):
    def test_history_becomes_tool_call_transcript(self) -> None:
        from repooperator_worker.agent_core.actions import AgentAction, ActionResult

        action = AgentAction(type="read_file", reason_summary="r", target_files=["a.py"])
        result = ActionResult(action_id=action.action_id, status="success", observation="file body", files_read=["a.py"])
        state = _state(actions_taken=[action], action_results=[result], files_read=["a.py"])
        messages = agentic_loop._build_transcript(_request(), state, _frame())
        # user turn + assistant tool_call + tool result
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(messages[2]["role"], "tool")
        self.assertIn("file body", messages[2]["content"])
        self.assertIn("a.py", messages[2]["content"])


if __name__ == "__main__":
    unittest.main()
