from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from repooperator_worker.agent_core.actions import AgentAction, ActionResult


@dataclass
class ClassifierResult:
    intent: str = "ambiguous"
    confidence: float = 0.0
    analysis_scope: str = "unknown"
    requested_workflow: str = "other"
    retrieval_goal: str = "answer"
    target_files: list[str] = field(default_factory=list)
    target_symbols: list[str] = field(default_factory=list)
    file_types_requested: list[str] = field(default_factory=list)
    requested_action: str = ""
    git_action: str | None = None
    needs_tool: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    requires_repository_wide_review: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentCoreState:
    run_id: str
    thread_id: str | None
    repo: str
    branch: str | None
    user_task: str
    classifier_result: ClassifierResult = field(default_factory=ClassifierResult)
    plan: list[str] = field(default_factory=list)
    current_step: str | None = None
    observations: list[str] = field(default_factory=list)
    actions_taken: list[AgentAction] = field(default_factory=list)
    action_results: list[ActionResult] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    pending_approval: dict[str, Any] | None = None
    steering_instructions: list[dict[str, Any]] = field(default_factory=list)
    cancellation_requested: bool = False
    skills_used: list[str] = field(default_factory=list)
    memories_used: list[str] = field(default_factory=list)
    recommendation_context: dict[str, Any] | None = None
    stop_reason: str | None = None
    final_response: str = ""
    loop_iteration: int = 0
    max_loop_iterations: int = 8
    max_file_reads: int = 40
    max_commands: int = 8
    max_edits: int = 6

