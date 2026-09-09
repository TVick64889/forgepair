import hashlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from litellm.types.utils import ChatCompletionMessageToolCall, Function

from aider.coders import Coder
from aider.io import InputOutput
from aider.models import Model

ECHO_SERVER_SCRIPT = str(
    Path(__file__).resolve().parent.parent / "fixtures" / "mcp_servers" / "echo_server.py"
)


def make_stdio_mcp_config(server_name="echo-test"):
    """A real, valid mcpServers config pointing at the trivial echo_server
    fixture, in the exact schema load_mcp_servers() parses."""
    return {
        "mcpServers": {
            server_name: {
                "command": sys.executable,
                "args": [ECHO_SERVER_SCRIPT],
            }
        }
    }


class TestAgentCoderRoundTrip(unittest.TestCase):
    """End-to-end test of AgentCoder (BUILD_PLAN.md Phase 6 exit criteria):
    a real MCP server, a mocked model response requesting a real tool call,
    approval gating, dispatch, and the result fed back into the message
    loop -- everything except the actual LLM call is real (real subprocess,
    real MCP protocol, real approval prompt path).
    """

    def setUp(self):
        self.tmpdir_obj = __import__("tempfile").TemporaryDirectory()
        self.tmpdir = Path(self.tmpdir_obj.name)
        self.original_cwd = __import__("os").getcwd()
        __import__("os").chdir(self.tmpdir)
        (self.tmpdir / ".mcp.json").write_text(
            json.dumps(make_stdio_mcp_config()), encoding="utf-8"
        )
        self.model = Model("gpt-3.5-turbo")
        # yes=True means "non-interactive"; combined with explicit_yes_required=True
        # (which AgentCoder's approval gate uses -- same semantics as Phase 4's
        # confirm_edits_before_apply) this deliberately DECLINES rather than
        # silently approving, matching that established safety behavior. Tests
        # that need an approved tool call must mock confirm_ask explicitly.
        self.io = InputOutput(yes=True)

    def tearDown(self):
        self.shutdown_managers()
        __import__("os").chdir(self.original_cwd)
        self.tmpdir_obj.cleanup()

    def shutdown_managers(self):
        for manager in getattr(self, "_managers_to_shutdown", []):
            manager.shutdown()

    def _make_coder(self):
        coder = Coder.create(
            self.model, "agent", io=self.io, fnames=[], use_git=False, stream=False
        )
        coder.init_before_message()
        self._managers_to_shutdown = getattr(self, "_managers_to_shutdown", [])
        self._managers_to_shutdown.append(coder.mcp_manager)
        return coder

    def _fake_tool_call_completion(self, name, arguments):
        function = Function(name=name, arguments=json.dumps(arguments))
        tool_call = ChatCompletionMessageToolCall(id="call_1", type="function", function=function)
        message = types.SimpleNamespace(
            content=None, tool_calls=[tool_call], reasoning_content=None
        )
        choice = types.SimpleNamespace(message=message, finish_reason="tool_calls")
        return types.SimpleNamespace(choices=[choice])

    def _fake_multi_tool_call_completion(self, calls):
        """calls: list of (call_id, name, arguments) -- simulates a single
        turn where the model requests multiple tool calls at once
        (parallel_tool_calls), which real providers support."""
        tool_calls = [
            ChatCompletionMessageToolCall(
                id=call_id,
                type="function",
                function=Function(name=name, arguments=json.dumps(arguments)),
            )
            for call_id, name, arguments in calls
        ]
        message = types.SimpleNamespace(content=None, tool_calls=tool_calls, reasoning_content=None)
        choice = types.SimpleNamespace(message=message, finish_reason="tool_calls")
        return types.SimpleNamespace(choices=[choice])

    def _fake_text_completion(self, text):
        message = types.SimpleNamespace(content=text, tool_calls=None, reasoning_content=None)
        choice = types.SimpleNamespace(message=message, finish_reason="stop")
        return types.SimpleNamespace(choices=[choice])

    def test_connects_and_exposes_echo_tool_as_a_function(self):
        coder = self._make_coder()
        self.assertIn("mcp__echo-test__echo", coder._mcp_tools_by_qualified_name)
        self.assertTrue(coder.functions)
        names = [f["name"] for f in coder.functions]
        self.assertIn("mcp__echo-test__echo", names)

    def test_full_round_trip_tool_call_approved_and_fed_back(self):
        coder = self._make_coder()
        coder.io.confirm_ask = MagicMock(return_value=True)

        # Turn 1: model calls the tool. Turn 2: model replies with plain text
        # (using the tool result, which we verify made it into cur_messages).
        responses = [
            self._fake_tool_call_completion(
                "mcp__echo-test__echo", {"message": "hello from the model"}
            ),
            self._fake_text_completion("Done, the echo tool returned your message."),
        ]

        with patch.object(
            self.model,
            "send_completion",
            side_effect=[(hashlib.sha1(b"x"), r) for r in responses],
        ) as mock_send:
            coder.run_one("please echo something", preproc=False)

        self.assertEqual(mock_send.call_count, 2, "should call the model again after the tool call")

        # The tool result must have been appended as a role=tool message
        # containing the real echoed text from the real MCP server.
        tool_messages = [m for m in coder.cur_messages if m.get("role") == "tool"]
        self.assertTrue(tool_messages, "expected a tool-role message with the MCP result")
        self.assertIn("hello from the model", tool_messages[-1]["content"])

        self.assertEqual(
            coder.partial_response_content, "Done, the echo tool returned your message."
        )

    def test_tool_call_rejected_by_user_is_not_executed(self):
        io = InputOutput(yes=False)  # yes=False -> confirm_ask defaults to declining
        io.confirm_ask = MagicMock(return_value=False)
        coder = Coder.create(self.model, "agent", io=io, fnames=[], use_git=False, stream=False)
        coder.init_before_message()
        self._managers_to_shutdown = getattr(self, "_managers_to_shutdown", [])
        self._managers_to_shutdown.append(coder.mcp_manager)

        responses = [
            self._fake_tool_call_completion("mcp__echo-test__echo", {"message": "should not run"}),
            self._fake_text_completion("Ok, I won't call the tool."),
        ]
        with patch.object(
            self.model,
            "send_completion",
            side_effect=[(hashlib.sha1(b"x"), r) for r in responses],
        ):
            coder.run_one("please echo something", preproc=False)

        io.confirm_ask.assert_called_once()
        tool_messages = [m for m in coder.cur_messages if m.get("role") == "tool"]
        self.assertTrue(tool_messages)
        self.assertIn("rejected", tool_messages[-1]["content"].lower())

    def test_unknown_tool_name_produces_error_result_not_crash(self):
        coder = self._make_coder()
        responses = [
            self._fake_tool_call_completion("mcp__echo-test__does-not-exist", {}),
            self._fake_text_completion("Sorry, that tool doesn't exist."),
        ]
        with patch.object(
            self.model,
            "send_completion",
            side_effect=[(hashlib.sha1(b"x"), r) for r in responses],
        ):
            coder.run_one("please call a bogus tool", preproc=False)

        tool_messages = [m for m in coder.cur_messages if m.get("role") == "tool"]
        self.assertTrue(tool_messages)
        self.assertIn("unknown tool", tool_messages[-1]["content"].lower())

    def test_multiple_tool_calls_in_one_turn_each_get_a_matching_result(self):
        """Real providers support parallel_tool_calls: a single assistant
        turn can request several tool calls at once, each with its own
        tool_call_id, and each needs its own role=tool result referencing
        that same id -- not just the last one processed."""
        coder = self._make_coder()
        coder.io.confirm_ask = MagicMock(return_value=True)

        responses = [
            self._fake_multi_tool_call_completion(
                [
                    ("call_a", "mcp__echo-test__echo", {"message": "first"}),
                    ("call_b", "mcp__echo-test__echo", {"message": "second"}),
                ]
            ),
            self._fake_text_completion("Both echoes done."),
        ]
        with patch.object(
            self.model,
            "send_completion",
            side_effect=[(hashlib.sha1(b"x"), r) for r in responses],
        ) as mock_send:
            coder.run_one("please echo two things", preproc=False)

        self.assertEqual(mock_send.call_count, 2)
        self.assertEqual(coder.io.confirm_ask.call_count, 2, "each call needs its own approval")

        tool_messages = [m for m in coder.cur_messages if m.get("role") == "tool"]
        self.assertEqual(len(tool_messages), 2)
        by_id = {m["tool_call_id"]: m["content"] for m in tool_messages}
        self.assertIn("first", by_id.get("call_a", ""))
        self.assertIn("second", by_id.get("call_b", ""))

        # The assistant message recording the tool_calls must list both
        # ids, not just the last one, so the tool-result messages have a
        # matching parent to reference.
        assistant_tool_call_msgs = [
            m for m in coder.cur_messages if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        self.assertEqual(len(assistant_tool_call_msgs), 1)
        recorded_ids = {tc["id"] for tc in assistant_tool_call_msgs[0]["tool_calls"]}
        self.assertEqual(recorded_ids, {"call_a", "call_b"})


if __name__ == "__main__":
    unittest.main()
