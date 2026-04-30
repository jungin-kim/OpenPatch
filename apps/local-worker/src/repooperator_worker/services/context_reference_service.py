"""LLM-based context reference resolver.

Determines whether the user's message refers to previously discussed content
(a file, symbol, proposal, command, or code change) and resolves it to concrete
repo artifacts. Deterministic code only validates model output and handles exact
symbol/file matches; it does not use multilingual phrase lists.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from repooperator_worker.services.common import resolve_project_path
from repooperator_worker.services.model_client import (
    ModelGenerationRequest,
    OpenAICompatibleModelClient,
)

logger = logging.getLogger(__name__)

ReferenceType = Literal["file", "symbol", "proposal", "command", "change_suggestion", "none"]

CONFIDENCE_THRESHOLD = 0.60


@dataclass
class ContextReferenceResult:
    refers_to_previous_context: bool
    reference_type: ReferenceType
    target_files: list[str]
    target_symbols: list[str]
    confidence: float
    needs_clarification: bool
    clarification_question: str | None
    resolver: str = "none"

    def to_debug_trace(self) -> dict[str, Any]:
        return {
            "context_reference_resolver": self.resolver,
            "resolved_reference_type": self.reference_type,
            "resolved_files": self.target_files,
            "resolved_symbols": self.target_symbols,
            "confidence": self.confidence,
            "clarification_needed": self.needs_clarification,
        }


_SYSTEM_PROMPT = """\
You are a context reference resolver for a code assistant. Your only job is to determine
whether the user's current message refers to something previously discussed in the conversation
— a file, symbol, proposal, command, or code change suggestion — and if so, what it refers to.

Return ONLY a JSON object with these exact fields. Do not include any other text or markdown.

{
  "refers_to_previous_context": bool,
  "reference_type": "file" | "symbol" | "proposal" | "command" | "change_suggestion" | "none",
  "target_files": [list of relative file paths, empty if none],
  "target_symbols": [list of symbol/function/class names, empty if none],
  "confidence": float between 0.0 and 1.0,
  "needs_clarification": bool,
  "clarification_question": string or null
}

reference_type rules:
- "proposal": user is accepting or confirming a previously shown diff or code proposal
- "change_suggestion": user wants to apply a code change described in the last assistant message
- "file": user refers to a specific file from the thread context
- "symbol": user refers to a specific function, class, or variable from the thread context
- "command": user refers to a previously discussed or shown command
- "none": the message is standalone and does not refer to prior conversation context

