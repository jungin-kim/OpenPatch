from __future__ import annotations

import json
from typing import Any
from urllib import error, parse, request

from repooperator_worker.config import get_settings

COMPOSIO_API_BASE_URL = "https://backend.composio.dev/api/v3"


def get_composio_status() -> dict[str, Any]:
    api_key = get_settings().composio_api_key
    if not api_key:
        return {
            "provider": "Composio",
            "status": "not configured",
            "configured": False,
            "message": "Set REPOOPERATOR_COMPOSIO_API_KEY and restart the worker to enable Composio status checks.",
            "accounts": [],
            "toolkits": [],
            "tools_count": 0,
        }

    toolkits_payload = _request_json("/toolkits", {"limit": "20"})
    accounts_payload = _request_json("/connected_accounts", {"limit": "20"})
    toolkits = _normalize_items(toolkits_payload)
    accounts = _normalize_items(accounts_payload)
    return {
        "provider": "Composio",
        "status": "connected" if accounts else "configured",
        "configured": True,
        "message": "Composio API key is configured. Connected accounts and toolkits were loaded from Composio.",
        "accounts": [_safe_account(account) for account in accounts],
        "toolkits": [_safe_toolkit(toolkit) for toolkit in toolkits],
        "toolkits_count": len(toolkits),
        "tools_count": _count_tools(toolkits),
    }


def list_composio_toolkits() -> dict[str, Any]:
    if not get_settings().composio_api_key:
        return {"toolkits": [], "status": "not configured"}
    payload = _request_json("/toolkits", {"limit": "100"})
    return {"toolkits": [_safe_toolkit(item) for item in _normalize_items(payload)], "status": "configured"}


def list_composio_connected_accounts() -> dict[str, Any]:
    if not get_settings().composio_api_key:
        return {"accounts": [], "status": "not configured"}
    payload = _request_json("/connected_accounts", {"limit": "100"})
    return {"accounts": [_safe_account(item) for item in _normalize_items(payload)], "status": "configured"}


def composio_connection_instructions() -> dict[str, Any]:
    configured = bool(get_settings().composio_api_key)
    return {
        "status": "ready" if configured else "not configured",
        "message": (
            "Create an auth config in the Composio dashboard, then initiate a connected account "
            "with Composio's official connected accounts API. RepoOperator can display connected "
            "accounts once REPOOPERATOR_COMPOSIO_API_KEY is configured."
            if configured
            else "Set REPOOPERATOR_COMPOSIO_API_KEY and restart the worker before starting a Composio connection."
        ),
        "docs": "https://docs.composio.dev/docs/authenticating-tools",
    }


def _request_json(path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
    api_key = get_settings().composio_api_key
    if not api_key:
        raise RuntimeError("REPOOPERATOR_COMPOSIO_API_KEY is not configured.")
    url = f"{COMPOSIO_API_BASE_URL}{path}"
    if query:
        url = f"{url}?{parse.urlencode(query)}"
    http_request = request.Request(
        url,
        headers={
            "x-api-key": api_key,
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with request.urlopen(http_request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Composio API returned {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Composio API is unreachable: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Composio API returned invalid JSON.") from exc


def _normalize_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "data", "toolkits", "connected_accounts", "connectedAccounts"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _safe_toolkit(toolkit: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": toolkit.get("id"),
        "slug": toolkit.get("slug") or toolkit.get("name"),
        "name": toolkit.get("name") or toolkit.get("slug"),
        "tools_count": toolkit.get("tools_count") or toolkit.get("toolsCount") or 0,
    }


def _safe_account(account: dict[str, Any]) -> dict[str, Any]:
    toolkit = account.get("toolkit") if isinstance(account.get("toolkit"), dict) else {}
    return {
        "id": account.get("id"),
        "status": account.get("status"),
        "toolkit": toolkit.get("slug") or toolkit.get("name") or account.get("toolkit_slug"),
        "user_id": account.get("user_id") or account.get("userId"),
    }


def _count_tools(toolkits: list[dict[str, Any]]) -> int:
    total = 0
    for toolkit in toolkits:
        value = toolkit.get("tools_count") or toolkit.get("toolsCount") or 0
        if isinstance(value, int):
            total += value
    return total
