---
sidebar_position: 8
title: "mcp"
description: "MCP Hub - Multi-workspace context server"
---

# `mcp` Command

Multi-workspace MCP Hub for serving context to coding agents. Manages multiple `.ctn` directories with lazy mounting, LRU residency, and cross-repo search.

## Serve MCP Hub

```bash
# Start MCP hub with stdio transport (for IDE integration)
batho mcp serve --transport stdio

# Start with SSE transport
batho mcp serve --transport sse --bind 127.0.0.1 --http-port 8770

# Start with HTTP transport
batho mcp serve --transport http --bind 127.0.0.1 --http-port 8770

# Use custom config file
batho mcp serve --config /path/to/mcp.yaml

# Disable REST API
batho mcp serve --transport sse --no-rest
```

### Options

| Option | Description |
|--------|-------------|
| `--config PATH` | Path to config file (default: ~/.batho/mcp.yaml) |
| `--transport stdio\|sse\|http` | MCP transport mode (default: stdio) |
| `--bind ADDRESS` | Bind address (default: 127.0.0.1) |
| `--http-port PORT` | MCP HTTP/SSE port (default: 8770) |
| `--rest-port PORT` | REST API port (default: 8771) |
| `--no-rest` | Disable REST API |

## List Workspaces

```bash
# List all registered workspaces
batho mcp list

# With custom config
batho mcp list --config /path/to/mcp.yaml
```

## Add Workspace

```bash
# Add a workspace with auto-generated ID
batho mcp add --ctn /path/to/repo/.ctn

# Add with custom ID and label
batho mcp add --ctn /path/to/repo/.ctn --id my-workspace --label "My Workspace"

# Add with tags
batho mcp add --ctn /path/to/repo/.ctn --tag python --tag core

# Pin workspace (prevent eviction)
batho mcp add --ctn /path/to/repo/.ctn --pinned
```

### Options

| Option | Description |
|--------|-------------|
| `--ctn PATH` | **Required** - Path to .ctn directory |
| `--id ID` | Workspace ID (default: derived from directory name) |
| `--label TEXT` | Display label |
| `--tag TAG` | Tags (can be repeated) |
| `--pinned` | Pin workspace to prevent eviction |

## Remove Workspace

```bash
# Remove a workspace
batho mcp remove --id my-workspace
```

## Discover Workspaces

```bash
# Discover workspaces from ctn_dir_globs in config
batho mcp discover

# With custom config
batho mcp discover --config /path/to/mcp.yaml
```

## Show Status

```bash
# Show all workspaces
batho mcp status

# Show specific workspace
batho mcp status --id my-workspace
```

## Pin/Unpin Workspace

```bash
# Pin workspace (prevent eviction)
batho mcp pin --id my-workspace

# Unpin workspace
batho mcp unpin --id my-workspace
```

## Configuration File

The MCP Hub uses `~/.batho/mcp.yaml` by default:

```yaml
schema_version: 1

server:
  bind: "127.0.0.1"
  http_port: 8770
  rest_port: 8771
  default_workspace: "batho"

residency:
  max_resident_workspaces: 32
  idle_evict_seconds: 600
  max_total_cache_bytes: 1073741824  # 1 GiB
  max_per_workspace_cache_bytes: 134217728  # 128 MiB
  prefetch_default_workspace: true

concurrency:
  global_inflight_limit: 256
  per_workspace_inflight_limit: 16
  request_timeout_seconds: 30

discovery:
  ctn_dir_globs:
    - "~/projects/*/.ctn"
  watch: true
  ignore_ids: []

cross_repo:
  enabled: true
  max_results_per_workspace: 25
  merge_strategy: "score_desc"

workspaces:
  - id: "batho"
    ctn_dir: "/path/to/batho/.ctn"
    label: "Batho Core"
    tags: ["core"]
    pinned: true
```

## MCP Tools Available

When connected via MCP, you have access to:

- **Workspace**: `workspace.list`, `workspace.health`, `workspace.stats`
- **Index**: `index.list`, `index.get`
- **Artifact**: `artifact.list`, `artifact.get`, `artifact.get_by_path`, `artifact.search`
- **BSG**: `bsg.get`, `bsg.search`
- **Context**: `context.overview`, `context.files`
- **Graph**: `graph.get`
- **File**: `file.read`, `file.list`
- **Cross-repo**: `cross.search`, `cross.symbols`, `cross.dependencies`

## REST API Endpoints

When REST is enabled (default on SSE/HTTP):

- `GET /api/v1/workspaces` - List workspaces
- `GET /api/v1/workspaces/{id}/health` - Workspace health
- `GET /api/v1/workspaces/{id}/stats` - Registry stats
- `GET /api/v1/workspaces/{id}/indexes` - List indexes
- `GET /api/v1/workspaces/{id}/artifacts` - List artifacts
- `GET /api/v1/workspaces/{id}/file-content?path=...` - File content
- `GET /api/v1/cross/search?q=...` - Cross-repo search
- `GET /healthz` - Health check
