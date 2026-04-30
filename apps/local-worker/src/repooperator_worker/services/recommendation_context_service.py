"""Structured recommendation context for follow-up proposal flows."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repooperator_worker.schemas import AgentRunRequest
from repooperator_worker.services.common import resolve_project_path
from repooperator_worker.services.model_client import (
    ModelGenerationRequest,
    OpenAICompatibleModelClient,
)


@dataclass
class RecommendationItem:
    id: str
    files: list[str]
    symbols: list[str] = field(default_factory=list)
    suggested_changes: list[str] = field(default_factory=list)
    rationale: str = ""
    risk_level: str = "medium"
    category: str = "code"
    needs_more_inspection: bool = False


def build_recommendation_context(
    *,
    request: AgentRunRequest,
    files_read: list[str],
    response: str,
    candidate_files: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    repo = request.project_path
    branch = request.branch
    seed = f"{repo}:{branch}:{request.task}:{time.time_ns()}"
    recommendation_id = "rec_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    candidates = candidate_files or [(path, "confirmed from inspected repository context") for path in files_read]
    items: list[dict[str, Any]] = []
    for index, (relative_path, reason) in enumerate(candidates[:8], start=1):
        item_id = f"{recommendation_id}_{index}"
        category = _category_for_path(relative_path)
        items.append(
            {
                "id": item_id,
                "files": [relative_path],
                "symbols": [],
                "suggested_changes": [_suggestion_for_path(relative_path, category)],
                "rationale": reason,
                "risk_level": "low" if category in {"docs", "test"} else "medium",
                "category": category,
                "needs_more_inspection": relative_path not in files_read,
            }
        )
    return {
        "recommendation_id": recommendation_id,
        "source_user_request_summary": _summarize(request.task),
        "recommended_files": sorted({file for item in items for file in item["files"]}),
        "recommended_symbols": [],
        "items": items,
        "rationale": _summarize(response, 500),
        "risk_level": "medium" if items else "low",
        "category": "mixed" if len({item["category"] for item in items}) > 1 else (items[0]["category"] if items else "code"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo": repo,
        "branch": branch,
    }


def recommendation_context_from_history(request: AgentRunRequest) -> dict[str, Any] | None:
    for message in reversed(request.conversation_history):
        metadata = message.metadata if isinstance(message.metadata, dict) else {}
        context = metadata.get("recommendation_context")
        if isinstance(context, dict) and context.get("repo") == request.project_path:
            if context.get("branch") in {request.branch, None, ""}:
                return context
    return None


def resolve_recommendation_followup(
    *,
    request: AgentRunRequest,
    recommendation_context: dict[str, Any],
) -> dict[str, Any]:
    """Use the model to resolve a follow-up against structured recommendations."""
    try:
        raw = OpenAICompatibleModelClient().generate_text(
            ModelGenerationRequest(
                system_prompt=(
                    "You resolve whether a user's latest message refers to previous structured "
                    "repository recommendations. Return JSON only with this schema: "
                    "{\"refers_to_previous_recommendation\": boolean, "
                    "\"selected_recommendation_ids\": [string], \"selected_files\": [string], "
                    "\"requested_action\": \"generate_proposal|explain_more|narrow_scope|clarify\", "
                    "\"confidence\": number, \"needs_clarification\": boolean, "
                    "\"clarification_question\": string|null}. Do not include prose."
                ),
                user_prompt=json.dumps(
                    {
                        "message": request.task,
                        "recent_messages": [
                            {"role": msg.role, "content": msg.content[:400]}
                            for msg in request.conversation_history[-6:]
                        ],
                        "recommendation_context": recommendation_context,
                    },
                    ensure_ascii=False,
                ),
            )
        )
        payload = _parse_json(raw)
    except Exception:  # noqa: BLE001
        payload = None
    if not isinstance(payload, dict):
        return {
            "refers_to_previous_recommendation": False,
            "selected_recommendation_ids": [],
            "selected_files": [],
            "requested_action": "clarify",
            "confidence": 0.0,
            "needs_clarification": True,
            "clarification_question": "Do you want me to turn the previous recommendations into file change proposals, or explain them further?",
        }
    return _validate_resolution(payload, recommendation_context, request.project_path)


def selected_recommendation_items(
    recommendation_context: dict[str, Any],
    selected_ids: list[str],
    selected_files: list[str],
) -> list[dict[str, Any]]:
    items = [item for item in recommendation_context.get("items", []) if isinstance(item, dict)]
    if selected_ids:
        id_set = set(selected_ids)
        return [item for item in items if item.get("id") in id_set]
    if selected_files:
        file_set = set(selected_files)
        return [item for item in items if file_set.intersection(set(item.get("files") or []))]
    return items


def _validate_resolution(payload: dict[str, Any], context: dict[str, Any], project_path: str) -> dict[str, Any]:
    repo_path = resolve_project_path(project_path).resolve()
    valid_files: list[str] = []
    for raw in payload.get("selected_files") or []:
        try:
            candidate = (repo_path / str(raw).lstrip("/")).resolve()
            candidate.relative_to(repo_path)
        except (OSError, ValueError):
            continue
        if candidate.is_file():
            rel = str(candidate.relative_to(repo_path))
            if rel not in valid_files:
                valid_files.append(rel)
    valid_ids = {
        str(item.get("id"))
        for item in context.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }
    selected_ids = [str(item) for item in payload.get("selected_recommendation_ids") or [] if str(item) in valid_ids]
    confidence = max(0.0, min(1.0, float(payload.get("confidence") or 0.0)))
    return {
        "refers_to_previous_recommendation": bool(payload.get("refers_to_previous_recommendation")),
        "selected_recommendation_ids": selected_ids,
        "selected_files": valid_files,
        "requested_action": str(payload.get("requested_action") or "clarify"),
        "confidence": confidence,
        "needs_clarification": bool(payload.get("needs_clarification")) or confidence < 0.55,
        "clarification_question": payload.get("clarification_question"),
    }


def _category_for_path(relative_path: str) -> str:
    suffix = Path(relative_path).suffix.lower()
    name = Path(relative_path).name.lower()
    if suffix in {".md", ".txt"}:
        return "docs"
    if suffix in {".yml", ".yaml", ".json", ".toml"} or "dockerfile" in name:
        return "config"
    if "test" in relative_path.lower():
        return "test"
    return "code"


def _suggestion_for_path(relative_path: str, category: str) -> str:
    if category == "docs":
        return "Clarify setup, usage, or project behavior in this documentation file."
    if category == "config":
        return "Review runtime, dependency, or deployment settings and tighten them where needed."
    if category == "test":
        return "Improve coverage around behavior that changed or looks under-tested."
    return "Refactor focused logic, improve validation, and preserve existing behavior."


def _summarize(text: str, max_len: int = 240) -> str:
    cleaned = " ".join((text or "").split())
    return cleaned if len(cleaned) <= max_len else cleaned[: max_len - 1].rstrip() + "..."


def _parse_json(text: str) -> dict[str, Any] | None:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines)
    try:
        payload = json.loads(stripped)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        return None
