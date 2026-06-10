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
| **Arrow IPC Bundle export** | Export optimized hypergraphs and indices as Arrow IPC bundles for downstream integration |

## Quick Links

- [Getting Started](/docs/getting-started/quick-start) — Install and run Batho in 30 seconds
- [Whitepaper](/docs/whitepaper) — Deep technical reference for every subsystem
- [CLI Reference](/docs/cli-reference) — Complete command documentation
- [GitHub](https://github.com/sageoz/batho) — Source code and issues
- [PyPI](https://pypi.org/project/batho/) — Install from Python Package Index

## Architecture at a Glance

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e3f2fd', 'primaryTextColor': '#1565c0', 'primaryBorderColor': '#1976d2', 'lineColor': '#42a5f5', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart LR
    Sources["Source Code & batho.yaml"] --> Extractor["AST Extractor (tree-sitter)"]
    Extractor --> Graph["InMemoryGraph"]
    Graph --> BSG["BSGMap"]
    BSG --> Arrow["Arrow IPC / JSON"]

    style Sources fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Extractor fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Graph fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style Arrow fill:#fce4ec,stroke:#c2185b,stroke-width:2px
```

<div class="sr-only">Architecture diagram showing Batho's data flow pipeline: Source code and batho.yaml feed into the AST Extractor, which builds the InMemoryGraph, is structured into a BSGMap, and exported as Arrow IPC or JSON.</div>

**Figure: Batho System Architecture** - High-level data flow from source inputs through the core engine to Arrow IPC / JSON outputs.

## Status

| Metric | Value |
|--------|-------|
| Supported Languages | 40+ via tree-sitter |
| Context Compression | Up to 10x for LLM injection |
| Incremental Patch Speed | 10–100x faster than full re-index |
| Test Coverage | 381 automated tests |
| Cache Hit Rate | >95% on typical PR-sized changes |
| Snapshot Retention | 90 days default, configurable |
| Max Indexed Files | 200,000 per repository |

---

Ready to dive in? Start with the [Quick Start Guide](/docs/getting-started/quick-start).
