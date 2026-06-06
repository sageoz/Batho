# Batho Storage Engine

Batho uses **Apache Arrow IPC** as its at-rest storage format. There are two independent storage subsystems:

| Subsystem | Class | Location | Format |
|-----------|-------|----------|--------|
| **Artifact store** | `BathoBundle` | `.batho/artifact/` (config: `paths.artifact_dir`) | Plain Arrow IPC File (`.ipc`) |
| **Graph store** | `BsgScratchStore` | `.batho/bsg/current/` (config: `paths.bsg_dir`) | Plain Arrow IPC File (`.ipc`) |

**Transport artifact** (produced by `batho export --pack`, consumed by `batho load`): a ZIP of zstd-compressed Arrow IPC stream files (`.ipc.zst`), one per table.

---

## 1. Directory Layout

```
<repo_root>/
  .batho/
    artifact/                 ← BathoBundle working dir
      manifest.json             — bundle schema version + table index
      runs.ipc                  — build run records
      file_tracking.ipc         — file metadata (mtime, hash, size, inode)
      file_changelog.ipc        — per-run file add/remove/modify log
      run_artifacts.ipc         — context overview, telemetry, security audit
      agents/
        <file_id>.ipc           — agent_view blob per indexed file
      rels/
        <file_id>.ipc           — relationship rows per indexed file
    bsg/
      current/                ← BsgScratchStore persistent graph
        entities.ipc            — all indexed entities (compacted)
        relationships.ipc       — all indexed relationships (compacted)
        entity_dict.ipc         — entity key → integer ID map
        dangling.ipc            — unresolved cross-file references (cleared post-build)
        meta.json               — run_uuid, run_internal_id, schema version
      _stream/                ← temporary flush buffers (auto-cleaned after compact)
        entities_<n>.ipc.zst    — streamed entity batches (IPC stream + zstd)
        relationships_<n>.ipc.zst
```

---

## 2. BathoBundle

**File:** `batho/modules/storage/arrow_bundle/bundle.py`

Entry point for all artifact-level reads and writes. Coordinates `BathoBundleManager` (writes) and `BathoBundleReader` (reads).

### Path Resolution

```python
from batho.modules.storage.arrow_bundle import resolve_bundle_dir

artifact_dir = resolve_bundle_dir(repo_root)
# → reads paths.artifact_dir from batho.yaml (default: root/.batho/artifact)
# → supports BATHO_ARTIFACT_DIR env override
```

### Key Methods

| Method | What |
|--------|------|
| `create_run(run_uuid, root_path, git_commit, git_branch)` | Inserts run row, returns `run_internal_id` |
| `insert_file_artifacts_batch(run_internal_id, batch_items)` | Writes agent/storage/rels blobs via `BathoBundleWriter` |
| `complete_run(run_uuid, entity_count, rel_count, file_count, duration_ms)` | Stamps `status='completed'` into `runs.ipc` |
| `get_file_artifacts(run_internal_id, ...)` | Reads and reconstructs file artifact dicts from IPC files |
| `get_latest_completed_run()` | Returns most recent `status='completed'` run record |
| `delete_run(run_uuid)` | Removes run and all its file artifacts |

### Concurrency

`BathoBundle` uses a single `threading.RLock` for all mutations. Reads are lock-free via `BathoBundleReader` + memory-mapped Arrow IPC files.

---

## 3. BathoBundleManager

**File:** `batho/modules/storage/arrow_bundle/manager.py`

Handles MVCC-style generation commits: writes to a temp file, then atomically replaces the active file.

### Commit Flow

```
write → <table>.tmp.ipc → commit_patch() → rename → <table>.ipc (active)
```

### Export / Load

| Method | What |
|--------|------|
| `export_artifact(zip_path)` | Reads all active `.ipc` files, zstd-compresses them, writes ZIP with `manifest.json` |
| `unpack_artifact(zip_path)` | Validates `schema_version` in manifest, decompresses `.ipc.zst` entries → writes plain `.ipc` files |

**Transport ZIP format:**
```
artifact_<dirname>.batho  (ZIP)
  manifest.json             — {"schema_version": "batho-bundle.v1", "tables": [...]}
  bsg/runs.ipc.zst          — zstd-compressed Arrow IPC stream
  bsg/file_tracking.ipc.zst
  bsg/file_changelog.ipc.zst
  bsg/run_artifacts.ipc.zst
  bsg/agents/<file_id>.ipc.zst
  bsg/rels/<file_id>.ipc.zst
```

