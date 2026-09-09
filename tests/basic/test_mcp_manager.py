import sys
import unittest
from pathlib import Path

from aider.mcp.config import MCPServerConfig
from aider.mcp.manager import MCPConnectionError, MCPManager

ECHO_SERVER_SCRIPT = str(
    Path(__file__).resolve().parent.parent / "fixtures" / "mcp_servers" / "echo_server.py"
)


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


if __name__ == "__main__":
    unittest.main()
