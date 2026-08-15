"""Batho MCP Server — FastMCP entry point.

Starts a stdio-based MCP server that reads pre-built .batho Arrow IPC
artifacts and serves code-graph intelligence to AI agents.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from fastmcp import FastMCP

from batho import __version__ as BATHO_MCP_VERSION
from batho.mcp.instructions import INSTRUCTIONS
from batho.mcp.tools import register_tools
from batho.mcp.prompts import register_prompts
from batho.mcp.resources import register_resources
from batho.mcp.registry import RepoRegistry
from batho.mcp.watcher import BathoWatcherEngine

import structlog

LOGGER = structlog.get_logger(__name__)


def create_app(
    root: str | None = None,
    registry_path: Path | None = None,
    watcher: BathoWatcherEngine | None = None,
    registry: RepoRegistry | None = None,
    disabled_tools: set[str] | None = None,
    enabled_tools: set[str] | None = None,
) -> FastMCP:
    """Create and configure the FastMCP application with all Batho tools.

    Args:
        root: Repository root containing .batho artifact. If None,
              tools will require repo parameter in each call.
        registry_path: Path to mcp-repos.json. If None, uses default
                       (~/.batho/mcp-repos.json). Ignored when ``registry``
                       is supplied.
        watcher: Optional BathoWatcherEngine instance for file watching.
        registry: Optional pre-constructed RepoRegistry instance. When
                  supplied, this exact instance is reused (avoiding a
                  second instance with an independent lock that races on
                  the same JSON file). When None, a new registry is built
                  from ``registry_path``.
        disabled_tools: blocklist of MCP tool names NOT to register. When
                        None, loaded from batho.yaml ``mcp.tools.disabled``
                        (secure-by-default: batho_build, batho_export,
                        batho_load, batho_gc).
        enabled_tools: optional allowlist. If set, ONLY these tools are
                       registered. When None, loaded from batho.yaml
                       ``mcp.tools.enabled`` (default: no allowlist).
    """
    if registry is None:
        registry = RepoRegistry(config_path=registry_path)
    entries = registry.list_all()

    if entries:
        LOGGER.info("batho_mcp_multi_repo", repos=[e.name for e in entries])
    elif root:
        LOGGER.info("batho_mcp_single_repo", root=root)
    else:
        LOGGER.warning("batho_mcp_no_repos")

    # Resolve tool filter from config when not explicitly provided.
    # Both None means "load from batho.yaml / env vars / defaults".
    if disabled_tools is None and enabled_tools is None:
        from batho.core.config import get_config_with_root
        cfg_root = Path(root).resolve() if root else Path.cwd().resolve()
        cfg = get_config_with_root(cfg_root)
        mcp_cfg = cfg.get("mcp", {})
        if not mcp_cfg.get("enabled", True):
            # Whole MCP surface disabled — register nothing
            enabled_tools = set()
        else:
            tools_cfg = mcp_cfg.get("tools", {})
            disabled = tools_cfg.get("disabled")
            if disabled is not None:
                disabled_tools = set(disabled)
            enabled = tools_cfg.get("enabled")
            if enabled is not None:
                enabled_tools = set(enabled)

    app = FastMCP(
        name="batho",
        instructions=INSTRUCTIONS,
        version=BATHO_MCP_VERSION,
    )
    register_tools(
        app,
        default_root=root,
        registry=registry,
        watcher=watcher,
        disabled_tools=disabled_tools,
        enabled_tools=enabled_tools,
    )
    register_prompts(app)
    register_resources(app, registry=registry if entries else None)
    return app


def run_server(
    root: str | None = None,
    registry_path: Path | None = None,
    watch: bool = True,
    disabled_tools: set[str] | None = None,
    enabled_tools: set[str] | None = None,
) -> None:
    """Start the MCP server on stdio transport.

    Args:
        root: Repository root containing .batho artifact. If None,
              defaults to current working directory.
        registry_path: Path to mcp-repos.json. If None, uses default
                       (~/.batho/mcp-repos.json).
        watch: If True, starts the BathoWatcherEngine for watched repos.
        disabled_tools: blocklist of tool names NOT to register. When None,
                        loaded from batho.yaml (secure-by-default).
        enabled_tools: optional allowlist. If set, ONLY these tools register.
    """
    import os

    if root is None:
        root = os.getcwd()
    root = str(Path(root).resolve())

    artifact_dir = Path(root) / ".batho" / "artifact"
    if not artifact_dir.exists():
        LOGGER.warning("batho_mcp_no_artifact", root=root, artifact_dir=str(artifact_dir))
    else:
        LOGGER.info("batho_mcp_starting", root=root, artifact_dir=str(artifact_dir))

    registry = RepoRegistry(config_path=registry_path)
    watcher = BathoWatcherEngine(registry) if watch else None
    if watcher:
        watcher.start()
        for entry in registry.list_all():
            if entry.watch:
                threading.Thread(
                    target=watcher.catch_up,
                    args=(entry.name,),
                    daemon=True,
                    name=f"batho-catchup-{entry.name}",
                ).start()

    app = create_app(
        root=root,
        registry_path=registry_path,
        watcher=watcher,
        registry=registry,
        disabled_tools=disabled_tools,
        enabled_tools=enabled_tools,
    )
    try:
        app.run(transport="stdio")
    except KeyboardInterrupt:
        LOGGER.info("batho_mcp_stopped")
        sys.exit(0)
    finally:
        if watcher:
            watcher.stop()


if __name__ == "__main__":
    run_server()

