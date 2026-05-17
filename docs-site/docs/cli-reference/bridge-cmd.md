---
sidebar_position: 7
title: "bridge"
description: "Artifact Bridge REST API and MCP server"
---

# `bridge` Command

Expose `.ctn/` artifacts via HTTP and MCP for dashboard/IDE integrations.

## REST API Server

```bash
# Start REST API server (default http://127.0.0.1:8766)
batho bridge serve --root /path/to/repo
batho bridge serve --root /path/to/repo --host 0.0.0.0 --port 8766
```

**REST endpoints** (mounted under `/api/v1/bridge/`):

- `GET /indexes` — List all indexes
- `GET /indexes/{index_id}` — Get specific index metadata
- `GET /artifacts?type={artifact_type}&limit={n}` — List artifact records
- `GET /artifacts/{artifact_type}?index_id={id}` — Load artifact JSON content
- `GET /artifacts/{artifact_type}/content?path={logical_path}` — Load by logical path
- `GET /stats` — Registry statistics

## MCP Server

```bash
# Start MCP server (stdio for IDE integration)
batho bridge mcp --root /path/to/repo --transport stdio

# Start MCP server (SSE for remote clients)
batho bridge mcp --root /path/to/repo --transport sse --port 8767
```

**MCP tools**: `bridge_list_indexes`, `bridge_get_index`, `bridge_list_artifacts`, `bridge_get_artifact`, `bridge_get_artifact_by_path`, `bridge_search_artifacts`, `bridge_get_stats`.

## Status & Verify

```bash
batho bridge status --root /path/to/repo      # Check status
batho bridge verify --root /path/to/repo       # Verify all artifacts are loadable
```
