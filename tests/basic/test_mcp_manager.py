import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import psutil

from aider.mcp.config import MCPServerConfig
from aider.mcp.manager import MCPConnectionError, MCPManager

ECHO_SERVER_SCRIPT = str(
    Path(__file__).resolve().parent.parent / "fixtures" / "mcp_servers" / "echo_server.py"
)
AUTH_HTTP_SERVER_SCRIPT = str(
    Path(__file__).resolve().parent.parent / "fixtures" / "mcp_servers" / "auth_http_server.py"
)
RESOURCES_PROMPTS_SERVER_SCRIPT = str(
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "mcp_servers"
    / "resources_prompts_server.py"
)
SINGLE_INSTANCE_SERVER_SCRIPT = str(
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "mcp_servers"
    / "single_instance_server.py"
)


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                s.connect(("127.0.0.1", port))
                return
            except OSError:
                time.sleep(0.1)
    raise TimeoutError(f"auth_http_server did not open port {port} within {timeout}s")


class TestMCPManagerRoundTrip(unittest.TestCase):
    """Real round-trip test against an actual MCP server subprocess (not a
    mock of the mcp SDK): connect, discover tools, call one, verify the
    result. This is the "mock MCP server exposing a trivial tool, full
    round-trip test" required by BUILD_PLAN.md Phase 6 step 7.
    """

    def setUp(self):
        self.servers = {
            "echo-test": MCPServerConfig(
                name="echo-test",
                command=sys.executable,
                args=[ECHO_SERVER_SCRIPT],
            )
        }
        self.manager = MCPManager(self.servers, timeout=20)

    def tearDown(self):
        self.manager.shutdown()

    def test_connect_discover_and_call_tool(self):
        tools_by_server = self.manager.connect_all()

        self.assertEqual(self.manager.connect_errors, {})
        self.assertIn("echo-test", tools_by_server)
        tools = tools_by_server["echo-test"]
        self.assertEqual(len(tools), 1)

        tool = tools[0]
        self.assertEqual(tool.name, "echo")
        self.assertEqual(tool.server_name, "echo-test")
        self.assertEqual(tool.qualified_name, "mcp__echo-test__echo")
        self.assertIn("message", tool.input_schema.get("properties", {}))

        # functions= schema translation (feeds Coder.send()'s existing plumbing)
        schema = tool.to_function_schema()
        self.assertEqual(schema["name"], "mcp__echo-test__echo")
        self.assertIn("parameters", schema)

        result = self.manager.call_tool("echo-test", "echo", {"message": "hello mcp"})
        self.assertFalse(result.isError)
        text_blocks = [c.text for c in result.content if c.type == "text"]
        self.assertIn("hello mcp", text_blocks)

    def test_call_tool_on_unconnected_server_raises(self):
        with self.assertRaises(MCPConnectionError):
            self.manager.call_tool("never-connected", "echo", {})

    def test_connect_all_with_no_servers_is_noop(self):
        manager = MCPManager({})
        tools = manager.connect_all()
        self.assertEqual(tools, {})
        manager.shutdown()

    def test_bad_command_records_connect_error_without_crashing(self):
        servers = {
            "broken": MCPServerConfig(
                name="broken",
                command="this-command-does-not-exist-anywhere",
                args=[],
            )
        }
        manager = MCPManager(servers, timeout=10)
        try:
            tools_by_server = manager.connect_all()
            self.assertEqual(tools_by_server, {})
            self.assertIn("broken", manager.connect_errors)
        finally:
            manager.shutdown()

    def test_server_without_resources_or_prompts_reports_empty_lists(self):
        """The echo-test fixture only implements the tools primitive --
        confirms MCPManager treats missing resources/prompts capabilities
        as an empty list, not a connection error (BUILD_PLAN.md/STATUS.md
        gap: many real MCP servers only expose tools)."""
        tools_by_server = self.manager.connect_all()
        self.assertEqual(self.manager.connect_errors, {})
        self.assertIn("echo-test", tools_by_server)
        self.assertEqual(self.manager.all_resources(), [])
        self.assertEqual(self.manager.all_prompts(), [])


