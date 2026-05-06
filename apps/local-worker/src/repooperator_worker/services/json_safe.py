from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def json_safe(value: Any) -> Any:
    """Return a JSON-serializable copy of common app payload objects."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, BaseException):
        return f"{value.__class__.__name__}: {value}"
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return json_safe(value.model_dump(mode="json"))
        except TypeError:
            return json_safe(value.model_dump())
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(json_safe(key)): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(item) for item in value]
    return safe_repr(value)


def safe_repr(value: Any, *, limit: int = 500) -> str:
    try:
        text = repr(value)
    except Exception:
        text = f"<unrepresentable {value.__class__.__name__}>"
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."
