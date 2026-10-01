"""Register the Batho MCP server across coding-agent clients.

Data source is the ``mcp_agents`` section of the vendored ``agent-paths.json``
(schema v2). For each detected client, the stdio server entry (``batho mcp``)
is merged into the client's config file. Merge-not-clobber: only the ``batho``
key inside the client's server map is added or replaced — every other key,
server, and setting in the file is preserved. Writes are atomic (tmp file +
``os.replace``).

Config surfaces verified against official client documentation (2026-09):

- claude-desktop  ``~/Library/Application Support/Claude/claude_desktop_config.json``
                  / ``%APPDATA%\\Claude\\claude_desktop_config.json`` — key ``mcpServers``
- claude-code     ``~/.claude.json`` top-level ``mcpServers`` (user scope)
- cursor          ``~/.cursor/mcp.json`` — ``mcpServers``
- windsurf        ``~/.codeium/windsurf/mcp_config.json`` (legacy, still read)
                  + ``~/.config/devin/mcp_config.json`` (Cortex-managed) — ``mcpServers``
- vscode          ``<user dir>/Code/User/mcp.json`` — top-level ``servers`` (outlier)
- codex           ``~/.codex/config.toml`` — ``[mcp_servers.batho]`` TOML table
- gemini          ``~/.gemini/settings.json`` — ``mcpServers``
- opencode        ``~/.config/opencode/opencode.json`` — ``mcp`` with ``command`` argv array
- copilot         ``~/.copilot/mcp-config.json`` — ``mcpServers`` (portable Agent Host)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from batho.install.detect import _expand, load_agent_table

MCP_SERVER_NAME = "batho"


class McpConfigError(Exception):
    """Fatal MCP config registration error (corrupt or unwritable client config)."""


@dataclass(frozen=True)
class McpTarget:
    """One client config file to write."""

    agent_id: str
    config_path: Path
    key: str  # top-level key holding the client's server map
    fmt: str  # "json" | "toml"
    entry_shape: str  # "command_args" | "command_array"


@dataclass(frozen=True)
class McpRecord:
    """Outcome for one client config file."""

    agent_id: str
    path: Path
    status: str  # installed | updated | skipped(not-installed) | error(<reason>)


def server_argv() -> list[str]:
    """Absolute argv launching the Batho MCP server from any cwd.

    Prefers the ``batho`` console script (absolute path — GUI clients such as
    Claude Desktop do not inherit the shell's PATH); falls back to
    ``<sys.executable> -m batho_cli mcp`` when the script is not on PATH.
    """
    exe = shutil.which("batho")
    if exe:
        return [os.path.abspath(exe), "mcp"]
    return [sys.executable, "-m", "batho_cli", "mcp"]


def _mcp_table() -> dict[str, dict[str, Any]]:
    return dict(load_agent_table().get("mcp_agents", {}))


def _config_paths(entry: dict[str, Any]) -> list[str]:
    if os.name == "nt":
        return list(entry.get("windows_configs") or entry.get("configs", []))
    if sys.platform.startswith("linux"):
        return list(entry.get("linux_configs") or entry.get("configs", []))
    return list(entry.get("configs", []))


def _client_detected(entry: dict[str, Any]) -> bool:
    """Client-installed probe: detect marker dirs or binaries on PATH.

    Deliberately does NOT probe config-file parents — for single-file clients
    whose config lives directly under $HOME (claude-code's ``~/.claude.json``)
    the parent always exists and would false-positive.
    """
    detect = entry.get("detect", {})
    if any(_expand(d).is_dir() for d in detect.get("global_dirs", [])):
        return True
    return any(shutil.which(b) for b in detect.get("bins", []))


def compute_mcp_targets(
    agents: list[str] | None = None,
    all_agents: bool = False,
) -> list[McpTarget]:
    """Resolve the client config files to write.

    Clients are detected when a config parent dir or detect marker exists or a
    detect binary is on PATH; ``agents``/``all_agents`` force detection. Every
    config path of a detected client whose parent dir exists is included (some
    clients document more than one live config location — all are written).
    """
    table = _mcp_table()
    forced = set(agents or []) | set(os.environ.get("BATHO_MCP_AGENTS", "").split())
    unknown = forced - set(table)
    if unknown:
        raise ValueError(
            f"unknown agent(s) for MCP install: {', '.join(sorted(unknown))} — "
            f"supported: {', '.join(sorted(table))}"
        )

    targets: list[McpTarget] = []
    for agent_id, entry in table.items():
        is_forced = agent_id in forced or all_agents
        if not is_forced and not _client_detected(entry):
            continue
        for raw in _config_paths(entry):
            path = _expand(raw)
            if not is_forced and not path.parent.is_dir():
                continue
            targets.append(
                McpTarget(
                    agent_id=agent_id,
                    config_path=path,
                    key=entry.get("key", "mcpServers"),
                    fmt=entry.get("format", "json"),
                    entry_shape=entry.get("entry_shape", "command_args"),
                )
            )
    return targets


def install_mcp_config(
    agents: list[str] | None = None,
    all_agents: bool = False,
) -> list[McpRecord]:
    """Write the Batho MCP server entry into every resolved client config.

    Returns one record per (client, config file). Per-file failures are
    reported as ``error(<reason>)`` records — one broken client config never
    blocks the others.
    """
    records: list[McpRecord] = []
    for target in compute_mcp_targets(agents=agents, all_agents=all_agents):
        try:
            status = _write_target(target)
        except (McpConfigError, OSError, ValueError, re.error) as exc:
            records.append(McpRecord(target.agent_id, target.config_path, f"error({exc})"))
            continue
        records.append(McpRecord(target.agent_id, target.config_path, status))
    return records


def _write_target(target: McpTarget) -> str:
    argv = server_argv()
    if target.fmt == "toml":
        return _merge_toml(target.config_path, argv)
    return _merge_json(target.config_path, target.key, _json_entry(argv, target.entry_shape))


def _json_entry(argv: list[str], shape: str) -> dict[str, Any]:
    if shape == "command_array":
        return {"type": "local", "command": argv, "enabled": True}
    return {"command": argv[0], "args": list(argv[1:])}


def _merge_json(path: Path, key: str, entry: dict[str, Any]) -> str:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    data: dict[str, Any] = {}
    if text.strip():
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise McpConfigError(
                f"{path} is not valid JSON ({exc}) — fix or remove the file, then re-run"
            ) from exc
    if not isinstance(data, dict):
        raise McpConfigError(f"{path} does not contain a JSON object")
    servers = data.get(key)
    if servers is None:
        servers = {}
    if not isinstance(servers, dict):
        raise McpConfigError(f"{path}: '{key}' is not an object — refusing to overwrite")
    existed = MCP_SERVER_NAME in servers
    servers[MCP_SERVER_NAME] = entry
    data[key] = servers
    _atomic_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return "updated" if existed else "installed"


_TOML_SECTION = re.compile(
    r"^\[mcp_servers\.batho\][^\n]*\n(?:(?!^\[).*\n)*", re.MULTILINE
)


def _merge_toml(path: Path, argv: list[str]) -> str:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    block = (
        f"[mcp_servers.{MCP_SERVER_NAME}]\n"
        f"command = {_toml_str(argv[0])}\n"
        f"args = [{', '.join(_toml_str(a) for a in argv[1:])}]\n"
    )
    existed = _TOML_SECTION.search(text) is not None
    if existed:
        text = _TOML_SECTION.sub(block, text, count=1)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += ("\n" if text else "") + block
    _atomic_text(path, text)
    return "updated" if existed else "installed"


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _toml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)
