"""Loading and validation for MCP (Model Context Protocol) server configuration.

Config file: `.mcp.json`, using the same key/shape as Claude Code and Claude
Desktop (`mcpServers: {name: {command, args, env} | {url}}`) so the format is
already familiar to anyone who has configured MCP servers for those tools.
Also matches those tools' `${ENV_VAR}` interpolation syntax in command/args/
env/url values, so a committed .mcp.json never needs to contain a literal
secret (see _interpolate_env_vars).

Search order mirrors `.aider.conf.yml` / `.env` (see
`aider.main.generate_search_path_list`): homedir, then git root, then cwd,
then an explicit `--mcp-config-file` path if given. Later files in that list
win on a per-server-name basis -- a server defined in both the homedir and
the repo's `.mcp.json` uses the repo's definition, but a server that only
exists in the homedir file is still included. This matches the override
semantics of aider's existing layered config files.
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


class MCPConfigError(ValueError):
    """Raised when an .mcp.json file is malformed or fails schema validation."""


_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _interpolate_env_vars(value, field_name, source_file):
    """Replace ${VAR_NAME} references in a string with os.environ[VAR_NAME].

    Matches Claude Code/Claude Desktop's .mcp.json interpolation syntax, so
    a server requiring a bearer token or API key can be configured (and the
    .mcp.json file safely committed) without ever writing the secret value
    into the file itself -- e.g. "env": {"API_KEY": "${MY_SERVICE_API_KEY}"}.

    Fails loud (MCPConfigError) rather than silently substituting an empty
    string or leaving the literal "${VAR}" in place if the referenced
    variable isn't set -- a half-configured auth header that connects but
    silently fails (or sends a literal "${TOKEN}" string as a credential)
    is a worse failure mode than refusing to start.
    """
    if not isinstance(value, str) or "${" not in value:
        return value

    def _replace(match):
        var_name = match.group(1)
        if var_name not in os.environ:
            raise MCPConfigError(
                f"{field_name} in {source_file} references ${{{var_name}}}, but"
                f" the {var_name} environment variable is not set"
            )
        return os.environ[var_name]

    return _ENV_VAR_PATTERN.sub(_replace, value)


@dataclass
class MCPServerConfig:
    """A single configured MCP server.

    Exactly one of (command) or (url) must be set:
      - stdio transport: command (+ optional args, env)
      - HTTP transport: url
    """

    name: str
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    url: Optional[str] = None
    source_file: Optional[str] = None

    @property
    def transport(self):
        return "http" if self.url else "stdio"


def _validate_server_entry(name, entry, source_file):
    if not isinstance(entry, dict):
        raise MCPConfigError(
            f"mcpServers.{name} in {source_file} must be an object, got {type(entry).__name__}"
        )

    has_command = "command" in entry
    has_url = "url" in entry

    if has_command and has_url:
        raise MCPConfigError(
            f"mcpServers.{name} in {source_file} has both 'command' and 'url' --"
            " specify only one (command for a stdio server, url for an HTTP server)"
        )
    if not has_command and not has_url:
        raise MCPConfigError(
            f"mcpServers.{name} in {source_file} must have either 'command'"
            " (stdio server) or 'url' (HTTP server)"
        )

    if has_command and not isinstance(entry["command"], str):
        raise MCPConfigError(f"mcpServers.{name}.command in {source_file} must be a string")

    args = entry.get("args", [])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise MCPConfigError(f"mcpServers.{name}.args in {source_file} must be a list of strings")

    env = entry.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values()):
        raise MCPConfigError(
            f"mcpServers.{name}.env in {source_file} must be a mapping of string to string"
        )

    if has_url and not isinstance(entry["url"], str):
        raise MCPConfigError(f"mcpServers.{name}.url in {source_file} must be a string")

    command = entry.get("command")
    if command is not None:
        command = _interpolate_env_vars(command, f"mcpServers.{name}.command", source_file)

    interpolated_args = [
        _interpolate_env_vars(a, f"mcpServers.{name}.args[{i}]", source_file)
        for i, a in enumerate(args)
    ]

    interpolated_env = {
        k: _interpolate_env_vars(v, f"mcpServers.{name}.env.{k}", source_file)
        for k, v in env.items()
    }

    url = entry.get("url")
    if url is not None:
        url = _interpolate_env_vars(url, f"mcpServers.{name}.url", source_file)

    return MCPServerConfig(
        name=name,
        command=command,
        args=interpolated_args,
        env=interpolated_env,
        url=url,
        source_file=source_file,
    )


def _parse_mcp_json_file(path):
    """Parse and validate a single .mcp.json file. Returns dict[name, MCPServerConfig]."""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as err:
        raise MCPConfigError(f"Could not read {path}: {err}")

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as err:
        raise MCPConfigError(f"Could not parse {path} as JSON: {err}")

    if not isinstance(data, dict):
        raise MCPConfigError(f"{path} must contain a JSON object, got {type(data).__name__}")

    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise MCPConfigError(f"mcpServers in {path} must be an object")

    result = {}
    for name, entry in servers.items():
        result[name] = _validate_server_entry(name, entry, str(path))
    return result


def generate_mcp_config_search_path(git_root, explicit_file=None, default_file=".mcp.json"):
    """Build the ordered list of .mcp.json candidates to load.

    Order (lowest to highest precedence, matching
    aider.main.generate_search_path_list's homedir -> git root -> cwd ->
    explicit-file layering): homedir, git root, cwd, explicit file.
    Nonexistent paths are dropped; duplicates (e.g. cwd == git root) are
    collapsed keeping the highest-precedence occurrence.
    """
    candidates = [Path.home() / default_file]
    if git_root:
        candidates.append(Path(git_root) / default_file)
    candidates.append(Path(default_file))
    if explicit_file:
        candidates.append(Path(explicit_file))

    resolved = []
    for candidate in candidates:
        try:
            resolved.append(candidate.resolve())
        except OSError:
            continue

    # Keep only the last occurrence of any duplicate path, preserving order.
    seen_at = {}
    for idx, path in enumerate(resolved):
        seen_at[path] = idx
    ordered = [path for idx, path in enumerate(resolved) if seen_at[path] == idx]

    return [p for p in ordered if p.exists()]


def load_mcp_servers(git_root=None, explicit_file=None, default_file=".mcp.json"):
    """Load and merge MCP server configs from all discovered .mcp.json files.

    Returns dict[name, MCPServerConfig]. Files later in the search path (see
    generate_mcp_config_search_path) override earlier ones on a per-server-name
    basis -- a name defined in an earlier file but absent from a later one is
    still included.

    Raises MCPConfigError if any discovered file is malformed.
    """
    merged: Dict[str, MCPServerConfig] = {}
    for path in generate_mcp_config_search_path(git_root, explicit_file, default_file):
        servers = _parse_mcp_json_file(path)
        merged.update(servers)
    return merged
