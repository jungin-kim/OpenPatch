"""Per-thread actual context usage, recorded each time context is packed.

Lets the context-window gauge show the *real* repo-context tokens from the most
recent run of a chat instead of only the fixed per-model budget.
"""

from __future__ import annotations

import json
from typing import Any

from repooperator_worker.services.common import get_repooperator_home_dir

_MAX_ENTRIES = 200


def _usage_file():
    return get_repooperator_home_dir() / "context-usage.json"


def _read() -> dict[str, Any]:
    try:
        data = json.loads(_usage_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_context_usage(thread_id: str | None, *, input_tokens: int, usage_ratio: float | None = None) -> None:
    if not thread_id or not input_tokens:
        return
    try:
        data = _read()
        data[str(thread_id)] = {
            "input_tokens": int(input_tokens),
            "usage_ratio": float(usage_ratio) if usage_ratio is not None else None,
        }
        # Keep the store bounded (drop oldest-inserted keys beyond the cap).
        if len(data) > _MAX_ENTRIES:
            for key in list(data.keys())[: len(data) - _MAX_ENTRIES]:
                data.pop(key, None)
        _usage_file().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return


def get_context_usage(thread_id: str | None) -> dict[str, Any] | None:
    if not thread_id:
        return None
    entry = _read().get(str(thread_id))
    return entry if isinstance(entry, dict) else None
