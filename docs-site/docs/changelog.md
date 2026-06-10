---
sidebar_position: 100
title: "Changelog"
description: "Batho release history"
---

# Changelog

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
