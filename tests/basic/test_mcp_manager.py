import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

from aider.mcp.config import MCPServerConfig
from aider.mcp.manager import MCPConnectionError, MCPManager

ECHO_SERVER_SCRIPT = str(
    Path(__file__).resolve().parent.parent / "fixtures" / "mcp_servers" / "echo_server.py"
)
AUTH_HTTP_SERVER_SCRIPT = str(
    Path(__file__).resolve().parent.parent / "fixtures" / "mcp_servers" / "auth_http_server.py"
)


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                s.connect(("127.0.0.1", port))
                return
            except OSError:
                time.sleep(0.1)
    raise TimeoutError(f"auth_http_server did not open port {port} within {timeout}s")


class TestMCPManagerRoundTrip(unittest.TestCase):
    """Real round-trip test against an actual MCP server subprocess (not a
    mock of the mcp SDK): connect, discover tools, call one, verify the
    result. This is the "mock MCP server exposing a trivial tool, full
    round-trip test" required by BUILD_PLAN.md Phase 6 step 7.
    """

    def setUp(self):
        self.servers = {
            "echo-test": MCPServerConfig(
                name="echo-test",
                command=sys.executable,
                args=[ECHO_SERVER_SCRIPT],
            )
        }
        self.manager = MCPManager(self.servers, timeout=20)

    def tearDown(self):
        self.manager.shutdown()

    def test_connect_discover_and_call_tool(self):
        tools_by_server = self.manager.connect_all()

        self.assertEqual(self.manager.connect_errors, {})
        self.assertIn("echo-test", tools_by_server)
        tools = tools_by_server["echo-test"]
        self.assertEqual(len(tools), 1)

        tool = tools[0]
        self.assertEqual(tool.name, "echo")
        self.assertEqual(tool.server_name, "echo-test")
        self.assertEqual(tool.qualified_name, "mcp__echo-test__echo")
        self.assertIn("message", tool.input_schema.get("properties", {}))

        # functions= schema translation (feeds Coder.send()'s existing plumbing)
        schema = tool.to_function_schema()
        self.assertEqual(schema["name"], "mcp__echo-test__echo")
        self.assertIn("parameters", schema)

        result = self.manager.call_tool("echo-test", "echo", {"message": "hello mcp"})
        self.assertFalse(result.isError)
        text_blocks = [c.text for c in result.content if c.type == "text"]
        self.assertIn("hello mcp", text_blocks)

    def test_call_tool_on_unconnected_server_raises(self):
        with self.assertRaises(MCPConnectionError):
            self.manager.call_tool("never-connected", "echo", {})

    def test_connect_all_with_no_servers_is_noop(self):
        manager = MCPManager({})
        tools = manager.connect_all()
        self.assertEqual(tools, {})
        manager.shutdown()

    def test_bad_command_records_connect_error_without_crashing(self):
        servers = {
            "broken": MCPServerConfig(
                name="broken",
                command="this-command-does-not-exist-anywhere",
                args=[],
            )
        }
        manager = MCPManager(servers, timeout=10)
        try:
            tools_by_server = manager.connect_all()
            self.assertEqual(tools_by_server, {})
            self.assertIn("broken", manager.connect_errors)
        finally:
            manager.shutdown()


class TestMCPManagerHTTPAuth(unittest.TestCase):
    """Real round-trip test against an actual HTTP MCP server subprocess
    that requires a bearer token (see auth_http_server.py) -- verifies
    MCPServerConfig.headers actually reaches the wire as a real
    Authorization header a real server enforces, not just that manager.py
    constructs an httpx.AsyncClient object correctly.
    """

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.proc = subprocess.Popen(
            [sys.executable, AUTH_HTTP_SERVER_SCRIPT, str(cls.port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_for_port(cls.port, timeout=15)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()

    def test_correct_bearer_token_connects_and_lists_tools(self):
        server = MCPServerConfig(
            name="auth-test",
            url=f"http://127.0.0.1:{self.port}/mcp",
            headers={"Authorization": "Bearer test-token-12345"},
        )
        manager = MCPManager({"auth-test": server}, timeout=15)
        try:
            tools_by_server = manager.connect_all()
            self.assertEqual(manager.connect_errors, {})
            self.assertIn("auth-test", tools_by_server)
            names = [t.name for t in tools_by_server["auth-test"]]
            self.assertIn("whoami", names)

            result = manager.call_tool("auth-test", "whoami", {})
            self.assertFalse(result.isError)
            text_blocks = [c.text for c in result.content if c.type == "text"]
            self.assertIn("authenticated", text_blocks)
        finally:
            manager.shutdown()

    def test_missing_auth_header_fails_to_connect(self):
        server = MCPServerConfig(
            name="auth-test-noauth",
            url=f"http://127.0.0.1:{self.port}/mcp",
        )
        manager = MCPManager({"auth-test-noauth": server}, timeout=15)
        try:
            tools_by_server = manager.connect_all()
            self.assertEqual(tools_by_server, {})
            self.assertIn("auth-test-noauth", manager.connect_errors)
        finally:
            manager.shutdown()

    def test_wrong_bearer_token_fails_to_connect(self):
        server = MCPServerConfig(
            name="auth-test-wrong",
            url=f"http://127.0.0.1:{self.port}/mcp",
            headers={"Authorization": "Bearer not-the-right-token"},
        )
        manager = MCPManager({"auth-test-wrong": server}, timeout=15)
        try:
            tools_by_server = manager.connect_all()
            self.assertEqual(tools_by_server, {})
            self.assertIn("auth-test-wrong", manager.connect_errors)
        finally:
            manager.shutdown()


if __name__ == "__main__":
    unittest.main()
