from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repooperator_worker.services.json_safe import json_safe


@dataclass(frozen=True)
class ContextBudget:
    max_chars: int = 120_000
    reserved_final_answer_chars: int = 8_000
    max_file_chars: int = 40_000
    max_tool_result_chars: int = 80_000


@dataclass
class CompactedContext:
    included_files: dict[str, str]
    omitted_files: list[dict[str, Any]] = field(default_factory=list)
    summaries: dict[str, str] = field(default_factory=dict)
    total_chars: int = 0
    compacted: bool = False

    def model_dump(self) -> dict[str, Any]:
        return json_safe(self)


def estimate_chars(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    try:
        return len(json.dumps(json_safe(value), ensure_ascii=False))
    except Exception:
        return len(str(value))


def compact_file_contents(
    file_contents: dict[str, str],
    budget: ContextBudget,
    *,
    explicit_files: list[str] | None = None,
) -> CompactedContext:
    explicit = {path.lower() for path in explicit_files or []}
    available = max(1, budget.max_chars - budget.reserved_final_answer_chars)
    included: dict[str, str] = {}
    omitted: list[dict[str, Any]] = []
    summaries: dict[str, str] = {}
    total = 0
    compacted = False

    for path, content in sorted(file_contents.items(), key=lambda item: _priority(item[0], explicit)):
        text = str(content or "")
        per_file = min(budget.max_file_chars, available)
        if total >= available:
            omitted.append({"path": path, "reason": "context_budget_exhausted", "chars": len(text)})
            summaries[path] = summarize_large_text_deterministic(path, text)
            compacted = True
            continue
        if len(text) > per_file:
            summary = summarize_large_text_deterministic(path, text)
            summaries[path] = summary
            keep = max(0, min(per_file, available - total))
            included[path] = text[:keep]
            total += len(included[path])
            omitted.append({"path": path, "reason": "file_truncated", "chars": len(text), "included_chars": keep})
            compacted = True
            continue
        if total + len(text) <= available:
            included[path] = text
            total += len(text)
            continue
        remaining = max(0, available - total)
        if remaining > 0 and _is_high_priority(path, explicit):
            included[path] = text[:remaining]
            total += len(included[path])
            omitted.append({"path": path, "reason": "budget_partial_high_priority", "chars": len(text), "included_chars": remaining})
        else:
            omitted.append({"path": path, "reason": "context_budget_exhausted", "chars": len(text)})
        summaries[path] = summarize_large_text_deterministic(path, text)
        compacted = True
    return CompactedContext(included_files=included, omitted_files=omitted, summaries=summaries, total_chars=total, compacted=compacted)


def summarize_large_text_deterministic(path: str, content: str) -> str:
    text = content or ""
    lines = text.splitlines()
    heading = next((line.strip() for line in lines if line.strip().startswith("#")), "")
    definitions = re.findall(r"^\s*(?:def|class|function|const|export\s+function|public\s+class)\s+([A-Za-z_][A-Za-z0-9_]*)", text, flags=re.MULTILINE)
    imports = re.findall(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+)|using\s+([\w.]+);)", text, flags=re.MULTILINE)
    flat_imports = [next((part for part in match if part), "") for match in imports]
    parts = [f"{Path(path).name}: {len(lines)} line(s), {len(text)} char(s)"]
    if heading:
        parts.append(f"first heading {heading[:120]}")
    if definitions:
        parts.append("definitions " + ", ".join(definitions[:8]))
    if flat_imports:
        parts.append("imports " + ", ".join(flat_imports[:8]))
    if len(parts) == 1:
        sample = " ".join(line.strip() for line in lines if line.strip())[:220]
        if sample:
            parts.append(sample)
    return "; ".join(parts)


def _priority(path: str, explicit: set[str]) -> tuple[int, str]:
    lowered = path.lower()
    name = Path(path).name.lower()
    if lowered in explicit or name in explicit:
        return (0, lowered)
    if name.startswith("readme"):
        return (1, lowered)
    if name in {"main.py", "index.js", "index.ts", "app.tsx", "cli.py"}:
        return (2, lowered)
    if name in {"package.json", "pyproject.toml", "cargo.toml", "go.mod", "manifest.json"}:
        return (3, lowered)
    return (4, lowered)


def _is_high_priority(path: str, explicit: set[str]) -> bool:
    return _priority(path, explicit)[0] <= 2
