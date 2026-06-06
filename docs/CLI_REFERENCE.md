# Batho CLI Reference

Complete reference for all Batho command-line commands, flags, and options.

---

## Global Usage

```bash
batho [command] [options]
```

**Entry point:** `batho_cli.py` → `main()` → subcommand dispatch

All commands accept:
- `--root <path>` — override repository root (defaults to current directory)
- `--verbose` / `-v` — enable verbose output (where supported)

**Exit codes** (consistent across all commands):

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Failure |
| `0` + warning | Success with non-fatal warnings (e.g., no changes detected) |

---

## `batho build` — Build Index

Parses all repository source files and builds the initial AST code graph database.

```bash
batho build [--root <path>] [--full] [--max-workers <N>] [--max-file-size-kb <KB>] [--verbose]
```

### Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--root <path>` | `str` | `.` (cwd) | Repository root directory |
| `--full` | flag | `false` | Force full rebuild — deletes existing `.batho/bsg/current/` before building |
| `--max-workers <N>` | `int` | 0 (auto) | Parallel worker processes. `0` = auto-scaled based on file count |
| `--max-file-size-kb <KB>` | `int` | `500` | Skip files larger than this (in KB) |
| `--verbose` | flag | `false` | Verbose logging output |

### Worker Auto-Scaling

| File Count | Workers |
|-----------|---------|
| ≤50       | 4       |
| ≤200      | 8       |
| ≤1000     | 16      |
| >1000     | min(32, cpu_count × 2) |

### Behavior

- **Guard**: If `.batho/bsg/current/` exists and `--full` is not specified, returns early with a warning. Use `batho patch` for incremental updates.
- **Phases**: A (validation) → B (config) → C (storage init) → D (dependency indexing) → E (graph build) → F (persistence) → G (BSG map) → H (finalization)

### Related Docs
- [BATHO_BUILD_FLOW.md](BATHO_BUILD_FLOW.md) — detailed phase documentation
- [EXTRACTION_MODULE_SPEC.md](EXTRACTION_MODULE_SPEC.md) — extraction pipeline
- [DEPENDENCY_MODULE_SPEC.md](DEPENDENCY_MODULE_SPEC.md) — CDEU dependency indexing

---

## `batho patch` — Incremental Patch

Scans for changed files since the last build/patch, re-parses only those files, and applies copy-on-write updates to the index.

```bash
batho patch [--root <path>] [--max-file-size-kb <KB>] [--verbose]
```

### Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--root <path>` | `str` | `.` (cwd) | Repository root directory |
| `--max-file-size-kb <KB>` | `int` | config default | Skip files larger than this |
| `--verbose` | flag | `false` | Verbose logging |

### Behavior

- Requires a prior `batho build` — fails with guidance if no bundle found
- Change detection: SHA256 hash comparison by default (`indexer.strict_hashing: true`)
- No changes → returns success with `"No changes detected"` warning
- Records node-level diffs into `file_changelog.ipc` (queryable via `batho diff`)

### Related Docs
- [ORCHESTRATOR_PATCH_SPEC.md](ORCHESTRATOR_PATCH_SPEC.md) — full patch flow documentation

---

## `batho export` — Export Views

Exports index data into structured JSON files. Supports 8 view types and a pack mode for CI/CD artifact handoff.

```bash
batho export [--view <view>] [--output <path>] [--filter <glob>] [--category <cat>]
             [--token-budget <N>] [--baseline <path>] [--rel] [--pack] [--format <fmt>]
             [--root <path>]
```

### Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--root <path>` | `str` | `.` (cwd) | Repository root directory |
| `--view <view>` | `str` | `storage` | View type (see below) |
| `--output <path>` | `str` | `<root>/batho_export.json` | Output file path |
| `--format <fmt>` | `json \| pretty` | `json` | JSON formatting |
| `--filter <glob>` | `str` | none | Glob pattern to filter files (e.g., `src/**/*.py`) |
| `--category <cat>` | `str` | `all` | Category filter (`source`, `test`, `doc`, `config`, `infra`, `all`) |
| `--token-budget <N>` | `int` | none | Max token budget for `agent` view |
| `--baseline <path>` | `str` | none | Baseline export file (required for `delta` view) |
| `--rel` | flag | `false` | Inject relationship list into any view output |
| `--pack` | flag | `false` | Produce transport ZIP (`artifact_<dir>.batho`) instead of JSON |

### View Types

