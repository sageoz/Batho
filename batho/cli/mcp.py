"""CLI command helpers for ``batho mcp`` subcommand."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

import structlog

from batho.bridge.artifact_cache import ArtifactCache
from batho.bridge.constants import DEFAULT_HUB_HTTP_PORT, DEFAULT_HUB_REST_PORT
from batho.bridge.hub import run_hub_sse, run_hub_stdio, run_hub_streamable_http
from batho.bridge.hub_http import create_hub_server
from batho.bridge.models import (
    ConcurrencyConfig,
    DiscoveryConfig,
    HubConfig,
    ResidencyConfig,
    ServerConfig,
    WorkspaceConfig,
)
from batho.bridge.workspace_discovery import WorkspaceDiscovery
from batho.bridge.workspace_manager import WorkspaceManager
from batho.bridge.workspace_registry import WorkspaceRegistry
from batho.cli.dashboard import _find_dashboard_assets

LOGGER = structlog.get_logger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".batho" / "mcp.yaml"


def _load_config(config_path: Path | None = None) -> HubConfig:
    """Load hub configuration from file."""
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return HubConfig()
    registry = WorkspaceRegistry(user_config_path=path)
    return registry.load()


def _save_config(config: HubConfig, config_path: Path | None = None) -> None:
    """Save hub configuration to file."""
    path = config_path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    registry = WorkspaceRegistry(user_config_path=path)
    registry.save(config)


def cmd_mcp_serve(args: argparse.Namespace) -> int:
    """Start the MCP hub server."""
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG_PATH

    if not config_path.exists():
        print(f"error: Config file not found: {config_path}")
        print("Run `batho mcp add --ctn PATH` to create one, or create ~/.batho/mcp.yaml manually")
        return 1

    registry = WorkspaceRegistry(user_config_path=config_path)
    config = registry.load()

    cache = ArtifactCache(
        max_total_bytes=config.residency.max_total_cache_bytes,
        max_per_workspace_bytes=config.residency.max_per_workspace_cache_bytes,
    )

    manager = WorkspaceManager(
        registry=registry,
        residency=config.residency,
        concurrency=config.concurrency,
        cache=cache,
    )

    transport = getattr(args, "transport", "stdio")
    bind = getattr(args, "bind", "127.0.0.1")
    http_port = getattr(args, "http_port", DEFAULT_HUB_HTTP_PORT)
    rest_port = getattr(args, "rest_port", DEFAULT_HUB_REST_PORT)
    no_rest = getattr(args, "no_rest", False)
    no_ui = getattr(args, "no_ui", False)
    open_browser = getattr(args, "open_browser", False)

    dashboard_dir = None
    if not no_ui:
        dashboard_dir = _find_dashboard_assets()
        if not dashboard_dir:
            print("warning: Dashboard assets not found, UI will be disabled")
            no_ui = True

    print(f"🚀 Batho MCP Hub")
    print(f"   Config:     {config_path}")
    print(f"   Transport:  {transport}")
    print(f"   Bind:       {bind}:{http_port}")

    if not no_rest:
        print(f"   REST API:   http://{bind}:{rest_port}/api/v1/")
        if not no_ui:
            print(f"   Dashboard:  http://{bind}:{rest_port}/")

    print(f"   Workspaces: {len(config.workspaces)}")
    print("Press Ctrl+C to stop")

    if open_browser and not no_rest and not no_ui:
        url = f"http://{bind}:{rest_port}/"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    try:
        if transport == "stdio":
            asyncio.run(run_hub_stdio(manager))
        elif transport == "sse":
            if not no_rest:
                try:
                    server = create_hub_server(
                        manager,
                        host=bind,
                        port=rest_port,
                        default_workspace=config.server.default_workspace,
                        registry=registry,
                        dashboard_dir=dashboard_dir,
                    )
                    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
                    server_thread.start()
                    time.sleep(0.5)
                except Exception as e:
                    print(f"error: REST server failed to start: {e}")
                    print("Cannot start SSE transport without REST API")
                    asyncio.run(manager.stop())
                    return 1

            asyncio.run(run_hub_sse(manager, host=bind, port=http_port))
        elif transport == "http":
            asyncio.run(run_hub_streamable_http(manager, host=bind, port=http_port))

    except KeyboardInterrupt:
        print("\nShutting down...")
        asyncio.run(manager.stop())
        return 0

    return 0


def cmd_mcp_list(args: argparse.Namespace) -> int:
    """List registered workspaces."""
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG_PATH

    if not config_path.exists():
        print(f"error: Config file not found: {config_path}")
        return 1

    registry = WorkspaceRegistry(user_config_path=config_path)
    config = registry.load()

    if not config.workspaces:
        print("No workspaces registered")
        return 0

    print(f"Registered workspaces ({len(config.workspaces)}):")
    for ws in config.workspaces:
        state = "enabled" if ws.enabled else "disabled"
        pinned = "📌" if ws.pinned else "  "
        print(f"  {pinned} {ws.id:20s} {ws.ctn_dir} [{state}]")

    return 0


def cmd_mcp_add(args: argparse.Namespace) -> int:
    """Add a new workspace."""
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG_PATH

    ctn_path = Path(args.ctn).resolve()
    if not ctn_path.exists():
        print(f"error: workspace path not found: {ctn_path}")
        return 1

    matches = list(ctn_path.glob("artifact_*.batho"))
    if not matches:
        print(f"error: {ctn_path} is not a valid Batho workspace (missing artifact_*.batho database)")
        return 1

    registry = WorkspaceRegistry(user_config_path=config_path)
    config = registry.load()

    ws_id = args.id or ctn_path.parent.name.lower().replace(" ", "-").replace("_", "-")

    if any(ws.id == ws_id for ws in config.workspaces):
        print(f"error: Workspace '{ws_id}' already exists")
        return 1

    ws_config = WorkspaceConfig(
        id=ws_id,
        ctn_dir=str(ctn_path),
        label=args.label or "",
        tags=args.tag or [],
        pinned=args.pinned,
    )

    config.workspaces.append(ws_config)
    registry.save(config)

    print(f"✅ Added workspace '{ws_id}' -> {ctn_path}")
    return 0


def cmd_mcp_remove(args: argparse.Namespace) -> int:
    """Remove a workspace."""
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG_PATH

    registry = WorkspaceRegistry(user_config_path=config_path)
    config = registry.load()

    ws_id = args.id
    found = None
    for ws in config.workspaces:
        if ws.id == ws_id:
            found = ws
            break

    if not found:
        print(f"error: Workspace '{ws_id}' not found")
        return 1

    config.workspaces = [ws for ws in config.workspaces if ws.id != ws_id]
    registry.save(config)

    print(f"✅ Removed workspace '{ws_id}'")
    return 0


def cmd_mcp_discover(args: argparse.Namespace) -> int:
    """Discover workspaces from glob patterns."""
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG_PATH

    registry = WorkspaceRegistry(user_config_path=config_path)
    config = registry.load()

    if not config.discovery.ctn_dir_globs:
        print("error: No discovery globs configured in config")
        print(f"Add 'discovery.ctn_dir_globs' to {config_path}")
        return 1

    discovery = WorkspaceDiscovery(registry, config.discovery)
    diff = discovery.scan()

    print(f"Discovered:")
    print(f"  Added: {len(diff.added)}")
    print(f"  Removed: {len(diff.removed)}")
    print(f"  Updated: {len(diff.updated)}")

    if diff.added:
        print("\nNew workspaces:")
        for ws in diff.added:
            print(f"  + {ws.id}: {ws.ctn_dir}")

    if diff.removed:
        print("\nRemoved workspaces:")
        for ws_id in diff.removed:
            print(f"  - {ws_id}")

    return 0


def cmd_mcp_status(args: argparse.Namespace) -> int:
    """Show workspace status."""
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG_PATH
    ws_id = getattr(args, "id", None)

    if not config_path.exists():
        print(f"error: Config file not found: {config_path}")
        return 1

    registry = WorkspaceRegistry(user_config_path=config_path)
    config = registry.load()

    if ws_id:
        workspaces = [ws for ws in config.workspaces if ws.id == ws_id]
    else:
        workspaces = config.workspaces

    if not workspaces:
        print(f"No workspace found: {ws_id or 'none registered'}")
        return 1

    for ws in workspaces:
        print(f"{ws.id}:")
        print(f"  ctn_dir: {ws.ctn_dir}")
        print(f"  enabled: {ws.enabled}")
        print(f"  pinned: {ws.pinned}")
        print(f"  label: {ws.label or '(none)'}")
        print(f"  tags: {', '.join(ws.tags) or '(none)'}")

    return 0


def cmd_mcp_pin(args: argparse.Namespace) -> int:
    """Pin a workspace."""
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG_PATH

    registry = WorkspaceRegistry(user_config_path=config_path)
    config = registry.load()

    ws_id = args.id
    found = None
    for ws in config.workspaces:
        if ws.id == ws_id:
            found = ws
            break

    if not found:
        print(f"error: Workspace '{ws_id}' not found")
        return 1

    found.pinned = True
    registry.save(config)

    print(f"✅ Pinned workspace '{ws_id}'")
    return 0


def cmd_mcp_unpin(args: argparse.Namespace) -> int:
    """Unpin a workspace."""
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG_PATH

    registry = WorkspaceRegistry(user_config_path=config_path)
    config = registry.load()

    ws_id = args.id
    found = None
    for ws in config.workspaces:
        if ws.id == ws_id:
            found = ws
            break

    if not found:
        print(f"error: Workspace '{ws_id}' not found")
        return 1

    found.pinned = False
    registry.save(config)

    print(f"✅ Unpinned workspace '{ws_id}'")
    return 0


def register_cli_subcommands(mcp_sub: argparse._SubParsersAction[Any]) -> None:
    """Attach ``mcp`` parser to an existing subparser group."""

    mcp_parser = mcp_sub.add_parser("mcp", help="MCP hub — multi-workspace context server")
    mcp_sub_parser = mcp_parser.add_subparsers(dest="mcp_command", required=True)

    serve_parser = mcp_sub_parser.add_parser("serve", help="Start MCP hub server")
    serve_parser.add_argument("--config", default=None, help="Path to config file (default: ~/.batho/mcp.yaml)")
    serve_parser.add_argument("--transport", choices=["stdio", "sse", "http"], default="stdio", help="MCP transport")
    serve_parser.add_argument("--bind", default="127.0.0.1", help="Bind address")
    serve_parser.add_argument("--http-port", type=int, default=DEFAULT_HUB_HTTP_PORT, help="MCP HTTP/SSE port")
    serve_parser.add_argument("--rest-port", type=int, default=DEFAULT_HUB_REST_PORT, help="REST API port")
    serve_parser.add_argument("--no-rest", action="store_true", help="Disable REST API")
    serve_parser.add_argument("--no-ui", action="store_true", help="Disable Dashboard UI")
    serve_parser.add_argument("--open-browser", action="store_true", help="Open dashboard in browser")
    serve_parser.set_defaults(func=cmd_mcp_serve)

    list_parser = mcp_sub_parser.add_parser("list", help="List registered workspaces")
    list_parser.add_argument("--config", default=None, help="Path to config file")
    list_parser.set_defaults(func=cmd_mcp_list)

    add_parser = mcp_sub_parser.add_parser("add", help="Add a workspace")
    add_parser.add_argument("--config", default=None, help="Path to config file")
    add_parser.add_argument("--ctn", required=True, help="Path to workspace root (with artifact_*.batho database)")
    add_parser.add_argument("--id", help="Workspace ID (default: derived from directory name)")
    add_parser.add_argument("--label", help="Workspace label")
    add_parser.add_argument("--tag", action="append", help="Tags (can be repeated)")
    add_parser.add_argument("--pinned", action="store_true", help="Pin workspace")
    add_parser.set_defaults(func=cmd_mcp_add)

    remove_parser = mcp_sub_parser.add_parser("remove", help="Remove a workspace")
    remove_parser.add_argument("--config", default=None, help="Path to config file")
    remove_parser.add_argument("--id", required=True, help="Workspace ID")
    remove_parser.set_defaults(func=cmd_mcp_remove)

    discover_parser = mcp_sub_parser.add_parser("discover", help="Discover workspaces from globs")
    discover_parser.add_argument("--config", default=None, help="Path to config file")
    discover_parser.set_defaults(func=cmd_mcp_discover)

    status_parser = mcp_sub_parser.add_parser("status", help="Show workspace status")
    status_parser.add_argument("--config", default=None, help="Path to config file")
    status_parser.add_argument("--id", help="Workspace ID (default: all)")
    status_parser.set_defaults(func=cmd_mcp_status)

    pin_parser = mcp_sub_parser.add_parser("pin", help="Pin a workspace")
    pin_parser.add_argument("--config", default=None, help="Path to config file")
    pin_parser.add_argument("--id", required=True, help="Workspace ID")
    pin_parser.set_defaults(func=cmd_mcp_pin)

    unpin_parser = mcp_sub_parser.add_parser("unpin", help="Unpin a workspace")
    unpin_parser.add_argument("--config", default=None, help="Path to config file")
    unpin_parser.add_argument("--id", required=True, help="Workspace ID")
    unpin_parser.set_defaults(func=cmd_mcp_unpin)


__all__ = [
    "cmd_mcp_serve",
    "cmd_mcp_list",
    "cmd_mcp_add",
    "cmd_mcp_remove",
    "cmd_mcp_discover",
    "cmd_mcp_status",
    "cmd_mcp_pin",
    "cmd_mcp_unpin",
    "register_cli_subcommands",
]
