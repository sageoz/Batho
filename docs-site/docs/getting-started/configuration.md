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

## Core Config Areas (`batho.yaml`)

The `batho.yaml` config is structured into the following sections:

### 1. `schema_version`
String identifier for configuration schema compatibility. For v1.2.0, this is `"batho-config.v1"`.

### 2. `logging`
Controls process-wide logging and CLI verbosity behavior.
- `level`: Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`).
- `json_format`: `true` for structured JSON logs, `false` for console logging, `null` to auto-detect.
- `quiet`: `true` to suppress non-error outputs.
- `file`: Path to an optional log file.
- `format`: Log format string.

### 3. `paths`
Controls artifact and cache locations.
- `db_path`: Base database directory path. Default is `.batho`.
- `cache_dir`: Shared cache directory for rules, dependencies, and AST caches. Default is `.batho/cache`.

### 4. `indexer`
Controls indexing limits and warning/strict levels.
- `max_file_size_kb`: Skip files exceeding this size (default: `500`).
- `max_indexed_files`: Hard cap on total indexed files (default: `200000`).
- `max_workers`: Max parallel workers for parsing (`0` = auto CPU count).
- `ignore_patterns`: List of gitignore-style glob patterns.
- `ignore_files`: Custom ignore files path.
- `default_patterns_file`: Custom patterns file path.
- `fail_on_warning`: Treat indexing warnings as failure.
- `strict`: Parse strictly, treating warnings as errors.

### 5. `graph`
Configures hypergraph consistency.
- `cycle_detection`:
  - `enabled`: Detect inheritance or import cycles.
  - `fatal`: If `true`, fails the build when a cycle is detected.
- `orphan_pruning`:
  - `enabled`: Remove nodes with no edges.
  - `keep_entry_points`: Do not prune program entry points.
  - `keep_exports`: Do not prune exported symbols.

### 6. `flags`
Top-level parser execution controls.
- `fail_on_warning`: Stop execution on warning.
- `strict`: Enable strict mode.
- `audit_log_enabled`: Write patch audit trails to `run_artifacts` in the database.

### 7. `dependency`
Consolidated Dependency Extraction Utility (CDEU) settings.
- `enabled`: Enable indexing of stdlib and third-party dependencies.
- `introspection`:
  - `enabled`: Introspect installed packages (e.g. from `.venv`).
  - `mode`: `shallow` (exports only) or `deep` (recursive).
  - `venv_auto_detect`: Find `.venv` directories automatically.
  - `timeout_seconds`: Timeout for introspecting one package.
  - `full_scan`: Scan all declared dependencies, not just popular packages.
  - `popular_packages_db_path`: Custom popular packages path.
- `stdlib`:
  - `enabled`: Index built-in language libraries.
  - `languages`: Languages to index (e.g., `["python", "javascript", "go", "rust"]`).
- `cache`:
  - `enabled`: Cache dependency lookups.
  - `ttl_days`: Days before dependency cache entries expire.
- `max_deps_per_manifest`: Limit on dependencies parsed per manifest file.

### 8. `artifact_blobs`
Fine-grained control over database size. Disable unused blobs to conserve disk space.
- `file_artifacts` (blobs written per file):
  - `bsg_agent_view`: LLM-optimized structural nodes.
  - `bsg_storage_view`: Full-fidelity delta blobs.
  - `bsg_rel_view`: Relationships array.
- `run_artifacts` (blobs written per run):
  - `context_overview`: Metadata summary.
  - `telemetry_metrics`: Timing and counts.
  - `structural_metrics`: LOC, fan-in/out, etc.
  - `security_audit`: Security rule violations.
  - `artifact_payload`: Minified LLM injection payload.
  - `delta_stats`: Churn and node diffs.

### 9. `rules`
Configures the BSG rule plugins engine.
- `enabled`: Enable semantic rule checks during indexing.
- `auto_load_all_plugins`: Auto-load all built-in rules.
- `builtin_plugins`: List of built-in plugins to run.
- `disabled_rules`: List of rules to explicitly disable.
- `custom_rules_path`: Path to an external YAML file with custom rules.
- `custom_rules_inline`: List of inline custom rules.
- `strict_validation`: Fail if a rule is invalid.
- `cache_ttl`: Cache time-to-live for rule evaluations.
- `fail_on_rule_error`: Fail build on rule execution error.

### 10. `plugins`
Overrides for individual plugin rules (e.g., setting a rule severity to `warning` or `error`).

### 11. `bsg`
Configures the Batho Structured Graph engine.
- `parallel`:
  - `enabled`: Enable parallel BSG rendering.
  - `max_workers`: Worker cap (1-32).
  - `chunk_size`: Files per chunk.
- `cache`:
  - `enabled`: Cache rendered BSGs.
  - `max_size_mb`: Memory limit.
  - `ttl_days`: Cache expiry.
- `symbol_resolution`:
  - `enabled`: Cross-file symbol mapping.
  - `cache_symbols`: Cache resolved targets.
- `parsing`:
  - `error_recovery`: Continue past tree-sitter parse errors.
  - `skip_comments`: Skip parsing comments.
- `bidirectional`:
  - `enabled`: Emit syntax glue for lossless byte-for-byte source reconstruction.
  - `include_gaps`: Emit `SYNTAX_GLUE` entities.
  - `verify_integrity`: Cryptographically check SHA-256 integrity on reconstruction.
  - `storage_view`: Keep raw content in the storage view.

### 12. `extraction`
Configures the AST parser cache.
- `cache`:
  - `enabled`: Cache parsed AST structures.
  - `ttl_days`: Expiry for AST entries.
  - `max_entries`: Max files in the cache.

---

## Environment Variables

Override settings on demand without changing your `batho.yaml` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `BATHO_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `BATHO_LOG_JSON` | `null` | Force JSON logs (`true`) or console (`false`) |
| `BATHO_LOG_QUIET` | `false` | Suppress non-error stdout outputs |
| `BATHO_LOG_FILE` | unset | Log file output destination |
| `BATHO_MAX_FILE_SIZE_KB` | `500` | Max file size to parse |
| `BATHO_MAX_INDEXED_FILES` | `200000` | Upper limit on file counts |
| `BATHO_INDEX_WORKERS` | `0` | Workers count (0 = auto CPU count) |
| `BATHO_PLUGINS_ENABLED` | `true` | Enable or disable rule plugins |
| `BATHO_PLUGINS_CUSTOM_PLUGINS_PATH` | unset | Custom rules file path override |
| `BATHO_PLUGINS_BUILTIN_PLUGINS` | config list | Comma-separated built-in plugin list |

---

## Scenario Playbooks

### 1) Local Dev Setup (Fast Iteration)

Configured for maximum AST caching and incremental patching:

```yaml
# ./batho.yaml
indexer:
  max_workers: 0
  max_file_size_kb: 500
bsg:
  cache:
    enabled: true
extraction:
  cache:
    enabled: true
```

Run CLI commands locally:
```bash
# Initialize database and build full graph
batho build --root .

# Apply incremental patches as files change
batho patch --root .

# Export light LLM-optimized agent view
batho export --root . --view agent --output bsg_agent.json
```
