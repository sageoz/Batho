---
sidebar_position: 2
title: "MCP Server"
description: "Model Context Protocol server capabilities"
---

# MCP Server

The MCP server exposes Batho's graph as a model context provider for IDE and AI tool integrations.

## Transports

| Transport | Use Case | Command |
|-----------|----------|---------|
| `stdio` | IDE integration (Cursor, Windsurf, etc.) | `batho bridge mcp --transport stdio` |
| `sse` | Remote clients | `batho bridge mcp --transport sse --port 8767` |

## Tools

| Tool | Description |
|------|-------------|
| `bridge_list_indexes` | List all available index IDs and timestamps |
| `bridge_get_index` | Get metadata for a specific index |
| `bridge_list_artifacts` | List artifact records, optionally filtered |
| `bridge_get_artifact` | Load full JSON content for an artifact type |
| `bridge_get_artifact_by_path` | Load artifact content by exact logical path |
| `bridge_search_artifacts` | Fuzzy search artifacts by logical path |
| `bridge_get_stats` | Return registry statistics |

## Example: stdio transport

```bash
batho bridge mcp --root /path/to/repo --transport stdio
```

This mode is designed to be consumed by MCP-compatible clients that spawn the process and communicate over stdin/stdout.
