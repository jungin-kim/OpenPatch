"""Tests for auto-compaction of out-of-window conversation history (0.18.0).

Older turns beyond the keep-window are summarized by one cached model call
instead of being silently dropped. The model is mocked; no network is used.
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from repooperator_worker.agent_core import agentic_loop  # noqa: E402


def _request(turns, task="current task", thread_id="t1"):
    return types.SimpleNamespace(
        conversation_history=[{"role": r, "content": c} for r, c in turns],
        task=task,
        thread_id=thread_id,
    )


class HistoryCompactionTests(unittest.TestCase):
    def setUp(self) -> None:
        agentic_loop._HISTORY_SUMMARY_CACHE.clear()

    def test_short_history_is_verbatim_and_makes_no_model_call(self) -> None:
        turns = [("user", "first question"), ("assistant", "first answer")]
        fake_client = mock.Mock()
        with mock.patch.object(agentic_loop, "endpoint_configured", return_value=True), \
             mock.patch.object(agentic_loop, "build_model_client", return_value=fake_client), \
             mock.patch.object(agentic_loop, "get_settings", return_value=object()):
            messages = agentic_loop._recent_history_messages(_request(turns))
        self.assertEqual(messages, [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
        ])
        fake_client.generate_text.assert_not_called()

    def test_long_history_prepends_one_cached_summary(self) -> None:
        turns = [(("user" if i % 2 == 0 else "assistant"), f"turn number {i}") for i in range(14)]
        fake_client = mock.Mock()
        fake_client.generate_text.return_value = "- earlier decisions summarized"
        with mock.patch.object(agentic_loop, "endpoint_configured", return_value=True), \
             mock.patch.object(agentic_loop, "build_model_client", return_value=fake_client), \
             mock.patch.object(agentic_loop, "get_settings", return_value=object()):
            req = _request(turns)
            first = agentic_loop._recent_history_messages(req)
            second = agentic_loop._recent_history_messages(req)  # same run → cache hit

        # First message is the compaction summary; the rest are the kept window.
        self.assertTrue(first[0]["content"].startswith("[Earlier conversation summary"))
        self.assertIn("earlier decisions summarized", first[0]["content"])
        # Kept window is the most recent MAX_HISTORY_TURNS turns, verbatim.
        kept = first[1:]
        self.assertEqual(len(kept), agentic_loop.MAX_HISTORY_TURNS)
        self.assertEqual(kept[-1]["content"], "turn number 13")
        # One model call total despite two builds (cache).
        fake_client.generate_text.assert_called_once()
        self.assertEqual(second[0], first[0])

    def test_no_summary_when_model_unavailable(self) -> None:
        turns = [(("user" if i % 2 == 0 else "assistant"), f"turn number {i}") for i in range(14)]
        with mock.patch.object(agentic_loop, "endpoint_configured", return_value=False), \
             mock.patch.object(agentic_loop, "get_settings", return_value=object()):
            messages = agentic_loop._recent_history_messages(_request(turns))
        # Gracefully falls back to the previous behaviour: keep window only.
        self.assertEqual(len(messages), agentic_loop.MAX_HISTORY_TURNS)
        self.assertFalse(messages[0]["content"].startswith("[Earlier conversation summary"))

    def test_summary_failure_is_swallowed(self) -> None:
        turns = [(("user" if i % 2 == 0 else "assistant"), f"turn number {i}") for i in range(14)]
        fake_client = mock.Mock()
        fake_client.generate_text.side_effect = RuntimeError("boom")
        with mock.patch.object(agentic_loop, "endpoint_configured", return_value=True), \
             mock.patch.object(agentic_loop, "build_model_client", return_value=fake_client), \
             mock.patch.object(agentic_loop, "get_settings", return_value=object()):
            messages = agentic_loop._recent_history_messages(_request(turns))
        self.assertEqual(len(messages), agentic_loop.MAX_HISTORY_TURNS)  # no summary, no crash


if __name__ == "__main__":
    unittest.main()