class TestMCPManagerHTTPAuth(unittest.TestCase):
    """Real round-trip test against an actual HTTP MCP server subprocess
    that requires a bearer token (see auth_http_server.py) -- verifies
    MCPServerConfig.headers actually reaches the wire as a real
    Authorization header a real server enforces, not just that manager.py
    constructs an httpx.AsyncClient object correctly.
    """

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.proc = subprocess.Popen(
            [sys.executable, AUTH_HTTP_SERVER_SCRIPT, str(cls.port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_for_port(cls.port, timeout=15)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()

    def test_correct_bearer_token_connects_and_lists_tools(self):
        server = MCPServerConfig(
            name="auth-test",
            url=f"http://127.0.0.1:{self.port}/mcp",
            headers={"Authorization": "Bearer test-token-12345"},
        )
        manager = MCPManager({"auth-test": server}, timeout=15)
        try:
            tools_by_server = manager.connect_all()
            self.assertEqual(manager.connect_errors, {})
            self.assertIn("auth-test", tools_by_server)
            names = [t.name for t in tools_by_server["auth-test"]]
            self.assertIn("whoami", names)

            result = manager.call_tool("auth-test", "whoami", {})
            self.assertFalse(result.isError)
            text_blocks = [c.text for c in result.content if c.type == "text"]
            self.assertIn("authenticated", text_blocks)
        finally:
            manager.shutdown()

    def test_missing_auth_header_fails_to_connect(self):
        server = MCPServerConfig(
            name="auth-test-noauth",
            url=f"http://127.0.0.1:{self.port}/mcp",
        )
        manager = MCPManager({"auth-test-noauth": server}, timeout=15)
        try:
            tools_by_server = manager.connect_all()
            self.assertEqual(tools_by_server, {})
            self.assertIn("auth-test-noauth", manager.connect_errors)
        finally:
            manager.shutdown()

    def test_wrong_bearer_token_fails_to_connect(self):
        server = MCPServerConfig(
            name="auth-test-wrong",
            url=f"http://127.0.0.1:{self.port}/mcp",
            headers={"Authorization": "Bearer not-the-right-token"},
        )
        manager = MCPManager({"auth-test-wrong": server}, timeout=15)
        try:
            tools_by_server = manager.connect_all()
            self.assertEqual(tools_by_server, {})
            self.assertIn("auth-test-wrong", manager.connect_errors)
        finally:
            manager.shutdown()


class TestMCPManagerResourcesAndPrompts(unittest.TestCase):
    """Real round-trip test against an actual MCP server subprocess that
    implements all three primitives (see resources_prompts_server.py) --
    verifies MCPManager's resource/prompt discovery and fetch methods
    against real protocol responses, not mocks of the mcp SDK."""

    def setUp(self):
        self.servers = {
            "res-prompt-test": MCPServerConfig(
                name="res-prompt-test",
                command=sys.executable,
                args=[RESOURCES_PROMPTS_SERVER_SCRIPT],
            )
        }
        self.manager = MCPManager(self.servers, timeout=20)

    def tearDown(self):
        self.manager.shutdown()

    def test_discover_and_read_resource(self):
        self.manager.connect_all()
        self.assertEqual(self.manager.connect_errors, {})

        resources = self.manager.all_resources()
        self.assertEqual(len(resources), 1)
        resource = resources[0]
        self.assertEqual(resource.server_name, "res-prompt-test")
        self.assertEqual(resource.uri, "test://readme")
        self.assertEqual(resource.name, "readme")
        self.assertEqual(resource.qualified_name, "res-prompt-test:test://readme")

        result = self.manager.read_resource("res-prompt-test", resource.uri)
        text_parts = [c.text for c in result.contents if hasattr(c, "text")]
        self.assertIn("Test Resource", "\n".join(text_parts))

    def test_discover_and_get_prompt_with_arguments(self):
        self.manager.connect_all()
        self.assertEqual(self.manager.connect_errors, {})

        prompts = self.manager.all_prompts()
        self.assertEqual(len(prompts), 1)
        prompt = prompts[0]
        self.assertEqual(prompt.server_name, "res-prompt-test")
        self.assertEqual(prompt.name, "greet")
        self.assertEqual(prompt.qualified_name, "res-prompt-test:greet")
        arg_names = [a["name"] for a in prompt.arguments]
        self.assertIn("name", arg_names)

        result = self.manager.get_prompt("res-prompt-test", "greet", {"name": "Bob"})
        text_parts = [m.content.text for m in result.messages if hasattr(m.content, "text")]
        self.assertIn("Bob", "\n".join(text_parts))

    def test_read_resource_on_unconnected_server_raises(self):
        with self.assertRaises(MCPConnectionError):
            self.manager.read_resource("never-connected", "test://readme")

    def test_get_prompt_on_unconnected_server_raises(self):
        with self.assertRaises(MCPConnectionError):
            self.manager.get_prompt("never-connected", "greet", {"name": "Bob"})

    def test_read_resource_unknown_uri_raises(self):
        self.manager.connect_all()
        with self.assertRaises(MCPConnectionError):
            self.manager.read_resource("res-prompt-test", "test://does-not-exist")


class TestMCPManagerOrphanDetection(unittest.TestCase):
    """STATUS.md gap: a previous session that died uncleanly (crash,
    dropped SSH connection, SIGKILL) never runs shutdown() or
    AgentCoder.__del__, so its MCP server subprocess is orphaned at the OS
    level. These tests simulate that by connecting a real server process
    and then discarding the MCPManager WITHOUT calling shutdown() (killing
    the underlying OS process out from under it the way a crash would),
    then verifying a fresh MCPManager pointed at the same pid_file finds
    it -- real subprocess, real pid_file on disk, no mocking of the
    detection logic itself."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmpdir_obj.name)
        self.pid_file = self.tmpdir / ".aider.mcp-pids.json"
        self.servers = {
            "echo-test": MCPServerConfig(
                name="echo-test",
                command=sys.executable,
                args=[ECHO_SERVER_SCRIPT],
            )
        }

    def tearDown(self):
        self.tmpdir_obj.cleanup()

    def _simulate_unclean_death(self, manager, server_name="echo-test"):
        """Kill the manager's spawned OS process directly (not via
        shutdown()) and drop the manager object without cleanup -- this is
        what happens when the whole aider process is crashed/SSH-dropped/
        SIGKILLed before any graceful shutdown path ever runs."""
        pid_data = json.loads(self.pid_file.read_text(encoding="utf-8"))
        pid = pid_data[server_name]["pids"][0]
        proc = psutil.Process(pid)
        # Deliberately do NOT call manager.shutdown() -- that's the whole
        # point of this simulation. Kill the OS process out from under the
        # manager and stop the background thread without any cleanup path
        # running, leaving the pid_file entry stale exactly like a crash
        # would (the entry is only ever cleared by a clean shutdown()).
        proc.terminate()
        proc.wait(timeout=10)
        if manager._loop is not None:
            manager._loop.call_soon_threadsafe(manager._loop.stop)
        if manager._thread is not None:
            manager._thread.join(timeout=10)
        self._fake_different_previous_session(server_name)

    def _fake_different_previous_session(self, server_name):
        """Rewrite the pid_file entry's recorded aider_pid to a value that
        cannot be this test process's own PID. Needed only because these
        tests run both the "previous" and "current" MCPManager instances
        in the same real OS process (the test runner) -- in real usage
        they're always genuinely different aider processes, so
        check_for_leftover_processes' own-entry skip (aider_pid == our own
        getpid()) naturally never fires against a real previous session's
        entry the way it would here without this rewrite."""
        data = json.loads(self.pid_file.read_text(encoding="utf-8"))
        data[server_name]["aider_pid"] = -1
        self.pid_file.write_text(json.dumps(data), encoding="utf-8")

    def _abandon_manager_leaving_process_alive(self, manager):
        """Stop the manager's background event-loop thread WITHOUT
        terminating the spawned OS subprocess -- this is the actually
        correct simulation of an orphan: the aider process dies (SSH drop,
        crash, SIGKILL) but any child process it already spawned keeps
        running independently at the OS level, since nothing killed it.
        (Contrast with _simulate_unclean_death, which is used only where
        the test wants the orphaned process itself no longer alive.)"""
        if manager._loop is not None:
            manager._loop.call_soon_threadsafe(manager._loop.stop)
        if manager._thread is not None:
            manager._thread.join(timeout=10)

    def test_pid_file_records_spawned_server_pid(self):
        manager = MCPManager(self.servers, pid_file=self.pid_file)
        try:
            manager.connect_all()
            self.assertEqual(manager.connect_errors, {})
            self.assertTrue(self.pid_file.exists())
            data = json.loads(self.pid_file.read_text(encoding="utf-8"))
            self.assertIn("echo-test", data)
            pid = data["echo-test"]["pids"][0]
            self.assertTrue(psutil.pid_exists(pid))
        finally:
            manager.shutdown()

    def test_clean_shutdown_clears_pid_file_entry(self):
        manager = MCPManager(self.servers, pid_file=self.pid_file)
        manager.connect_all()
        self.assertTrue(self.pid_file.exists())
        manager.shutdown()
        # Either the file is gone entirely (only entry was ours) or our
        # entry specifically is no longer present.
        if self.pid_file.exists():
            data = json.loads(self.pid_file.read_text(encoding="utf-8"))
            self.assertNotIn("echo-test", data)

    def test_detects_leftover_process_from_uncleanly_terminated_session(self):
        first_manager = MCPManager(self.servers, pid_file=self.pid_file)
        first_manager.connect_all()
        self.assertEqual(first_manager.connect_errors, {})
        pid_data = json.loads(self.pid_file.read_text(encoding="utf-8"))
        recorded_pids = pid_data["echo-test"]["pids"]
        self._fake_different_previous_session("echo-test")

        try:
            alive_recorded_pids = [p for p in recorded_pids if psutil.pid_exists(p)]
            self.assertTrue(alive_recorded_pids, "at least one recorded pid must be alive")

            second_manager = MCPManager({}, pid_file=self.pid_file)
            leftovers = second_manager.check_for_leftover_processes()
            self.assertEqual(len(leftovers), 1)
            self.assertEqual(leftovers[0]["server_name"], "echo-test")
            # The recursive PID snapshot can record more than one
            # descendant (e.g. an intermediate launcher process on
            # Windows) -- every PID it reports as a leftover must be one
            # this session actually recorded and must still be alive, not
            # pinned to any single specific index.
            self.assertTrue(set(leftovers[0]["pids"]).issubset(set(recorded_pids)))
            for pid in leftovers[0]["pids"]:
                self.assertTrue(psutil.pid_exists(pid))
            # Detection alone must not kill anything -- warn-by-default.
            self.assertEqual(second_manager.killed_leftover_processes, [])
        finally:
            # Real cleanup for the test itself (not exercising shutdown()
            # here -- that's the point of this test class). Recursive PID
            # capture can record more than one descendant PID (e.g. an
            # intermediate launcher process on Windows) -- clean up all of
            # them, not just the one asserted above.
            pid_data_now = (
                json.loads(self.pid_file.read_text(encoding="utf-8"))
                if self.pid_file.exists()
                else {}
            )
            for pid in pid_data_now.get("echo-test", {}).get("pids", recorded_pids):
                try:
                    proc = psutil.Process(pid)
                    proc.terminate()
                    proc.wait(timeout=10)
                except psutil.NoSuchProcess:
                    pass
                except psutil.TimeoutExpired:
                    pass
            if first_manager._loop is not None:
                first_manager._loop.call_soon_threadsafe(first_manager._loop.stop)
            if first_manager._thread is not None:
                first_manager._thread.join(timeout=10)

    def test_leftover_with_dead_pid_is_not_reported(self):
        """A PID recorded in a stale pid_file that's no longer running at
        all (fully exited, not orphaned) must not be reported as a
        leftover -- only PIDs that are still actually alive count."""
        self.pid_file.write_text(
            json.dumps(
                {
                    "echo-test": {
                        "pids": [999999999],  # not a real PID
                        "command": sys.executable,
                        "args": [ECHO_SERVER_SCRIPT],
                        "recorded_at": 0,
                        "aider_pid": 999999998,
                    }
                }
            ),
            encoding="utf-8",
        )
        manager = MCPManager({}, pid_file=self.pid_file)
        leftovers = manager.check_for_leftover_processes()
        self.assertEqual(leftovers, [])

    def test_leftover_with_pid_reused_by_unrelated_process_is_not_reported(self):
        """PID-reuse guard: a recorded PID that's alive again but now
        belongs to a completely different, unrelated process (simulated
        here by recording this test's own interpreter PID against a
        command it obviously never ran) must NOT be reported as a
        leftover -- 'PID still exists' alone is not sufficient evidence.
        """
        self.pid_file.write_text(
            json.dumps(
                {
                    "echo-test": {
                        "pids": [os.getpid()],
                        "command": "definitely-not-the-real-command.exe",
                        "args": ["--totally-unrelated"],
                        "recorded_at": 0,
                        "aider_pid": os.getpid() + 1,
                    }
                }
            ),
            encoding="utf-8",
        )
        manager = MCPManager({}, pid_file=self.pid_file)
        leftovers = manager.check_for_leftover_processes()
        self.assertEqual(leftovers, [])

    def test_kill_if_blocking_terminates_leftover_and_succeeds_on_retry(self):
        """Real end-to-end kill-if-blocking scenario: a single-instance
        server's leftover process (from a simulated uncleanly-terminated
        previous session) holds the only lock a fresh connect for that
        exact server name needs, so the fresh connect fails -- and only
        because of that failure does MCPManager kill the leftover (after
        re-verifying it) and retry, succeeding the second time."""
        lock_file = self.tmpdir / "single_instance.lock"
        single_instance_servers = {
            "single-inst": MCPServerConfig(
                name="single-inst",
                command=sys.executable,
                args=[SINGLE_INSTANCE_SERVER_SCRIPT, str(lock_file)],
            )
        }

        first_manager = MCPManager(single_instance_servers, pid_file=self.pid_file)
        first_manager.connect_all()
        self.assertEqual(first_manager.connect_errors, {})
        self.assertTrue(lock_file.exists(), "first instance should hold the lock")

        # Simulate the whole aider process dying uncleanly: abandon the
        # manager (stop its background thread) WITHOUT killing the actual
        # spawned subprocess, since a real orphan is still alive at the OS
        # level -- only the parent aider process is gone. Leaves both the
        # pid_file entry AND the lock file behind exactly like a crash.
        self._abandon_manager_leaving_process_alive(first_manager)
        self._fake_different_previous_session("single-inst")
        self.assertTrue(lock_file.exists(), "lock file must survive an unclean kill")

        second_manager = MCPManager(single_instance_servers, pid_file=self.pid_file)
        try:
            tools_by_server = second_manager.connect_all()
            self.assertEqual(
                second_manager.connect_errors,
                {},
                "second session should succeed once the blocking leftover is killed",
            )
            self.assertIn("single-inst", tools_by_server)
            killed = second_manager.killed_leftover_processes
            self.assertEqual(len(killed), 1)
            self.assertEqual(killed[0]["server_name"], "single-inst")
        finally:
            second_manager.shutdown()


if __name__ == "__main__":
    unittest.main()
