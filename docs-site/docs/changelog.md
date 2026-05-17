---
sidebar_position: 100
title: "Changelog"
description: "Batho release history"
---

# Changelog

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
