# Batho Documentation

Welcome to the Batho v1.1.0 documentation. This directory contains detailed specifications and guides for every subsystem of the Batho code intelligence engine.

---

## Quick Start

```bash
# Install
pip install batho

# Build index for a repository
batho build --root /path/to/repo

# Export for LLM context injection
batho export --view agent --output context.json --root /path/to/repo

# Update index incrementally after code changes
batho patch --root /path/to/repo
```

For a complete CLI reference, see [CLI_REFERENCE.md](CLI_REFERENCE.md).

---

## Documentation Index

### Architecture & Lifecycle

| Document | Description |
|----------|-------------|
| [BATHO_BUILD_FLOW.md](BATHO_BUILD_FLOW.md) | Complete build pipeline — CLI entry through Arrow IPC persistence. Phases A–H, call graph, data flow diagrams. |
| [ORCHESTRATOR_PATCH_SPEC.md](ORCHESTRATOR_PATCH_SPEC.md) | `batho patch` incremental update — hash-based change detection, copy-on-write BSG store, node-level diff changelog. |
| [ORCHESTRATOR_EXPORT_SPEC.md](ORCHESTRATOR_EXPORT_SPEC.md) | `batho export` — 8 view types (storage/agent/overview/files/symbols/dependencies/delta/rel), pack mode for CI/CD handoff. |
| [ORCHESTRATOR_GC_SPEC.md](ORCHESTRATOR_GC_SPEC.md) | `batho gc` — run deletion, prune by age, vacuum, storage status. |
| [ORCHESTRATOR_LOAD_SPEC.md](ORCHESTRATOR_LOAD_SPEC.md) | `batho load` — transport ZIP ingestion, schema validation, BSG reconstruction. |

### Storage

| Document | Description |
|----------|-------------|
| [STORAGE_ENGINE.md](STORAGE_ENGINE.md) | Arrow IPC at-rest storage — `BathoBundle`, `BsgScratchStore`, `IncrementalEngine`, `BathoCache`, complete Arrow schema tables. |

### Core Modules

| Document | Description |
|----------|-------------|
| [CORE_SCHEMAS_SPEC.md](CORE_SCHEMAS_SPEC.md) | Shared type system — `Entity`, `Relationship`, all enums, ID generation, `SymbolRole`, `FileSnapshot`, exceptions. |
| [GRAPH_MODULE_SPEC.md](GRAPH_MODULE_SPEC.md) | Graph construction — `CodeGraphIndexer`, `InMemoryGraph`, post-processing passes, node diff engine, file reconstructor. |
| [EXTRACTION_MODULE_SPEC.md](EXTRACTION_MODULE_SPEC.md) | AST extraction — `ASTExtractor`, multiprocessing pipeline, `AstCache`, `ScopeManager`, language registry, 28+ supported languages. |
| [COMPRESSION_MODULE_SPEC.md](COMPRESSION_MODULE_SPEC.md) | BSGMap and rule engine — dual-mode rendering (agent/storage), BSG plugin catalog, `apply_bsg_rules_to_entities()`. |
| [DEPENDENCY_MODULE_SPEC.md](DEPENDENCY_MODULE_SPEC.md) | CDEU dependency indexing — manifest parsing, live introspection, `ResolutionCache`, stdlib tables, popular packages DB. |
| [INTEGRITY_MODULE_SPEC.md](INTEGRITY_MODULE_SPEC.md) | `batho fix` engine — 4 checker phases (db/state/blobs/graph), 3 repairers, report formats (text/json/csv). |
| [UTILS_MODULE_SPEC.md](UTILS_MODULE_SPEC.md) | Shared utilities — structured logging, file I/O, hashing, gitignore filtering, memory monitoring, path sanitization. |

### Reference

| Document | Description |
|----------|-------------|
| [CLI_REFERENCE.md](CLI_REFERENCE.md) | Complete CLI reference — all 7 commands with all flags, exit codes, environment variables quick-reference. |
| [config.md](config.md) | Complete configuration schema — all `batho.yaml` keys, types, defaults, environment variable overrides. |
| [CICD_INTEGRATION_GUIDE.md](CICD_INTEGRATION_GUIDE.md) | CI/CD integration — GitHub Actions, GitLab CI, pack/load workflow, cache strategies, common pitfalls. |

---

## Recommended Reading Order

**New to Batho?**
1. [CLI_REFERENCE.md](CLI_REFERENCE.md) — understand the commands
2. [BATHO_BUILD_FLOW.md](BATHO_BUILD_FLOW.md) — understand what `batho build` does
3. [config.md](config.md) — configure for your project
4. [CICD_INTEGRATION_GUIDE.md](CICD_INTEGRATION_GUIDE.md) — integrate into your pipeline

**Building on Batho?**
1. [CORE_SCHEMAS_SPEC.md](CORE_SCHEMAS_SPEC.md) — understand the data model (`Entity`, `Relationship`)
2. [COMPRESSION_MODULE_SPEC.md](COMPRESSION_MODULE_SPEC.md) — understand BSGMap views (agent vs storage)
3. [ORCHESTRATOR_EXPORT_SPEC.md](ORCHESTRATOR_EXPORT_SPEC.md) — consume the index via `batho export`
4. [STORAGE_ENGINE.md](STORAGE_ENGINE.md) — read Arrow IPC files directly

**Debugging / Contributing?**
1. [EXTRACTION_MODULE_SPEC.md](EXTRACTION_MODULE_SPEC.md) — how parsing works
2. [GRAPH_MODULE_SPEC.md](GRAPH_MODULE_SPEC.md) — how the graph is built and post-processed
3. [INTEGRITY_MODULE_SPEC.md](INTEGRITY_MODULE_SPEC.md) — how to diagnose and repair issues
4. [STORAGE_ENGINE.md](STORAGE_ENGINE.md) — Arrow IPC schemas and storage layout

---

## Architecture Overview

```
CLI (batho_cli.py)
  │
  ├── build ──────────── orchestrator/build.py
  │     ├── Dependency Indexing   (modules/dependency/)
  │     ├── AST Extraction        (modules/extraction/)
  │     ├── Graph Construction    (modules/graph/)
  │     ├── BSG Compression       (modules/compression/)
  │     └── Arrow IPC Storage     (modules/storage/)
  │
  ├── patch ──────────── orchestrator/patch.py
  │     ├── IncrementalEngine     (storage/arrow_bundle/incremental.py)
  │     ├── Copy-on-write BSG     (storage/arrow_store/store.py)
  │     └── Node Diff Engine      (modules/graph/diff_engine/)
  │
  ├── export ─────────── orchestrator/export.py
  │     └── BSGMap Views          (modules/compression/bsg_map/)
  │
  ├── fix ────────────── modules/integrity/engine.py
  │     ├── Checkers              (integrity/checkers/)
  │     └── Repairers             (integrity/repairers/)
  │
  ├── gc ─────────────── orchestrator/gc.py
  ├── load ───────────── orchestrator/load.py
  └── diff ───────────── cli/diff.py
```

---

## Version

This documentation covers **Batho v1.1.0 / v1.1.1**.

For the changelog, see `CHANGELOG.md` in the repository root.
