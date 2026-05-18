---
sidebar_position: 1
title: "Introduction"
description: "Batho — Bidirectional AST Traversal & Hypergraph Orchestrator"
---

# Batho Documentation

**Batho** (Bidirectional AST Traversal & Hypergraph Orchestrator) is a deterministic, production-grade code intelligence engine that transforms raw codebases into queryable, time-aware structured hypergraphs.

## What Batho Does

| Capability | Description |
|-----------|-------------|
| **AST Extraction** | Parse 40+ languages via tree-sitter into structured entities and relationships |
| **Code Graph** | Build in-memory hypergraphs with cross-file symbol resolution |
| **BSG Compression** | Compress code intelligence into token-budgeted formats for LLM injection |
| **Time Machine** | Snapshot, diff, and incrementally patch code intelligence over time |
| **Git Hooks** | Enterprise-grade client-side hook automation with YAML configuration |
| **Dashboard** | Interactive web UI for exploring hypergraphs, files, metrics, and snapshots |
| **Artifact Bridge** | REST API + MCP server for IDE and tool integrations |

## Quick Links

- [Getting Started](/docs/getting-started/quick-start) — Install and run Batho in 30 seconds
- [Whitepaper](/docs/whitepaper) — Deep technical reference for every subsystem
- [CLI Reference](/docs/cli-reference) — Complete command documentation
- [GitHub](https://github.com/sageoz/batho) — Source code and issues
- [PyPI](https://pypi.org/project/batho/) — Install from Python Package Index

## Architecture at a Glance

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
        Graph["InMemoryGraph<br/>(Entities + Relationships)"]
        Cache["AST Cache<br/>(SQLite)"]
        SymbolIndex["SymbolIndex<br/>(Cross-file Resolution)"]
        Incremental["IncrementalGraphUpdater"]
    end

    subgraph Intelligence["Intelligence Layer"]
        BSG["BSGMap<br/>(Structured Graph)"]
        Rules["BSG Rule Plugins<br/>(Semantic Overlay)"]
    end

    subgraph Output["Output & Interfaces"]
        Snapshots["Time Machine Snapshots<br/>(.ctn/snapshots/)"]
        Dashboard["Web Dashboard v1"]
        Bridge["Artifact Bridge<br/>(REST + MCP)"]
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

<div class="sr-only">Architecture diagram showing Batho's data flow: Source Inputs (Git Repository, batho.yaml, hooks.yaml) feed into Batho Core Engine (AST Extractor, InMemoryGraph, AST Cache, SymbolIndex, IncrementalGraphUpdater) which connects to Intelligence Layer (BSGMap, BSG Rule Plugins) and produces Output & Interfaces (Time Machine Snapshots, Web Dashboard, Artifact Bridge, batho CLI).</div>

**Figure: Batho System Architecture** - High-level data flow from source inputs through the core engine to consumption interfaces.

## Status

| Metric | Value |
|--------|-------|
| Supported Languages | 40+ via tree-sitter |
| Context Compression | Up to 10x for LLM injection |
| Incremental Patch Speed | 10–100x faster than full re-index |
| Test Coverage | 859+ automated tests |
| Cache Hit Rate | >95% on typical PR-sized changes |
| Snapshot Retention | 90 days default, configurable |
| Max Indexed Files | 200,000 per repository |

---

Ready to dive in? Start with the [Quick Start Guide](/docs/getting-started/quick-start).
