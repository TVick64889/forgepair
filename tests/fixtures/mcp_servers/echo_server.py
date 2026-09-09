"""A trivial stdio MCP server for tests: exposes one tool, `echo`, that
returns its input argument back as text. Used by test_mcp_manager.py for a
real round-trip test (connect -> discover tool -> call it -> get result)
against an actual MCP server process, not a mock of the SDK.

Run directly (not imported) as a subprocess:
    python tests/fixtures/mcp_servers/echo_server.py
"""

from mcp.server.fastmcp import FastMCP

mcp_app = FastMCP("echo-test-server")


@mcp_app.tool()
def echo(message: str) -> str:
    """Echo the given message back."""
    return message


if __name__ == "__main__":
    mcp_app.run(transport="stdio")
