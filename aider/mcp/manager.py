"""Background asyncio event-loop bridge for connecting to MCP servers.

aider's Coder is entirely synchronous; the `mcp` SDK's ClientSession and
transport clients (stdio_client, streamable_http_client) are all async
(anyio-based). Rather than spin up a fresh event loop and reconnect for
every single tool call (slow: re-runs the server process/handshake each
time), this module runs ONE background asyncio event loop in a daemon
thread for the coder's lifetime, keeps all MCP sessions alive on that
loop, and exposes plain synchronous methods (connect/list_tools/call_tool)
that submit work to the loop via asyncio.run_coroutine_threadsafe() and
block for the result -- so calling code never has to know async exists.
"""

import asyncio
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from aider.mcp.config import MCPServerConfig

# Default timeout for any single MCP operation (connect, list_tools, call_tool).
# MCP servers can have arbitrary side effects/latency; this bounds how long a
# single hung/misbehaving server can freeze the coder's turn.
DEFAULT_MCP_TIMEOUT = 30


class MCPConnectionError(RuntimeError):
    """Raised when connecting to or communicating with an MCP server fails."""


@dataclass
class MCPTool:
    """A tool exposed by a connected MCP server, with enough info to route a
    resolved tool_call back to the right server and translate its schema into
    the `functions=` format Coder.send() already accepts."""

    server_name: str
    name: str
    description: Optional[str]
    input_schema: dict

    @property
    def qualified_name(self):
        """Namespaced name used as the function name sent to the model, so
        tools from different servers (or an aider-internal edit) never
        collide even if two MCP servers happen to expose a tool with the
        same short name."""
        return f"mcp__{self.server_name}__{self.name}"

    def to_function_schema(self):
        return {
            "name": self.qualified_name,
            "description": self.description or "",
            "parameters": self.input_schema or {"type": "object", "properties": {}},
        }


