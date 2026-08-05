"""MCP server management: bundled catalog, enable/disable, discovery.

Servers persist to ``~/.repooperator/mcp.json`` in the Claude-Code-compatible
``mcpServers`` format that the MCP registry already loads. Enabling a server
live-discovers its tools (tools/list) and persists the metadata so the tool
registry can expose real schemas to the model.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from repooperator_worker.services.common import get_repooperator_home_dir
from repooperator_worker.services.json_safe import json_safe

_DISCOVERY_TIMEOUT = 30.0


def _mcp_config_path() -> Path:
    return get_repooperator_home_dir() / "mcp.json"


def _workspace_dir() -> str:
    """Active repository checkout if one is open, else the repo base dir."""
    try:
        from repooperator_worker.services.active_repository import get_active_repository

        active = get_active_repository()
        path = getattr(active, "local_repo_path", None)
        if path and Path(str(path)).is_dir():
            return str(path)
    except Exception:
        pass
    try:
        from repooperator_worker.services.common import get_repo_base_dir

        return str(get_repo_base_dir())
    except Exception:
        return str(Path.home())


def bundled_catalog() -> list[dict[str, Any]]:
    """The standard coding-agent MCP set, ready to enable with one click.

    Ordered complementary-first: servers that add capabilities the built-in
    tools don't have come before ones that overlap built-ins (those carry an
    ``overlap`` note so users enable them knowingly — built-in tools stay the
    default path). ``{workspace}`` is stored as a placeholder and resolved to
    the active checkout at connect time, so switching repos stays correct.
    """
    return [
        {
            "id": "memory",
            "name": "Memory",
            "description": "Persistent knowledge-graph memory across chats (official server-memory).",
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-memory"],
            "runtime": "npx",
        },
        {
            "id": "sequential-thinking",
            "name": "Sequential Thinking",
            "description": "Structured step-by-step reasoning scratchpad (official server-sequential-thinking).",
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
            "runtime": "npx",
        },
        {
            "id": "github",
            "name": "GitHub",
            "description": "Issues, PRs, code search and repo operations via the GitHub API (needs GITHUB_PERSONAL_ACCESS_TOKEN).",
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "runtime": "npx",
            "env_keys": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
            "overlap": "Overlaps with built-in github_create_pr for PR creation — enable for the broader API (issues, code search, reviews).",
        },
        {
            "id": "filesystem",
            "name": "Filesystem",
            "description": "Read/write files under the active workspace (official server-filesystem).",
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "{workspace}"],
            "runtime": "npx",
            "overlap": "Overlaps with built-in read_file / modify_file / create_file — the built-ins are approval-gated and repo-scoped, so enable this only if you need raw FS access.",
        },
        {
            "id": "fetch",
            "name": "Fetch",
            "description": "Fetch web pages as markdown (official mcp-server-fetch, needs uvx).",
            "transport": "stdio",
            "command": "uvx",
            "args": ["mcp-server-fetch"],
            "runtime": "uvx",
            "overlap": "Overlaps with built-in fetch_url / search_web — enable only if you prefer the official fetcher's markdown extraction.",
        },
        {
            "id": "git",
            "name": "Git",
            "description": "Rich git operations on the active workspace (official mcp-server-git, needs uvx).",
            "transport": "stdio",
            "command": "uvx",
            "args": ["mcp-server-git", "--repository", "{workspace}"],
            "runtime": "uvx",
            "overlap": "Overlaps with built-in git_status / git_diff / git_log / git_commit / git_push — built-ins are approval-gated; enable for extras like blame or worktrees.",
        },
    ]


def _runtime_available(runtime: str | None) -> bool:
    if not runtime:
        return True
    return shutil.which(runtime) is not None


def _read_config() -> dict[str, Any]:
    path = _mcp_config_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_config(payload: dict[str, Any]) -> None:
    path = _mcp_config_path()
    path.write_text(json.dumps(json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _servers_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    servers = config.get("mcpServers")
    return servers if isinstance(servers, dict) else {}


def list_mcp_status() -> dict[str, Any]:
    """Bundled catalog + custom servers with enabled state and runtime checks."""
    from repooperator_worker.agent_core.mcp import list_configured_mcp_servers

    configured = {str(s.get("id")): s for s in list_configured_mcp_servers()}
    workspace = _workspace_dir()
    bundled_rows: list[dict[str, Any]] = []
    for entry in bundled_catalog():
        server = configured.get(entry["id"])
        bundled_rows.append(
            json_safe(
                {
                    **entry,
                    # Resolve the placeholder for display so the row shows the
                    # real directory the server would operate on right now.
                    "args": [str(a).replace("{workspace}", workspace) for a in entry.get("args") or []],
                    "bundled": True,
                    "enabled": bool(server and server.get("enabled")),
                    "configured": bool(server),
                    "tool_count": len((server or {}).get("tools") or []),
                    "runtime_available": _runtime_available(entry.get("runtime")),
                }
            )
        )
    bundled_ids = {entry["id"] for entry in bundled_catalog()}
    custom_rows = [
        json_safe(
            {
                **server,
                "bundled": False,
                "configured": True,
                "tool_count": len(server.get("tools") or []),
                "runtime_available": True,
            }
        )
        for server_id, server in configured.items()
        if server_id not in bundled_ids
    ]
    return {"bundled": bundled_rows, "custom": custom_rows}


def _discover_tools(spec_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """Connect to the server and list its tools (raises MCPClientError on failure)."""
    from repooperator_worker.agent_core.mcp import mcp_server_spec_from_dict
    from repooperator_worker.services.mcp_client import list_mcp_tools

    spec = mcp_server_spec_from_dict({**spec_dict, "enabled": True})
    tools = list_mcp_tools(spec, timeout=_DISCOVERY_TIMEOUT)
    normalized: list[dict[str, Any]] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        normalized.append(
            {
                "name": tool.get("name"),
                "description": tool.get("description") or "",
                "input_schema": tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else (tool.get("input_schema") or {}),
            }
        )
    return normalized


def enable_mcp_server(server_id: str, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Enable a bundled (or already-configured custom) server.

    Bundled entries are materialized into mcp.json; tools are live-discovered so
    the agent gets real schemas. Env vars (e.g. a GitHub token) are stored under
    the server's config.env.
    """
    config = _read_config()
    servers = dict(_servers_map(config))
    entry = next((item for item in bundled_catalog() if item["id"] == server_id), None)
    if entry is None and server_id not in servers:
        raise ValueError(f"Unknown MCP server: {server_id}")

    if entry is not None:
        record = dict(servers.get(server_id) or {})
        record.update(
            {
                "name": entry["name"],
                "transport": entry["transport"],
                "command": entry["command"],
                "args": entry["args"],
                "description": entry["description"],
            }
        )
        if entry.get("runtime") and not _runtime_available(entry.get("runtime")):
            raise RuntimeError(
                f"'{entry['runtime']}' is not installed. Install it first (npx ships with Node.js; uvx ships with uv)."
            )
    else:
        record = dict(servers[server_id])

    if env:
        existing_config = record.get("config") if isinstance(record.get("config"), dict) else {}
        existing_env = existing_config.get("env") if isinstance(existing_config.get("env"), dict) else {}
        record["config"] = {**existing_config, "env": {**existing_env, **env}}

    tools = _discover_tools(record)
    record["tools"] = tools
    record["enabled"] = True
    servers[server_id] = record
    _write_config({**config, "mcpServers": servers})
    return {"id": server_id, "enabled": True, "tool_count": len(tools), "tools": json_safe(tools)}


