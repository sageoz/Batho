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
    end

    subgraph Core["Batho Core Engine"]
        Orchestrator["Orchestrator Layer<br/>(build / patch / export / load / gc)"]
        Extractor["Multi-Language AST Extractor<br/>(tree-sitter)"]
        Graph["InMemoryGraph / ArrowGraph<br/>(Entities and Relationships)"]
        Cache["AST Cache<br/>(msgpack)"]
        SymbolIndex["SymbolIndex<br/>(Cross-file Resolution)"]
        Incremental["IncrementalGraphUpdater"]
        Storage["Arrow Bundle Store<br/>(MVCC + zero-copy mmap)"]
    end

    subgraph Intelligence["Intelligence Layer"]
        BSG["BSGMap<br/>(Structured Graph)"]
        Rules["BSG Rule Plugins<br/>(Semantic Overlay)"]
    end

    subgraph Output["Output and Interfaces"]
        Bundle["Arrow IPC Bundle<br/>(.batho/artifact/)"]
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
    BSG --> Storage
    Storage --> Bundle
    CLI --> Orchestrator
    Orchestrator --> Core
    Orchestrator --> Intelligence
    Orchestrator --> Output

    style Sources fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Core fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Intelligence fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style Output fill:#fce4ec,stroke:#c2185b,stroke-width:2px
```

<div class="sr-only">Figure 2: High-Level System Architecture - Flowchart showing the layered architecture from source inputs through the core engine to output interfaces. Components include Source Inputs (Git Repository, batho.yaml), Batho Core Engine (AST Extractor, InMemoryGraph, AST Cache, SymbolIndex, IncrementalGraphUpdater), Intelligence Layer (BSGMap, BSG Rule Plugins), and Output Interfaces (Arrow IPC Bundle, batho CLI).</div>

**Figure 2: High-Level System Architecture** - Detailed component view showing the layered architecture from source inputs through the core engine to output interfaces.

## 1.2 Data Flow Pipeline

The data flow pipeline ensures deterministic processing with built-in caching and validation:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e3f2fd', 'primaryTextColor': '#1565c0', 'primaryBorderColor': '#1976d2', 'lineColor': '#42a5f5', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
sequenceDiagram
    actor User
    participant CLI as batho CLI
    participant Orch as Orchestrator
    participant Extractor as AST Extractor
    participant Cache as AST Cache
    participant Graph as InMemoryGraph
    participant BSG as BSGMap
    participant Rules as Rule Plugins
    participant Store as Arrow Bundle Store

    User->>CLI: batho build --root .
    CLI->>Orch: BuildOptions
    Orch->>Extractor: Discover files (respect .gitignore)
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
    BSG->>Store: Write Arrow IPC Bundle
    Store-->>Orch: Database created
    Orch-->>CLI: Build result
    CLI-->>User: Build output summary shown
```

<div class="sr-only">Figure 3: Data Flow Pipeline - Sequence diagram showing the deterministic indexing process with caching and validation steps. Flow: User triggers batho CLI build command, CLI discovers files respecting gitignore, Extractor checks cache using mtime and SHA-256 hash, parallel extraction parses files with tree-sitter and emits entities to InMemoryGraph, Graph resolves imports via SymbolIndex, BSGMap builds flat symbol index, Rule Plugins apply semantic overlay, and the output is serialized to the Arrow Bundle Store.</div>

**Figure 3: Data Flow Pipeline** - Sequence diagram showing the deterministic indexing process with caching and validation steps.

## 1.3 Component Responsibilities

### Core Engine Components

| Component | Purpose | Key Features |
|-----------|---------|--------------|
| **Orchestrator Layer** | High-level command implementations | Typed options/results, module delegation, error recovery |
| **AST Extractor** | Multi-language parsing via tree-sitter | 40+ language support, parallel processing, mtime tracking |
| **InMemoryGraph** | Hypergraph storage | Lazy adjacency indexing, relationship deduplication, cross-file resolution |
| **ArrowGraph** | Columnar graph storage | Memory-mapped IPC, CSR/CSC adjacency indexes, streaming compaction, auto-selection |
| **AST Cache** | Persistent entity cache | msgpack-backed, SHA-256 validation, automatic invalidation |
| **SymbolIndex** | Cross-file symbol resolution | Two-pass resolution, unresolved target tracking |
| **IncrementalUpdater** | Patch application | Diff-based updates, content-hash comparisons, rollback support |
| **Arrow Bundle Store** | Persistent artifact storage | MVCC generation commit, zero-copy memory-mapped reads, O(1) point lookup |

### Intelligence Layer Components

| Component | Purpose | Key Features |
|-----------|---------|--------------|
| **BSGMap** | Structured graph representation | Flat symbol index, priority scoring, rendering modes |
| **Rule Plugins** | Semantic analysis | YAML-defined rules, plugin architecture, tag-based annotation |

## 1.4 Output Interfaces

| Interface | Transport | Purpose |
|-----------|-----------|---------|
| **CLI** | Terminal | Direct control, scripting, automation, history diffs, integrity repair, gc |
| **Arrow IPC Bundle** | Arrow / IPC (.batho) | High-performance serialized storage of entities, dependencies, and BSG views |
| **JSON Export** | JSON Stream | Standard representation for LLM context injection and downstream tool integrations |
