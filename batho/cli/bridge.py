"""CLI command helpers for ``batho bridge`` subcommand.

Mirrors the structure of ``batho.bsg.plugins_cli``: a registration
helper (:func:`register_cli_subcommands`) plus command handlers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import structlog

from batho.bridge import ArtifactRegistryBridge, create_bridge_server
from batho.bridge.mcp_server import run_mcp_sse, run_mcp_stdio

LOGGER = structlog.get_logger(__name__)

DEFAULT_BRIDGE_PORT = 8766
DEFAULT_MCP_PORT = 8767
MAX_PORT_RETRIES = 10


def _find_ctn_dir(start_path: Path) -> Path | None:
    """Walk up from start_path to find the nearest ancestor with .ctn/."""
    current = start_path.resolve()
    while True:
        ctn_path = current / ".ctn"
        if ctn_path.is_dir():
            return ctn_path
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _find_workspace_root(ctn_path: Path) -> Path:
    """Return the workspace root (parent of .ctn/)."""
    return ctn_path.parent


def _is_port_available(host: str, port: int) -> bool:
    """Check if a port is available for binding."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            sock.bind((host, port))
            return True
    except OSError:
        return False


def _find_available_port(host: str, start_port: int) -> int | None:
    """Find an available port starting from start_port."""
    for offset in range(MAX_PORT_RETRIES):
        port = start_port + offset
        if _is_port_available(host, port):
            return port
    return None


def cmd_bridge_mcp(args: argparse.Namespace) -> int:
    """Start the Batho bridge MCP server."""
    root_arg = getattr(args, "root", None) or "."
    root_path = Path(root_arg).resolve()

    ctn_path = _find_ctn_dir(root_path)
    if not ctn_path:
        print(f"error: No .ctn/ directory found walking up from {root_path}")
        print("Run `batho index` from the repo root to populate .ctn/")
        return 1

    transport = getattr(args, "transport", "stdio")
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", DEFAULT_MCP_PORT)

    if transport == "sse":
        available_port = _find_available_port(host, port)
        if not available_port:
            print(f"error: Could not find available port in range [{port}, {port + MAX_PORT_RETRIES})")
            return 3
        print(f"🚀 Batho Bridge MCP (SSE)")
        print(f"   Transport: sse")
        print(f"   URL:       http://{host}:{available_port}/sse")
        print(f"   CTN:       {ctn_path}")
        print("Press Ctrl+C to stop")
        try:
            run_mcp_sse(ctn_path, host=host, port=available_port)
        except KeyboardInterrupt:
            print("\nShutting down...")
            return 0
    else:
        print("🚀 Batho Bridge MCP (stdio)")
        print(f"   Transport: stdio")
        print(f"   CTN:       {ctn_path}")
        run_mcp_stdio(ctn_path)

    return 0


