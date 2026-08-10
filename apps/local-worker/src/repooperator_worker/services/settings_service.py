"""Read/write user-editable settings (model connection, repository sources)
from the web UI.

Reuses the atomic config read/write helpers from permissions_service so the
web Settings screen persists to the same ~/.repooperator/config.json the CLI
onboarding writes. Secrets (API keys, provider tokens) are NEVER returned in
plaintext — GET reports only whether a secret is configured, and POST keeps
the stored secret when the client omits it (masked-edit support).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from repooperator_worker.config import get_settings
from repooperator_worker.services.permissions_service import _read_config, _write_config

_SECRET_SENTINEL = "__stored__"  # marks "a secret is set; unchanged" over the wire


def _mask(value: Any) -> str | None:
    """Report secret presence without leaking it."""
    return _SECRET_SENTINEL if (value and str(value).strip()) else None


def _log_dir() -> Path:
    return get_settings().repooperator_home_dir / "logs"


def get_settings_snapshot() -> dict[str, Any]:
    config = _read_config(get_settings().repooperator_config_path)
    model = dict(config.get("model") or {})
    sources = [dict(s) for s in (config.get("repositorySources") or []) if isinstance(s, dict)]
    for src in sources:
        src["token"] = _mask(src.get("token"))
    return {
        "model": {
            "connectionMode": model.get("connectionMode") or "local-runtime",
            "provider": model.get("provider") or "",
            "baseUrl": model.get("baseUrl") or "",
            "model": model.get("model") or "",
            "contextWindow": model.get("contextWindow"),
            "apiKey": _mask(model.get("apiKey")),
        },
        "repositorySources": sources,
        "gitProvider": config.get("gitProvider") or "",
        "localRepoBaseDir": config.get("localRepoBaseDir") or "",
        "autoContextWindow": _auto_context_window(),
    }


def _auto_context_window() -> int:
    """Mirror the CLI's RAM-based num_ctx auto value so the web form can offer
    the same 'Auto (from RAM)' option."""
    try:
        total_gb = (os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")) / (1024**3)
    except (ValueError, OSError, AttributeError):
        return 8192
    if total_gb >= 64:
        return 131072
    if total_gb >= 32:
        return 65536
    if total_gb >= 16:
        return 32768
    return 8192


def _validate_url(value: str, field: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError(f"{field} must not be empty.")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} must be a valid http(s) URL.")
    return value


def update_model_settings(payload: dict[str, Any]) -> dict[str, Any]:
    config = _read_config(get_settings().repooperator_config_path)
    model = dict(config.get("model") or {})

    connection_mode = (payload.get("connectionMode") or model.get("connectionMode") or "local-runtime").strip()
    provider = (payload.get("provider") or "").strip()
    if not provider:
        raise ValueError("provider must not be empty.")
    base_url = _validate_url(payload.get("baseUrl") or "", "baseUrl")
    model_name = (payload.get("model") or "").strip()
    if not model_name:
        raise ValueError("model must not be empty.")

    model.update(
        {
            "connectionMode": connection_mode,
            "provider": provider,
            "baseUrl": base_url,
            "model": model_name,
        }
    )

    ctx = payload.get("contextWindow")
    if ctx is not None:
        try:
            ctx_int = int(ctx)
        except (TypeError, ValueError):
            raise ValueError("contextWindow must be an integer.")
        if ctx_int < 1024:
            raise ValueError("contextWindow must be at least 1024.")
        model["contextWindow"] = ctx_int

    # Secret: only overwrite when the client actually sent a new one. A missing
    # key or the sentinel keeps the stored value (masked-edit).
    api_key = payload.get("apiKey")
    if api_key is not None and api_key != _SECRET_SENTINEL:
        model["apiKey"] = str(api_key)

    config["model"] = model
    _write_config(get_settings().repooperator_config_path, config)
    _reload_worker_config()
    return get_settings_snapshot()


def update_repository_settings(payload: dict[str, Any]) -> dict[str, Any]:
    config = _read_config(get_settings().repooperator_config_path)
    sources = [dict(s) for s in (config.get("repositorySources") or []) if isinstance(s, dict)]

    provider = (payload.get("provider") or "").strip()
    if provider not in {"github", "gitlab", "local"}:
        raise ValueError("provider must be one of github, gitlab, local.")

    incoming = {
        "provider": provider,
        "baseUrl": (payload.get("baseUrl") or "").strip(),
        "owner": (payload.get("owner") or "").strip(),
    }
    if provider != "local":
        incoming["baseUrl"] = _validate_url(incoming["baseUrl"] or _default_base_url(provider), "baseUrl")

    # Match by provider: update in place or append.
    existing = next((s for s in sources if s.get("provider") == provider), None)
    token = payload.get("token")
    if existing is not None:
        existing.update(incoming)
        if token is not None and token != _SECRET_SENTINEL:
            existing["token"] = str(token)
    else:
        if token is not None and token != _SECRET_SENTINEL:
            incoming["token"] = str(token)
        sources.append(incoming)

    config["repositorySources"] = sources
    if payload.get("makeDefault"):
        config["gitProvider"] = provider
    _write_config(get_settings().repooperator_config_path, config)
    _reload_worker_config()
    return get_settings_snapshot()


def _default_base_url(provider: str) -> str:
    return {"github": "https://github.com", "gitlab": "https://gitlab.com"}.get(provider, "")


def read_log_tail(target: str, lines: int = 200) -> dict[str, Any]:
    target = (target or "worker").strip().lower()
    if target not in {"worker", "web", "ollama"}:
        raise ValueError("target must be one of worker, web, ollama.")
    lines = max(1, min(int(lines or 200), 2000))
    path = _log_dir() / f"{target}.log"
    if not path.exists():
        return {"target": target, "path": str(path), "lines": [], "exists": False}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            tail = fh.readlines()[-lines:]
    except OSError as exc:
        return {"target": target, "path": str(path), "lines": [f"(로그를 읽을 수 없습니다: {exc})"], "exists": True}
    return {"target": target, "path": str(path), "lines": [line.rstrip("\n") for line in tail], "exists": True}


def _reload_worker_config() -> None:
    """Best-effort in-process reload so edits take effect without a restart.

    get_settings() reads config fresh each call, so most paths pick up changes
    automatically; this clears any cached model client if present.
    """
    try:
        from repooperator_worker.services import model_client

        if hasattr(model_client, "reset_cached_client"):
            model_client.reset_cached_client()
    except Exception:
        pass
    # Touch env so a subsequent get_settings() re-resolves (no-op if unused).
    os.environ.pop("REPOOPERATOR_SETTINGS_CACHE", None)
