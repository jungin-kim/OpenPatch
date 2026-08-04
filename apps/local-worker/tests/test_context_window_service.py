"""Context-window snapshot for the per-chat context UI."""

from __future__ import annotations

import unittest

from repooperator_worker.services.context_window_service import _tokens, context_window_snapshot


class ContextWindowSnapshotTests(unittest.TestCase):
    def test_token_estimate(self) -> None:
        self.assertEqual(_tokens(None), 0)
        self.assertEqual(_tokens("abcd"), 1)  # 4 chars ~= 1 token
        self.assertGreater(_tokens({"a": "x" * 40}), 5)

    def test_snapshot_shape(self) -> None:
        snap = context_window_snapshot()
        self.assertIn("context_window", snap)
        self.assertGreater(snap["context_window"], 0)
        self.assertIn("max_output_tokens", snap)
        for key in ("system_prompt", "system_tools", "mcp_tools", "skills"):
            self.assertIn(key, snap["components"])
            self.assertGreaterEqual(snap["components"][key], 0)
        self.assertIn("system_tools", snap["deferred"])
        # Loaded system tools should carry real token weight.
        self.assertGreater(snap["components"]["system_tools"], 0)


if __name__ == "__main__":
    unittest.main()
