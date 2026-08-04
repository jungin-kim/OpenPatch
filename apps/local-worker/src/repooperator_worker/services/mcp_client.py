"""Minimal Model Context Protocol (MCP) client.

Implements just enough of MCP to start a server, complete the ``initialize``
handshake, list tools, and call a tool. Two transports are supported:

- **stdio**: spawn ``command args`` and exchange newline-delimited JSON-RPC 2.0
  messages over stdin/stdout (the standard local MCP transport).
- **http/sse**: POST JSON-RPC to a URL and accept either a JSON body or an SSE
  ``data:`` framed response (streamable HTTP).

No third-party dependency is required; this uses only the standard library so
the packaged worker stays light. Servers are connected on demand (per tool
call), which keeps the worker from holding long-lived subprocesses.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request

MCP_PROTOCOL_VERSION = "2024-11-05"
_CLIENT_INFO = {"name": "repooperator-worker", "version": "0.1.0"}
_DEFAULT_TIMEOUT = 30.0


class MCPClientError(RuntimeError):
    """Raised when an MCP server cannot be reached or returns an error."""


@dataclass
class MCPToolResult:
    text: str
    is_error: bool = False
    raw: dict[str, Any] | None = None


def _normalize_tool_result(payload: dict[str, Any]) -> MCPToolResult:
    content = payload.get("content")
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block, dict):
                parts.append(json.dumps(block, ensure_ascii=False))
    elif isinstance(content, str):
        parts.append(content)
    return MCPToolResult(text="\n".join(p for p in parts if p), is_error=bool(payload.get("isError")), raw=payload)


class MCPStdioClient:
    """JSON-RPC 2.0 client over a spawned MCP server's stdio."""

    def __init__(
        self,
        *,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._command = command
        self._args = list(args or [])
        self._env = {**os.environ, **(env or {})}
        self._cwd = cwd
        self._timeout = float(timeout)
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 0
        # Lines are read on a background thread so we never mix a timeout with
        # TextIOWrapper's internal buffering (select() cannot see buffered lines).
        self._lines: "queue.Queue[str | None]" = queue.Queue()
        self._reader: threading.Thread | None = None

    def __enter__(self) -> "MCPStdioClient":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def start(self) -> None:
        if not self._command:
            raise MCPClientError("MCP stdio server requires a command.")
        try:
            self._process = subprocess.Popen(  # noqa: S603
                [self._command, *self._args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._env,
                cwd=self._cwd,
                text=True,
                bufsize=1,
            )
        except (OSError, ValueError) as exc:
            raise MCPClientError(f"Failed to start MCP server '{self._command}': {exc}") from exc
        self._reader = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader.start()
        self._handshake()

    def _reader_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            self._lines.put(None)
            return
        try:
            for line in process.stdout:  # iterator handles line buffering safely
                self._lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self._lines.put(None)  # sentinel: stream closed

    def _handshake(self) -> None:
        self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": _CLIENT_INFO,
            },
        )
        self._notify("notifications/initialized", {})

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        return [tool for tool in (tools or []) if isinstance(tool, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> MCPToolResult:
        result = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        if not isinstance(result, dict):
            raise MCPClientError("MCP tools/call returned an unexpected payload.")
        return _normalize_tool_result(result)

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
        try:
            process.terminate()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return self._read_response(request_id)

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _write(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise MCPClientError("MCP server is not running.")
        try:
            process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise MCPClientError(f"Failed to write to MCP server: {exc}") from exc

    def _read_response(self, request_id: int) -> dict[str, Any]:
        if self._process is None:
            raise MCPClientError("MCP server is not running.")
        deadline = time.monotonic() + self._timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPClientError(f"MCP server timed out after {self._timeout:.0f}s.")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                raise MCPClientError(f"MCP server timed out after {self._timeout:.0f}s.")
            if line is None:
                stderr = self._drain_stderr()
                raise MCPClientError(f"MCP server closed the connection before responding.{stderr}")
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue  # ignore non-JSON log lines
            if not isinstance(message, dict) or message.get("id") != request_id:
                continue  # skip notifications / other ids
            if "error" in message and message["error"]:
                err = message["error"]
                raise MCPClientError(f"MCP error {err.get('code')}: {err.get('message')}")
            result = message.get("result")
            return result if isinstance(result, dict) else {}

    def _drain_stderr(self) -> str:
        process = self._process
        if process is None or process.stderr is None:
            return ""
        try:
            data = process.stderr.read() or ""
        except OSError:
            return ""
        data = data.strip()
        return f" stderr: {data[:500]}" if data else ""


class MCPHttpClient:
    """JSON-RPC 2.0 client over HTTP/SSE (streamable HTTP transport)."""

    def __init__(self, *, url: str, headers: dict[str, str] | None = None, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self._url = url
        self._headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **(headers or {})}
        self._timeout = float(timeout)
        self._next_id = 0

    def __enter__(self) -> "MCPHttpClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:  # no persistent connection to release
        return None

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        return [tool for tool in (tools or []) if isinstance(tool, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> MCPToolResult:
        result = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        return _normalize_tool_result(result if isinstance(result, dict) else {})

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._url:
            raise MCPClientError("MCP http server requires a url.")
        self._next_id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}).encode("utf-8")
        http_request = request.Request(self._url, data=body, headers=self._headers, method="POST")
        try:
            with request.urlopen(http_request, timeout=self._timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MCPClientError(f"MCP http request failed ({exc.code}): {detail[:500]}") from exc
        except (error.URLError, TimeoutError) as exc:
            raise MCPClientError(f"MCP http connection failed: {exc}") from exc
        message = _parse_http_message(raw)
        if "error" in message and message["error"]:
            err = message["error"]
            raise MCPClientError(f"MCP error {err.get('code')}: {err.get('message')}")
        result = message.get("result")
        return result if isinstance(result, dict) else {}


def _parse_http_message(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    # SSE framing: pull the last JSON data: line.
    if "data:" in text:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("data:"):
                candidate = line.removeprefix("data:").strip()
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    continue
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MCPClientError(f"MCP server returned a non-JSON response: {text[:200]}") from exc
    return parsed if isinstance(parsed, dict) else {}


def connect(spec: Any, *, timeout: float = _DEFAULT_TIMEOUT) -> MCPStdioClient | MCPHttpClient:
    """Create (and, for stdio, start) a client for an MCPServerSpec-like object."""

    transport = str(getattr(spec, "transport", "stdio") or "stdio").lower()
    config = getattr(spec, "config", {}) or {}
    if transport in {"http", "sse", "streamable-http"}:
        url = getattr(spec, "url", None)
        if not url:
            raise MCPClientError(f"MCP server '{getattr(spec, 'id', '')}' has no url for {transport} transport.")
        headers = config.get("headers") if isinstance(config.get("headers"), dict) else {}
        return MCPHttpClient(url=url, headers=headers, timeout=timeout)
    client = MCPStdioClient(
        command=getattr(spec, "command", None) or "",
        args=list(getattr(spec, "args", []) or []),
        env=config.get("env") if isinstance(config.get("env"), dict) else None,
        cwd=config.get("cwd") if isinstance(config.get("cwd"), str) else None,
        timeout=timeout,
    )
    client.start()
    return client


def list_mcp_tools(spec: Any, *, timeout: float = _DEFAULT_TIMEOUT) -> list[dict[str, Any]]:
    client = connect(spec, timeout=timeout)
    try:
        return client.list_tools()
    finally:
        client.close()


def call_mcp_tool(spec: Any, name: str, arguments: dict[str, Any] | None = None, *, timeout: float = _DEFAULT_TIMEOUT) -> MCPToolResult:
    client = connect(spec, timeout=timeout)
    try:
        return client.call_tool(name, arguments or {})
    finally:
        client.close()
