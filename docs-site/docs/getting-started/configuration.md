---
sidebar_position: 3
title: "Configuration"
description: "Configure Batho with batho.yaml and environment variables"
---

# Configuration

Batho works out of the box with zero config. For production use, configure with the unified root config file `./batho.yaml` (or start from `batho.yaml.example`) plus optional environment overrides.

## Configuration Precedence

1. Built-in defaults
2. `./batho.yaml`
3. Environment variables (override file values)
4. CLI flags (override for a specific run)

## Core Config Areas

| Area | Keys | What it controls |
|----------|------|------------------|
| `logging` | `level`, `json_format`, `quiet`, `file`, `format` | Process-wide logging and CLI verbosity behavior |
| `paths` | `ctn_dir` | Artifact output directory |
| `indexer` | `max_file_size_kb`, `max_workers`, `max_indexed_files`, `ignore_*`, `metrics_output` | Base indexing limits and outputs |
| `rules` | `enabled`, `builtin_plugins`, `custom_rules_*`, `strict_validation` | Rule plugins and metadata enrichment |
| `bsg.parallel` | `enabled`, `max_workers`, `chunk_size` | Parallel file extraction |
| `bsg.ignore` | `enabled` | `.gitignore` integration |
| `bsg.cache` | `enabled`, `path`, `max_size_mb`, `ttl_days` | AST cache behavior |
| `bsg.incremental` | `enabled`, `fallback_to_full`, `auto_detect_git` | Incremental indexing strategy |
| `bsg.symbol_resolution` | `enabled`, `fuzzy_matching`, `cache_symbols` | Cross-file symbol resolution |
| `bsg.serialization` | `method`, `compression`, `batch_size` | BSG render strategy |
| `bsg.parsing` | `error_recovery`, `partial_parsing`, `max_file_size_mb`, `skip_comments` | Parser behavior |
| `bsg.query` | `enabled`, `index_on_write`, `cache_enabled`, `cache_size`, `default_limit`, `query_timeout_ms` | Persistent query indexes |
| `bsg.storage` | `enabled`, `backend`, `registry_path`, `content_scope`, `cloud_sync_ready`, `mmap_enabled`, `retention.*` | Durable artifact registry and retention |
| `hooks` | `enabled`, `include` | Git client-side hook automation pointer |

## Environment Variables (Common)

| Variable | Default | Description |
|----------|---------|-------------|
| `BATHO_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `BATHO_LOG_JSON` | `null` | Force JSON logs (`true`) or leave auto mode (`unset`) |
| `BATHO_LOG_QUIET` | `false` | Suppress non-error output globally |
| `BATHO_LOG_FILE` | unset | Optional log file path |
| `BATHO_CTN_DIR` | `.ctn` | Output directory |
| `BATHO_MAX_FILE_SIZE_KB` | `500` | Max file size to parse |
| `BATHO_MAX_INDEXED_FILES` | `200000` | Hard cap on indexed files |
| `BATHO_INDEX_WORKERS` | `0` | Worker threads (0 = auto) |
| `BATHO_METRICS_OUTPUT` | `.ctn/metrics.json` | Metrics output path |
| `BATHO_PLUGINS_ENABLED` | config value | `#/plugins` | BSG plugin catalog (Phase 4) |
| `BATHO_PLUGINS_CUSTOM_PLUGINS_PATH` | unset | YAML file containing custom BSG plugins |
| `BATHO_PLUGINS_BUILTIN_PLUGINS` | `bsg_core` | Comma-separated built-in plugin names |
| `BATHO_PLUGINS_DISABLED_PLUGINS` | unset | Comma-separated plugin names to disable |
| `BATHO_BSG_STORAGE_ENABLED` | `true` | Enable durable artifact registry |
| `BATHO_BSG_STORAGE_REGISTRY_PATH` | `.ctn/artifact_registry.db` | Registry database path |
| `BATHO_BSG_STORAGE_MMAP_ENABLED` | `false` | Enable mmap reads for large persisted JSON |
| `BATHO_BSG_QUERY_INDEX_ON_WRITE` | `true` | Build query index at write time |
| `BATHO_BSG_QUERY_CACHE_SIZE` | `256` | Query service cache size |

> For the complete env override set, see `batho/config.py`.

## Config File Example

```yaml
# ./batho.yaml
logging:
  level: DEBUG
  json_format: true
  quiet: false
  file: .ctn/batho.log
  format: "%(message)s"

indexer:
  max_file_size_kb: 1000
  max_workers: 16
  ignore_patterns:
    - "**/vendor/**"
    - "**/dist/**"

flags:
  strict: true
  fail_on_warning: true

rules:
  enabled: true
  builtin_plugins: [bsg_core]
  disabled_rules: []
  custom_rules_path: ./bsg-rules.yaml
  custom_rules_inline:
    - name: payment-cluster
      entity_types: ["function", "method"]
      name_patterns: ["*payment*", "*invoice*"]
      metadata:
        bsg.cluster_hint: billing

  # Validation controls
  strict_validation: false
  fail_on_rule_error: false

bsg:
  parallel:
    enabled: true
    max_workers: 16
    chunk_size: 50
  cache:
    enabled: true
    path: .ctn/local/cache/cache.db
    max_size_mb: 1024
    ttl_days: 30
  query:
    enabled: true
    index_on_write: true
    cache_enabled: true
    cache_size: 256
    default_limit: 200
  storage:
    enabled: true
    backend: sqlite
    registry_path: .ctn/artifact_registry.db
    content_scope: durable
    cloud_sync_ready: true
    mmap_enabled: false
    retention:
      enabled: true
      snapshot_ttl_days: 90
      patch_ttl_days: 90
      metrics_ttl_days: 30
      context_ttl_days: 90
```

## Scenario Playbooks

### 1) Local Dev (fast feedback)

```yaml
indexer:
  max_workers: 0
  max_file_size_kb: 500
bsg:
  incremental:
    enabled: true
  cache:
    enabled: true
```

```bash
batho index --root .
batho patch --root . --scan
batho bsg --root . --mode compressed --budget 12000
```
