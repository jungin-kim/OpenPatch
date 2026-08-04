"""Model-driven agentic decision loop (native tool calling).

This is the Phase 1 replacement for the deterministic ``choose_graph_next_action``
priority chain as the *primary* planner. Instead of Python heuristics deciding
the next tool, the model sees the real tool schemas plus the running
think -> act -> observe transcript and emits a native tool call. Each graph
iteration calls :func:`propose_next_action_with_tool_calling`, which maps the
model's chosen tool call into an :class:`AgentAction`; execution, permissions,
secret redaction, and budgets remain enforced by the existing tool orchestrator
and graph budget checks.

When the model is not tool-calling-capable, not configured, or declines to
produce a usable call, this returns ``None`` and the deterministic choosers in
``graph_routes.py`` take over as a safety fallback.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from repooperator_worker.agent_core.actions import AgentAction
from repooperator_worker.agent_core.model_profile import detect_model_profile
from repooperator_worker.agent_core.state import AgentCoreState
from repooperator_worker.agent_core.tools.registry import get_default_tool_registry
from repooperator_worker.config import Settings, get_settings
from repooperator_worker.schemas import AgentRunRequest
from repooperator_worker.services.json_safe import json_safe
from repooperator_worker.services.model_client import build_model_client, resolve_model_provider

MAX_TRANSCRIPT_ACTIONS = 12
MAX_OBSERVATION_CHARS = 1500
MAX_ANSWER_CHARS = 8000

AGENTIC_SYSTEM_PROMPT = """\
You are RepoOperator, an autonomous local repository agent working on a
checked-out repository through a set of safe tools.

Operate as a think -> act -> observe loop:
- Choose exactly one tool call that makes the most progress on the user's task.
- ALWAYS gather evidence first: inspect the repository tree and read the
  relevant files (e.g. README, entry points) BEFORE answering. Never answer a
  question about the repository from prior knowledge or assumptions — even a
  high-level summary must be grounded in files you actually read this run.
- All file paths must be repository-relative; never invent files or contents.
- Mutating, command, and network tools are gated by an approval policy. Request
  them only when genuinely needed; they may pause for user approval.
- Do not repeat a tool call that already failed or returned nothing useful.
- When you have enough grounded evidence, call `final_answer`. If the task is
  ambiguous and evidence cannot resolve it, call `ask_clarification`.

