import json
import os
import tempfile
import unittest
from pathlib import Path

from aider.mcp.config import (
    MCPConfigError,
    MCPServerConfig,
    generate_mcp_config_search_path,
    load_mcp_servers,
)


def write_mcp_json(path, servers):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"mcpServers": servers}, f)


class TestMCPConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmpdir_obj.name)
        self.original_cwd = os.getcwd()
        os.chdir(self.tmpdir)

        # Isolate from any real ~/.mcp.json on the test-running machine.
        self.homedir_obj = tempfile.TemporaryDirectory()
        self.original_home = os.environ.get("HOME")
        self.original_userprofile = os.environ.get("USERPROFILE")
        os.environ["HOME"] = self.homedir_obj.name
        os.environ["USERPROFILE"] = self.homedir_obj.name

    def tearDown(self):
        os.chdir(self.original_cwd)
        self.tmpdir_obj.cleanup()
        if self.original_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.original_home
        if self.original_userprofile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = self.original_userprofile
        self.homedir_obj.cleanup()

    def test_load_stdio_server(self):
        write_mcp_json(
            self.tmpdir / ".mcp.json",
            {
                "chrome-devtools": {
                    "command": "npx",
                    "args": ["-y", "chrome-devtools-mcp@latest"],
                }
            },
        )
        servers = load_mcp_servers(git_root=None)
        self.assertIn("chrome-devtools", servers)
        server = servers["chrome-devtools"]
        self.assertIsInstance(server, MCPServerConfig)
        self.assertEqual(server.command, "npx")
        self.assertEqual(server.args, ["-y", "chrome-devtools-mcp@latest"])
        self.assertEqual(server.transport, "stdio")

    def test_load_http_server(self):
        write_mcp_json(self.tmpdir / ".mcp.json", {"remote": {"url": "https://example.com/mcp"}})
        servers = load_mcp_servers(git_root=None)
        self.assertEqual(servers["remote"].transport, "http")
        self.assertEqual(servers["remote"].url, "https://example.com/mcp")

    def test_no_config_file_returns_empty(self):
        servers = load_mcp_servers(git_root=None)
        self.assertEqual(servers, {})

    def test_both_command_and_url_is_error(self):
        write_mcp_json(
            self.tmpdir / ".mcp.json",
            {"broken": {"command": "foo", "url": "https://example.com"}},
        )
        with self.assertRaises(MCPConfigError):
            load_mcp_servers(git_root=None)

    def test_neither_command_nor_url_is_error(self):
        write_mcp_json(self.tmpdir / ".mcp.json", {"broken": {}})
        with self.assertRaises(MCPConfigError):
            load_mcp_servers(git_root=None)

    def test_invalid_json_is_error(self):
        (self.tmpdir / ".mcp.json").write_text("not json", encoding="utf-8")
        with self.assertRaises(MCPConfigError):
            load_mcp_servers(git_root=None)

    def test_non_dict_mcp_servers_is_error(self):
        (self.tmpdir / ".mcp.json").write_text(
            json.dumps({"mcpServers": ["not", "a", "dict"]}), encoding="utf-8"
        )
        with self.assertRaises(MCPConfigError):
            load_mcp_servers(git_root=None)

    def test_args_must_be_list_of_strings(self):
        write_mcp_json(self.tmpdir / ".mcp.json", {"bad": {"command": "x", "args": [1, 2]}})
        with self.assertRaises(MCPConfigError):
            load_mcp_servers(git_root=None)

    def test_env_must_be_string_map(self):
        write_mcp_json(
            self.tmpdir / ".mcp.json", {"bad": {"command": "x", "env": {"KEY": 123}}}
        )
        with self.assertRaises(MCPConfigError):
            load_mcp_servers(git_root=None)

    def test_git_root_and_cwd_merge_with_cwd_precedence(self):
        git_root = self.tmpdir / "repo"
        git_root.mkdir()
        write_mcp_json(
            git_root / ".mcp.json",
            {
                "root-only": {"command": "a"},
                "shared": {"command": "root-version"},
            },
        )
        cwd = git_root / "sub"
        cwd.mkdir()
        os.chdir(cwd)
        write_mcp_json(
            cwd / ".mcp.json",
            {
                "cwd-only": {"command": "b"},
                "shared": {"command": "cwd-version"},
            },
        )

        servers = load_mcp_servers(git_root=str(git_root))

        self.assertIn("root-only", servers)
        self.assertIn("cwd-only", servers)
        self.assertEqual(servers["shared"].command, "cwd-version")

    def test_explicit_file_has_highest_precedence(self):
        write_mcp_json(self.tmpdir / ".mcp.json", {"shared": {"command": "cwd-version"}})
        explicit = self.tmpdir / "custom.mcp.json"
        write_mcp_json(explicit, {"shared": {"command": "explicit-version"}})

        servers = load_mcp_servers(git_root=None, explicit_file=str(explicit))
        self.assertEqual(servers["shared"].command, "explicit-version")

    def test_search_path_skips_nonexistent_files(self):
        # No .mcp.json anywhere -- search path should just be empty, not error.
        paths = generate_mcp_config_search_path(git_root=None)
        self.assertEqual(paths, [])


if __name__ == "__main__":
    unittest.main()
