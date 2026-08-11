"""Role-aware, non-mutating tool scoping for worker subagents (0.19.0).

Verifies that each worker role is granted the tools it actually needs (web-read,
git-read, command-classify) on top of the base read tools, that unrelated roles
are not, and that these deferred tools are surfaceable to the model.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from repooperator_worker.agent_core import subagent  # noqa: E402
from repooperator_worker.agent_core.tools.registry import get_default_tool_registry  # noqa: E402


class SubagentRoleToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = get_default_tool_registry()

    def test_base_read_tools_available_to_every_role(self) -> None:
        for role in ("AnalysisAgent", "WebResearchAgent", "GitAgent", "TestAgent"):
            allowed = subagent.allowed_tools_for_role(role, self.registry)
            self.assertIn("read_file", allowed)
            self.assertIn("search_text", allowed)

    def test_web_role_gets_web_tools(self) -> None:
        allowed = subagent.allowed_tools_for_role("WebResearchAgent", self.registry)
        self.assertIn("search_web", allowed)
        self.assertIn("fetch_url", allowed)
        self.assertNotIn("git_diff", allowed)

    def test_git_role_gets_git_read_tools_but_no_writes(self) -> None:
        allowed = subagent.allowed_tools_for_role("GitAgent", self.registry)
        self.assertIn("git_diff", allowed)
        self.assertIn("git_status", allowed)
        # Mutating/remote git tools stay with the parent.
        self.assertNotIn("git_commit", allowed)
        self.assertNotIn("git_push", allowed)
        self.assertNotIn("apply_change_set", allowed)

    def test_test_and_validation_roles_get_command_classify_only(self) -> None:
        for role in ("TestAgent", "ValidationAgent"):
            allowed = subagent.allowed_tools_for_role(role, self.registry)
            self.assertIn("preview_command", allowed)
            # Never actual execution.
            self.assertNotIn("run_approved_command", allowed)
            self.assertNotIn("run_validation_command", allowed)

    def test_unrelated_role_has_base_only(self) -> None:
        allowed = subagent.allowed_tools_for_role("AnalysisAgent", self.registry)
        self.assertNotIn("search_web", allowed)
        self.assertNotIn("git_diff", allowed)
        self.assertNotIn("preview_command", allowed)

    def test_deferred_role_tool_is_surfaceable_to_model(self) -> None:
        specs = self.registry.specs_for_model(tool_names={"git_diff"}, include_default=False)
        names = {spec["name"] for spec in specs}
        self.assertIn("git_diff", names)


if __name__ == "__main__":
    unittest.main()
