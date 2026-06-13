---
sidebar_position: 12
title: "9. Appendix: Schema Reference"
description: "Schema versions, directory structure, and glossary"
---

# 9. Appendix: Schema Reference

## 9.1 Schema Versions

| Artifact / Config | Schema Version | Description / Location |
|-------------------|----------------|------------------------|
| Configuration | `batho-config.v1` | Unified YAML configuration (`batho.yaml`) |
| Entity Schema | `pydantic.Entity` | Frozen Pydantic model (`batho/core/schemas.py`) |
| Relationship Schema | `pydantic.Relationship` | Frozen Pydantic model (`batho/core/schemas.py`) |
| Arrow Bundle | `batho-bundle.v1` | Arrow IPC tables: `file_tracking`, `file_artifacts`, `run_artifacts` |
| BSG View | `bsg.v1` | Memory-mapped Arrow IPC views |

### Schema Dependency Graph

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e3f2fd', 'primaryTextColor': '#1565c0', 'primaryBorderColor': '#1976d2', 'lineColor': '#42a5f5', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart TB
    subgraph Config["Configuration"]
        BATHO_YAML["batho.yaml<br/>(schema_version: batho-config.v1)"]
    end

    subgraph Database["Arrow Bundle (.batho/artifact/)"]
        TRACKING["file_tracking<br/>(mtime, SHA-256 hashes)"]
        FILE_ARTS["file_artifacts<br/>(bsg_agent_view, bsg_storage_view)"]
        RUN_ARTS["run_artifacts<br/>(telemetry, audit, delta_stats)"]
    end

    subgraph Output["Output Formats"]
        ARROW["Arrow IPC Views"]
        JSON["JSON Export Views"]
    end

    BATHO_YAML -->|"Configures"| TRACKING
    BATHO_YAML -->|"Controls blobs"| FILE_ARTS
    BATHO_YAML -->|"Controls audit"| RUN_ARTS
    FILE_ARTS -->|"Serializes to"| ARROW
    FILE_ARTS -->|"Exports to"| JSON
    RUN_ARTS -->|"Exports to"| JSON

    style Config fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Database fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Output fill:#fff3e0,stroke:#f57c00,stroke-width:2px
```

**Figure 24: Schema Dependency Graph** - Diagram showing the relationships between configuration schemas, database tables, and output views.

---

## 9.2 Directory Structure

```
.batho/
├── artifact/
│   └── artifact_<dirname>.batho    # Arrow IPC transport artifact
└── cache/
    └── cache.json                  # Shared AST cache metadata
```

---

## 9.3 Glossary

| Term | Definition |
|------|------------|
| **AST** | Abstract Syntax Tree — structured representation of source code |
| **BSG** | Batho Structured Graph — compressed, queryable code representation |
| **Arrow Bundle** | High-performance binary database file containing entities, dependencies, and BSG views |
| **Entity** | A node in the code graph (function, class, variable, etc.) |
| **Hypergraph** | Graph where edges can connect any number of nodes |
| **Patch** | Incremental update to the database based on content-hash changes |
| **Relationship** | A directed edge between entities |
| **Symbol Index** | Cross-file lookup table for imports and exports |
| **Syntax Glue** | Whitespace, comments, braces, and non-semantic gaps recorded for lossless file reconstruction |

---

## 9.4 Error Codes

| Code | Description |
|------|-------------|
| `E001` | File not found |
| `E002` | Parse error |
| `E003` | Cache corruption |
| `E004` | Snapshot mismatch |
| `E005` | Permission denied |
| `E100` | Configuration error |
| `E200` | Plugin load failure |
| `E300` | Storage registry error |
