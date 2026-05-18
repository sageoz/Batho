---
sidebar_position: 10
title: "MCP Integration"
description: "Connect Batho to Claude Desktop, Cursor, Continue, Cline, Windsurf"
---

# Batho MCP Integration

Batho provides a Model Context Protocol (MCP) Hub that allows AI coding agents to discover and query multiple codebases through a unified tool surface.

## Architecture

The Batho MCP Hub acts as a bridge between your AI agents and the underlying `.ctn` workspaces:

1. **Agent** (Claude, Cursor, etc.) connects via **Transport** (stdio or SSE).
2. **MCP Hub** manages the **Workspace Registry**.
3. **Workspace Manager** handles lazy mounting and LRU caching of registered `.ctn` directories.
4. **Tools** are dispatched to the appropriate workspace or executed across all workspaces.

## Quickstart

The easiest way to get the configuration for your favorite agent is through the Batho Dashboard's **MCP** page, which provides ready-to-paste snippets.

### Claude Desktop

1. Open Claude Desktop.
2. Go to **Settings** -> **Developer** -> **Edit Config**.
3. Add `batho` to your `mcpServers`:

```json
{
  "mcpServers": {
    "batho": {
      "command": "batho",
      "args": ["mcp", "serve", "--transport", "stdio"]
    }
  }
}
```

### Cursor

Cursor supports MCP through its settings:
1. Go to **Cursor Settings** -> **General** -> **MCP**.
2. Click **+ Add New MCP Server**.
3. Name: `Batho`
4. Type: `stdio`
5. Command: `batho mcp serve --transport stdio`

### Windsurf

Windsurf uses a configuration file at `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "batho": {
      "command": "batho",
      "args": ["mcp", "serve", "--transport", "stdio"]
    }
  }
}
```

## Discovery Affordances

Batho publishes MCP **Resources** and **Prompts** to help agents understand the available context.

### Resources

- `batho://workspaces/list`: Returns a JSON list of all registered workspaces and their status.
- `batho://workspace/{id}/index.json`: Returns the full index for a specific workspace.

### Prompts

- `find_symbol`: Helps the agent find a symbol definition across all or specific repos.
- `summarise_workspace`: Provides a high-level summary of a workspace's purpose and structure.
- `cross_repo_search`: Guides the agent through searching for patterns across the entire registry.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| **Command not found** | Ensure `batho` is in your PATH. If using `uv`, use `uv run batho`. |
| **Port conflict (8770)** | If using SSE, ensure no other process is using port 8770. |
| **Workspace not ready** | Check the dashboard to see if the `.ctn` directory is valid and indexed. |
| **Checksum mismatch** | Re-index the workspace using `batho index --root .`. |