def cmd_bridge_serve(args: argparse.Namespace) -> int:
    """Start the Batho bridge REST HTTP server."""
    root_arg = getattr(args, "root", None) or "."
    root_path = Path(root_arg).resolve()

    ctn_path = _find_ctn_dir(root_path)
    if not ctn_path:
        print(f"error: No .ctn/ directory found walking up from {root_path}")
        print("Run `batho index` from the repo root to populate .ctn/")
        return 1

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", DEFAULT_BRIDGE_PORT)

    if host == "0.0.0.0":
        print("warning: Binding to 0.0.0.0 exposes server to network")

    available_port = _find_available_port(host, port)
    if not available_port:
        print(f"error: Could not find available port in range [{port}, {port + MAX_PORT_RETRIES})")
        return 3

    print(f"🚀 Batho Bridge REST API")
    print(f"   CTN:   {ctn_path}")
    print(f"   URL:   http://{host}:{available_port}/api/v1/bridge/")
    print("Press Ctrl+C to stop")

    server = create_bridge_server(ctn_path, host=host, port=available_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
        return 0

    return 0


def cmd_bridge_status(args: argparse.Namespace) -> int:
    """Print bridge registry status."""
    root_arg = getattr(args, "root", None) or "."
    root_path = Path(root_arg).resolve()

    ctn_path = _find_ctn_dir(root_path)
    if not ctn_path:
        print(f"error: No .ctn/ directory found walking up from {root_path}")
        return 1

    bridge = ArtifactRegistryBridge(ctn_path)
    stats = bridge.stats()
    payload = {
        "ctn_dir": str(ctn_path),
        "registry_enabled": stats.enabled,
        "registry_path": stats.registry_path,
        "artifact_count": stats.artifact_count,
        "artifact_types": stats.artifact_types,
        "sync_status": stats.sync_status,
        "db_size_bytes": stats.db_size_bytes,
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_bridge_verify(args: argparse.Namespace) -> int:
    """Verify all registered artifacts are loadable."""
    root_arg = getattr(args, "root", None) or "."
    root_path = Path(root_arg).resolve()

    ctn_path = _find_ctn_dir(root_path)
    if not ctn_path:
        print(f"error: No .ctn/ directory found walking up from {root_path}")
        return 1

    from batho.bridge import ArtifactLoader

    bridge = ArtifactRegistryBridge(ctn_path)
    loader = ArtifactLoader(ctn_path)
    types = bridge.list_artifact_types()

    verified = 0
    failed = 0
    errors: list[dict[str, Any]] = []

    for artifact_type in types:
        records = bridge.get_artifacts_by_type(artifact_type, limit=1000)
        for record in records:
            try:
                loader.load_artifact(record)
                verified += 1
            except Exception as exc:
                failed += 1
                errors.append(
                    {
                        "artifact_type": artifact_type,
                        "logical_path": record.logical_path,
                        "error": str(exc),
                    }
                )

    payload = {
        "verified": verified,
        "failed": failed,
        "total": verified + failed,
        "errors": errors[:50],  # cap output
    }
    print(json.dumps(payload, indent=2))
    return 0 if failed == 0 else 1


def register_cli_subcommands(bridge_sub: argparse._SubParsersAction[Any]) -> None:
    """Attach ``bridge`` parser to an existing subparser group."""

    bridge_parser = bridge_sub.add_parser(
        "bridge",
        help="Batho bridge — access .ctn artifacts via REST and MCP",
    )
    bridge_sub_parser = bridge_parser.add_subparsers(dest="bridge_command", required=True)

    # mcp
    mcp_parser = bridge_sub_parser.add_parser("mcp", help="Start MCP server")
    mcp_parser.add_argument(
        "--root",
        default=".",
        help="Path to repository root (walks up to find .ctn/)",
    )
    mcp_parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    mcp_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address for SSE transport",
    )
    mcp_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_MCP_PORT,
        help=f"TCP port for SSE transport (default: {DEFAULT_MCP_PORT})",
    )
    mcp_parser.set_defaults(func=cmd_bridge_mcp)

    # serve
    serve_parser = bridge_sub_parser.add_parser("serve", help="Start REST HTTP server")
    serve_parser.add_argument(
        "--root",
        default=".",
        help="Path to repository root (walks up to find .ctn/)",
    )
    serve_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_BRIDGE_PORT,
        help=f"TCP port to bind (default: {DEFAULT_BRIDGE_PORT})",
    )
    serve_parser.set_defaults(func=cmd_bridge_serve)

    # status
    status_parser = bridge_sub_parser.add_parser("status", help="Show registry status")
    status_parser.add_argument(
        "--root",
        default=".",
        help="Path to repository root (walks up to find .ctn/)",
    )
    status_parser.set_defaults(func=cmd_bridge_status)

    # verify
    verify_parser = bridge_sub_parser.add_parser("verify", help="Verify all artifacts loadable")
    verify_parser.add_argument(
        "--root",
        default=".",
        help="Path to repository root (walks up to find .ctn/)",
    )
    verify_parser.set_defaults(func=cmd_bridge_verify)


__all__ = [
    "cmd_bridge_mcp",
    "cmd_bridge_serve",
    "cmd_bridge_status",
    "cmd_bridge_verify",
    "register_cli_subcommands",
]
