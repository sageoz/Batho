"""Agent snippet service — MCP configuration generation for IDEs.

Generates MCP configuration snippets for various AI agent IDEs
(Claude Desktop, Cursor, Windsurf, Continue, Cline, Generic).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.services.snippets")

SUPPORTED_AGENTS = {
    "claude_desktop",
    "cursor",
    "continue",
    "cline",
    "windsurf",
    "generic",
}


class AgentSnippetGenerator:
    """Generates MCP configuration snippets for AI agent IDEs."""

    def __init__(self, repo_root: Path, port: int = 8765, host: str = "127.0.0.1"):
        """Initialize snippet generator.

        Args:
            repo_root: Repository root path
            port: Bridge server port
            host: Bridge server host
        """
        self.repo_root = repo_root
        self.port = port
        self.host = host

    def generate(self, agent: str, transport: str = "stdio") -> str | None:
        """Generate MCP configuration snippet for the specified agent.

        Args:
            agent: Agent name (claude_desktop, cursor, continue, cline, windsurf, generic)
            transport: Transport type (stdio, sse)

        Returns:
            Configuration snippet as string, or None if agent is unknown
        """
        if agent not in SUPPORTED_AGENTS:
            return None

        if agent == "claude_desktop":
            return self._generate_claude_desktop(transport)
        elif agent == "cursor":
            return self._generate_cursor(transport)
        elif agent == "continue":
            return self._generate_continue(transport)
        elif agent == "cline":
            return self._generate_cline(transport)
        elif agent == "windsurf":
            return self._generate_windsurf(transport)
        elif agent == "generic":
            return self._generate_generic()

        return None

    def _generate_claude_desktop(self, transport: str = "stdio") -> str:
        """Generate Claude Desktop MCP configuration."""
        if transport == "sse":
            mcp_servers = {
                "batho": {
                    "sse": {
                        "url": f"http://{self.host}:{self.port}/sse"
                    }
                }
            }
        else:
            mcp_servers = {
                "batho": {
                    "command": "batho",
                    "args": ["bridge", "serve", "--transport", "stdio"],
                    "env": {
                        "BATHO_REPO_ROOT": str(self.repo_root),
                    },
                }
            }

        config_json = {
            "mcpServers": mcp_servers,
        }

        return json.dumps(config_json, indent=2)

    def _generate_cursor(self, transport: str = "stdio") -> str:
        """Generate Cursor MCP configuration."""
        if transport == "sse":
            mcp_servers = {
                "batho": {
                    "url": f"http://{self.host}:{self.port}/sse"
                }
            }
        else:
            mcp_servers = {
                "batho": {
                    "command": "batho",
                    "args": ["bridge", "serve", "--transport", "stdio"],
                }
            }

        config_json = {
            "mcpServers": mcp_servers,
        }

        return json.dumps(config_json, indent=2)

    def _generate_continue(self, transport: str = "stdio") -> str:
        """Generate Continue MCP configuration."""
        if transport == "sse":
            mcp_servers = [{
                "name": "batho",
                "url": f"http://{self.host}:{self.port}/sse"
            }]
        else:
            mcp_servers = [{
                "name": "batho",
                "command": "batho",
                "args": ["bridge", "serve", "--transport", "stdio"],
            }]

        config_json = {
            "mcpServers": mcp_servers,
        }

        return json.dumps(config_json, indent=2)

    def _generate_cline(self, transport: str = "stdio") -> str:
        """Generate Cline MCP configuration."""
        if transport == "sse":
            mcp_servers = {
                "batho": {
                    "url": f"http://{self.host}:{self.port}/sse"
                }
            }
        else:
            mcp_servers = {
                "batho": {
                    "command": "batho",
                    "args": ["bridge", "serve", "--transport", "stdio"],
                }
            }

        config_json = {
            "mcpServers": mcp_servers,
        }

        return json.dumps(config_json, indent=2)

    def _generate_windsurf(self, transport: str = "stdio") -> str:
        """Generate Windsurf MCP configuration."""
        if transport == "sse":
            mcp_servers = {
                "batho": {
                    "url": f"http://{self.host}:{self.port}/sse"
                }
            }
        else:
            mcp_servers = {
                "batho": {
                    "command": "batho",
                    "args": ["bridge", "serve", "--transport", "stdio"],
                }
            }

        config_json = {
            "mcpServers": mcp_servers,
        }

        return json.dumps(config_json, indent=2)

    def _generate_generic(self) -> str:
        """Generate generic MCP configuration (HTTP transport)."""
        servers = [{
            "id": "batho",
            "name": "Batho Bridge",
            "url": f"http://{self.host}:{self.port}",
            "transport": "http",
        }]

        config_json = {
            "version": "1.0",
            "servers": servers,
        }

        return json.dumps(config_json, indent=2)


def handle_agent_snippet(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle GET /api/v2/snippets/{agent}

    Returns MCP configuration snippet for the specified agent.

    Args:
        deps: Workspace dependencies
        params: Query parameters (required: agent; optional: transport, port, host)

    Returns:
        dict with keys: agent, snippet, transport
    """
    agent = params.get("agent")
    if not agent:
        return {
            "ok": False,
            "error": "Missing required parameter: agent",
            "data": {},
        }

    transport = params.get("transport", "stdio")
    port = int(params.get("port", 8765))
    host = params.get("host", "127.0.0.1")

    try:
        generator = AgentSnippetGenerator(deps.repo_root, port=port, host=host)
        snippet = generator.generate(agent, transport)

        if snippet is None:
            return {
                "ok": False,
                "error": f"Unknown agent: {agent}. Supported: {', '.join(sorted(SUPPORTED_AGENTS))}",
                "data": {},
            }

        return {
            "ok": True,
            "data": {
                "agent": agent,
                "snippet": snippet,
                "transport": transport,
                "supported_agents": sorted(SUPPORTED_AGENTS),
            },
        }
    except Exception as e:
        LOGGER.error("agent_snippet_error", error=str(e), agent=agent)
        return {
            "ok": False,
            "error": str(e),
            "data": {},
        }


__all__ = [
    "AgentSnippetGenerator",
    "handle_agent_snippet",
    "SUPPORTED_AGENTS",
]
