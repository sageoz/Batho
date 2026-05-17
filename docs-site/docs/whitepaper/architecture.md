---
sidebar_position: 2
title: "1. Architecture Overview"
description: "High-level system architecture and data flow pipeline"
---

# 1. Architecture Overview

## 1.1 High-Level System Architecture

Batho's architecture follows a layered approach with clear separation between extraction, indexing, intelligence, and output layers. The system is designed for deterministic processing, enabling reliable caching and incremental updates.

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e3f2fd', 'primaryTextColor': '#1565c0', 'primaryBorderColor': '#1976d2', 'lineColor': '#42a5f5', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart TB
    subgraph Sources["Source Inputs"]
        Repo["Git Repository<br/>(40+ Languages)"]
        Config["batho.yaml"]
        Hooks[".batho/hooks.yaml"]
    end

    subgraph Core["Batho Core Engine"]
        Extractor["Multi-Language AST Extractor<br/>(tree-sitter)"]
        Graph["InMemoryGraph<br/>(Entities and Relationships)"]
        Cache["AST Cache<br/>(SQLite)"]
        SymbolIndex["SymbolIndex<br/>(Cross-file Resolution)"]
        Incremental["IncrementalGraphUpdater"]
    end

    subgraph Intelligence["Intelligence Layer"]
        BSG["BSGMap<br/>(Structured Graph)"]
        Rules["BSG Rule Plugins<br/>(Semantic Overlay)"]
    end

    subgraph Output["Output and Interfaces"]
        Snapshots["Time Machine Snapshots<br/>(.ctn/snapshots/)"]
        Dashboard["Web Dashboard v1"]
        Bridge["Artifact Bridge<br/>(REST and MCP)"]
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

    style Sources fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Core fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Intelligence fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style Output fill:#fce4ec,stroke:#c2185b,stroke-width:2px
```

<div class="sr-only">Figure 2: High-Level System Architecture - Flowchart showing the layered architecture from source inputs through the core engine to output interfaces. Components include Source Inputs (Git Repository, batho.yaml, hooks.yaml), Batho Core Engine (AST Extractor, InMemoryGraph, AST Cache, SymbolIndex, IncrementalGraphUpdater), Intelligence Layer (BSGMap, BSG Rule Plugins), and Output Interfaces (Time Machine Snapshots, Web Dashboard, Artifact Bridge, batho CLI).</div>

**Figure 2: High-Level System Architecture** - Detailed component view showing the layered architecture from source inputs through the core engine to output interfaces.

## 1.2 Data Flow Pipeline

The data flow pipeline ensures deterministic processing with built-in caching and validation:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e3f2fd', 'primaryTextColor': '#1565c0', 'primaryBorderColor': '#1976d2', 'lineColor': '#42a5f5', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
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

<div class="sr-only">Figure 3: Data Flow Pipeline - Sequence diagram showing the deterministic indexing process with caching and validation steps. Flow: User triggers batho CLI index command, CLI discovers files respecting gitignore, Extractor checks cache using mtime and SHA-256 hash, parallel extraction parses files with tree-sitter and emits entities to InMemoryGraph, Graph resolves imports via SymbolIndex, BSGMap builds flat symbol index, Rule Plugins apply semantic overlay, Snapshot Store persists with UUID and timestamp, CLI returns snapshot ID and updates index.json.</div>

**Figure 3: Data Flow Pipeline** - Sequence diagram showing the deterministic indexing process with caching and validation steps.

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
