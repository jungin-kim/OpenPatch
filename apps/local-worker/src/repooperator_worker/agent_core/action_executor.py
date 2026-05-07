from __future__ import annotations

from repooperator_worker.agent_core.actions import AgentAction, ActionResult
from repooperator_worker.agent_core.repository_review import run_repository_review
from repooperator_worker.agent_core.tool_orchestrator import ToolOrchestrator
from repooperator_worker.agent_core.tools.builtin import (
    build_fallback_edit_proposal,
    csharp_roughly_valid,
    extract_source_structure,
    is_supported_text_file,
    model_generate_edit_proposal,
    propose_content_update,
    summarize_diff,
    validate_edit_proposal,
)
from repooperator_worker.agent_core.tools.registry import ToolRegistry, get_default_tool_registry
from repooperator_worker.schemas import AgentRunRequest
from repooperator_worker.services.model_client import OpenAICompatibleModelClient


class ActionExecutor:
    """Compatibility shim for the historical action executor API."""

    def __init__(self, *, run_id: str, request: AgentRunRequest, registry: ToolRegistry | None = None) -> None:
        self.run_id = run_id
        self.request = request
        self.registry = registry or get_default_tool_registry()
        self.orchestrator = ToolOrchestrator(run_id=run_id, request=request, registry=self.registry)

    def execute(self, action: AgentAction) -> ActionResult:
        return self.orchestrator.execute_action(action)


__all__ = [
    "ActionExecutor",
    "OpenAICompatibleModelClient",
    "build_fallback_edit_proposal",
    "csharp_roughly_valid",
    "extract_source_structure",
    "is_supported_text_file",
    "model_generate_edit_proposal",
    "propose_content_update",
    "run_repository_review",
    "summarize_diff",
    "validate_edit_proposal",
]
