"""Phase 2: real MCP client execution over a spawned stdio server."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from repooperator_worker.agent_core.mcp import MCPServerSpec, MCPToolAdapter, _mcp_arguments_from_payload
from repooperator_worker.services import mcp_client
from repooperator_worker.services.mcp_client import (
    MCPClientError,
    MCPHttpClient,
    MCPStdioClient,
    _parse_http_message,
    connect,
    list_mcp_tools,
)

# A tiny but real MCP stdio server: JSON-RPC over newline-delimited stdio.
ECHO_SERVER = """\
import sys, json
sys.stderr.write("echo server up\\n")  # logs go to stderr
print("not-json-noise")  # a stray stdout log line the client must skip
sys.stdout.flush()
def send(msg):
    sys.stdout.write(json.dumps(msg) + "\\n"); sys.stdout.flush()
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    mid = msg.get("id"); method = msg.get("method")
    if method == "initialize":
        send({"jsonrpc":"2.0","id":mid,"result":{"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{"name":"echo","version":"1"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        send({"jsonrpc":"2.0","id":mid,"result":{"tools":[{"name":"echo","description":"Echo text","inputSchema":{"type":"object","properties":{"text":{"type":"string"}}}}]}})
    elif method == "tools/call":
        params = msg.get("params", {})
        args = params.get("arguments", {})
        if params.get("name") == "boom":
            send({"jsonrpc":"2.0","id":mid,"result":{"content":[{"type":"text","text":"failure detail"}],"isError":True}})
        else:
            send({"jsonrpc":"2.0","id":mid,"result":{"content":[{"type":"text","text":"echo: " + str(args.get("text",""))}]}})
    else:
        send({"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":"unknown method"}})
"""


class _ServerFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server_path = Path(self.tmp.name) / "echo_server.py"
        self.server_path.write_text(ECHO_SERVER, encoding="utf-8")

    def _spec(self, **overrides) -> MCPServerSpec:
        base = dict(
            id="echo",
            name="echo",
            transport="stdio",
            command=sys.executable,
            args=[str(self.server_path)],
            tools=[{"name": "echo", "description": "Echo text"}],
            enabled=True,
        )
        base.update(overrides)
        return MCPServerSpec(**base)


class StdioClientTests(_ServerFixture):
    def test_list_tools(self) -> None:
        with MCPStdioClient(command=sys.executable, args=[str(self.server_path)]) as client:
            tools = client.list_tools()
        self.assertEqual([t["name"] for t in tools], ["echo"])

    def test_call_tool_success(self) -> None:
        with MCPStdioClient(command=sys.executable, args=[str(self.server_path)]) as client:
            result = client.call_tool("echo", {"text": "hi"})
        self.assertFalse(result.is_error)
        self.assertEqual(result.text, "echo: hi")

    def test_call_tool_error_flag(self) -> None:
        with MCPStdioClient(command=sys.executable, args=[str(self.server_path)]) as client:
            result = client.call_tool("boom", {})
        self.assertTrue(result.is_error)
        self.assertIn("failure detail", result.text)

    def test_missing_command_raises(self) -> None:
        with self.assertRaises(MCPClientError):
            MCPStdioClient(command="/nonexistent/mcp-server-xyz", args=[]).start()


class ModuleHelperTests(_ServerFixture):
    def test_list_mcp_tools_connects_and_closes(self) -> None:
        tools = list_mcp_tools(self._spec())
        self.assertEqual(tools[0]["name"], "echo")

    def test_connect_http_returns_http_client(self) -> None:
        client = connect(MCPServerSpec(id="remote", name="remote", transport="http", url="https://example.test/mcp", enabled=True))
        self.assertIsInstance(client, MCPHttpClient)


class AdapterExecutionTests(_ServerFixture):
    def test_adapter_call_executes_and_strips_meta(self) -> None:
        spec = self._spec()
        adapter = MCPToolAdapter(server=spec, tool_metadata={"name": "echo", "description": "Echo text"})
        result = adapter.call(
            {"text": "hello", "reason_summary": "meta strip", "action_id": "a1", "requires_approval": True},
            context=None,  # adapter.call does not use context
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.observation, "echo: hello")
        self.assertTrue(result.payload["executed"])
        self.assertEqual(result.payload["arguments"], {"text": "hello"})

    def test_adapter_call_marks_error_result_failed(self) -> None:
        adapter = MCPToolAdapter(server=self._spec(), tool_metadata={"name": "boom"})
        result = adapter.call({}, context=None)
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.payload["is_error"])

    def test_adapter_call_handles_unreachable_server(self) -> None:
        spec = self._spec(command="/nonexistent/mcp-server-xyz", args=[])
        adapter = MCPToolAdapter(server=spec, tool_metadata={"name": "echo"})
        result = adapter.call({"text": "x"}, context=None)
        self.assertEqual(result.status, "failed")
        self.assertFalse(result.payload["executed"])


class ArgumentAndParsingTests(unittest.TestCase):
    def test_explicit_arguments_object_wins(self) -> None:
        args = _mcp_arguments_from_payload({"arguments": {"a": 1}, "text": "ignored", "reason_summary": "x"})
        self.assertEqual(args, {"a": 1})

    def test_non_meta_keys_forwarded(self) -> None:
        args = _mcp_arguments_from_payload({"text": "keep", "count": 3, "action_id": "a", "requires_approval": True})
        self.assertEqual(args, {"text": "keep", "count": 3})

    def test_parse_http_message_json(self) -> None:
        self.assertEqual(_parse_http_message('{"jsonrpc":"2.0","id":1,"result":{"ok":true}}')["result"], {"ok": True})

    def test_parse_http_message_sse(self) -> None:
        raw = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"v":2}}\n\n'
        self.assertEqual(_parse_http_message(raw)["result"], {"v": 2})


if __name__ == "__main__":
    unittest.main()
