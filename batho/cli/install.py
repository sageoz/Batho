"""CLI subcommand: batho install

One command for agent setup: installs the Batho skill pack (canonical
~/.agents/skills + per-agent mirrors) AND registers the Batho MCP server
with every detected coding-agent client. Re-running it refreshes the pack
when the upstream release differs (BATHO_VERSION pins honored).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from batho.install.install import InstallRecord
    from batho.install.mcp_config import McpRecord


def register_install_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the `install` subcommand on the given subparsers action."""
    parser = subparsers.add_parser(
        "install",
        help="Install the skill pack and register the MCP server with detected agents",
        description=(
            "Download the published batho-skills release (checksum-verified), "
            "install the 5 pack skills to ~/.agents/skills plus mirrors for "
            "detected agents, and register the Batho MCP server in every "
            "detected coding-agent client's config (claude-desktop, "
            "claude-code, cursor, windsurf, vscode, codex, gemini, opencode, "
            "copilot). Re-running the command updates the pack when the "
            "upstream release differs and refreshes the MCP registrations."
        ),
    )
    parser.add_argument(
        "--agent",
        action="append",
        default=[],
        metavar="NAME",
        help="Force a specific agent's native dirs / MCP config (repeatable)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Write every known agent's dirs and every supported client's MCP config (skip detection)",
    )
    parser.add_argument(
        "--project",
        action="store_true",
        default=False,
        help="Install skills to ./.agents/skills instead of the global dir (MCP registration stays global)",
    )
    parser.add_argument(
        "--version",
        default=None,
        metavar="V",
        help="Pin a skill-pack release version (e.g. 1.2.0 or v1.2.0)",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        default=False,
        help="Copy instead of symlink for skill mirrors",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite existing skill dirs even without the .batho-skill marker",
    )
    parser.add_argument(
        "--no-mcp",
        action="store_true",
        default=False,
        help="Skip MCP server registration (skills only)",
    )
    parser.set_defaults(func=cmd_install)


def cmd_install(args: argparse.Namespace) -> int:
    """Execute the install command: skill pack + MCP registration."""
    from batho.install import SkillsError, install_pack, pack_status
    from batho.install.fetch import resolve_latest_version, resolve_version

    scope = "project" if getattr(args, "project", False) else (
        os.environ.get("BATHO_SCOPE") or "global"
    )
    receipt = pack_status()
    # SKL-10: without --project, refresh the scope the receipt recorded —
    # a project-scope install must not silently retarget the global dir.
    if not getattr(args, "project", False) and receipt:
        scope = receipt.get("scope") or scope

    try:
        # SKL-02: honor the BATHO_VERSION pin — a pinned install is "up to
        # date" at the pinned tag, not at upstream latest.
        target = resolve_version(args.version)
        if target == "latest":
            latest = resolve_latest_version()
        else:
            latest = target
    except SkillsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if receipt and receipt.get("version") == latest:
        print(f"skill pack already up to date ({latest})")
    else:
        try:
            result = install_pack(
                agents=args.agent or None,
                scope=scope,
                version=args.version,
                copy=args.copy,
                force=args.force or bool(receipt),
                all_agents=args.all,
            )
        except (SkillsError, ValueError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        _print_records(result.records)
        verb = "updated" if receipt else "installed"
        print(f"batho install: skills {verb} to {result.version} — restart your agent(s) to pick up the skills")

    mcp_code = _install_mcp(
        agents=args.agent or None,
        all_agents=args.all,
        project_scope=getattr(args, "project", False),
        skip=getattr(args, "no_mcp", False),
    )
    if mcp_code:
        print("batho install: completed with errors — see messages above", file=sys.stderr)
        return 1
    return 0


def _install_mcp(
    agents: list[str] | None,
    all_agents: bool,
    project_scope: bool,
    skip: bool = False,
) -> int:
    """Register the Batho MCP server with detected clients (global scope only)."""
    from batho.install.mcp_config import install_mcp_config

    if skip:
        return 0
    if project_scope:
        print(
            "note: MCP registration is global-scope only — skipping "
            "(drop --project to register the MCP server)"
        )
        return 0

    if agents:
        from batho.install.mcp_config import _mcp_table

        supported = set(_mcp_table())
        unsupported = [a for a in agents if a not in supported]
        if unsupported:
            print(
                f"note: no MCP support for {', '.join(sorted(unsupported))} — "
                f"supported clients: {', '.join(sorted(supported))}"
            )
        agents = [a for a in agents if a in supported] or None
        if agents is None:
            return 0

    records = install_mcp_config(agents=agents, all_agents=all_agents)
    if not records:
        print(
            "note: no coding-agent client detected — use --agent NAME "
            "(e.g. --agent cursor) or --all to force"
        )
        return 0
    _print_mcp_records(records)
    print(
        "batho install: MCP registered — restart the client(s) or reload "
        "the window to pick up the server"
    )
    return 1 if any(r.status.startswith("error") for r in records) else 0


def _print_records(records: list["InstallRecord"]) -> None:
    for r in records:
        print(f"{r.status:<18} {r.agent_id}:{r.path}")


def _print_mcp_records(records: list["McpRecord"]) -> None:
    for r in records:
        print(f"{r.status:<22} {r.agent_id}:{r.path}")
