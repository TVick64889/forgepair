"""End-to-end tests for the /mcp-resources and /mcp-prompts slash commands
(STATUS.md's "MCP resources/prompts primitives" scoped follow-up): real
AgentCoder, real MCP server subprocess exposing all three primitives, real
Commands.do_run() dispatch -- only the LLM call itself is out of scope
(these commands never call the model).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from aider.coders import Coder
from aider.commands import Commands
from aider.io import InputOutput
from aider.models import Model

RESOURCES_PROMPTS_SERVER_SCRIPT = str(
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "mcp_servers"
    / "resources_prompts_server.py"
)


def make_stdio_mcp_config(server_name="res-prompt-test"):
    return {
        "mcpServers": {
            server_name: {
                "command": sys.executable,
                "args": [RESOURCES_PROMPTS_SERVER_SCRIPT],
            }
        }
    }


class TestMCPResourcesAndPromptsCommands(unittest.TestCase):
    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmpdir_obj.name)
        self.original_cwd = __import__("os").getcwd()
        __import__("os").chdir(self.tmpdir)
        (self.tmpdir / ".mcp.json").write_text(
            json.dumps(make_stdio_mcp_config()), encoding="utf-8"
        )
        self.io = InputOutput(pretty=False, fancy_input=False, yes=True)
        self.coder = Coder.create(
            Model("gpt-3.5-turbo"), "agent", io=self.io, fnames=[], use_git=False, stream=False
        )
        self.coder.init_before_message()
        self.commands = Commands(self.io, self.coder)

    def tearDown(self):
        self.coder.mcp_manager.shutdown()
        __import__("os").chdir(self.original_cwd)
        self.tmpdir_obj.cleanup()

    def test_mcp_resources_list_shows_the_fixture_resource(self):
        output = []
        self.io.tool_output = lambda msg="", *a, **k: output.append(msg)
        self.commands.cmd_mcp_resources("")
        joined = "\n".join(output)
        self.assertIn("test://readme", joined)
        self.assertIn("res-prompt-test", joined)

    def test_mcp_resources_fetch_by_uri_adds_content_to_chat(self):
        self.commands.cmd_mcp_resources("test://readme")
        contents = [m["content"] for m in self.coder.cur_messages if m["role"] == "user"]
        self.assertTrue(any("Test Resource" in c for c in contents))

    def test_mcp_resources_unknown_uri_errors_without_crashing(self):
        errors = []
        self.io.tool_error = lambda msg="", *a, **k: errors.append(msg)
        self.commands.cmd_mcp_resources("test://does-not-exist")
        self.assertTrue(any("does-not-exist" in e for e in errors))
        self.assertEqual(self.coder.cur_messages, [])

    def test_mcp_prompts_list_shows_the_fixture_prompt(self):
        output = []
        self.io.tool_output = lambda msg="", *a, **k: output.append(msg)
        self.commands.cmd_mcp_prompts("")
        joined = "\n".join(output)
        self.assertIn("greet", joined)
        self.assertIn("res-prompt-test", joined)

    def test_mcp_prompts_run_with_argument_adds_rendered_text_to_chat(self):
        self.commands.cmd_mcp_prompts("greet name=Bob")
        contents = [m["content"] for m in self.coder.cur_messages if m["role"] == "user"]
        self.assertTrue(any("Bob" in c for c in contents))

    def test_mcp_prompts_unknown_name_errors_without_crashing(self):
        errors = []
        self.io.tool_error = lambda msg="", *a, **k: errors.append(msg)
        self.commands.cmd_mcp_prompts("does-not-exist")
        self.assertTrue(any("does-not-exist" in e for e in errors))
        self.assertEqual(self.coder.cur_messages, [])

    def test_mcp_prompts_malformed_argument_errors_without_crashing(self):
        errors = []
        self.io.tool_error = lambda msg="", *a, **k: errors.append(msg)
        self.commands.cmd_mcp_prompts("greet not-a-kv-pair")
        self.assertTrue(any("key=value" in e for e in errors))
        self.assertEqual(self.coder.cur_messages, [])

    def test_commands_registered_with_expected_slash_names(self):
        names = self.commands.get_commands()
        self.assertIn("/mcp-resources", names)
        self.assertIn("/mcp-prompts", names)


class TestMCPResourcesAndPromptsCommandsOutsideAgentMode(unittest.TestCase):
    """A non-agent coder (e.g. the default 'diff' edit format) has no
    mcp_manager at all -- both commands must fail with clear guidance
    rather than an AttributeError."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmpdir_obj.name)
        self.original_cwd = __import__("os").getcwd()
        __import__("os").chdir(self.tmpdir)
        self.io = InputOutput(pretty=False, fancy_input=False, yes=True)
        self.coder = Coder.create(Model("gpt-3.5-turbo"), None, io=self.io, fnames=[], use_git=False)
        self.commands = Commands(self.io, self.coder)

    def tearDown(self):
        __import__("os").chdir(self.original_cwd)
        self.tmpdir_obj.cleanup()

    def test_mcp_resources_outside_agent_mode_gives_clear_error(self):
        errors = []
        self.io.tool_error = lambda msg="", *a, **k: errors.append(msg)
        self.commands.cmd_mcp_resources("")
        self.assertTrue(any("agent mode" in e for e in errors))

    def test_mcp_prompts_outside_agent_mode_gives_clear_error(self):
        errors = []
        self.io.tool_error = lambda msg="", *a, **k: errors.append(msg)
        self.commands.cmd_mcp_prompts("")
        self.assertTrue(any("agent mode" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
