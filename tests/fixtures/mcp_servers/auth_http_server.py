"""A streamable-HTTP MCP server, run as a real subprocess+socket (not a
mock), that requires a bearer token on every request. Used by
test_mcp_manager.py to verify MCPManager's HTTP auth headers support
(server.headers -> httpx.AsyncClient(headers=...)) against a real ASGI
server enforcing real auth, not just inspecting outgoing request objects.

Run directly (not imported) as a subprocess:
    python tests/fixtures/mcp_servers/auth_http_server.py <port>

Requires the header `Authorization: Bearer test-token-12345` on every
request, or responds 401 before MCP protocol negotiation even starts --
mirroring how a real hosted MCP server (Claude Desktop / Claude Code
convention: .mcp.json headers -> Authorization) would reject an
unauthenticated client.
"""

import sys

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

REQUIRED_TOKEN = "test-token-12345"

mcp_app = FastMCP("auth-test-server", stateless_http=True)


@mcp_app.tool()
def whoami() -> str:
    """Return a fixed string, only reachable if auth succeeded."""
    return "authenticated"


class RequireBearerTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {REQUIRED_TOKEN}":
            return PlainTextResponse("Unauthorized", status_code=401)
        return await call_next(request)


def build_app():
    inner = mcp_app.streamable_http_app()
    return Starlette(
        routes=inner.routes,
        middleware=[Middleware(RequireBearerTokenMiddleware)],
        lifespan=inner.router.lifespan_context,
    )


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    uvicorn.run(build_app(), host="127.0.0.1", port=port, log_level="warning")