class MCPManager:
    """Owns the background event loop, one ClientSession per configured
    server, and the sync-facing connect/list/call API.

    Usage:
        manager = MCPManager(server_configs, timeout=30)
        manager.start()
        tools = manager.connect_all()   # -> dict[server_name, list[MCPTool]]
        result = manager.call_tool("server_name", "tool_name", {"arg": 1})
        manager.shutdown()
    """

    def __init__(self, servers: Dict[str, MCPServerConfig], timeout=DEFAULT_MCP_TIMEOUT):
        self.servers = servers
        self.timeout = timeout
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._sessions: Dict[str, ClientSession] = {}
        self._tools_by_server: Dict[str, List[MCPTool]] = {}
        self._connect_errors: Dict[str, str] = {}
        self._server_tasks: Dict[str, "asyncio.Task"] = {}
        self._shutdown_event: Optional[asyncio.Event] = None

    # -- lifecycle -----------------------------------------------------

    def start(self):
        """Start the background event loop thread. Idempotent."""
        if self._loop is not None:
            return
        ready = threading.Event()

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            ready.set()
            loop.run_forever()

        self._thread = threading.Thread(target=_run, name="mcp-event-loop", daemon=True)
        self._thread.start()
        ready.wait(timeout=self.timeout)
        if self._loop is None:
            raise MCPConnectionError("MCP background event loop failed to start")

    def _run_coro(self, coro, timeout=None):
        if self._loop is None:
            raise MCPConnectionError("MCPManager.start() must be called before use")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout or self.timeout)
        except asyncio.TimeoutError:
            raise MCPConnectionError(f"MCP operation timed out after {timeout or self.timeout}s")

    def shutdown(self):
        """Close all sessions/transports and stop the event loop. Safe to
        call multiple times or if start() was never called."""
        if self._loop is None:
            return
        if self._shutdown_event is not None:
            self._loop.call_soon_threadsafe(self._shutdown_event.set)
        for task in self._server_tasks.values():
            try:
                self._run_coro(self._await_task(task), timeout=self.timeout)
            except MCPConnectionError:
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=self.timeout)
        self._loop = None
        self._thread = None
        self._sessions = {}
        self._server_tasks = {}
        self._shutdown_event = None

    @staticmethod
    async def _await_task(task):
        await task

    # -- connecting ------------------------------------------------------

    def connect_all(self):
        """Connect to every configured server, enumerate its tools. Returns
        dict[server_name, list[MCPTool]]. A server that fails to connect is
        recorded in self._connect_errors (see connect_errors) and simply
        contributes no tools, rather than aborting every other server or
        crashing the coder -- one misconfigured/offline MCP server should
        not block using aider at all, let alone the other configured servers.
        """
        if not self.servers:
            return {}
        self.start()
        return self._run_coro(
            self._aconnect_all(), timeout=self.timeout * max(1, len(self.servers))
        )

    @property
    def connect_errors(self):
        """dict[server_name, error message] for servers that failed to connect."""
        return dict(self._connect_errors)

    async def _aconnect_all(self):
        self._shutdown_event = asyncio.Event()
        ready_events = {}
        for name, server in self.servers.items():
            ready = asyncio.Event()
            ready_events[name] = ready
            task = asyncio.ensure_future(self._server_lifetime(name, server, ready))
            self._server_tasks[name] = task

        for name, ready in ready_events.items():
            # Each server connects/fails independently; wait for its own
            # readiness signal (or for it to already be done, e.g. errored
            # immediately) rather than a fixed sleep.
            wait_ready = asyncio.ensure_future(ready.wait())
            done, _ = await asyncio.wait(
                {wait_ready, self._server_tasks[name]}, return_when=asyncio.FIRST_COMPLETED
            )
            if wait_ready not in done:
                wait_ready.cancel()

        return dict(self._tools_by_server)

    async def _server_lifetime(self, name, server: MCPServerConfig, ready: asyncio.Event):
        """Owns one server's full connection lifetime in a single task, so the
        anyio cancel scopes opened by its transport/session context managers
        are entered AND exited by this same task (required by anyio -- see
        the RuntimeError this fixes: 'Attempted to exit cancel scope in a
        different task than it was entered in'). Runs until shutdown() sets
        self._shutdown_event, then unwinds its own context managers here.
        """
        try:
            if server.transport == "stdio":
                params = StdioServerParameters(
                    command=server.command, args=server.args, env=server.env or None
                )
                transport_cm = stdio_client(params)
            else:
                transport_cm = streamable_http_client(server.url)

            async with transport_cm as transport_streams:
                read, write = transport_streams[0], transport_streams[1]
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._sessions[name] = session
                    try:
                        result = await session.list_tools()
                        self._tools_by_server[name] = [
                            MCPTool(
                                server_name=name,
                                name=t.name,
                                description=t.description,
                                input_schema=t.inputSchema,
                            )
                            for t in result.tools
                        ]
                    except Exception as err:  # noqa: BLE001
                        self._connect_errors[name] = f"connected but list_tools failed: {err}"

                    ready.set()
                    await self._shutdown_event.wait()
        except Exception as err:  # noqa: BLE001 - any transport/protocol failure
            self._connect_errors.setdefault(name, str(err))
            ready.set()
        finally:
            self._sessions.pop(name, None)

    # -- tool calls --------------------------------------------------------

    def all_tools(self):
        """Flat list of MCPTool across every successfully connected server."""
        tools = []
        for server_tools in self._tools_by_server.values():
            tools.extend(server_tools)
        return tools

    def call_tool(self, server_name, tool_name, arguments):
        """Call a tool on a specific server, blocking for the result.

        Returns the MCP CallToolResult. Raises MCPConnectionError if the
        server isn't connected or the call fails/times out.
        """
        session = self._sessions.get(server_name)
        if session is None:
            raise MCPConnectionError(f"MCP server '{server_name}' is not connected")
        try:
            return self._run_coro(session.call_tool(tool_name, arguments or {}))
        except MCPConnectionError:
            raise
        except Exception as err:  # noqa: BLE001
            raise MCPConnectionError(
                f"Calling tool '{tool_name}' on MCP server '{server_name}' failed: {err}"
            )
