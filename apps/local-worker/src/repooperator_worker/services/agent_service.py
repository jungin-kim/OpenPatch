"""
Agent service — public entry point for /agent/run.

The execution path now uses LangGraph (via ``agent_graph.run_agent_graph``).
If LangGraph is unavailable for any reason, the service falls back to the
legacy direct execution path so existing Q&A behavior is never broken.

Write intent routing intercepts the request before the read-only graph runs.
If the user's task contains write-intent signals AND the current permission
mode allows it, a change proposal is generated inline.  This lets the normal
chat composer handle both Q&A and coding-agent write requests.
"""

import logging
import re
from pathlib import Path

from repooperator_worker.config import (
    WRITE_MODE_AUTO_APPLY,
    WRITE_MODE_WRITE_WITH_APPROVAL,
    get_settings,
)
from repooperator_worker.schemas import AgentRunRequest, AgentRunResponse
from repooperator_worker.services.active_repository import ActiveRepository, get_active_repository
from repooperator_worker.services.context_service import build_query_aware_context
from repooperator_worker.services.model_client import (
    ModelGenerationRequest,
    OpenAICompatibleModelClient,
)

logger = logging.getLogger(__name__)

_USE_LANGGRAPH = True  # set to False to force the legacy path for debugging

# ── Write intent detection ────────────────────────────────────────────────────

_WRITE_INTENT_KEYWORDS = frozenset({
    # English
    "change", "update", "fix", "modify", "refactor", "add", "remove", "delete",
    "highlight", "implement", "edit", "rewrite", "rename", "replace", "insert",
    "improve", "enhance", "convert", "format", "clean", "restructure",
    "reorganize", "move", "make", "create",
    # Korean
    "수정", "바꿔", "고쳐", "추가", "하이라이트", "변경", "만들어", "구현",
    "삭제", "수정해", "변경해", "추가해", "리팩토링", "개선", "고쳐줘",
    "바꿔줘", "만들어줘", "구현해줘", "추가해줘", "삭제해줘",
})

_FILE_HINT_RE = re.compile(r'\b([\w./\\-]+\.[a-zA-Z]{1,6})\b', re.ASCII)

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

def _extract_pending_context_from_history(
    history: list,
) -> tuple[list[str], str]:
    """Scan conversation history for the most recent assistant suggestion with file hints.

    Returns (file_hints, suggestion_text).  file_hints may be empty if the
    assistant's previous message contained no recognisable filenames.
    """
    from repooperator_worker.services.retrieval_service import SOURCE_EXTENSIONS

    for msg in reversed(history):
        if getattr(msg, "role", None) != "assistant":
            continue
        content = getattr(msg, "content", "") or ""
        # Extract file hints from the assistant's previous response
        hints: list[str] = []
        for match in _FILE_HINT_RE.finditer(content):
            candidate = match.group(1)
            suffix = Path(candidate).suffix.lower()
            if suffix in SOURCE_EXTENSIONS and not candidate.lower().startswith("http"):
                hints.append(candidate)
        # Even without file hints return the text so the caller can decide
        return hints, content

    return [], ""


def detect_write_intent(task: str) -> tuple[bool, list[str]]:
    """Return (is_write_request, file_hints) for a user task string.

    Uses keyword matching for English and Korean write-intent signals plus
    file-extension detection.  Not perfect, but handles common coding-agent
    requests reliably.
    """
    from repooperator_worker.services.retrieval_service import SOURCE_EXTENSIONS

    lower = task.lower()
    tokens = re.findall(r'\w+', lower)
    has_keyword = any(tok in _WRITE_INTENT_KEYWORDS for tok in tokens)

    # Korean non-word characters (e.g. 수정해줘) need substring match
    if not has_keyword:
        has_keyword = any(kw in lower for kw in _WRITE_INTENT_KEYWORDS if not kw.isascii())

    file_hints: list[str] = []
    for match in _FILE_HINT_RE.finditer(task):
        candidate = match.group(1)
        suffix = Path(candidate).suffix.lower()
        if suffix in SOURCE_EXTENSIONS and not candidate.lower().startswith("http"):
            file_hints.append(candidate)

    return has_keyword, file_hints


