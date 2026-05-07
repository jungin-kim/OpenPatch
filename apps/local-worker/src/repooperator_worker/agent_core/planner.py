from __future__ import annotations

from dataclasses import dataclass, field

from repooperator_worker.agent_core.tools.registry import get_default_tool_registry


PLANNER_ACTION_TYPES = set(get_default_tool_registry().allowed_action_types())


NEXT_ACTION_PROMPT = """\
You are RepoOperator's bounded next-action planner. Return JSON only.
Choose one safe primitive action from the available tool specs. Do not use hidden reasoning.
Schema:
{
  "action_type": "one of available_actions",
  "reason_summary": "short user-visible reason",
  "target_files": [],
  "target_symbols": [],
  "search_queries": [],
  "text_queries": [],
  "symbol_queries": [],
  "file_globs": [],
  "command": [],
  "expected_output": "short description",
  "requires_approval": false,
  "confidence": 0.0,
  "enough_evidence": false
}
Prefer gathering missing evidence before answering. Commands are policy-previewed later; never request direct shell execution.
"""


@dataclass
class TaskFrame:
    user_goal: str
    mentioned_files: list[str] = field(default_factory=list)
    mentioned_symbols: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    likely_capabilities: list[str] = field(default_factory=list)
    answer_style: str | None = None
    safety_notes: list[str] = field(default_factory=list)
    uncertainty: list[str] = field(default_factory=list)
    should_ask_clarification: bool = False
    clarification_question: str | None = None
    legacy_intent: str | None = None


def build_task_frame(*args, **kwargs):
    from repooperator_worker.agent_core.controller_graph import build_task_frame as _impl

    return _impl(*args, **kwargs)


def propose_next_action_with_model(*args, **kwargs):
    from repooperator_worker.agent_core.controller_graph import propose_next_action_with_model as _impl

    return _impl(*args, **kwargs)


def validate_model_next_action(*args, **kwargs):
    from repooperator_worker.agent_core.controller_graph import validate_model_next_action as _impl

    return _impl(*args, **kwargs)
