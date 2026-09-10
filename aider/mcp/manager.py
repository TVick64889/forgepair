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
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import httpx
import psutil
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from aider.mcp.config import MCPServerConfig

# Default timeout for any single MCP operation (connect, list_tools, call_tool).
# MCP servers can have arbitrary side effects/latency; this bounds how long a
# single hung/misbehaving server can freeze the coder's turn.
DEFAULT_MCP_TIMEOUT = 30

# Default filename for the per-workdir PID-tracking file used to find MCP
# server subprocesses orphaned by a previous session that died uncleanly
# (crash, SSH drop, SIGKILL) before shutdown() or AgentCoder.__del__ ever
# ran -- both of those cleanup paths require the aider process itself to
# still be alive, which doesn't help here. See STATUS.md. Covered by
# .gitignore's ".aider*" pattern, same as the other .aider.* runtime files.
DEFAULT_MCP_PID_FILE = ".aider.mcp-pids.json"


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


@dataclass
class MCPResource:
    """A resource (readable, non-executable data source, e.g. a file, a
    live status page) exposed by a connected MCP server. Unlike a tool,
    a resource isn't callable via functions= -- it's fetched directly by
    URI (see MCPManager.read_resource) and pulled into chat as content,
    not exposed to the model as something it can invoke mid-turn."""

    server_name: str
    uri: str
    name: Optional[str]
    description: Optional[str]
    mime_type: Optional[str]

    @property
    def qualified_name(self):
        return f"{self.server_name}:{self.uri}"


