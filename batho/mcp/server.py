"""Batho MCP Server — FastMCP entry point.

Starts a stdio-based MCP server that reads pre-built .batho Arrow IPC
artifacts and serves code-graph intelligence to AI agents.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastmcp import FastMCP

from batho.mcp.instructions import INSTRUCTIONS
from batho.mcp.tools import register_tools

import structlog

LOGGER = structlog.get_logger(__name__)


def create_app(root: str | None = None) -> FastMCP:
    """Create and configure the FastMCP application with all Batho tools.

    Args:
        root: Repository root containing .batho artifact. If None,
              tools will require root_path in each call.
    """
    app = FastMCP(
        name="batho",
        instructions=INSTRUCTIONS,
    )
    register_tools(app, default_root=root)
    return app


def run_server(root: str | None = None) -> None:
    """Start the MCP server on stdio transport.

    Args:
        root: Repository root containing .batho artifact. If None,
              defaults to current working directory.
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

    app = create_app(root=root)
    try:
        app.run(transport="stdio")
    except KeyboardInterrupt:
        LOGGER.info("batho_mcp_stopped")
        sys.exit(0)


if __name__ == "__main__":
    run_server()
