"""Guard: a bare-JSON final answer (e.g. a leaked skill output_contract) is
detected as needing repair instead of being shown to the user."""

from __future__ import annotations

import unittest

from repooperator_worker.agent_core.final_synthesis import (
    _looks_like_bare_json_answer,
    _needs_general_final_answer_repair,
)
from repooperator_worker.agent_core.state import AgentCoreState


def _state() -> AgentCoreState:
    return AgentCoreState(run_id="r1", thread_id="t1", repo="/tmp/repo", branch=None, user_task="what does this repo do")


class BareJsonAnswerTests(unittest.TestCase):
    def test_detects_plain_json_object(self) -> None:
        answer = '{"include": {"purpose": true, "important_files": ["README.md"]}, "type": "summary"}'
        self.assertTrue(_looks_like_bare_json_answer(answer))
        self.assertTrue(_needs_general_final_answer_repair(answer, _state()))

    def test_detects_fenced_json(self) -> None:
        answer = '```json\n{"type": "summary", "include": ["purpose", "structure"]}\n```'
        self.assertTrue(_looks_like_bare_json_answer(answer))
        self.assertTrue(_needs_general_final_answer_repair(answer, _state()))

    def test_detects_json_array(self) -> None:
        self.assertTrue(_looks_like_bare_json_answer('["README.md", "src/app.py"]'))

    def test_prose_answer_is_not_json(self) -> None:
        answer = "This repository is a local-first coding agent. The decision loop lives in graph_routes.py."
        self.assertFalse(_looks_like_bare_json_answer(answer))
        self.assertFalse(_needs_general_final_answer_repair(answer, _state()))

    def test_prose_that_mentions_json_is_not_flagged(self) -> None:
        answer = "The config is a JSON file like {\"model\": ...} but this sentence is prose, not a bare object."
        self.assertFalse(_looks_like_bare_json_answer(answer))

    def test_empty_is_not_json(self) -> None:
        self.assertFalse(_looks_like_bare_json_answer(""))
        self.assertFalse(_looks_like_bare_json_answer("   "))


if __name__ == "__main__":
    unittest.main()