Keep any user-visible reasoning in the tool call's `reason_summary`; do not emit
hidden or private deliberation.
"""


def endpoint_configured(settings: Settings) -> bool:
    """Whether a reachable model endpoint + model name are configured."""

    if not settings.openai_model:
        return False
    if resolve_model_provider(settings) == "anthropic":
        return bool(settings.openai_api_key or settings.openai_base_url)
    return bool(settings.openai_base_url)


def tool_calling_available(settings: Settings | None = None) -> bool:
    """Whether the model-driven loop should act as the primary planner."""

    settings = settings or get_settings()
    if not settings.agentic_tool_calling:
        return False
    if not endpoint_configured(settings):
        return False
    return bool(detect_model_profile(settings=settings).supports_tool_calls)


def propose_next_action_with_tool_calling(
    request: AgentRunRequest,
    state: AgentCoreState,
    task_frame: Any,
    *,
    client_factory: Callable[[Settings], Any] = build_model_client,
    settings: Settings | None = None,
) -> AgentAction | None:
    """Ask the model for the next tool call and map it to an AgentAction."""

    settings = settings or get_settings()
    if not tool_calling_available(settings):
        return None

    registry = get_default_tool_registry()
    allowed = set(registry.allowed_action_types())
    tool_specs = registry.specs_for_model(
        capabilities=_capability_hints(registry, task_frame),
        tool_names=[str(item) for item in getattr(task_frame, "likely_needed_tools", []) or []],
    )
    if not tool_specs:
        return None

    messages = _build_transcript(request, state, task_frame)
    try:
        profile = detect_model_profile(settings=settings)
        response = client_factory(settings).generate_with_tools(
            system_prompt=AGENTIC_SYSTEM_PROMPT,
            messages=messages,
            tools=tool_specs,
            tool_choice="auto",
            max_output_tokens=min(4096, profile.max_output_tokens),
        )
    except Exception:
        return None

    action = _action_from_response(response, allowed)
    # Guard against a lazy model that answers (or asks to clarify) before
    # gathering any evidence. Defer to the deterministic evidence-gathering
    # choosers so the agent inspects the tree / reads files first; the model
    # gets another turn once real evidence is in the transcript.
    if action is not None and action.type in {"final_answer", "ask_clarification"} and not _has_min_evidence(state):
        return None
    return action


_EVIDENCE_ACTION_TYPES = frozenset(
    {
        "inspect_repo_tree",
        "read_file",
        "read_many_files",
        "search_files",
        "search_text",
        "analyze_file",
        "analyze_repository",
        "inspect_symbol",
        "run_approved_command",
        "inspect_git_state",
    }
)


def _has_min_evidence(state: AgentCoreState) -> bool:
    """Whether the run has gathered any repository evidence yet."""

    if getattr(state, "files_read", None):
        return True
    if getattr(state, "commands_run", None):
        return True
    for action in getattr(state, "actions_taken", []) or []:
        if getattr(action, "type", None) in _EVIDENCE_ACTION_TYPES:
            return True
    return False


def _capability_hints(registry, task_frame: Any) -> list[str]:
    hints = [str(item).strip() for item in getattr(task_frame, "likely_capabilities", []) or [] if str(item).strip()]
    for tool_hint in getattr(task_frame, "likely_needed_tools", []) or []:
        hints.extend(registry.capabilities_for_tool(str(tool_hint), available_only=True))
    seen: list[str] = []
    for hint in hints:
        if hint and hint not in seen:
            seen.append(hint)
    return seen


def _build_transcript(request: AgentRunRequest, state: AgentCoreState, task_frame: Any) -> list[dict[str, Any]]:
    user_payload = {
        "task": request.task,
        "task_frame": json_safe(task_frame),
        "context_packet": json_safe(getattr(state, "context_packet", {}) or {}),
        "files_read": list(getattr(state, "files_read", []) or []),
        "budgets": {
            "max_file_reads": getattr(state, "max_file_reads", None),
            "max_commands": getattr(state, "max_commands", None),
            "loop_iteration": getattr(state, "loop_iteration", None),
        },
    }
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
    ]

    actions = list(getattr(state, "actions_taken", []) or [])
    results = list(getattr(state, "action_results", []) or [])
    for action, result in list(zip(actions, results))[-MAX_TRANSCRIPT_ACTIONS:]:
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": action.action_id,
                        "type": "function",
                        "function": {
                            "name": action.type,
                            "arguments": json.dumps(_action_arguments(action), ensure_ascii=False),
                        },
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": action.action_id,
                "content": _observation_text(result),
            }
        )
    return messages


def _action_arguments(action: AgentAction) -> dict[str, Any]:
    args: dict[str, Any] = dict(action.payload or {})
    if action.target_files:
        args.setdefault("target_files", list(action.target_files))
    if action.target_symbols:
        args.setdefault("target_symbols", list(action.target_symbols))
    if action.command:
        args.setdefault("command", list(action.command))
    return args


def _observation_text(result: Any) -> str:
    if result is None:
        return "(no result)"
    parts = [f"status={getattr(result, 'status', 'unknown')}"]
    observation = str(getattr(result, "observation", "") or "")
    if observation:
        parts.append(observation)
    files_read = list(getattr(result, "files_read", []) or [])
    if files_read:
        parts.append("files_read: " + ", ".join(files_read[:10]))
    payload = getattr(result, "payload", {}) or {}
    if isinstance(payload, dict):
        candidates = payload.get("candidates")
        if isinstance(candidates, list) and candidates:
            names = [str(c.get("path") if isinstance(c, dict) else c) for c in candidates[:10]]
            parts.append("candidates: " + ", ".join(names))
        matches = payload.get("matches")
        if isinstance(matches, list) and matches:
            parts.append(f"matches: {len(matches)}")
    text = "\n".join(parts)
    if len(text) > MAX_OBSERVATION_CHARS:
        text = text[:MAX_OBSERVATION_CHARS] + "\n…(truncated)"
    return text


def _action_from_response(response: Any, allowed: set[str]) -> AgentAction | None:
    if getattr(response, "has_tool_calls", False):
        call = response.tool_calls[0]
        name = str(call.name or "")
        if name not in allowed:
            return None
        args = dict(call.arguments or {})
        reason = str(args.get("reason_summary") or (response.text or "") or f"Use {name} for the next step.").strip()
        action = AgentAction(
            type=name,  # type: ignore[arg-type]
            reason_summary=(reason or f"Use {name}.")[:300],
            payload=json_safe(args),
        )
        _map_common_fields(action, args)
        return action

    text = (getattr(response, "text", "") or "").strip()
    if text:
        return AgentAction(
            type="final_answer",
            reason_summary="Answer from gathered evidence.",
            payload={"model_answer": text[:MAX_ANSWER_CHARS]},
        )
    return None


def _map_common_fields(action: AgentAction, args: dict[str, Any]) -> None:
    files = _string_list(args, ("target_files", "paths", "files", "path", "file"))
    if files:
        action.target_files = files
    symbols = _string_list(args, ("target_symbols", "symbols", "symbol", "symbol_queries"))
    if symbols:
        action.target_symbols = symbols
    command = args.get("command")
    if isinstance(command, list) and command:
        action.command = [str(item) for item in command]
    expected = args.get("expected_output")
    if expected:
        action.expected_output = str(expected)


def _string_list(args: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            out.append(value.strip().lstrip("/"))
        elif isinstance(value, list):
            out.extend(str(item).strip().lstrip("/") for item in value if str(item).strip())
    deduped: list[str] = []
    for item in out:
        if item and item not in deduped:
            deduped.append(item)
    return deduped