def _resolve_write_target(
    project_path: str, file_hints: list[str]
) -> tuple[str | None, list[str]]:
    """Return (resolved_relative_path | None, candidate_paths).

    If exactly one file matches, return it.  If multiple match, return
    None + candidate list so the caller can ask for clarification.
    """
    from repooperator_worker.services.retrieval_service import SKIP_DIRS

    try:
        from repooperator_worker.services.common import resolve_project_path
        repo_path = resolve_project_path(project_path)
    except Exception:
        return None, []

    def _find(filename: str) -> list[Path]:
        target_name = Path(filename).name.lower()
        matches: list[Path] = []
        for path in repo_path.rglob("*"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if not path.is_file():
                continue
            name = path.name.lower()
            if name == target_name or target_name in name:
                matches.append(path)
        matches.sort(key=lambda p: (len(p.parts), str(p)))
        return matches

    for hint in file_hints:
        matches = _find(hint)
        if len(matches) == 1:
            return str(matches[0].relative_to(repo_path)), []
        if len(matches) > 1:
            candidates = [str(m.relative_to(repo_path)) for m in matches[:5]]
            return None, candidates

    return None, []


def _build_minimal_run_response(request: AgentRunRequest, *, response: str, response_type: str = "assistant_answer") -> AgentRunResponse:
    """Build a minimal AgentRunResponse for write-intent routing outcomes."""
    settings = get_settings()
    client = OpenAICompatibleModelClient()
    try:
        model_name = client.model_name
    except ValueError:
        model_name = settings.configured_model_name or "unknown"
    return AgentRunResponse(
        project_path=request.project_path,
        git_provider=request.git_provider,
        active_repository_source=request.git_provider,
        active_repository_path=request.project_path,
        active_branch=request.branch,
        task=request.task,
        model=model_name,
        branch=request.branch,
        repo_root_name=request.project_path.split("/")[-1] or request.project_path,
        context_summary="",
        top_level_entries=[],
        readme_included=False,
        diff_included=False,
        is_git_repository=True,
        files_read=[],
        response=response,
        response_type=response_type,
    )


def _find_original_user_instruction(history: list) -> str | None:
    """Return the most recent user message that looks like a write instruction."""
    for msg in reversed(history):
        if getattr(msg, "role", None) != "user":
            continue
        content = getattr(msg, "content", "") or ""
        has_keyword, _ = detect_write_intent(content)
        if has_keyword:
            return content
        return content
    return None


def _generate_proposal(
    request: AgentRunRequest,
    resolved_path: str,
    instruction: str,
) -> AgentRunResponse:
    """Generate a change proposal for a resolved file path and return the response."""
    from repooperator_worker.schemas import AgentProposeFileRequest
    from repooperator_worker.services.edit_service import propose_file_edit

    proposal = propose_file_edit(
        AgentProposeFileRequest(
            project_path=request.project_path,
            relative_path=resolved_path,
            instruction=instruction,
        )
    )
    base = _build_minimal_run_response(
        request,
        response=f"Proposed change to `{resolved_path}`. Review the diff and apply if it looks correct.",
        response_type="change_proposal",
    )
    return base.model_copy(update={
        "model": proposal.model,
        "proposal_relative_path": proposal.relative_path,
        "proposal_original_content": proposal.original_content,
        "proposal_proposed_content": proposal.proposed_content,
        "proposal_context_summary": proposal.context_summary,
        "files_read": [proposal.relative_path],
    })


def _route_write_request(
    request: AgentRunRequest,
    file_hints: list[str],
    instruction: str,
) -> AgentRunResponse:
    """Resolve target file and generate a proposal, or return a clarification."""
    resolved_path, candidates = _resolve_write_target(request.project_path, file_hints)

    if not resolved_path and candidates:
        candidate_list = "\n".join(f"- `{c}`" for c in candidates)
        return _build_minimal_run_response(
            request,
            response=f"I found multiple possible targets. Choose one to continue:\n\n{candidate_list}",
        )

    if not resolved_path and not file_hints:
        return _build_minimal_run_response(
            request,
            response=(
                "I need one target from the repository context before preparing a diff. "
                "Choose a recent file, name a symbol, or ask RepoOperator to recommend targets."
            ),
        )

    if not resolved_path:
        hint_list = ", ".join(f"`{h}`" for h in file_hints)
        return _build_minimal_run_response(
            request,
            response=f"I could not find {hint_list} in this repository. Check the file name and try again.",
        )

    try:
        return _generate_proposal(request, resolved_path, instruction)
    except (ValueError, RuntimeError) as exc:
        logger.warning("agent_service: proposal generation failed: %r", exc)
        return _build_minimal_run_response(
            request,
            response=f"Unable to generate a proposal: {exc}",
        )


def run_agent_task(request: AgentRunRequest) -> AgentRunResponse:
    """Run the agent task, using LangGraph when available.

    Write-intent requests are intercepted before the read-only graph:
    - In read-only mode: the user is told to switch to Auto review.
    - In write-with-approval mode: a change proposal is generated inline.

    Write confirmations ("응 바꿔줘", "go ahead", …) are resolved against the
    most recent assistant suggestion in conversation_history.

    Falls back to the legacy direct execution path if LangGraph raises an
    unexpected import or runtime error that is not a user-facing ValueError.
    """
    if _USE_LANGGRAPH:
        try:
            from repooperator_worker.services.agent_orchestration_graph import (
                run_agent_orchestration_graph,
            )

            logger.debug("agent_service: using LangGraph orchestration path")
            return run_agent_orchestration_graph(request)
        except (ValueError, RuntimeError):
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "agent_service: LangGraph orchestration failed with unexpected error %r; "
                "falling back to legacy routing",
                exc,
            )

    settings = get_settings()

    # ── Direct write intent legacy fallback ──────────────────────────────────
    is_write, file_hints = detect_write_intent(request.task)

    if is_write:
        if settings.write_mode not in {WRITE_MODE_WRITE_WITH_APPROVAL, WRITE_MODE_AUTO_APPLY}:
            logger.info(
                "agent_service: write intent detected but mode=%r — returning permission_required",
                settings.write_mode,
            )
            return _build_minimal_run_response(
                request,
                response=(
                    "This looks like a code change request. "
                    "Switch the permission mode to **Auto review** to let RepoOperator "
                    "propose a diff for your approval."
                ),
                response_type="permission_required",
            )

        logger.info(
            "agent_service: write intent detected, mode=write-with-approval, hints=%r",
            file_hints,
        )
        return _route_write_request(request, file_hints, request.task)

    if _USE_LANGGRAPH:
        try:
            from repooperator_worker.services.agent_graph import run_agent_graph

            logger.debug("agent_service: using LangGraph execution path")
            return run_agent_graph(request)
        except (ValueError, RuntimeError):
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
