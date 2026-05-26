"""Bridge CLI command — batho bridge serve.

Provides CLI interface for starting bridge_core HTTP or MCP servers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from batho.bridge_core.server import serve
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="cli.bridge")

DEFAULT_PORT = 8765


def _find_workspace_with_db(start_path: Path) -> Path | None:
    """Find workspace directory containing artifact database."""
    from batho.storage.engine import artifact_filename
    
    current = start_path.resolve()
    
    while True:
        db_name = artifact_filename(current)
        if (current / db_name).exists():
            return current
        
        parent = current.parent
        if parent == current:
            break
        current = parent
    
    return None


def cmd_bridge_serve(args: argparse.Namespace) -> int:
    """Handle `batho bridge serve` command.
    
    Starts bridge_core server (HTTP or MCP) for the specified repository.
    
    Args:
        args: Parsed CLI arguments
        
    Returns:
        Exit code (0 for success, non-zero for error)
    """
    root = Path(args.root).resolve() if args.root else Path.cwd()
    
    # Find workspace with artifact database
    workspace = _find_workspace_with_db(root)
    if workspace is None:
        from batho.storage.engine import artifact_filename
        expected_db = artifact_filename(root)
        print(f"error: No artifact database found at {root}")
        print(f"Expected: {expected_db}")
        print("Run 'batho build' first to create artifacts")
        return 1
    
    root = workspace
    
    # Resolve global db path if specified or configured
    from batho.bridge_core.global_registry import resolve_global_db_path
    global_db_path = None
    if args.global_db:
        global_db_path = Path(args.global_db).resolve()
    else:
        try:
            global_db_path = resolve_global_db_path(root)
        except Exception:
            pass
            
    # Auto-register directory if --scan-dir is specified
    if args.scan_dir:
        if not global_db_path:
            print("error: --scan-dir requires a global database path to be resolved.")
            return 1
            
        try:
            from batho.bridge_core.global_registry import GlobalPlatformDeps
            from batho.storage.engine import get_database
            import subprocess
            
            scan_dir = Path(args.scan_dir).resolve()
            if not scan_dir.is_dir():
                print(f"error: Scan directory not found: {scan_dir}")
                return 1
                
            LOGGER.info("auto_registration_started", scan_dir=str(scan_dir))
            global_deps = GlobalPlatformDeps(global_db_path)
            
            # Find artifact_*.batho files
            artifact_files = list(scan_dir.glob("artifact_*.batho"))
            registered_count = 0
            
            for art_path in artifact_files:
                try:
                    filename = art_path.name
                    # Extract name
                    repo_name = filename[len("artifact_"):-len(".batho")]
                    if not repo_name:
                        continue
                        
                    db = get_database(art_path.parent, db_path=art_path)
                    latest_run_id = db.get_latest_run_id()
                    if not latest_run_id:
                        continue
                        
                    conn = db._get_connection()
                    row = conn.execute(
                        """SELECT val FROM string_dict WHERE id = (
                               SELECT root_path_id FROM index_runs WHERE status = 'completed' ORDER BY completed_at DESC LIMIT 1
                           )"""
                    ).fetchone()
                    
                    if row:
                        repo_path = Path(row["val"]).resolve()
                    else:
                        repo_path = art_path.parent.resolve()
                        
                    origin_url = None
                    if repo_path.exists():
                        try:
                            res = subprocess.run(
                                ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
                                capture_output=True, text=True, timeout=2
                            )
                            if res.returncode == 0:
                                origin_url = res.stdout.strip()
                        except Exception:
                            pass
                            
                    repo_id = global_deps.register_workspace(
                        repo_name=repo_name,
                        repo_path=repo_path,
                        origin_url=origin_url
                    )
                    global_deps.register_artifact(repo_id=repo_id, artifact_path=art_path)
                    registered_count += 1
                    LOGGER.info("auto_registered_workspace", repo_name=repo_name, repo_id=repo_id)
                except Exception as e:
                    LOGGER.error("auto_register_failed", artifact=art_path.name, error=str(e))
                    
            if registered_count > 0:
                LOGGER.info("rebuilding_cross_repo_edges")
                global_deps.rebuild_cross_repo_edges()
                LOGGER.info("cross_repo_edges_rebuilt")
                
            print(f"Auto-registered {registered_count} workspaces from {scan_dir}")
            
        except Exception as e:
            print(f"error: Auto-registration failed: {e}")
            return 1
            
    # Register current repo if --register is specified
    if args.register:
        if not global_db_path:
            print("error: --register requires a global database path to be resolved.")
            return 1
            
        try:
            from batho.bridge_core.global_registry import GlobalPlatformDeps
            from batho.storage.engine import get_database, artifact_filename
            import subprocess
            
            global_deps = GlobalPlatformDeps(global_db_path)
            
            repo_name = root.name
            origin_url = None
            try:
                res = subprocess.run(
                    ["git", "-C", str(root), "remote", "get-url", "origin"],
                    capture_output=True, text=True, timeout=2
                )
                if res.returncode == 0:
                    origin_url = res.stdout.strip()
            except Exception:
                pass
                
            repo_id = global_deps.register_workspace(
                repo_name=repo_name,
                repo_path=root,
                origin_url=origin_url
            )
            
            db_name = artifact_filename(root)
            db_path = root / db_name
            
            global_deps.register_artifact(repo_id=repo_id, artifact_path=db_path)
            
            # Rebuild cross-repo edges
            global_deps.rebuild_cross_repo_edges()
            
            print(f"Registered workspace '{repo_name}' with ID {repo_id} in registry {global_db_path}")
        except Exception as e:
            print(f"error: Registration failed: {e}")
            return 1
            
    transport = args.transport.lower()
    
    if transport not in ("http", "stdio", "sse"):
        print(f"error: Unknown transport: {transport}")
        print("Valid transports: http, stdio, sse")
        return 1
    
    LOGGER.info(
        "bridge_serve_starting",
        root=str(root),
        transport=transport,
        port=args.port,
        global_db_path=str(global_db_path) if global_db_path else None,
    )
    
    try:
        serve(
            repo_root=root,
            transport=transport,  # type: ignore
            port=args.port,
            host=args.host,
            global_db_path=global_db_path
        )
        return 0
    except FileNotFoundError as e:
        print(f"error: {e}")
        return 1
    except ValueError as e:
        print(f"error: {e}")
        return 1
    except KeyboardInterrupt:
        print("\nBridge server stopped")
        return 0
    except Exception as e:
        LOGGER.error("bridge_serve_error", error=str(e))
        print(f"error: {e}")
        return 2


def register_bridge_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register `bridge` subcommand with argparse.
    
    Args:
        subparsers: Subparsers action from main parser
    """
    bridge_parser = subparsers.add_parser(
        "bridge",
        help="Start Batho Bridge server (HTTP or MCP)",
        description="Start a bridge server for API access to Batho artifacts",
    )
    
    bridge_subparsers = bridge_parser.add_subparsers(dest="bridge_command")
    
    # bridge serve
    serve_parser = bridge_subparsers.add_parser(
        "serve",
        help="Start bridge server",
    )
    
    serve_parser.add_argument(
        "--root", "-r",
        type=Path,
        default=Path("."),
        help="Repository root directory (default: current directory)",
    )
    
    serve_parser.add_argument(
        "--transport", "-t",
        default="http",
        choices=["http", "stdio", "sse"],
        help="Transport protocol (default: http)",
    )
    
    serve_parser.add_argument(
        "--port", "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"HTTP/SSE port (default: {DEFAULT_PORT})",
    )
    
    serve_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    
    serve_parser.add_argument(
        "--open-browser", "-b",
        action="store_true",
        help="Open browser (HTTP mode only)",
    )
    
    serve_parser.add_argument(
        "--global-db",
        help="Path to global.batho database",
    )
    
    serve_parser.add_argument(
        "--register",
        action="store_true",
        help="Register current repo in global registry",
    )
    
    serve_parser.add_argument(
        "--scan-dir",
        help="Scan directory for multiple .batho files and auto-register",
    )
    
    serve_parser.set_defaults(func=cmd_bridge_serve)


__all__ = ["register_bridge_parser", "cmd_bridge_serve"]