---

## 4. BsgScratchStore

**File:** `batho/modules/storage/arrow_store/store.py`

Persistent graph store for entity and relationship data. Supports bulk writes via streaming flush + compaction.

### Initialization

```python
# Fresh build
store = BsgScratchStore(run_uuid=run_uuid, batho_dir=batho_dir, run_internal_id=run_internal_id)

# Patch (copy-on-write from previous run)
store, delta_store = BsgScratchStore.open_for_patch(
    batho_dir=batho_dir,
    new_run_uuid=run_uuid,
    new_run_internal_id=run_internal_id,
    changed_paths=changed_file_paths,
    db=bundle,
)

# Read-only (integrity check, metrics)
store = BsgScratchStore.from_run_dir(current_dir, run_internal_id=0)
```

### Write Path

Large builds use a streaming write strategy to bound memory usage:

```
append_entities() / append_relationships()
    │
    ├─ buffer < FLUSH_THRESHOLD (100,000 rows) → hold in memory
    │
    └─ buffer >= FLUSH_THRESHOLD → flush to _stream/<table>_<n>.ipc.zst
                                       (Arrow IPC stream + zstd)
                                       │
                                       └─ compact() → merge all _stream/ files
                                                       + existing current/*.ipc
                                                       → new current/*.ipc
                                                       (plain Arrow IPC File, memory-mappable)
```

### File Format: `.ipc` vs `.ipc.zst`

| Suffix | Format | Where used | Purpose |
|--------|--------|-----------|---------|
| `.ipc` | Arrow IPC **File** | `bsg/current/`, `artifact/*.ipc` | At-rest persistent storage — supports memory-mapped zero-copy reads |
| `.ipc.zst` | Arrow IPC **Stream** + zstd | `bsg/_stream/`, transport ZIP | Intermediate flush buffers and transport — compact but requires decompression |

### Key Methods

| Method | What |
|--------|------|
| `append_entities(tuples)` | Buffer entity rows; auto-flush to `_stream/` at threshold |
| `append_relationships(tuples)` | Buffer relationship rows; auto-flush at threshold |
| `append_dangling(tuples)` | Buffer unresolved cross-file references |
| `compact()` | Merge all `_stream/` files into final `current/*.ipc` plain files |
| `resolve_dangling(db)` | Resolve `dangling.ipc` entries against entity dict; emit resolved relationships |
| `bulk_get_or_create_entity_keys(keys)` | Batch entity key → integer ID map lookup/insert |

### Arrow Schemas

Defined in `batho/modules/storage/arrow_store/schemas.py`:

```python
ENTITY_DICT_SCHEMA   # entity_key (str), entity_id (int64)
ENTITIES_SCHEMA      # entity_id, entity_type, file_id, start_line, end_line, ...
RELATIONSHIPS_SCHEMA # source_id, target_id, relationship_type, file_id, ...
DANGLING_SCHEMA      # source_id, target_name (str), relationship_type, file_id, ...
```

---

## 5. IncrementalEngine — Change Detection

**File:** `batho/modules/storage/arrow_bundle/incremental.py`

Tracks which files have changed since the last build or patch. Reads and writes the `file_tracking.ipc` table.

```python
Incremental Engine(db, base_run_uuid)
changes = engine.scan_changes(
    root=root,
    max_file_size_kb=max_file_size_kb,
    strict_hashing=True,  # config: indexer.strict_hashing
)
```

### Key Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `scan_changes(root, max_file_size_kb, strict_hashing)` | `list[FileChange]` | Compare filesystem vs `file_tracking.ipc` to detect added/modified/deleted files |
| `update_state(fingerprints)` | `None` | Write new fingerprints to `file_tracking.ipc` after re-parsing |
| `handle_deleted_files(deleted_paths)` | `None` | Remove tracking records for deleted files |

### Detection Modes

| Mode | Trigger | Algorithm |
|------|---------|----------|
| **Strict** | `indexer.strict_hashing: true` (default) | Full SHA256 content hash comparison — catches all content changes |
| **Fast** | `indexer.strict_hashing: false` | `mtime_ns + inode + size` — faster but can miss edits that restore original mtime |

### `FileChange` Dataclass