If the reference is ambiguous (e.g., multiple recent files with no clear match), set
needs_clarification to true and provide a clarification_question. Never guess blindly.
"""


def resolve_context_reference(
    *,
    task: str,
    conversation_history: list[dict[str, str]],
    project_path: str,
    recent_files: list[str],
    last_analyzed_file: str | None,
    symbols: dict[str, str],
    suggestion_summary: str | None,
    proposal_file: str | None,
    candidate_files: list[str],
) -> ContextReferenceResult:
    """LLM-based context reference resolution with deterministic validation."""
    has_prior_context = bool(
        recent_files
        or last_analyzed_file
        or symbols
        or proposal_file
        or any(m.get("role") == "assistant" for m in conversation_history)
    )
    if not has_prior_context:
        return ContextReferenceResult(
            refers_to_previous_context=False,
            reference_type="none",
            target_files=[],
            target_symbols=[],
            confidence=0.0,
            needs_clarification=False,
            clarification_question=None,
            resolver="none",
        )

    user_prompt = _build_user_prompt(
        task=task,
        conversation_history=conversation_history,
        recent_files=recent_files,
        last_analyzed_file=last_analyzed_file,
        symbols=symbols,
        suggestion_summary=suggestion_summary,
        proposal_file=proposal_file,
    )

    try:
        client = OpenAICompatibleModelClient()
        raw = client.generate_text(
            ModelGenerationRequest(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
        )
        parsed = _parse_llm_json(raw)
        if parsed is None:
            raise ValueError("LLM returned unparseable JSON")

        confidence = float(parsed.get("confidence", 0.0))
        refers = bool(parsed.get("refers_to_previous_context")) and confidence >= CONFIDENCE_THRESHOLD
        ref_type: ReferenceType = parsed.get("reference_type", "none") if refers else "none"

        raw_symbols: list[str] = parsed.get("target_symbols") or []
        raw_files: list[str] = parsed.get("target_files") or []
        if not raw_files and raw_symbols:
            raw_files = [
                symbols[symbol]
                for symbol in raw_symbols
                if symbol in symbols
            ]
        valid_files = _validate_files(raw_files, project_path)

        needs_clarification = bool(parsed.get("needs_clarification"))
        clarification_q: str | None = parsed.get("clarification_question")

        # If LLM resolved a file reference but validation shows it doesn't exist
        # and we have candidate files, ask clarification rather than silently failing.
        if refers and ref_type in {"file", "symbol", "proposal", "change_suggestion"} and not valid_files:
            needs_clarification = True
            clarification_q = clarification_q or _clarification_for_candidates(candidate_files or recent_files)

        return ContextReferenceResult(
            refers_to_previous_context=refers,
            reference_type=ref_type,
            target_files=valid_files,
            target_symbols=raw_symbols,
            confidence=confidence,
            needs_clarification=needs_clarification,
            clarification_question=clarification_q,
            resolver="llm",
        )

    except (ValueError, RuntimeError, OSError) as exc:
        logger.info("LLM context reference resolution failed (%s); using deterministic validation fallback", exc)
        return _deterministic_fallback(
            task=task,
            recent_files=recent_files,
            last_analyzed_file=last_analyzed_file,
            symbols=symbols,
            proposal_file=proposal_file,
            project_path=project_path,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_user_prompt(
    *,
    task: str,
    conversation_history: list[dict[str, str]],
    recent_files: list[str],
    last_analyzed_file: str | None,
    symbols: dict[str, str],
    suggestion_summary: str | None,
    proposal_file: str | None,
) -> str:
    parts: list[str] = [f"Current message: {task}"]

    history_items = [
        m for m in conversation_history[-6:]
        if m.get("role") in ("user", "assistant")
    ]
    if history_items:
        lines = [
            f"{m['role'].upper()}: {str(m.get('content', ''))[:300]}"
            for m in history_items
        ]
        parts.append("Recent conversation:\n" + "\n".join(lines))

    ctx_lines: list[str] = []
    if last_analyzed_file:
        ctx_lines.append(f"Last analyzed file: {last_analyzed_file}")
    if recent_files:
        ctx_lines.append("Recently read files: " + ", ".join(recent_files[:8]))
    if symbols:
        ctx_lines.append("Mentioned symbols: " + ", ".join(list(symbols)[:10]))
    if proposal_file:
        ctx_lines.append(f"Last proposal target: {proposal_file}")
    if suggestion_summary:
        ctx_lines.append(f"Last assistant message summary: {suggestion_summary[:200]}")

    if ctx_lines:
        parts.append("Thread context:\n" + "\n".join(ctx_lines))

    return "\n\n".join(parts)


def _parse_llm_json(raw: str) -> dict[str, Any] | None:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        end = -1 if lines[-1].strip() in ("```", "```json") else len(lines)
        cleaned = "\n".join(lines[1:end])
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    # Try to extract a JSON object from somewhere in the response
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return None


def _validate_files(files: list[str], project_path: str) -> list[str]:
    """Return only those paths that exist inside the repo."""
    if not files:
        return []
    try:
        repo_path = resolve_project_path(project_path).resolve()
    except (ValueError, OSError):
        return []
    valid: list[str] = []
    for f in files:
        candidate = (repo_path / f.lstrip("/")).resolve()
        try:
            candidate.relative_to(repo_path)
        except ValueError:
            continue
        if candidate.is_file():
            valid.append(str(candidate.relative_to(repo_path)))
    return valid


def _deterministic_fallback(
    *,
    task: str,
    recent_files: list[str],
    last_analyzed_file: str | None,
    symbols: dict[str, str],
    proposal_file: str | None,
    project_path: str,
) -> ContextReferenceResult:
    """Low-confidence fallback with exact symbol/file validation only."""
    lowered = task.lower()

    for symbol, file_path in symbols.items():
        if symbol.lower() in lowered:
            return ContextReferenceResult(
                refers_to_previous_context=True,
                reference_type="symbol",
                target_files=_validate_files([file_path], project_path),
                target_symbols=[symbol],
                confidence=0.75,
                needs_clarification=False,
                clarification_question=None,
                resolver="deterministic_fallback",
            )

    explicit_files = [
        file_path for file_path in recent_files
        if Path(file_path).name.lower() in lowered or file_path.lower() in lowered
    ]
    valid_explicit = _validate_files(explicit_files, project_path)
    if valid_explicit:
        return ContextReferenceResult(
            refers_to_previous_context=True,
            reference_type="file",
            target_files=valid_explicit,
            target_symbols=[],
            confidence=0.7,
            needs_clarification=False,
            clarification_question=None,
            resolver="deterministic_fallback",
        )

    candidates = [file for file in [proposal_file, last_analyzed_file, *recent_files] if file]
    candidates = list(dict.fromkeys(candidates))
    if candidates:
        return ContextReferenceResult(
            refers_to_previous_context=False,
            reference_type="none",
            target_files=[],
            target_symbols=[],
            confidence=0.0,
            needs_clarification=True,
            clarification_question=_clarification_for_candidates(candidates),
            resolver="deterministic_fallback",
        )

    return ContextReferenceResult(
        refers_to_previous_context=False,
        reference_type="none",
        target_files=[],
        target_symbols=[],
        confidence=0.0,
        needs_clarification=False,
        clarification_question=None,
        resolver="deterministic_fallback",
    )


def _clarification_for_candidates(candidates: list[str]) -> str:
    if not candidates:
        return "I need one target from the recent context before preparing a change. Which recent file or suggestion should I use?"
    rendered = ", ".join(f"`{candidate}`" for candidate in candidates[:5])
    return f"I found multiple possible targets in the recent context ({rendered}). Which one should I use?"