def disable_mcp_server(server_id: str) -> dict[str, Any]:
    config = _read_config()
    servers = dict(_servers_map(config))
    if server_id in servers:
        servers[server_id] = {**servers[server_id], "enabled": False}
        _write_config({**config, "mcpServers": servers})
    return {"id": server_id, "enabled": False}


def remove_mcp_server(server_id: str) -> dict[str, Any]:
    config = _read_config()
    servers = dict(_servers_map(config))
    if server_id in servers:
        servers.pop(server_id)
        _write_config({**config, "mcpServers": servers})
    return {"id": server_id, "removed": True}


def add_custom_mcp_server(payload: dict[str, Any]) -> dict[str, Any]:
    """Register a custom server (stdio command or http/sse url) and discover tools."""
    server_id = str(payload.get("id") or payload.get("name") or "").strip().lower().replace(" ", "-")
    if not server_id:
        raise ValueError("MCP server needs an id or name.")
    transport = str(payload.get("transport") or ("http" if payload.get("url") else "stdio"))
    record: dict[str, Any] = {
        "name": str(payload.get("name") or server_id),
        "transport": transport,
        "enabled": True,
    }
    if transport == "stdio":
        command = str(payload.get("command") or "").strip()
        if not command:
            raise ValueError("stdio MCP server needs a command.")
        record["command"] = command
        record["args"] = [str(a) for a in payload.get("args") or []]
    else:
        url = str(payload.get("url") or "").strip()
        if not url:
            raise ValueError(f"{transport} MCP server needs a url.")
        record["url"] = url
    if isinstance(payload.get("env"), dict) and payload["env"]:
        record["config"] = {"env": {str(k): str(v) for k, v in payload["env"].items()}}

    tools = _discover_tools(record)
    record["tools"] = tools

    config = _read_config()
    servers = dict(_servers_map(config))
    servers[server_id] = record
    _write_config({**config, "mcpServers": servers})
    return {"id": server_id, "enabled": True, "tool_count": len(tools), "tools": json_safe(tools)}


def test_mcp_server(server_id: str) -> dict[str, Any]:
    """Connect to a configured server, refresh its tool metadata, report tools."""
    config = _read_config()
    servers = dict(_servers_map(config))
    record = servers.get(server_id)
    if record is None:
        entry = next((item for item in bundled_catalog() if item["id"] == server_id), None)
        if entry is None:
            raise ValueError(f"Unknown MCP server: {server_id}")
        record = {k: entry[k] for k in ("name", "transport", "command", "args")}
    tools = _discover_tools(record)
    if server_id in servers:
        servers[server_id] = {**servers[server_id], "tools": tools}
        _write_config({**config, "mcpServers": servers})
    return {"id": server_id, "ok": True, "tool_count": len(tools), "tools": json_safe(tools)}