| Field | Type | Description |
|-------|------|-------------|
| `path` | `str` | Relative file path (relative to root — never absolute) |
| `change_type` | `str` | `"added"`, `"modified"`, or `"deleted"` |
| `old_hash` | `str \| None` | Previous content hash |
| `new_hash` | `str \| None` | New content hash |

**Key invariant**: `FileChange.path` must always be a relative path. Absolute paths raise `ValueError` in `orchestrator/patch.py`.

---

## 6. BathoCache (Unified Cache)

**File:** `batho/modules/storage/cache/unified_cache.py`

`BathoCache` is the unified cache facade used by extraction pipeline workers. It combines the disk-based `AstCache` (for parsed AST results) with the dependency `ResolutionCache` under a single API.

```python
BathoCache(
    cache_path: str,                     # legacy path (for compatibility)
    ast_cache_dir: str | None = None,    # directory for AstCache (.batho/cache/ast/)
)
```

### Key Methods

| Method | Delegates To | Description |
|--------|-------------|-------------|
| `get_ast(file_path, content_hash, variant)` | `AstCache.get_ast()` | Read parsed entities/relationships from disk cache |
| `set_ast(file_path, content_hash, variant, entities, rels, mtime, size, ttl_days)` | `AstCache.set_ast()` | Write parsed results to disk cache |
| `delete_ast_by_path(rel_path)` | `AstCache.delete_ast()` | Invalidate all AST cache entries for a file path |
| `delete_ast_prefix(path_prefix)` | `AstCache.delete_by_path_prefix()` | Batch invalidation by path prefix |

### Cache Initialization in Workers

Worker processes call `_initialize_worker(..., ast_cache_dir)` which creates a `BathoCache` per process:

```python
# In multiprocessing worker initialization:
_WORKER_CACHE = BathoCache(cache_path, ast_cache_dir=ast_cache_dir)
```

This ensures each worker has its own cache handle while reading the same shared disk cache directory.

---

## 7. Arrow Schema Tables

All Arrow IPC tables use fixed schemas defined in `batho/modules/storage/arrow_store/schemas.py` and `batho/modules/storage/arrow_bundle/schemas.py`.

### `runs.ipc` Schema

| Column | Type | Description |
|--------|------|-------------|
| `run_uuid` | `utf8` | Unique run identifier (e.g., `build_1234567890_abc12345`) |
| `root_path` | `utf8` | Absolute repository root path |
| `status` | `utf8` | `in_progress`, `completed`, `failed` |
| `started_at` | `utf8` | ISO 8601 timestamp |
| `completed_at` | `utf8 \| null` | ISO 8601 timestamp |
| `git_commit` | `utf8 \| null` | Git HEAD commit hash |
| `git_branch` | `utf8 \| null` | Git branch name |
| `entity_count` | `int64` | Total entities indexed |
| `rel_count` | `int64` | Total relationships indexed |
| `file_count` | `int64` | Total files indexed |
| `duration_ms` | `int64` | Build duration in milliseconds |
| `error_message` | `utf8 \| null` | Error message if `status='failed'` |

### `file_tracking.ipc` Schema

| Column | Type | Description |
|--------|------|-------------|
| `file_path` | `utf8` | Relative file path (key for change detection) |
| `content_hash` | `utf8` | SHA256 of file content |
| `mtime` | `float64` | File mtime (seconds since epoch) |
| `mtime_ns` | `int64` | File mtime in nanoseconds |
| `inode` | `int64 \| null` | File inode number |
| `size` | `int64` | File size in bytes |
| `is_indexed` | `int8` | `1` = has AST entities; `0` = opaque/unindexed |
| `last_run_id` | `utf8` | UUID of the run that last indexed this file |
| `encoding` | `utf8` | File encoding (typically `utf-8`) |

### `file_changelog.ipc` Schema

| Column | Type | Description |
|--------|------|-------------|
| `run_uuid` | `utf8` | Run in which the change was recorded |
| `base_run_uuid` | `utf8` | Previous run UUID being compared against |
| `file_path` | `utf8` | Relative file path |
| `entity_id` | `utf8` | Entity ID that changed |
| `change_kind` | `utf8` | `added`, `removed`, `modified`, `renamed` |
| `old_data` | `utf8 \| null` | JSON-serialized previous entity (agent view) |
| `new_data` | `utf8 \| null` | JSON-serialized new entity (agent view) |
| `recorded_at` | `utf8` | ISO 8601 timestamp |

