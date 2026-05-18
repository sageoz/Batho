"""Agent configuration snippet generation for MCP clients."""

from __future__ import annotations

import json
from typing import Any

from batho.bridge.models import HubConfig


SUPPORTED_AGENTS = {
    "claude_desktop",
    "cursor",
    "continue",
    "cline",
    "windsurf",
    "generic",
}


def generate_agent_snippet(agent: str, config: HubConfig, transport: str = "stdio") -> str | None:
    """Generate MCP configuration snippet for the specified agent.

    Args:
        agent: Agent name (claude_desktop, cursor, continue, cline, windsurf, generic)
        config: Hub configuration
        transport: Transport type (stdio, sse)

    Returns:
        Configuration snippet as string, or None if agent is unknown
    """
    if agent not in SUPPORTED_AGENTS:
        return None

    bind = config.server.bind
    http_port = config.server.http_port
    rest_port = config.server.rest_port

    if agent == "claude_desktop":
        return _generate_claude_desktop(bind, http_port, config, transport)
    elif agent == "cursor":
        return _generate_cursor(bind, http_port, config, transport)
    elif agent == "continue":
        return _generate_continue(bind, http_port, config, transport)
    elif agent == "cline":
        return _generate_cline(bind, http_port, config, transport)
    elif agent == "windsurf":
        return _generate_windsurf(bind, http_port, config, transport)
    elif agent == "generic":
        return _generate_generic(bind, http_port, rest_port, config)

    return None


def _generate_claude_desktop(bind: str, http_port: int, config: HubConfig, transport: str = "stdio") -> str:
    """Generate Claude Desktop MCP configuration."""
    mcp_servers = {}

    for ws in config.workspaces:
        if not ws.enabled:
            continue
        
        if transport == "sse":
            mcp_servers[f"batho-{ws.id}"] = {
                "sse": {
                    "url": f"http://{bind}:{http_port}/sse"
                }
            }
        else:
            mcp_servers[f"batho-{ws.id}"] = {
                "command": "batho",
                "args": ["mcp", "serve", "--transport", "stdio"],
                "env": {
                    "BATHO_CONFIG_PATH": str(config.workspaces[0].ctn_dir) if config.workspaces else "",
                },
            }

    config_json = {
        "mcpServers": mcp_servers,
    }

    return json.dumps(config_json, indent=2)


def _generate_cursor(bind: str, http_port: int, config: HubConfig, transport: str = "stdio") -> str:
    """Generate Cursor MCP configuration."""
    mcp_servers = {}

    for ws in config.workspaces:
        if not ws.enabled:
            continue
        
        if transport == "sse":
            # Cursor SSE uses a URL directly
            mcp_servers[f"batho-{ws.id}"] = {
                "url": f"http://{bind}:{http_port}/sse"
            }
        else:
            mcp_servers[f"batho-{ws.id}"] = {
                "command": "batho",
                "args": ["mcp", "serve", "--transport", "stdio"],
            }

    config_json = {
        "mcpServers": mcp_servers,
    }

    return json.dumps(config_json, indent=2)


def _generate_continue(bind: str, http_port: int, config: HubConfig, transport: str = "stdio") -> str:
    """Generate Continue MCP configuration."""
    mcp_servers = []

    for ws in config.workspaces:
        if not ws.enabled:
            continue
        
        if transport == "sse":
            mcp_servers.append({
                "name": f"batho-{ws.id}",
                "url": f"http://{bind}:{http_port}/sse"
            })
        else:
            mcp_servers.append({
                "name": f"batho-{ws.id}",
                "command": "batho",
                "args": ["mcp", "serve", "--transport", "stdio"],
            })

    config_json = {
        "mcpServers": mcp_servers,
    }

    return json.dumps(config_json, indent=2)


def _generate_cline(bind: str, http_port: int, config: HubConfig, transport: str = "stdio") -> str:
    """Generate Cline MCP configuration."""
    mcp_servers = {}

    for ws in config.workspaces:
        if not ws.enabled:
            continue
            
        if transport == "sse":
            # Cline supports SSE via URL
            mcp_servers[f"batho-{ws.id}"] = {
                "url": f"http://{bind}:{http_port}/sse"
            }
        else:
            mcp_servers[f"batho-{ws.id}"] = {
                "command": "batho",
                "args": ["mcp", "serve", "--transport", "stdio"],
            }

    config_json = {
        "mcpServers": mcp_servers,
    }

    return json.dumps(config_json, indent=2)


def _generate_windsurf(bind: str, http_port: int, config: HubConfig, transport: str = "stdio") -> str:
    """Generate Windsurf MCP configuration."""
    mcp_servers = {}

    for ws in config.workspaces:
        if not ws.enabled:
            continue
            
        if transport == "sse":
            mcp_servers[f"batho-{ws.id}"] = {
                "url": f"http://{bind}:{http_port}/sse"
            }
        else:
            mcp_servers[f"batho-{ws.id}"] = {
                "command": "batho",
                "args": ["mcp", "serve", "--transport", "stdio"],
            }

    config_json = {
        "mcpServers": mcp_servers,
    }

    return json.dumps(config_json, indent=2)


def _generate_generic(bind: str, http_port: int, rest_port: int, config: HubConfig) -> str:
    """Generate generic MCP configuration (HTTP transport)."""
    servers = []

    for ws in config.workspaces:
        if not ws.enabled:
            continue
        servers.append({
            "id": f"batho-{ws.id}",
            "name": ws.label or ws.id,
            "url": f"http://{bind}:{http_port}",
            "transport": "http",
        })

    config_json = {
        "version": "1.0",
        "servers": servers,
    }

    return json.dumps(config_json, indent=2)


__all__ = [
    "generate_agent_snippet",
    "SUPPORTED_AGENTS",
]
