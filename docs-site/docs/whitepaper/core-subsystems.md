---
sidebar_position: 3
title: "2. Core Subsystems"
description: "Subsystem inventory and technology stack"
---

# 2. Core Subsystems

## 2.1 Subsystem Inventory

| Subsystem | Module Path | Purpose | Status |
|-----------|-------------|---------|--------|
| AST Extraction | `batho/context/extractor.py` | tree-sitter based multi-language parsing | Production |
| Language Registry | `batho/context/languages/` | Detector + per-language extractors | Production |
| Code Graph | `batho/context/codegraph.py` | In-memory hypergraph with adjacency indexing | Production |
| Symbol Index | `batho/context/symbol_index.py` | Cross-file import resolution | Production |
| AST Cache | `batho/context/cache.py` | SQLite-backed entity caching | Production |
| Pipeline | `batho/context/pipeline.py` | Parallel graph construction | Production |
| BSG Map | `batho/context/bsg_map.py` | Flat symbol index + renderers | Production |
| BSG Rules | `batho/bsg/rules.py` | Plugin loader + semantic overlay | Production |
| Time Machine | `batho/time_machine.py` | Snapshots, diffs, incremental patches | Production |
| Hooks | `batho/hooks/` | Git hook management | Production |
| Dashboard | `batho/dashboard/` | Interactive web UI | Production |
| Bridge | `batho/bridge/` | REST API + MCP server | Production |
| Cloud Sync | `batho/cloud_sync/` | Artifact synchronization | Production |
| Config | `batho/config.py` | Pydantic-validated configuration | Production |
| Storage | `batho/context/storage.py` | SQLite artifact registry | Production |
| Query Service | `batho/context/query.py` | Persisted graph indexes | Production |
| Synthesizer | `batho/synthesizer.py` | Evolution ledger + failure rule synthesis | Production |

## 2.2 Technology Stack

| Layer | Technology | Version |
|-------|------------|---------|
| Language Runtime | Python | 3.11+ |
| AST Parsing | tree-sitter | 0.25+ |
| Language Pack | tree-sitter-language-pack | Latest |
| Configuration | Pydantic | 2.x |
| CLI Framework | argparse (stdlib) | — |
| Web Dashboard | Vanilla JS + Static HTML | — |
| REST API | stdlib http.server | — |
| MCP Server | stdio / sse transport | — |
| Cache / Registry | SQLite | 3.x |
| Testing | pytest + pytest-cov | 8.x / 5.x |
| Build Tool | uv | Latest |
