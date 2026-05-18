---
sidebar_position: 100
title: "Changelog"
description: "Batho release history"
---

# Changelog

## v1.1.0 — 2026-05-18

**MCP Hub - Multi-workspace context server.**

### New Features

- **MCP Hub** - Multi-workspace context server with lazy mounting and LRU residency
- **Workspace Management** - Register, pin, and manage multiple `.ctn` directories
- **Cross-Repo Search** - Search BSG entities across all workspaces
- **New CLI Commands**:
  - `batho mcp serve` - Start MCP hub server
  - `batho mcp list` - List registered workspaces
  - `batho mcp add` - Add a workspace
  - `batho mcp remove` - Remove a workspace
  - `batho mcp discover` - Discover workspaces from globs
  - `batho mcp status` - Show workspace status
  - `batho mcp pin/unpin` - Pin workspaces to prevent eviction

### MCP Tools (22 tools)

- Workspace: `workspace.list`, `workspace.health`, `workspace.stats`
- Index: `index.list`, `index.get`
- Artifact: `artifact.list`, `artifact.get`, `artifact.get_by_path`, `artifact.search`
- BSG: `bsg.get`, `bsg.search`
- Context: `context.overview`, `context.files`
- Graph: `graph.get`
- File: `file.read`, `file.list`
- Cross-repo: `cross.search`, `cross.symbols`, `cross.dependencies`, `cross.workspaces_with_artifact`

### REST API

- Workspace-scoped endpoints: `/api/v1/workspaces/{id}/...`
- Cross-repo endpoints: `/api/v1/cross/...`
- Legacy compatibility: `/api/v1/bridge/...` (deprecated)

### Configuration

- `~/.batho/mcp.yaml` - User-level MCP hub configuration
- Supports glob-based workspace discovery
- Configurable residency, concurrency, and caching

---

## v1.0.0 — 2026-05-17

**Initial production release.**

### Features

- Multi-language AST extraction (40+ languages via tree-sitter)
- In-memory hypergraph with cross-file symbol resolution
- BSG compression with token-budgeted rendering for LLM injection
- Time Machine snapshots with incremental patching
- Git Hooks Enterprise with YAML-driven configuration
- Interactive web dashboard (v1)
- Artifact Bridge with REST API and MCP server
- SQLite-backed caching and artifact registry
- Cloud sync capabilities
- 859+ automated tests

### Subsystems

- AST Extraction Engine
- Code Graph (`InMemoryGraph`)
- Symbol Index
- BSG Map & Rules
- Time Machine & Incremental Patcher
- Git Hooks Manager
- Web Dashboard
- REST API Bridge
- MCP Server
- Cloud Sync Client

---

For the latest releases, see [GitHub Releases](https://github.com/sageoz/batho/releases).
