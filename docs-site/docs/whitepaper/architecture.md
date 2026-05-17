---
sidebar_position: 2
title: "1. Architecture Overview"
description: "High-level system architecture and data flow pipeline"
---

# 1. Architecture Overview

## 1.1 High-Level System Architecture

Batho's architecture follows a layered approach with clear separation between extraction, indexing, intelligence, and output layers. The system is designed for deterministic processing, enabling reliable caching and incremental updates.

```mermaid
flowchart TB
    subgraph Sources["Source Inputs"]
        Repo["Git Repository (40+ Languages)"]
        Config["batho.yaml"]
        Hooks[".batho/hooks.yaml"]
    end

    subgraph Core["Batho Core Engine"]
        Extractor["Multi-Language AST Extractor (tree-sitter)"]
        Graph["InMemoryGraph (Entities + Relationships)"]
        Cache["AST Cache (SQLite)"]
        SymbolIndex["SymbolIndex (Cross-file Resolution)"]
        Incremental["IncrementalGraphUpdater"]
    end

    subgraph Intelligence["Intelligence Layer"]
        BSG["BSGMap (Structured Graph)"]
        Rules["BSG Rule Plugins (Semantic Overlay)"]
    end

    subgraph Output["Output & Interfaces"]
        Snapshots["Time Machine Snapshots (.ctn/snapshots/)"]
        Dashboard["Web Dashboard v1"]
        Bridge["Artifact Bridge (REST + MCP)"]
        CLI["batho CLI"]
    end

    Repo --> Extractor
    Config --> Extractor
    Extractor --> Cache
    Extractor --> Graph
    Graph --> SymbolIndex
    SymbolIndex --> Graph
    Graph --> Incremental
    Graph --> BSG
    BSG --> Rules
    BSG --> Snapshots
    Snapshots --> Dashboard
    BSG --> Bridge
    Bridge --> Dashboard
    CLI --> Core
    CLI --> Intelligence
    CLI --> Output
    Hooks --> CLI
```

## 1.2 Data Flow Pipeline

The data flow pipeline ensures deterministic processing with built-in caching and validation:

```mermaid
sequenceDiagram
    actor User
    participant CLI as batho CLI
    participant Extractor as AST Extractor
    participant Cache as SQLite Cache
    participant Graph as InMemoryGraph
    participant BSG as BSGMap
    participant Rules as Rule Plugins
    participant Snap as Snapshot Store

    User->>CLI: batho index --root . --snapshot
    CLI->>Extractor: Discover files (respect .gitignore)
    Extractor->>Cache: Check mtime + SHA-256
    Cache-->>Extractor: Cache hit / miss
    loop Parallel Extraction
        Extractor->>Extractor: tree-sitter parse
        Extractor->>Graph: Emit Entity + Relationship
    end
    Graph->>Graph: Resolve imports (SymbolIndex)
    Graph->>BSG: Build flat symbol index
    BSG->>Rules: Apply semantic overlay
    Rules-->>BSG: Tagged graph
    BSG->>Snap: Persist snapshot (UUID + timestamp)
    Snap-->>CLI: Snapshot ID
    CLI-->>User: .ctn/index.json updated
```

## 1.3 Component Responsibilities

### Core Engine Components

| Component | Purpose | Key Features |
|-----------|---------|--------------|
| **AST Extractor** | Multi-language parsing via tree-sitter | 40+ language support, parallel processing, mtime tracking |
| **InMemoryGraph** | Hypergraph storage | Lazy adjacency indexing, relationship deduplication, cross-file resolution |
| **AST Cache** | Persistent entity cache | SQLite-backed, SHA-256 validation, automatic invalidation |
| **SymbolIndex** | Cross-file symbol resolution | Two-pass resolution, unresolved target tracking |
| **IncrementalUpdater** | Patch application | Diff-based updates, chain validation, rollback support |

### Intelligence Layer Components

| Component | Purpose | Key Features |
|-----------|---------|--------------|
| **BSGMap** | Structured graph representation | Flat symbol index, priority scoring, rendering modes |
| **Rule Plugins** | Semantic analysis | YAML-defined rules, plugin architecture, tag-based annotation |

## 1.4 Output Interfaces

| Interface | Transport | Purpose |
|-----------|-----------|---------|
| **CLI** | Terminal | Direct control, scripting, automation |
| **Dashboard** | HTTP (port 8080) | Interactive exploration, visualization |
| **Bridge (REST)** | HTTP | Programmatic access, CI/CD integration |
| **Bridge (MCP)** | stdio/SSE | LLM context provisioning |
| **Snapshots** | JSON files | Time-travel, audit trail, backup |
