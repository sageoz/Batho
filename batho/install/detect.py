"""Agent detection and install-target computation.

Data source is the vendored ``agent-paths.json`` (byte-identical copy of the
batho-skills repo file; schema v2 — skill dirs plus the ``mcp_agents`` MCP
config table). Mirrors the detection semantics of ``install.sh``: an agent
counts as detected when any of its global dirs exists, any of its project dirs
exists under the project root, or any of its bins is on PATH.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class InstallTarget:
    """One skills directory to write into."""

    agent_id: str  # "canonical" | "custom" | agent id from the table
    skills_dir: Path


def load_agent_table() -> dict[str, Any]:
    """Load the vendored agent-paths.json."""
    ref = resources.files("batho.install").joinpath("agent-paths.json")
    return json.loads(ref.read_text(encoding="utf-8"))


def pack_skills(table: dict[str, Any] | None = None) -> list[str]:
    """Return the pack skill names (e.g. batho, batho-setup, ...)."""
    return list((table or load_agent_table())["pack_skills"])


def _expand(raw: str) -> Path:
    """Expand ``~`` and ``%VAR%``/``$VAR`` in a table path."""
    return Path(os.path.expandvars(os.path.expanduser(raw)))


def _detected(entry: dict[str, Any], project_root: Path) -> bool:
    detect = entry.get("detect", {})
    if any(_expand(d).is_dir() for d in detect.get("global_dirs", [])):
        return True
    if any((project_root / d).is_dir() for d in detect.get("project_dirs", [])):
        return True
    return any(shutil.which(b) for b in detect.get("bins", []))


def _native_dirs(entry: dict[str, Any], scope: str) -> list[Path]:
    if scope == "project":
        return [Path(d) for d in entry.get("project_dirs", [])]
    if os.name == "nt":
        dirs = entry.get("windows_global_dirs") or entry.get("global_dirs", [])
    else:
        dirs = entry.get("global_dirs", [])
    return [_expand(d) for d in dirs]


def canonical_dir(scope: str, project_root: Path) -> Path:
    """Canonical ``.agents/skills`` dir for the given scope."""
    table = load_agent_table()
    canonical = table["canonical"]
    if scope == "project":
        return project_root / canonical["project"]
    if os.name == "nt":
        return _expand(canonical["global_windows"])
    return _expand(canonical["global_posix"])


def compute_targets(
    scope: str = "global",
    project_root: Path | None = None,
    agents: list[str] | None = None,
    all_agents: bool = False,
) -> list[InstallTarget]:
    """Compute the skills dirs to write, mirroring install.sh target selection.

    Always includes the canonical target first; adds per-agent native dirs for
    agents that don't read ``.agents/skills`` natively, or that were explicitly
    forced via ``agents``/``all_agents``.
    """
    proot = (project_root or Path.cwd()).resolve()
    canonical = canonical_dir(scope, proot)

    install_dir = os.environ.get("BATHO_INSTALL_DIR")
    if install_dir:
        return [InstallTarget("custom", _expand(install_dir).resolve())]

    env_agents = os.environ.get("BATHO_AGENTS", "").split()
    forced = set(agents or []) | set(env_agents)
    table = load_agent_table()
    known = table["agents"]
    unknown = forced - set(known)
    if unknown:
        raise ValueError(f"unknown agent(s): {', '.join(sorted(unknown))}")

    targets = [InstallTarget("canonical", canonical)]
    for agent_id, entry in known.items():
        is_forced = agent_id in forced or all_agents
        if not is_forced and not _detected(entry, proot):
            continue
        if entry.get("reads_agents_dir") and not is_forced:
            continue
        for d in _native_dirs(entry, scope):
            targets.append(
                InstallTarget(agent_id, d if d.is_absolute() else proot / d)
            )
    return targets
