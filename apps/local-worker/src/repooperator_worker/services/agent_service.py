"""
Agent service — public entry point for /agent/run.

The execution path now uses LangGraph (via ``agent_graph.run_agent_graph``).
If LangGraph is unavailable for any reason, the service falls back to the
legacy direct execution path so existing Q&A behavior is never broken.

What moved into LangGraph (agent_graph.py):
  - classify_request   — query classification + file hint extraction
  - resolve_repo_context — active-repository validation
  - retrieve_or_read_files — file retrieval pipeline
  - answer_read_only   — model call
  - format_response    — AgentRunResponse assembly

What stayed outside LangGraph (unchanged):
  - FastAPI routes  (api/routes.py)
  - Repository open flow  (repo_service.py)
  - Provider integration  (provider_service.py, git_providers.py)
  - Thread persistence  (thread_service.py)
  - CLI lifecycle  (packages/cli)
  - Web UI state  (apps/web)
"""

import logging

from repooperator_worker.schemas import AgentRunRequest, AgentRunResponse
from repooperator_worker.services.active_repository import ActiveRepository, get_active_repository
from repooperator_worker.services.context_service import build_query_aware_context
from repooperator_worker.services.model_client import (
    ModelGenerationRequest,
    OpenAICompatibleModelClient,
)

logger = logging.getLogger(__name__)

_USE_LANGGRAPH = True  # set to False to force the legacy path for debugging

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


def run_agent_task(request: AgentRunRequest) -> AgentRunResponse:
    """Run the agent task, using LangGraph when available.

    Falls back to the legacy direct execution path if the graph raises an
    unexpected import or runtime error that is not a user-facing ValueError.
    """
    if _USE_LANGGRAPH:
        try:
            from repooperator_worker.services.agent_graph import run_agent_graph

            logger.debug("agent_service: using LangGraph execution path")
            return run_agent_graph(request)
        except (ValueError, RuntimeError):
            # User-facing errors (bad repo context, model failure) — re-raise
            # so the route handler can return the correct HTTP status.
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "agent_service: LangGraph path failed with unexpected error %r, "
                "falling back to legacy path",
                exc,
            )

    logger.debug("agent_service: using legacy execution path")
    return _run_agent_task_legacy(request)


# ── Legacy execution path (kept as safe fallback) ─────────────────────────────


def _run_agent_task_legacy(request: AgentRunRequest) -> AgentRunResponse:
    """Original direct execution path, preserved as a fallback."""
    active_repository = _validate_active_repository(request)
    context = build_query_aware_context(request.project_path, request.task)
    client = OpenAICompatibleModelClient()

    files_read = context.files_read
    logger.info(
        "agent_run_legacy project=%r task_len=%d query_type=%r files_retrieved=%d files=%r",
        request.project_path,
        len(request.task),
        context.retrieval.query_type,
        len(files_read),
        files_read,
    )

    trace_source = request.git_provider or (
        active_repository.git_provider if active_repository else None
    )
    repository_trace = _format_repository_trace(
        git_provider=trace_source,
        project_path=request.project_path,
        branch=context.branch or request.branch,
    )
    user_prompt = f"{repository_trace}\n\nTask:\n{request.task}\n\n{context.to_prompt_context()}"

    response_text = client.generate_text(
        ModelGenerationRequest(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
    )

    return AgentRunResponse(
        project_path=request.project_path,
        git_provider=trace_source,
        active_repository_source=trace_source,
        active_repository_path=request.project_path,
        active_branch=context.branch or request.branch,
        task=request.task,
        model=client.model_name,
        branch=context.branch,
        repo_root_name=context.repo_root_name,
        context_summary=context.summary,
        top_level_entries=context.top_level_entries,
        readme_included=bool(context.readme_excerpt),
        diff_included=False,
        is_git_repository=context.is_git_repository,
        files_read=files_read,
        response=response_text,
    )


def _validate_active_repository(request: AgentRunRequest) -> ActiveRepository | None:
    active_repository = get_active_repository()
    if active_repository is None:
        return None

    if request.git_provider and active_repository.git_provider != request.git_provider:
        raise ValueError(
            "Active repository source changed before the answer was generated. "
            "Open the selected repository again and retry."
        )

    if active_repository.project_path != request.project_path:
        raise ValueError(
            "Active repository context does not match this agent request. "
            f"Active repository is {active_repository.git_provider}:{active_repository.project_path}; "
            f"request was {request.git_provider or 'unknown'}:{request.project_path}."
        )

    if request.branch and active_repository.branch and request.branch != active_repository.branch:
        raise ValueError(
            "Active repository branch changed before the answer was generated. "
            f"Active branch is {active_repository.branch}; request branch was {request.branch}."
        )

    return active_repository


def _format_repository_trace(
    *,
    git_provider: str | None,
    project_path: str,
    branch: str | None,
) -> str:
    return "\n".join(
        [
            "Active repository trace:",
            f"- source: {git_provider or 'unknown'}",
            f"- project_path: {project_path}",
            f"- branch: {branch or 'none'}",
        ]
    )
