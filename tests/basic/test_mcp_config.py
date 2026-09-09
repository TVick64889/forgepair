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
        write_mcp_json(self.tmpdir / ".mcp.json", {"bad": {"command": "x", "env": {"KEY": 123}}})
        with self.assertRaises(MCPConfigError):
            load_mcp_servers(git_root=None)

    def test_load_http_server_with_headers(self):
        write_mcp_json(
            self.tmpdir / ".mcp.json",
            {
                "remote": {
                    "url": "https://example.com/mcp",
                    "headers": {"Authorization": "Bearer abc123"},
                }
            },
        )
        servers = load_mcp_servers(git_root=None)
        self.assertEqual(servers["remote"].headers, {"Authorization": "Bearer abc123"})

    def test_headers_must_be_string_map(self):
        write_mcp_json(
            self.tmpdir / ".mcp.json",
            {"bad": {"url": "https://example.com", "headers": {"X-Key": 123}}},
        )
        with self.assertRaises(MCPConfigError):
            load_mcp_servers(git_root=None)

    def test_headers_on_stdio_server_is_error(self):
        write_mcp_json(
            self.tmpdir / ".mcp.json",
            {"bad": {"command": "x", "headers": {"Authorization": "Bearer abc"}}},
        )
        with self.assertRaises(MCPConfigError):
            load_mcp_servers(git_root=None)

    def test_http_server_without_headers_defaults_to_empty(self):
        write_mcp_json(self.tmpdir / ".mcp.json", {"remote": {"url": "https://example.com/mcp"}})
        servers = load_mcp_servers(git_root=None)
        self.assertEqual(servers["remote"].headers, {})

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


class TestMCPConfigEnvVarInterpolation(unittest.TestCase):
    """${ENV_VAR} interpolation in .mcp.json, matching Claude Code/Claude
    Desktop's syntax -- lets a committed .mcp.json reference a secret via
    an env var name instead of containing the secret value itself."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmpdir_obj.name)
        self.original_cwd = os.getcwd()
        os.chdir(self.tmpdir)

        self.homedir_obj = tempfile.TemporaryDirectory()
        self.original_home = os.environ.get("HOME")
        self.original_userprofile = os.environ.get("USERPROFILE")
        os.environ["HOME"] = self.homedir_obj.name
        os.environ["USERPROFILE"] = self.homedir_obj.name

        self._env_vars_to_clean = []

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
        for var in self._env_vars_to_clean:
            os.environ.pop(var, None)

    def set_env(self, name, value):
        os.environ[name] = value
        self._env_vars_to_clean.append(name)

    def test_env_value_interpolated_into_env_field(self):
        self.set_env("FORGEPAIR_TEST_TOKEN", "sekret-123")
        write_mcp_json(
            self.tmpdir / ".mcp.json",
            {"auth-server": {"command": "x", "env": {"API_KEY": "${FORGEPAIR_TEST_TOKEN}"}}},
        )
        servers = load_mcp_servers(git_root=None)
        self.assertEqual(servers["auth-server"].env["API_KEY"], "sekret-123")

    def test_env_value_interpolated_into_url(self):
        self.set_env("FORGEPAIR_TEST_TOKEN", "abc")
        write_mcp_json(
            self.tmpdir / ".mcp.json",
            {"remote": {"url": "https://example.com/mcp?token=${FORGEPAIR_TEST_TOKEN}"}},
        )
        servers = load_mcp_servers(git_root=None)
        self.assertEqual(servers["remote"].url, "https://example.com/mcp?token=abc")

    def test_env_value_interpolated_into_headers(self):
        self.set_env("FORGEPAIR_TEST_TOKEN", "sekret-456")
        write_mcp_json(
            self.tmpdir / ".mcp.json",
            {
                "remote": {
                    "url": "https://example.com/mcp",
                    "headers": {"Authorization": "Bearer ${FORGEPAIR_TEST_TOKEN}"},
                }
            },
        )
        servers = load_mcp_servers(git_root=None)
        self.assertEqual(servers["remote"].headers["Authorization"], "Bearer sekret-456")

    def test_env_value_interpolated_into_command_and_args(self):
        self.set_env("FORGEPAIR_TEST_BIN", "real-binary")
        self.set_env("FORGEPAIR_TEST_ARG", "real-arg")
        write_mcp_json(
            self.tmpdir / ".mcp.json",
            {
                "srv": {
                    "command": "${FORGEPAIR_TEST_BIN}",
                    "args": ["--flag", "${FORGEPAIR_TEST_ARG}"],
                }
            },
        )
        servers = load_mcp_servers(git_root=None)
        self.assertEqual(servers["srv"].command, "real-binary")
        self.assertEqual(servers["srv"].args, ["--flag", "real-arg"])

    def test_multiple_vars_in_one_string(self):
        self.set_env("FORGEPAIR_TEST_HOST", "api.example.com")
        self.set_env("FORGEPAIR_TEST_PORT", "8443")
        write_mcp_json(
            self.tmpdir / ".mcp.json",
            {"srv": {"url": "https://${FORGEPAIR_TEST_HOST}:${FORGEPAIR_TEST_PORT}/mcp"}},
        )
        servers = load_mcp_servers(git_root=None)
        self.assertEqual(servers["srv"].url, "https://api.example.com:8443/mcp")

    def test_missing_env_var_fails_loud_not_silent(self):
        write_mcp_json(
            self.tmpdir / ".mcp.json",
            {"srv": {"command": "x", "env": {"KEY": "${DEFINITELY_NOT_SET_ANYWHERE_12345}"}}},
        )
        with self.assertRaises(MCPConfigError) as ctx:
            load_mcp_servers(git_root=None)
        self.assertIn("DEFINITELY_NOT_SET_ANYWHERE_12345", str(ctx.exception))

    def test_no_interpolation_syntax_passes_through_unchanged(self):
        write_mcp_json(
            self.tmpdir / ".mcp.json",
            {"srv": {"command": "npx", "args": ["-y", "some-package@latest"]}},
        )
        servers = load_mcp_servers(git_root=None)
        self.assertEqual(servers["srv"].command, "npx")
        self.assertEqual(servers["srv"].args, ["-y", "some-package@latest"])

    def test_literal_dollar_sign_without_braces_passes_through(self):
        write_mcp_json(
            self.tmpdir / ".mcp.json",
            {"srv": {"command": "x", "args": ["price=$5"]}},
        )
        servers = load_mcp_servers(git_root=None)
        self.assertEqual(servers["srv"].args, ["price=$5"])


if __name__ == "__main__":
    unittest.main()