@dataclass
class MCPPrompt:
    """A reusable prompt template exposed by a connected MCP server.
    Fetched by name (+ optional arguments) via MCPManager.get_prompt,
    which returns the server-rendered message text -- also not callable
    via functions=, since a prompt template produces conversation
    content for the user/model to see, not a side-effecting action."""

    server_name: str
    name: str
    description: Optional[str]
    arguments: List[dict]

    @property
    def qualified_name(self):
        return f"{self.server_name}:{self.name}"


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

    def __init__(
        self,
        servers: Dict[str, MCPServerConfig],
        timeout=DEFAULT_MCP_TIMEOUT,
        pid_file: Optional[Path] = None,
    ):
        self.servers = servers
        self.timeout = timeout
        self.pid_file = Path(pid_file) if pid_file else None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._sessions: Dict[str, ClientSession] = {}
        self._tools_by_server: Dict[str, List[MCPTool]] = {}
        self._resources_by_server: Dict[str, List[MCPResource]] = {}
        self._prompts_by_server: Dict[str, List[MCPPrompt]] = {}
        self._connect_errors: Dict[str, str] = {}
        self._server_tasks: Dict[str, "asyncio.Task"] = {}
        self._shutdown_event: Optional[asyncio.Event] = None
        self._pid_lock: Optional[asyncio.Lock] = None
        # PIDs *this* manager instance spawned and recorded to pid_file,
        # cleared from the file on a clean shutdown() -- see _record_pid /
        # _clear_own_pid_file_entries.
        self._recorded_pids: Dict[str, List[int]] = {}
        # Leftover processes found by check_for_leftover_processes() at the
        # start of connect_all() (from a *previous*, uncleanly-terminated
        # session's pid_file entries) -- see leftover_processes.
        self._leftover_processes: List[dict] = []
        self._leftover_by_name: Dict[str, dict] = {}
        self._killed_leftover_processes: List[dict] = []
        self._killed_leftover_pids: set = set()

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
            raise MCPConnectionError(
                f"MCP operation timed out after {timeout or self.timeout}s"
            )

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
        self._resources_by_server = {}
        self._prompts_by_server = {}
        # This session exited cleanly -- our own recorded PIDs are about to
        # be genuinely gone (or are being closed by the code above), so
        # remove only *our* entries from the shared pid_file. Leaves any
        # entries this instance didn't write (e.g. another concurrent
        # session's) untouched.
        self._clear_own_pid_file_entries()
        self._recorded_pids = {}

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

        Before spawning anything, checks pid_file for MCP server
        subprocesses left running by a previous session that died
        uncleanly (crash, dropped SSH connection, SIGKILL) -- see
        check_for_leftover_processes(). Any found are reported via
        leftover_processes for the caller to warn about; by default they
        are left running (not touched) -- the exception is a server whose
        own connect attempt below actually fails while a matching leftover
        for that same server name is present, which is taken as evidence
        the leftover is blocking the new one from loading (e.g. a
        single-instance-only stdio server, or a local port already bound).
        Only then is it killed (after re-verifying it's still the same
        process, not a reused PID) and the connect retried once.
        """
        if not self.servers:
            return {}
        self.check_for_leftover_processes()
        self.start()
        return self._run_coro(
            self._aconnect_all(), timeout=self.timeout * max(1, len(self.servers))
        )

    @property
    def connect_errors(self):
        """dict[server_name, error message] for servers that failed to connect."""
        return dict(self._connect_errors)

    @property
    def leftover_processes(self):
        """List of dicts describing MCP server subprocesses from a previous,
        uncleanly-terminated session that are still alive, as found by the
        most recent check_for_leftover_processes() call (connect_all() runs
        it automatically). Each dict: {server_name, pids, command, args}.
        These are left running by default -- see killed_leftover_processes
        for the ones actually terminated because they blocked a fresh
        connect."""
        return list(self._leftover_processes)

    @property
    def killed_leftover_processes(self):
        """List of dicts (same shape as leftover_processes) for leftover
        processes this session actually killed, because leaving them
        running was blocking that same server name's own connect attempt
        from succeeding."""
        return list(self._killed_leftover_processes)

    async def _aconnect_all(self):
        self._shutdown_event = asyncio.Event()
        self._pid_lock = asyncio.Lock()
        await self._aconnect_servers(self.servers)

        # Kill-if-blocking: only for servers whose fresh connect attempt
        # above actually failed AND which have a still-alive leftover
        # (from a previous, uncleanly-terminated session) recorded under
        # that exact server name -- taken together as evidence the
        # leftover is what's blocking the new one from loading (e.g. a
        # single-instance-only stdio server, or a local port/lock already
        # held). This is the one case that kills a leftover automatically;
        # otherwise leftovers are left alone (see leftover_processes) and
        # only reported for the caller to warn about.
        retry_servers = {}
        for name in list(self._connect_errors.keys()):
            leftover = self._leftover_by_name.get(name)
            if leftover and self._kill_leftover(name, leftover):
                retry_servers[name] = self.servers[name]

        if retry_servers:
            for name in retry_servers:
                self._connect_errors.pop(name, None)
                self._server_tasks.pop(name, None)
            await self._aconnect_servers(retry_servers)

        return dict(self._tools_by_server)

    async def _aconnect_servers(self, servers):
        """Spawn/connect the given dict[name, MCPServerConfig] and wait for
        each to either become ready or fail. Factored out of _aconnect_all
        so the kill-if-blocking retry (see _aconnect_all) can re-run just
        the subset of servers it killed a leftover for, without repeating
        the ones that already connected fine."""
        ready_events = {}
        for name, server in servers.items():
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
                {wait_ready, self._server_tasks[name]},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if wait_ready not in done:
                wait_ready.cancel()

    async def _server_lifetime(
        self, name, server: MCPServerConfig, ready: asyncio.Event
    ):
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
                # Capture the PID of the subprocess stdio_client spawns so a
                # future session (after this one dies uncleanly, without
                # ever reaching shutdown()) can recognize it as a leftover
                # -- see check_for_leftover_processes(). stdio_client's API
                # doesn't expose the Process object to callers, so this
                # diffs this OS process's children immediately before/after
                # entering the transport context manager (that's exactly
                # where anyio spawns it), serialized via _pid_lock so
                # concurrent server connects in this same batch can't steal
                # credit for each other's new child.
                async with self._pid_lock:
                    before_pids = self._snapshot_child_pids()
                    transport_streams = await transport_cm.__aenter__()
                    spawned_pids = self._snapshot_child_pids() - before_pids
                if spawned_pids:
                    self._record_pids(name, spawned_pids, server)
                try:
                    await self._run_session(name, transport_streams, ready)
                except BaseException:
                    if not await transport_cm.__aexit__(*sys.exc_info()):
                        raise
                else:
                    await transport_cm.__aexit__(None, None, None)
            else:
                # A custom httpx.AsyncClient with default headers is how
                # streamable_http_client supports authenticated remote
                # servers (bearer tokens, API keys, etc. via server.headers
                # in .mcp.json) -- it has no separate headers= param of its
                # own. Only bother constructing one when headers are
                # actually configured; an unauthenticated server keeps using
                # the library's own default client.
                if server.headers:
                    async with httpx.AsyncClient(headers=server.headers) as http_client:
                        async with streamable_http_client(
                            server.url, http_client=http_client
                        ) as transport_streams:
                            await self._run_session(name, transport_streams, ready)
                else:
                    async with streamable_http_client(server.url) as transport_streams:
                        await self._run_session(name, transport_streams, ready)
        except Exception as err:  # noqa: BLE001 - any transport/protocol failure
            self._connect_errors.setdefault(name, str(err))
            ready.set()
        finally:
            self._sessions.pop(name, None)

    async def _run_session(self, name, transport_streams, ready):
        """Open the ClientSession over an already-connected transport,
        discover tools/resources/prompts, then hold the session open until
        shutdown -- shared by both the stdio and HTTP branches of
        _server_lifetime so the auth-aware httpx.AsyncClient wiring doesn't
        have to duplicate the session/discovery/ready logic.
        """
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

            # Resources and prompts are optional MCP primitives -- a server
            # that only implements the tools capability (the common case)
            # raises for these, which is not itself a connection failure.
            # Each is tried independently so a server exposing resources but
            # not prompts (or vice versa) doesn't lose the one it does support.
            try:
                res_result = await session.list_resources()
                self._resources_by_server[name] = [
                    MCPResource(
                        server_name=name,
                        uri=str(r.uri),
                        name=r.name,
                        description=r.description,
                        mime_type=r.mimeType,
                    )
                    for r in res_result.resources
                ]
            except Exception:  # noqa: BLE001 - resources capability not supported
                self._resources_by_server[name] = []

            try:
                prompt_result = await session.list_prompts()
                self._prompts_by_server[name] = [
                    MCPPrompt(
                        server_name=name,
                        name=p.name,
                        description=p.description,
                        arguments=[a.model_dump() for a in (p.arguments or [])],
                    )
                    for p in prompt_result.prompts
                ]
            except Exception:  # noqa: BLE001 - prompts capability not supported
                self._prompts_by_server[name] = []

            ready.set()
            await self._shutdown_event.wait()

    # -- tool calls --------------------------------------------------------

    def all_tools(self):
        """Flat list of MCPTool across every successfully connected server."""
        tools = []
        for server_tools in self._tools_by_server.values():
            tools.extend(server_tools)
        return tools

    def all_resources(self):
        """Flat list of MCPResource across every successfully connected
        server (empty for servers that don't implement the resources
        primitive)."""
        resources = []
        for server_resources in self._resources_by_server.values():
            resources.extend(server_resources)
        return resources

    def all_prompts(self):
        """Flat list of MCPPrompt across every successfully connected
        server (empty for servers that don't implement the prompts
        primitive)."""
        prompts = []
        for server_prompts in self._prompts_by_server.values():
            prompts.extend(server_prompts)
        return prompts

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

    def read_resource(self, server_name, uri):
        """Read a resource by URI from a specific server, blocking for the
        result. Returns the MCP ReadResourceResult (contents is a list of
        TextResourceContents/BlobResourceContents). Raises
        MCPConnectionError if the server isn't connected or the read
        fails/times out."""
        session = self._sessions.get(server_name)
        if session is None:
            raise MCPConnectionError(f"MCP server '{server_name}' is not connected")
        try:
            return self._run_coro(session.read_resource(uri))
        except MCPConnectionError:
            raise
        except Exception as err:  # noqa: BLE001
            raise MCPConnectionError(
                f"Reading resource '{uri}' from MCP server '{server_name}' failed: {err}"
            )

    def get_prompt(self, server_name, prompt_name, arguments=None):
        """Fetch a rendered prompt by name from a specific server, blocking
        for the result. Returns the MCP GetPromptResult (messages is a list
        of PromptMessage). Raises MCPConnectionError if the server isn't
        connected or the fetch fails/times out."""
        session = self._sessions.get(server_name)
        if session is None:
            raise MCPConnectionError(f"MCP server '{server_name}' is not connected")
        try:
            return self._run_coro(session.get_prompt(prompt_name, arguments or {}))
        except MCPConnectionError:
            raise
        except Exception as err:  # noqa: BLE001
            raise MCPConnectionError(
                f"Fetching prompt '{prompt_name}' from MCP server '{server_name}' failed: {err}"
            )

    # -- orphaned-subprocess tracking (STATUS.md: process death, not switch) --
    #
    # Separate from the SwitchCoder cleanup (main.py explicitly calling
    # shutdown() when the coder is replaced mid-session): that only helps
    # while the aider process itself stays alive. If the whole process
    # dies uncleanly -- crash, dropped SSH connection, SIGKILL -- neither
    # shutdown() nor AgentCoder.__del__ ever runs, and any live stdio MCP
    # server subprocess is orphaned at the OS level with nothing in
    # aider's own code watching for it. The mechanism here is PID
    # tracking, not command-line guessing: each spawned stdio server's PID
    # is recorded to pid_file (JSON) as soon as it's spawned, and the
    # entry is cleared on a clean shutdown(). A *future* session checks
    # that file at the start of connect_all() and reports (but does not
    # kill, except when blocking a fresh connect -- see _aconnect_all) any
    # entry whose PID is still alive.

    def _snapshot_child_pids(self):
        """Set of PIDs of this OS process's descendants right now (recursive,
        not just direct children), used to detect which PID(s) stdio_client
        just spawned (see _server_lifetime) by diffing before/after
        entering its transport context manager. Recursive because on
        Windows the actual interpreter running the server script is
        sometimes a grandchild (anyio/the mcp SDK's Windows process
        creation can go through an intermediate launcher process), not a
        direct child -- a non-recursive snapshot would record the wrong
        PID and never recognize the real server process again later."""
        try:
            return {p.pid for p in psutil.Process(os.getpid()).children(recursive=True)}
        except psutil.Error:
            return set()

    def _default_pid_file_path(self):
        for server in self.servers.values():
            if server.source_file:
                return Path(server.source_file).resolve().parent / DEFAULT_MCP_PID_FILE
        return Path.cwd() / DEFAULT_MCP_PID_FILE

    def _resolved_pid_file(self):
        return self.pid_file or self._default_pid_file_path()

    def _record_pids(self, server_name, pids, server: MCPServerConfig):
        """Append newly-spawned PIDs for server_name to pid_file, tagged
        with enough info (command/args, recorded time) that a future
        session can both find them and sanity-check a PID match isn't
        just a reused PID before ever acting on it (see
        check_for_leftover_processes / _kill_leftover)."""
        self._recorded_pids.setdefault(server_name, []).extend(sorted(pids))
        pid_file = self._resolved_pid_file()
        try:
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            data = self._read_pid_file(pid_file)
            data[server_name] = {
                "pids": sorted(set(data.get(server_name, {}).get("pids", [])) | pids),
                "command": server.command,
                "args": list(server.args),
                "recorded_at": time.time(),
                "aider_pid": os.getpid(),
            }
            pid_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            # Best-effort: a pid_file write failure must never block using
            # MCP tools -- it only degrades the leftover-detection safety
            # net for the *next* session, not this one.
            pass

    @staticmethod
    def _read_pid_file(pid_file):
        if not pid_file.exists():
            return {}
        try:
            data = json.loads(pid_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _clear_own_pid_file_entries(self):
        if not self._recorded_pids:
            return
        pid_file = self._resolved_pid_file()
        try:
            data = self._read_pid_file(pid_file)
            for server_name in self._recorded_pids:
                data.pop(server_name, None)
            if data:
                pid_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            else:
                pid_file.unlink(missing_ok=True)
        except OSError:
            pass

    def check_for_leftover_processes(self):
        """Read pid_file and report any entry whose recorded PID is still a
        live process AND whose command/args still match what was recorded
        (the PID-reuse guard -- a bare 'PID still exists' check is not
        enough on its own, since PIDs get recycled by the OS for unrelated
        processes over time). Populates leftover_processes; does not kill
        anything here (that only happens from connect_all()'s
        kill-if-blocking path when a fresh connect for that same server
        name actually fails). Safe to call multiple times; entries for
        servers not currently configured are still reported (renamed/
        removed from .mcp.json since the crash) but can't be
        kill-if-blocking candidates since there's no current config to
        retry against.
        """
        self._leftover_processes = []
        self._leftover_by_name = {}
        pid_file = self._resolved_pid_file()
        data = self._read_pid_file(pid_file)
        our_pid = os.getpid()
        for server_name, entry in data.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("aider_pid") == our_pid:
                # Can't be a leftover from a *previous* session if it's an
                # entry this exact process just wrote (re-entrant call).
                continue
            command = entry.get("command")
            args = entry.get("args") or []
            alive_pids = []
            for pid in entry.get("pids") or []:
                if self._pid_matches_recorded(pid, command, args):
                    alive_pids.append(pid)
            if not alive_pids:
                continue
            leftover = {
                "server_name": server_name,
                "pids": alive_pids,
                "command": command,
                "args": args,
            }
            self._leftover_processes.append(leftover)
            self._leftover_by_name[server_name] = leftover
        return list(self._leftover_processes)

    @staticmethod
    def _pid_matches_recorded(pid, command, args):
        """True if `pid` is currently alive AND its own command/args still
        look like the ones recorded for it -- the PID-reuse guard. Without
        this, a PID that legitimately got reassigned by the OS to some
        unrelated process after the original MCP server exited would be
        misreported (or, worse, ever auto-killed) as a leftover."""
        try:
            proc = psutil.Process(pid)
            if not proc.is_running():
                return False
            proc_cmdline = proc.cmdline()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False
        if not proc_cmdline:
            return False
        recorded_cmdline = [command] + list(args) if command else []
        # Exact argv equality is too strict (path normalization, quoting
        # differences across a resolved executable) -- match on the
        # recorded command appearing somewhere in the live process's argv,
        # which is enough to rule out an unrelated reused-PID process
        # while tolerating those normalization differences.
        if command and not any(command in part for part in proc_cmdline):
            return False
        return bool(recorded_cmdline)

    def _kill_leftover(self, server_name, leftover):
        """Terminate every PID in `leftover` after re-verifying (right
        before killing, not just at check_for_leftover_processes() time --
        time has passed) that each is still alive and still matches the
        recorded command/args. Returns True if at least one process was
        actually killed. Only called from _aconnect_all's kill-if-blocking
        path: a fresh connect for this exact server_name already failed,
        taken as evidence this leftover is what's blocking it."""
        killed_pids = []
        for pid in leftover["pids"]:
            if not self._pid_matches_recorded(
                pid, leftover["command"], leftover["args"]
            ):
                continue
            try:
                proc = psutil.Process(pid)
                proc.terminate()
                try:
                    proc.wait(timeout=min(self.timeout, 5))
                except psutil.TimeoutExpired:
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            killed_pids.append(pid)
            self._killed_leftover_pids.add(pid)
        if killed_pids:
            self._killed_leftover_processes.append(dict(leftover, pids=killed_pids))
            self._remove_pid_file_entry(server_name)
        return bool(killed_pids)

    def _remove_pid_file_entry(self, server_name):
        pid_file = self._resolved_pid_file()
        try:
            data = self._read_pid_file(pid_file)
            if server_name in data:
                del data[server_name]
                if data:
                    pid_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
                else:
                    pid_file.unlink(missing_ok=True)
        except OSError:
            pass
