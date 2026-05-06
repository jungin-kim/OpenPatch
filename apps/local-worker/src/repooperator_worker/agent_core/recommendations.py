from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from repooperator_worker.schemas import AgentRunRequest


def evidence_backed_recommendation_context(
    *,
    request: AgentRunRequest,
    items: list[dict[str, Any]],
    rationale: str,
) -> dict[str, Any]:
    seed = f"{request.project_path}:{request.branch}:{request.task}:{time.time_ns()}"
    context_id = "rec_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items[:12], start=1):
        files = [str(path) for path in item.get("files", []) if str(path)]
        evidence = item.get("evidence") or []
        if not evidence:
            evidence = [
                {
                    "file": file_path,
                    "symbol": None,
                    "excerpt": "",
                    "reason": item.get("exact_issue") or item.get("rationale") or "Selected from inspected repository context.",
                }
                for file_path in files
            ]
        normalized.append(
            {
                "id": item.get("id") or f"{context_id}_{index}",
                "files": files,
                "symbols": [str(symbol) for symbol in item.get("symbols", [])],
                "exact_issue": str(item.get("exact_issue") or ""),
                "suggested_changes": [str(change) for change in item.get("suggested_changes", [])],
                "proposed_change_plan": [str(step) for step in item.get("proposed_change_plan", [])],
                "evidence": evidence,
                "rationale": str(item.get("rationale") or ""),
                "risk_level": str(item.get("risk_level") or "medium"),
                "category": str(item.get("category") or _category(files)),
                "confidence": float(item.get("confidence") or 0.5),
                "needs_more_inspection": bool(item.get("needs_more_inspection")),
                "generated_from": str(item.get("generated_from") or "file_content"),
            }
        )
    return {
        "recommendation_id": context_id,
        "repo": request.project_path,
        "branch": request.branch,
        "source_user_request_summary": " ".join(request.task.split())[:240],
        "recommended_files": sorted({file for item in normalized for file in item["files"]}),
        "recommended_symbols": sorted({symbol for item in normalized for symbol in item["symbols"]}),
        "items": normalized,
        "rationale": rationale[:700],
        "risk_level": "medium" if normalized else "low",
        "category": "mixed" if len({item["category"] for item in normalized}) > 1 else (normalized[0]["category"] if normalized else "code"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _category(files: list[str]) -> str:
    suffixes = {Path(file).suffix.lower() for file in files}
    if suffixes & {".md", ".txt", ".rst"}:
        return "docs"
    if suffixes & {".json", ".toml", ".yaml", ".yml", ".ini", ".cfg"}:
        return "config"
    if any("test" in file.lower() for file in files):
        return "test"
    return "code"