| View | Description | Key Output Fields |
|------|-------------|-------------------|
| `storage` | Full-fidelity JSON with all entity metadata | `files[].entities[]` with full metadata |
| `agent` | Token-budget-capped LLM-optimized view | Compact entity list per file |
| `overview` | High-level summary | Language dist, category dist, entity type dist |
| `files` | Per-file listing | Entity counts, language, category, scope tier |
| `symbols` | Flat symbol index | `{id, name, type, file, line, signature}` per symbol |
| `dependencies` | Cross-file dependency graph | `dependencies[]` + `reverse_dependencies[]` |
| `delta` | Changed entities since baseline | `added`, `modified`, `removed`, `unchanged` |
| `rel` | Relationship graph + dependency map | Full relationship list |

### Pack Mode

```bash
batho export --pack [--output <zip_path>]
```

Produces `artifact_<sanitized-dir>.batho` ZIP for CI/CD artifact handoff. Consumed by `batho load`.

### Related Docs
- [ORCHESTRATOR_EXPORT_SPEC.md](ORCHESTRATOR_EXPORT_SPEC.md) — detailed view documentation
- [STORAGE_ENGINE.md](STORAGE_ENGINE.md) — Arrow IPC storage layout
- [CICD_INTEGRATION_GUIDE.md](CICD_INTEGRATION_GUIDE.md) — CI/CD pack/load workflow

---

## `batho fix` — Database Integrity Check

Performs multi-stage database verification and executes repair routines.

```bash
batho fix [--deep] [--dry-run] [--target <target>] [--phase <1-4>]
           [--parallel] [--format <fmt>] [--root <path>]
```

### Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--root <path>` | `str` | `.` (cwd) | Repository root directory |
| `--deep` | flag | `false` | Full validation — decompresses and validates all zstd blobs |
| `--dry-run` | flag | `false` | Diagnose issues without committing any repairs |
| `--target <target>` | `str` | `all` | Run only a specific checker |
| `--phase <1-4>` | `int` | all | Run only a specific verification phase |
| `--parallel` | flag | `false` | Run independent checks concurrently |
| `--format <fmt>` | `text \| json \| csv` | `text` | Report output format |

### Verification Targets

| Target | Phase | Checks |
|--------|-------|--------|
| `db` | 1 | Arrow IPC file format, schema version, table completeness |
| `state` | 2 | Run status consistency, orphan artifact detection |
| `blobs` | 3 | zstd payload decompression (requires `--deep` for full check) |
| `graph` | 4 | Dangling reference count, entity/relationship sync |
| `all` | all | All of the above |

### Related Docs
- [INTEGRITY_MODULE_SPEC.md](INTEGRITY_MODULE_SPEC.md) — integrity engine documentation

---

## `batho diff` — Node History

Queries granular node-level changes across runs, files, or specific symbols.

```bash
batho diff [--run <uuid>] [--entity <id>] [--file <rel_path>]
            [--since <uuid>] [--json] [--root <path>]
```

### Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--root <path>` | `str` | `.` (cwd) | Repository root directory |
| `--run <uuid>` | `str` | none | Show all node changes in a specific run |
| `--entity <entity_id>` | `str` | none | Full evolution history of a specific symbol |
| `--file <rel_path>` | `str` | none | All node-level changes in a file across all runs |
| `--since <uuid>` | `str` | none | Bounded history start (only with `--entity`) |
| `--json` | flag | `false` | Output as JSON instead of human-readable text |

### Change Kinds

| Kind | Description |
|------|-------------|
| `added` | Entity was introduced in this run |
| `removed` | Entity was deleted in this run |
| `modified` | Entity content/signature changed |
| `renamed` | Entity name changed but content hash matches |

### Data Source

`diff` reads from `file_changelog.ipc` which is written by `batho patch` and `batho build`. Each changelog entry records `(run_id, base_run_id, file_path, entity_id, change_kind, old_data, new_data)`.

---

## `batho gc` — Storage Maintenance

Manages database runs, prunes old history, and vacuums storage.

```bash
batho gc <subcommand> [options]
```

### Subcommands

#### `batho gc run <run_uuid>`
Delete a specific indexing run and all its file artifacts.

```bash
batho gc run abc123-...
```

**Cascade**: Removes run record from `runs.ipc`, all associated `agents/<file_id>.ipc` and `rels/<file_id>.ipc` files, and the run's `run_artifacts.ipc` entry.

#### `batho gc runs --older-than <days>`
Prune all runs older than the specified number of days.

```bash
batho gc runs --older-than 30
```

