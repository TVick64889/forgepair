"""A stdio MCP server that refuses to start a second time while another
instance holds its lock file -- used by test_mcp_manager.py to exercise
MCPManager's kill-if-blocking leftover-process path realistically (a fresh
connect attempt for this server genuinely fails while a previous-session
leftover is still holding the lock, and succeeds once that leftover is
killed), rather than mocking the failure.

Usage: python single_instance_server.py <lock_file_path>

On startup: if <lock_file_path> exists and names a PID that's still alive,
exit immediately with a distinct nonzero status (this is the "blocked"
case a real single-instance MCP server would hit -- e.g. a port already
bound, or its own advisory lock file already held). Otherwise write our
own PID to the lock file, run the trivial echo tool like echo_server.py,
and remove the lock file on clean exit.
"""

import atexit
import os
import sys

import psutil
from mcp.server.fastmcp import FastMCP

LOCK_PATH = sys.argv[1] if len(sys.argv) > 1 else "single_instance.lock"


def _pid_is_alive(pid):
    # os.kill(pid, 0) is not a reliable liveness check on Windows (it
    # raises OSError regardless of whether the target process is alive),
    # so use psutil instead, same as aider/mcp/manager.py's own
    # _pid_matches_recorded / check_for_leftover_processes.
    return psutil.pid_exists(pid)


def _check_and_acquire_lock():
    if os.path.exists(LOCK_PATH):
        try:
            with open(LOCK_PATH, "r", encoding="utf-8") as f:
                held_pid = int(f.read().strip())
        except (OSError, ValueError):
            held_pid = None
        if held_pid is not None and _pid_is_alive(held_pid):
            sys.exit(17)  # distinct status: "another instance holds the lock"
    with open(LOCK_PATH, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))


def _release_lock():
    try:
        os.remove(LOCK_PATH)
    except OSError:
        pass


_check_and_acquire_lock()
atexit.register(_release_lock)

mcp_app = FastMCP("single-instance-test-server")


@mcp_app.tool()
def echo(message: str) -> str:
    """Echo the given message back."""
    return message


if __name__ == "__main__":
    mcp_app.run(transport="stdio")
