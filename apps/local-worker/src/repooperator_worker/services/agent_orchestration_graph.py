"""Compatibility adapter; active execution is handled by agent_core.controller_graph."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterator

from repooperator_worker.agent_core.controller_graph import (
    classify_intent,
    run_controller_graph,
    stream_controller_graph,
)
from repooperator_worker.agent_core.repository_review import (
    MAX_REPOSITORY_REVIEW_BYTES,
    REPOSITORY_REVIEW_BINARY_SUFFIXES,
    REPOSITORY_REVIEW_SUFFIXES,
    run_repository_review,
    should_use_repository_wide_review,
)
from repooperator_worker.schemas import AgentRunRequest, AgentRunResponse


def run_agent_orchestration_graph(request: AgentRunRequest) -> AgentRunResponse:
    """Deprecated adapter for callers that still import the former graph name."""
    return run_controller_graph(request)


def stream_agent_orchestration_graph(request: AgentRunRequest, *, run_id: str | None = None) -> Iterator[dict[str, Any]]:
    """Deprecated adapter for callers that still import the former stream name."""
    yield from stream_controller_graph(request, run_id=run_id)


def _classify_intent(state: dict[str, Any]) -> dict[str, Any]:
    """Deprecated test/helper adapter around the agent_core classifier."""
    request = state["request"]
    classifier = classify_intent(request)
    payload = asdict(classifier)
    payload["classifier"] = "llm" if classifier.raw else "fallback"
    return payload


def _should_use_repository_wide_review(state: dict[str, Any]) -> bool:
    """Deprecated test/helper adapter around the agent_core review gate."""
    class _Classifier:
        target_files = state.get("target_files") or state.get("file_hints") or []
        requires_repository_wide_review = bool(state.get("requires_repository_wide_review"))
        analysis_scope = str(state.get("analysis_scope") or "unknown")
        requested_workflow = str(state.get("requested_workflow") or "other")

    return should_use_repository_wide_review(_Classifier())


def _repository_wide_review(state: dict[str, Any]) -> dict[str, AgentRunResponse]:
    """Deprecated test/helper adapter around the agent_core repository review."""
    request = state["request"]

    class _Classifier:
        intent = str(state.get("intent") or "repo_analysis")

    result = run_repository_review(
        request=request,
        run_id=str(state.get("run_id") or "compat_repository_review"),
        classifier=_Classifier(),
    )
    return {"result": result}
