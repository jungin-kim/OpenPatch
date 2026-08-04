"""Phase 4: agent planner mode is surfaced in debug runtime status."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from repooperator_worker.services.debug_service import _agent_runtime_status


def _settings(*, agentic, base_url="http://127.0.0.1:11434/v1", model="llama3", provider="ollama"):
    return SimpleNamespace(
        agentic_tool_calling=agentic,
        openai_base_url=base_url,
        openai_model=model,
        openai_api_key=None,
        configured_model_provider=provider,
        configured_model_name=model,
        configured_model_connection_mode="local-runtime",
        model_request_timeout_seconds=30,
    )


class AgentRuntimeStatusTests(unittest.TestCase):
    def test_autonomous_when_enabled_and_configured(self) -> None:
        status = _agent_runtime_status(_settings(agentic=True), SimpleNamespace(supports_tool_calls=True))
        self.assertEqual(status["planner"], "autonomous_tool_calling")
        self.assertTrue(status["tool_calling_active"])
        self.assertTrue(status["tool_calling_enabled"])
        self.assertEqual(status["orchestration_mode"], "langgraph")

    def test_guided_when_flag_off(self) -> None:
        status = _agent_runtime_status(_settings(agentic=False), SimpleNamespace(supports_tool_calls=True))
        self.assertEqual(status["planner"], "deterministic")
        self.assertFalse(status["tool_calling_active"])
        self.assertFalse(status["tool_calling_enabled"])

    def test_guided_when_no_endpoint(self) -> None:
        status = _agent_runtime_status(
            _settings(agentic=True, base_url=None, provider="openai-compatible"),
            SimpleNamespace(supports_tool_calls=True),
        )
        self.assertEqual(status["planner"], "deterministic")
        self.assertFalse(status["model_endpoint_configured"])


if __name__ == "__main__":
    unittest.main()
