"""AgentCoder: aider's MCP tool-use mode (BUILD_PLAN.md Phase 6 step 6).

Scoped to its own edit_format ("agent") rather than layered onto every
existing coder, per BUILD_PLAN.md's recommendation to control the surface
area the same way ArchitectCoder is a distinct mode rather than a flag on
every coder. AgentCoder does no aider-internal edit-format parsing at all;
every function/tool_call it sees is routed to a connected MCP server.
"""

import json

from aider.mcp import MCPConnectionError, MCPManager, load_mcp_servers

from .agent_prompts import AgentPrompts
from .base_coder import Coder


class AgentCoder(Coder):
    """Chat with tools exposed by configured MCP servers.

    Every MCP tool call is gated behind an explicit approval prompt
    (io.confirm_ask), regardless of --confirm-edits, since MCP tools can
    have arbitrary side effects (not just file edits) with a less
    predictable blast radius than an in-repo edit (BUILD_PLAN.md Phase 6
    step 5).
    """

    edit_format = "agent"
    gpt_prompts = AgentPrompts()
    # Each tool call consumes one reflection cycle (see reply_completed()
    # below); base_coder's shared default of 3 is tuned for lint/test-fix
    # loops that rarely chain more than 2-3 times, but a real tool-using
    # agent turn often needs several sequential tool calls to complete one
    # user request (e.g. list a directory, then read a file it found, then
    # edit it). Raised here rather than for every coder.
    max_reflections = 20

    def __init__(self, *args, mcp_manager=None, mcp_timeout=None, **kwargs):
        super().__init__(*args, **kwargs)

        self._owns_mcp_manager = mcp_manager is None
        if mcp_manager is not None:
            self.mcp_manager = mcp_manager
        else:
            servers = load_mcp_servers(git_root=self.root)
            self.mcp_manager = MCPManager(
                servers, **({"timeout": mcp_timeout} if mcp_timeout else {})
            )

        self._mcp_tools_by_qualified_name = {}
        self._connect_mcp_tools()

    def _connect_mcp_tools(self):
        tools_by_server = self.mcp_manager.connect_all()

        for name, error in self.mcp_manager.connect_errors.items():
            self.io.tool_warning(f"MCP server '{name}' failed to connect: {error}")

        all_tools = []
        for server_tools in tools_by_server.values():
            all_tools.extend(server_tools)

        self._mcp_tools_by_qualified_name = {t.qualified_name: t for t in all_tools}
        self.functions = [t.to_function_schema() for t in all_tools] or None

        if all_tools:
            self.io.tool_output(
                f"Connected {len(tools_by_server)} MCP server(s), {len(all_tools)} tool(s)"
                " available."
            )
        elif not self.mcp_manager.servers:
            self.io.tool_warning(
                "AgentCoder started with no MCP servers configured (no .mcp.json found)."
                " Add one to give the model tools to call."
            )

    def get_edits(self, mode="update"):
        # AgentCoder never applies aider-internal file edits -- all actions
        # go through MCP tool calls instead.
        return []

    def apply_edits(self, edits):
        pass

    def reply_completed(self):
        """Called after each model turn. If the model made tool call(s),
        dispatch each to its MCP server (with approval gating), append the
        results as tool-role messages, and drive another turn via
        reflected_message -- reusing aider's existing reflection loop
        (run_one) rather than adding a second, parallel multi-turn
        mechanism. Returns True (turn genuinely finished, no pending tool
        calls) or False/None (falls through to normal reply handling).
        """
        tool_calls = self.partial_response_tool_calls
        if not tool_calls:
            return None

        for tool_call in tool_calls:
            self._dispatch_tool_call(tool_call)

        # Drive another turn: the tool results are already appended to
        # cur_messages as role="tool" messages below; reflected_message just
        # needs to be truthy to make run_one() call send_message() again.
        # Using a marker rather than real content since the actual content
        # the model needs is the tool-role messages already in history, not
        # a synthetic user turn.
        self.reflected_message = "(continuing after tool call)"
        return True

    def _dispatch_tool_call(self, tool_call):
        qualified_name = tool_call.function.name
        try:
            arguments = json.loads(tool_call.function.arguments or "{}")
        except (TypeError, ValueError) as err:
            self._append_tool_result(
                tool_call, is_error=True, text=f"Could not parse tool call arguments: {err}"
            )
            return

        tool = self._mcp_tools_by_qualified_name.get(qualified_name)
        if tool is None:
            self._append_tool_result(
                tool_call,
                is_error=True,
                text=f"Unknown tool '{qualified_name}' -- not exposed by any connected MCP server.",
            )
            return

        approved = self.io.confirm_ask(
            "Allow this MCP tool call?",
            subject=f"{tool.server_name}.{tool.name}({json.dumps(arguments)})",
            explicit_yes_required=True,
        )
        if not approved:
            self._append_tool_result(
                tool_call, is_error=True, text="Tool call rejected by user."
            )
            return

        try:
            result = self.mcp_manager.call_tool(tool.server_name, tool.name, arguments)
        except MCPConnectionError as err:
            self._append_tool_result(tool_call, is_error=True, text=str(err))
            return

        text_parts = [c.text for c in result.content if getattr(c, "type", None) == "text"]
        text = "\n".join(text_parts) if text_parts else "(tool call returned no text content)"
        self._append_tool_result(tool_call, is_error=bool(result.isError), text=text)

    def _append_tool_result(self, tool_call, is_error, text):
        if is_error:
            self.io.tool_error(f"MCP tool call failed: {text}")
        else:
            self.io.tool_output(f"MCP tool result: {text}")

        self.cur_messages += [
            dict(
                role="tool",
                tool_call_id=tool_call.id,
                content=text,
            )
        ]

    def __del__(self):
        try:
            if getattr(self, "_owns_mcp_manager", False):
                self.mcp_manager.shutdown()
        except Exception:  # noqa: BLE001 - never raise from __del__
            pass
        try:
            super().__del__()
        except Exception:  # noqa: BLE001
            pass
