---
sidebar_position: 100
title: "Changelog"
description: "Batho release history"
---

# Changelog

## v1.2.1 — 2026-07-20

**Bug fixes, concurrency safety, and documentation alignment.**

### Bug Fixes

- **Critical: `patch.py` NameError on delete-only runs** — `indexer` variable was only defined inside the `if added_or_modified:` block; delete-only patch runs crashed with `NameError`. Fixed by initializing `indexer = None` and guarding the `getattr` call.
- **`RepoRegistry` race condition** — `add()` and `remove()` performed load→mutate→save without locking. Concurrent MCP tool calls could lose entries. Fixed with `threading.Lock` and atomic file writes.
- **`ResolutionCache` non-atomic writes** — `put_symbols()` and `_save_index()` wrote directly to cache files without temp+rename. Crash during write could corrupt the cache. Fixed with `tempfile.mkstemp` + `os.replace` pattern.

### Improvements

- **`graph_overview` truncation indicator** — Truncated output now appends a visible notice to the markdown, matching `graph_query` and `get_file_graph` behavior.
- **`get_file_graph` cross-file ref performance** — Replaced per-entity `pc.equal()` loop with single `pc.is_in()` batch filter.
- **`graph_overview` file entity counts** — Fixed hardcoded `entities: 0` in file list; now computes actual entity counts per file from the agent table.
- **Dependency introspector input validation** — Added package name regex validation before subprocess execution.
- **Git subprocess hardening** — Added `GIT_PAGER=cat` to environment to prevent pager invocation.

### Documentation

- Updated all version references from `v1.2.0` to `v1.2.1` across whitepaper, CI/CD, configuration, and test docs.

---

## v1.2.0 — 2026-07-05

**MCP server, multi-repo registry, and community detection — Batho becomes an AI agent platform.**

### New Features & Enhancements

- **MCP Server** (`batho mcp`): FastMCP-based stdio server exposing 10 tools for AI agents to query the code graph:
  - `graph_overview` — high-level codebase summary with entity counts, relationships, and communities
  - `graph_query` — filtered graph query by file, entity type, relation type, or name pattern
  - `get_entity` — detailed info for a single entity with relationships and optional source code
  - `trace_path` — shortest dependency path between two entities (BFS traversal)
  - `get_file_graph` — all entities and relationships within a single file
  - `search_entities` — substring/regex search across entity names
  - `get_delta` — incremental changes from the latest patch
  - `list_repos` / `add_repo` / `remove_repo` — multi-repo registry management
- **Multi-Repo Registry**: JSON-based registry at `~/.batho/mcp-repos.json` — one MCP config entry serves all repos. Register repos at runtime via `add_repo` tool.
- **Community Detection**: Leiden clustering via `leidenalg` + `igraph` — automatically groups related entities into communities for codebase overview.
- **Dual-Output Architecture**: All MCP tools return both markdown `content` (model-facing, ~34% fewer tokens) and JSON `structuredContent` (machine-facing).
- **Token Budget Truncation**: Configurable `max_tokens` parameter on graph tools with automatic truncation and reporting.
- **MCP Prompts**: Workflow-specific prompt templates for agent onboarding (`explore_codebase`, `trace_dependencies`, `security_audit`, `refactor_prep`).
- **MCP Resources**: Static schema and dynamic repo-list resources accessible via URI references.
- **Structured Error Handling**: Typed errors (`CLIENT_ERROR`, `EXTERNAL_ERROR`) with retry hints and actionable messages.
- **SKILL.md**: AI agent setup skill file for automated global install, MCP configuration across Claude Desktop, Cursor, Windsurf, and VS Code.
- **GitHub Actions Fleet Indexer**: Automated code graph indexing workflow with incremental patching on every push/PR.
- **New CLI Command**: `batho mcp` — starts the MCP server (8th CLI command).
- **New Dependencies**: `fastmcp>=2.14.0`, `leidenalg>=0.10`, `python-igraph>=0.11`

### Tests

- **507 tests** (up from 381) — 126 new MCP tests covering tools, prompts, resources, registry, community detection, token budget, and error handling.

---

## v1.1.0 — 2026-06-10

**Refactored v1.1.0 release focusing on unified configuration, performance, and CLI simplicity.**

### New Features & Enhancements

- **Unified Configuration**: All settings consolidated into a single `./batho.yaml` (see `batho.yaml.example` for the complete schema).
- **Arrow IPC Bundle Storage**: Relational data and symbol indices are serialized in high-performance Arrow IPC table formats directly in the `.batho/artifact/` directory.
- **Lossless Bidirectional Traversal**: Graph-to-code reconstruction supported via `SYNTAX_GLUE` entity preservation and cryptographic hash validation.
- **Simplified CLI Interface**: Restructured the toolchain into exactly 7 command entrypoints:
  - `build` — baseline repository builds.
  - `patch` — native content-hash-based incremental indexing.
  - `export` — JSON and pack ZIP exports.
  - `fix` — database diagnostic and auto-repair routines.
  - `diff` — node-level evolution history.
  - `gc` — garbage collection, Sweeping, and vacuums.
  - `load` — unpack transport ZIPs.

### Removals

- **Subsystem Removal**: Removed the legacy Web Dashboard, REST API Bridge, MCP Hub Context Server, and client-side Git Hook automation to focus exclusively on high-performance developer command-line workflows.

---

## v1.0.0 — 2026-05-17

**Initial pre-refactor production baseline.**

### Features

- Multi-language AST extraction (40+ languages via tree-sitter).
- In-memory hypergraph with cross-file symbol resolution.
- BSG compression with token-budgeted rendering.
- Time Machine snapshots with incremental patching.
- Pre-refactor subsystems (legacy dashboard, REST bridge, MCP server, git hooks).
- 381 automated tests.
