---
sidebar_position: 10
title: "7. Performance & Scalability"
description: "Benchmarks, scaling dimensions, and cache strategy"
---

# 7. Performance & Scalability

## 7.1 Benchmarks

Performance metrics from production workloads in Batho v1.1.0:

| Metric | Value | Notes |
|--------|-------|-------|
| Indexing throughput | ~1,000 files/sec | 8 workers, cached AST |
| Full build (100K files) | ~3 minutes | Cold start, Python repository |
| Incremental patch (50 files) | ~1.5 seconds | Content-hash based patch |
| AST Cache hit rate | >95% | Typical pull request size |
| Memory footprint | ~1.5GB | 100K Python files |
| Arrow Bundle size | ~45MB | Compressed Arrow IPC Bundle database |
| Agent BSG export size | ~3.5MB | 12K token budget |

## 7.2 Scaling Dimensions

| Dimension | Strategy | Limit |
|-----------|----------|-------|
| Files | Parallel extraction + caching | 200,000 default |
| Workers | CPU × 2, capped at 32 | Auto-detected |
| File size | Configurable max (default 500KB) | Per-file |
| Runs | GC cleanup & vacuum policies | Configurable retention |

### Resource Requirements

| Repository Size | CPU | Memory | Disk |
|-----------------|-----|--------|------|
| Small (≤10K files) | 2 cores | 512MB | 100MB |
| Medium (10K-50K) | 4 cores | 1.5GB | 500MB |
| Large (50K-200K) | 8+ cores | 4GB+ | 2GB |

## 7.3 Cache Strategy

The caching strategy minimizes redundant work:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e3f2fd', 'primaryTextColor': '#1565c0', 'primaryBorderColor': '#1976d2', 'lineColor': '#42a5f5', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart LR
    A[File Discovered] --> B{In Cache?}
    B -->|Yes| C{mtime + SHA Match?}
    C -->|Yes| D[Skip Parsing]
    C -->|No| E[Parse + Update Cache]
    B -->|No| E
    D --> F[Add to Graph]
    E --> F

    style A fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style B fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style D fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style E fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style F fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
```

**Figure 17: Cache Strategy** - Flowchart showing the caching logic that minimizes redundant parsing through mtime and SHA-256 validation.

### Cache Layers

| Layer | Technology | TTL | Purpose |
|-------|------------|-----|---------|
| **AST Cache** | msgpack | 30 days | Persisted tree-sitter parsed entity structure |
| **Dependency Cache** | msgpack | 90 days | Shared third-party symbol resolution mapping |
| **BSG Cache** | Arrow IPC | 30 days | Rendered views stored in `file_artifacts` |

### Cache Invalidation & Maintenance

- **mtime + SHA-256 Verification**: Changes in files are caught by comparing filesystem markers and file content hashes against the database tracking schema.
- **Garbage Collection**: Outdated runs and cache entries are cleaned up using `batho gc`. Running `batho gc vacuum` frees up database sectors by triggering vacuum operations on Arrow IPC files.
