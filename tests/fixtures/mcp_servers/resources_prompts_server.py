"""A stdio MCP server exposing all three MCP primitives (tool, resource,
prompt) so MCPManager's resource/prompt discovery and fetch code can be
tested against a real server, not a mock of the SDK.

Run directly (not imported) as a subprocess:
    python tests/fixtures/mcp_servers/resources_prompts_server.py
"""

from mcp.server.fastmcp import FastMCP

mcp_app = FastMCP("resources-prompts-test-server")


@mcp_app.tool()
def echo(message: str) -> str:
    """Echo the given message back."""
    return message


@mcp_app.resource("test://readme")
def readme() -> str:
    """A trivial static text resource."""
    return "# Test Resource\n\nThis is fixture content for MCP resource tests."


@mcp_app.prompt()
def greet(name: str) -> str:
    """A trivial prompt template taking one argument."""
    return f"Please write a friendly greeting for {name}."


if __name__ == "__main__":
    mcp_app.run(transport="stdio")