| Flag | Type | Description |
|------|------|-------------|
| `--older-than <days>` | `int` | Delete runs created more than N days ago |
| `--dry-run` | flag | Show what would be deleted without deleting |

#### `batho gc status`
Display storage metrics.

```bash
batho gc status
```

Output includes: total runs, total files indexed, entity count, relationship count, disk usage breakdown by directory.

#### `batho gc vacuum`
Compact Arrow IPC files and reclaim disk space.

```bash
batho gc vacuum
```

**Operations**: Compacts fragmented Arrow IPC files, removes orphan artifact files not referenced by any run, updates `manifest.json`.

### Related Docs
- [ORCHESTRATOR_GC_SPEC.md](ORCHESTRATOR_GC_SPEC.md) — GC implementation details
- [STORAGE_ENGINE.md](STORAGE_ENGINE.md) — Arrow IPC storage layout

---

## `batho load` — Load Transport Artifact

Ingests a `artifact_<dir>.batho` transport ZIP produced by `batho export --pack`.

```bash
batho load <zip_path> [--root <path>]
```

### Arguments

| Argument | Type | Description |
|----------|------|-------------|
| `<zip_path>` | `str` | Path to the `.batho` transport ZIP file |
| `--root <path>` | `str` | Target repository root (defaults to cwd) |

### Behavior

1. Validates ZIP contains `manifest.json` with correct `schema_version`
2. Decompresses `.ipc.zst` entries → plain `.ipc` files in `.batho/artifact/`
3. Reconstructs `.batho/bsg/current/` from `bsg/` entries in the ZIP
4. After loading, `batho patch` can be used to update the index incrementally

### CI/CD Pattern

```bash
# In CI: download artifact, load, then patch for incremental update
batho load artifact_myrepo.batho --root .
batho patch --root .
```

### Related Docs
- [ORCHESTRATOR_LOAD_SPEC.md](ORCHESTRATOR_LOAD_SPEC.md) — load implementation details
- [CICD_INTEGRATION_GUIDE.md](CICD_INTEGRATION_GUIDE.md) — full CI/CD workflow

---

## Environment Variables Quick Reference

| Variable | Config Path | Default | Description |
|----------|-------------|---------|-------------|
| `BATHO_LOG_LEVEL` | `logging.level` | `ERROR` | Log level: DEBUG, INFO, WARNING, ERROR |
| `BATHO_LOG_QUIET` | `logging.quiet` | `false` | Suppress all non-error output |
| `BATHO_LOG_JSON` | `logging.json_format` | `null` | Force JSON log format |
| `BATHO_LOG_FILE` | `logging.file` | `null` | Log to file |
| `BATHO_ARTIFACT_DIR` | `paths.artifact_dir` | `.batho/artifact` | Override artifact directory |
| `BATHO_MAX_FILE_SIZE_KB` | `indexer.max_file_size_kb` | `500` | Max file size to index |
| `BATHO_MAX_INDEXED_FILES` | `indexer.max_indexed_files` | `200000` | Hard cap on total files |
| `BATHO_INDEX_WORKERS` | `indexer.max_workers` | `0` | Worker count override |
| `BATHO_IGNORE_PATTERNS` | `indexer.ignore_patterns` | `[]` | Extra ignore patterns (comma-separated) |
| `BATHO_RULES_ENABLED` | `rules.enabled` | `true` | Enable/disable BSG rule plugins |
| `BATHO_RULES_DISABLED_RULES` | `rules.disabled_rules` | `[]` | Comma-separated rule IDs to skip |
| `BATHO_RULES_CUSTOM_RULES_PATH` | `rules.custom_rules_path` | `null` | Custom YAML plugin path |
| `BATHO_BSG_MAX_WORKERS` | `bsg.parallel.max_workers` | `16` | BSG parallel workers (1–32) |
| `BATHO_BSG_CACHE_ENABLED` | `bsg.cache.enabled` | `true` | AST disk cache toggle |
| `BATHO_BSG_BIDIRECTIONAL_ENABLED` | `bsg.bidirectional.enabled` | `true` | Bidirectional reconstruction |
| `BATHO_BSG_BIDIRECTIONAL_INCLUDE_GAPS` | `bsg.bidirectional.include_gaps` | `true` | SYNTAX_GLUE gap entities |

For the complete environment variable index, see [config.md](config.md#environment-variable-index).

---

## Configuration

All commands read `./batho.yaml` by default (auto-created with defaults if missing). Override with `BATHO_ARTIFACT_DIR` and other env vars.

See [config.md](config.md) for complete configuration documentation.

---

*Generated for Batho v1.1.0*
