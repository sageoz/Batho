"""Structured error handling for Batho MCP tools.

Provides classified error responses with `isError` flag, error types,
retryability hints, and actionable guidance for agents.
"""

from __future__ import annotations

from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent

# Error type constants
CLIENT_ERROR = "client_error"
SERVER_ERROR = "server_error"
EXTERNAL_ERROR = "external_error"


def _err(
    msg: str,
    error_type: str = CLIENT_ERROR,
    retryable: bool = False,
    hint: str | None = None,
) -> ToolResult:
    """Build a structured error ToolResult.

    Args:
        msg: Human-readable error message.
        error_type: One of CLIENT_ERROR, SERVER_ERROR, EXTERNAL_ERROR.
        retryable: Whether the agent should retry the call.
        hint: Actionable next step for the agent.
    """
    content_text = f"Error: {msg}"
    if hint:
        content_text += f"\nHint: {hint}"

    structured: dict = {
        "error": True,
        "error_type": error_type,
        "message": msg,
        "retryable": retryable,
    }
    if hint:
        structured["hint"] = hint

    return ToolResult(
        content=[TextContent(type="text", text=content_text)],
        structured_content=structured,
        is_error=True,
    )