### `run_artifacts.ipc` Schema

Stores JSON-serialized payloads (one row per run per artifact type):

| Column | Type | Description |
|--------|------|-------------|
| `run_uuid` | `utf8` | Run identifier |
| `artifact_type` | `utf8` | `context_overview`, `telemetry_metrics`, `structural_metrics`, `security_audit`, `artifact_payload`, `delta_stats` |
| `payload` | `utf8` | JSON-encoded artifact payload |
| `created_at` | `utf8` | ISO 8601 timestamp |

### BSG Store Schemas (from `arrow_store/schemas.py`)

| Schema | Key Columns |
|--------|-------------|
| `ENTITY_DICT_SCHEMA` | `entity_key (utf8)`, `entity_id (int64)` |
| `ENTITIES_SCHEMA` | `entity_id (int64)`, `entity_type (utf8)`, `file_id (utf8)`, `start_line (int32)`, `end_line (int32)`, `entity_key (utf8)` |
| `RELATIONSHIPS_SCHEMA` | `source_id (int64)`, `target_id (int64)`, `relationship_type (utf8)`, `file_id (utf8)`, `confidence (float32)` |
| `DANGLING_SCHEMA` | `source_id (int64)`, `target_name (utf8)`, `relationship_type (utf8)`, `file_id (utf8)` |

---

## 8. Export / Load Cycle (CI/CD)

```
batho build / patch
    └─ produces: .batho/artifact/*.ipc + .batho/bsg/current/*.ipc

batho export --pack
    └─ BathoBundleManager.export_artifact(zip_path, bsg_current_dir)
    └─ produces: artifact_<dirname>.batho (ZIP of .ipc.zst files)

[upload artifact_*.batho to CI artifact store]

[next run: download artifact_*.batho]

batho load artifact_*.batho
    └─ BathoBundleManager.unpack_artifact(zip_path)
    └─ validates schema_version in manifest.json
    └─ decompresses .ipc.zst → writes plain .ipc to .batho/artifact/
    └─ reconstructs .batho/bsg/current/ from bsg/ entries

batho patch
    └─ BsgScratchStore.open_for_patch(...)
    └─ IncrementalEngine.scan_changes()
    └─ re-parses only changed files
```

For the full CI/CD workflow, see [CICD_INTEGRATION_GUIDE.md](CICD_INTEGRATION_GUIDE.md).

---

## 9. Integrity Checking

**File:** `batho/modules/integrity/checkers/graph_checker.py`

`GraphIntegrityChecker` reads `bsg/current/` via `BsgScratchStore.from_run_dir()` and checks:

- Dangling reference count in `dangling.ipc` (warning if > 0)
- Entity/relationship sync between Arrow store and bundle (`--deep` flag)

Repairs are handled by `GraphRepairer.repair_dangling()` which calls `store.resolve_dangling(db)`.

For the full integrity module documentation, see [INTEGRITY_MODULE_SPEC.md](INTEGRITY_MODULE_SPEC.md).

---

## 10. Metrics

**File:** `batho/modules/storage/arrow_store/metrics.py`

Reads `entities.ipc` and `relationships.ipc` from `bsg/current/` for metric aggregation. Uses Arrow compute functions for efficient column operations (no Python loops over rows).

Metrics are produced by `_compute_run_metrics()` in `orchestrator/build.py` and stored in `run_artifacts.ipc` under the `structural_metrics` and `context_overview` artifact types.

---

## 11. Storage GC and Maintenance

**File:** `batho/orchestrator/gc.py`

The `batho gc` command manages artifact lifecycle:

| Subcommand | Operation |
|------------|----------|
| `batho gc run <uuid>` | Delete a specific run and all its IPC files |
| `batho gc runs --older-than <days>` | Prune old runs by date |
| `batho gc vacuum` | `db.garbage_collect()` — removes orphaned Arrow IPC generations |
| `batho gc orphans` | Same as vacuum — sweeps stale IPC files |
| `batho gc status` | Display size metrics from `db.get_stats()` |

For the full GC documentation, see [ORCHESTRATOR_GC_SPEC.md](ORCHESTRATOR_GC_SPEC.md).

---

*Updated for Batho v1.1.0 — added IncrementalEngine (§5), BathoCache (§6), Arrow schema tables (§7), GC section (§11)*
