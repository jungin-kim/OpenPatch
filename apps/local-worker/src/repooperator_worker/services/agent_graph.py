"""
LangGraph-based read-only agent graph for RepoOperator.

Graph shape:
  classify_request → resolve_repo_context → retrieve_or_read_files
                   → answer_read_only → format_response → END

This module is the only part of the agent path that uses LangGraph.
Everything outside this module (API routes, repo open, provider
integration, CLI lifecycle, thread management) remains unchanged.
"""

import logging
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from repooperator_worker.schemas import AgentRunRequest, AgentRunResponse
from repooperator_worker.services.active_repository import (
    ActiveRepository,
    get_active_repository,
)
from repooperator_worker.services.context_service import (
    QueryAwareContext,
    build_query_aware_context,
)
from repooperator_worker.services.model_client import (
    ModelGenerationRequest,
    OpenAICompatibleModelClient,
)
from repooperator_worker.services.retrieval_service import classify_query

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are RepoOperator, a read-only repository assistant.

You have been given repository metadata and the actual contents of relevant files \
retrieved from the repository based on the user's question.

How to answer:
- Ground your answer in the file contents provided. Quote specific functions, classes, \
or lines when useful.
- If multiple files are shown, reason across them to give a complete answer.
- If the retrieved files do not fully answer the question, say so clearly and specify \
which additional files should be inspected.
- Do not speculate about code that is not shown in the context.
- Mention which files you drew from when it adds clarity (e.g. "In main.py, …").
- Keep answers focused and practical."""


# ── State ────────────────────────────────────────────────────────────────────


class AgentGraphState(TypedDict, total=False):
    """Mutable state threaded through all graph nodes.

    Fields are populated incrementally as the graph executes.
    ``total=False`` allows nodes to return partial updates without
    declaring every key upfront.
    """

    # Supplied at graph entry
    request: AgentRunRequest

    # Populated by classify_request
    query_type: str
    file_hints: list[str]

    # Populated by resolve_repo_context
    active_repository: ActiveRepository | None

    # Populated by retrieve_or_read_files
    context: QueryAwareContext | None

    # Populated by answer_read_only
    response_text: str

    # Populated by format_response (final output)
    result: AgentRunResponse | None

    # Set by any node on unrecoverable error
    error: str | None


# ── Nodes ────────────────────────────────────────────────────────────────────


def _classify_request(state: AgentGraphState) -> dict[str, Any]:
    """Classify the user task and extract file hints from the task text.

    Uses the same ``classify_query`` function as the retrieval service so
    that classification logic stays in one place.
    """
    request: AgentRunRequest = state["request"]
    query_type, file_hints = classify_query(request.task)
    logger.debug(
        "agent_graph classify project=%r query_type=%r hints=%r",
        request.project_path,
        query_type,
        file_hints,
    )
    return {"query_type": query_type, "file_hints": file_hints}


def _resolve_repo_context(state: AgentGraphState) -> dict[str, Any]:
    """Validate the active repository against the incoming request.

    Raises ``ValueError`` if the active repository context does not match,
    which propagates as a 400 error through the FastAPI route handler.
    """
    request: AgentRunRequest = state["request"]
    active_repository = get_active_repository()

    if active_repository is not None:
        if request.git_provider and active_repository.git_provider != request.git_provider:
            raise ValueError(
                "Active repository source changed before the answer was generated. "
                "Open the selected repository again and retry."
            )
        if active_repository.project_path != request.project_path:
            raise ValueError(
                "Active repository context does not match this agent request. "
                f"Active: {active_repository.git_provider}:{active_repository.project_path}; "
                f"request: {request.git_provider or 'unknown'}:{request.project_path}."
            )
        if (
            request.branch
            and active_repository.branch
            and request.branch != active_repository.branch
        ):
            raise ValueError(
                "Active repository branch changed before the answer was generated. "
                f"Active branch: {active_repository.branch}; "
                f"request branch: {request.branch}."
            )

    return {"active_repository": active_repository}


def _retrieve_or_read_files(state: AgentGraphState) -> dict[str, Any]:
    """Build query-aware repository context by classifying and retrieving files.

    Delegates to ``build_query_aware_context`` which applies the full
    retrieval pipeline (file-specific, directory, project-review, etc.).
    """
    request: AgentRunRequest = state["request"]
    context = build_query_aware_context(request.project_path, request.task)
    logger.info(
        "agent_graph retrieve project=%r query_type=%r files=%r",
        request.project_path,
        context.retrieval.query_type,
        context.files_read,
    )
    return {"context": context}


def _answer_read_only(state: AgentGraphState) -> dict[str, Any]:
    """Call the model with the assembled repository context and task.

    Builds the full prompt (repository trace header + task + context block)
    and calls the configured OpenAI-compatible model client.
    """
    request: AgentRunRequest = state["request"]
    active_repository: ActiveRepository | None = state.get("active_repository")
    context: QueryAwareContext = state["context"]

    trace_source = request.git_provider or (
        active_repository.git_provider if active_repository else None
    )
    repository_trace = "\n".join(
        [
            "Active repository trace:",
            f"- source: {trace_source or 'unknown'}",
            f"- project_path: {request.project_path}",
            f"- branch: {context.branch or request.branch or 'none'}",
        ]
    )
    user_prompt = (
        f"{repository_trace}\n\nTask:\n{request.task}\n\n{context.to_prompt_context()}"
    )

    client = OpenAICompatibleModelClient()
    response_text = client.generate_text(
        ModelGenerationRequest(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
    )
    return {"response_text": response_text}


def _format_response(state: AgentGraphState) -> dict[str, Any]:
    """Assemble the final ``AgentRunResponse`` from accumulated graph state."""
    request: AgentRunRequest = state["request"]
    active_repository: ActiveRepository | None = state.get("active_repository")
    context: QueryAwareContext = state["context"]
    response_text: str = state["response_text"]

    trace_source = request.git_provider or (
        active_repository.git_provider if active_repository else None
    )
    active_branch = context.branch or request.branch

    # Look up the model name from a fresh client instance (stateless).
    client = OpenAICompatibleModelClient()

    result = AgentRunResponse(
        project_path=request.project_path,
        git_provider=trace_source,
        active_repository_source=trace_source,
        active_repository_path=request.project_path,
        active_branch=active_branch,
        task=request.task,
        model=client.model_name,
        branch=context.branch,
        repo_root_name=context.repo_root_name,
        context_summary=context.summary,
        top_level_entries=context.top_level_entries,
        readme_included=bool(context.readme_excerpt),
        diff_included=False,
        is_git_repository=context.is_git_repository,
        files_read=context.files_read,
        response=response_text,
    )
    return {"result": result}


# ── Graph construction ────────────────────────────────────────────────────────


def _build_agent_graph() -> StateGraph:
    graph = StateGraph(AgentGraphState)

    graph.add_node("classify_request", _classify_request)
    graph.add_node("resolve_repo_context", _resolve_repo_context)
    graph.add_node("retrieve_or_read_files", _retrieve_or_read_files)
    graph.add_node("answer_read_only", _answer_read_only)
    graph.add_node("format_response", _format_response)

    graph.set_entry_point("classify_request")
    graph.add_edge("classify_request", "resolve_repo_context")
    graph.add_edge("resolve_repo_context", "retrieve_or_read_files")
    graph.add_edge("retrieve_or_read_files", "answer_read_only")
    graph.add_edge("answer_read_only", "format_response")
    graph.add_edge("format_response", END)

    return graph


# Compile once at import time; the compiled graph is thread-safe and reusable.
_COMPILED_GRAPH = _build_agent_graph().compile()


# ── Public API ────────────────────────────────────────────────────────────────


def run_agent_graph(request: AgentRunRequest) -> AgentRunResponse:
    """Execute the read-only LangGraph agent and return the response.

    Raises ``ValueError`` for invalid/mismatched repository context and
    ``RuntimeError`` for model or retrieval failures. Both propagate
    unchanged to the FastAPI route handler.
    """
    initial_state: AgentGraphState = {
        "request": request,
        "query_type": "",
        "file_hints": [],
        "active_repository": None,
        "context": None,
        "response_text": "",
        "result": None,
        "error": None,
    }

    final_state: AgentGraphState = _COMPILED_GRAPH.invoke(initial_state)

    result = final_state.get("result")
    if result is None:
        raise RuntimeError("Agent graph did not produce a result.")
    return result
