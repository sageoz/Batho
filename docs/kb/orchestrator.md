# Module: `batho.orchestrator`

## Overview

The `batho.orchestrator` package is the **primary dispatch layer** for Batho's three data-mutation CLI commands: `build`, `patch`, and `export`. Each sub-module encapsulates all business logic for one command — validating inputs, driving the parsing pipeline, persisting results to the SQLite artifact database, computing run metrics, and returning a typed result dataclass. No UI or CLI argument parsing lives here; the orchestrators receive strongly typed `*Options` dataclasses from the CLI layer and return `*Result` dataclasses back. This strict boundary makes the orchestrators independently testable and reusable from non-CLI callers (e.g., API servers, test harnesses).

---

## Files Covered

| Filename | Size (bytes) | Purpose |
|---|---|---|
| `__init__.py` | 349 | Re-exports `ExportOptions`, `ExportResult`, `run_export`, `PatchOptions`, `PatchResult`, `run_patch` as the public surface of the package. `BuildOptions`/`BuildResult`/`run_build` are **not** re-exported here (build.py is imported directly by the CLI). |
| `build.py` | 21 192 | Full-index build orchestrator (`batho build`). Drives `CodeGraphIndexer`, `BSGMap`, batch file-artifact writes, file tracking, cross-file reference resolution, and run-metrics finalization. |
| `patch.py` | 22 746 | Incremental patch orchestrator (`batho patch`). Hash-based filesystem change detection, copy-on-write blob propagation for unchanged files, per-file re-parse, node-level diffing, and delta stats. |
| `export.py` | 18 802 | Export orchestrator (`batho export`). Loads a `BSGMap` from the artifact DB, applies glob/category filters, dispatches to one of eight view renderers, serializes to JSON, and writes output. |
| `gc.py` | ~5 000 | GC orchestrator (`batho gc`). Garbage collection for old runs, vacuum for SQLite optimization, storage status reporting. |

---

## Classes & Functions

### `__init__.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `ExportOptions` | TypeAlias (re-export) | Public re-export from `export.py` | export | ✅ Used |
| `ExportResult` | TypeAlias (re-export) | Public re-export from `export.py` | export | ✅ Used |
| `run_export` | function (re-export) | Public re-export from `export.py` | export | ✅ Used |
| `PatchOptions` | TypeAlias (re-export) | Public re-export from `patch.py` | patch | ✅ Used |
| `PatchResult` | TypeAlias (re-export) | Public re-export from `patch.py` | patch | ✅ Used |
| `run_patch` | function (re-export) | Public re-export from `patch.py` | patch | ✅ Used |

> **Note:** `BuildOptions`, `BuildResult`, and `run_build` are intentionally absent from `__all__`. The build CLI imports directly from `batho.orchestrator.build`.

---

### `build.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `BuildOptions` | dataclass | Input parameters for a build run (`root`, `force_full`, `verbose`, `max_workers`, `max_file_size_kb`) | build | ✅ Used |
| `BuildResult` | dataclass | Outcome of a build run — counts, timing, warnings, snapshot ID | build | ✅ Used |
| `run_build` | function | Main build orchestrator; entry point from `cmd_build()` | build | ✅ Used |
| `_generate_run_id` | function | Generates `build_<timestamp>_<8hex>` unique run identifier | build | ✅ Used |
| `_compute_run_metrics` | function | Queries DB for entity/relationship/file stats and assembles `context_overview`, `structural_metrics`, and `artifact_payload` dicts for `finalize_run_artifacts` | build, patch | ✅ Used |
| `_build_file_tracking` | function | Iterates over graph entities and unindexed files to produce `file_tracking` records (path, hash, mtime, size, encoding, `is_indexed`) | build | ✅ Used |

#### Class Diagram

```mermaid
classDiagram
    class BuildOptions {
        +Path root
        +bool force_full
        +bool verbose
        +int|None max_workers
        +int|None max_file_size_kb
    }

    class BuildResult {
        +bool success
        +str run_id
        +int entity_count
        +int relationship_count
        +int file_count
        +int bsg_file_count
        +str snapshot_id
        +int duration_ms
        +list~str~ warnings
    }

    class PatchOptions {
        +Path root
        +bool verbose
        +int|None max_file_size_kb
    }

    class PatchResult {
        +bool success
        +str run_id
        +str base_snapshot_id
        +str new_snapshot_id
        +int changes_applied
        +int added
        +int modified
        +int deleted
        +int entity_count
        +int relationship_count
        +int duration_ms
        +list~str~ warnings
        +int nodes_added
        +int nodes_removed
        +int nodes_modified
        +int nodes_renamed
    }

    class ExportOptions {
        +Path root
        +str view
        +Path|None output
        +str format
        +str|None filter_pattern
        +str category
        +str|None index_id
        +int|None token_budget
        +Path|None baseline_path
        +bool include_relationships
    }

    class ExportResult {
        +bool success
        +int entity_count
        +int file_count
        +Path|None output_path
        +Iterator~str~|None stream_generator
        +list~str~ errors
    }

    class FileChange {
        +str path
        +str change_type
        +str|None old_hash
        +str|None new_hash
    }

    class FileChangeType {
        +ADDED = "added"
        +MODIFIED = "modified"
        +DELETED = "deleted"
    }

    FileChange --> FileChangeType : uses
```

#### Call-Flow Flowchart — `batho build`

```mermaid
flowchart TD
    A["cmd_build()"] --> B["run_build(BuildOptions)"]
    B --> B1{"root exists\n& is dir?"}
    B1 -- No --> B1E["return BuildResult(success=False)"]
    B1 -- Yes --> B2["set_active_root(root)"]
    B2 --> B3{"db_path exists\n& not force_full?"}
    B3 -- Yes --> B3W["return BuildResult(success=True, warning='already_built')"]
    B3 -- No --> B4["force_full → unlink existing DB"]
    B4 --> B5["get_config_cached()\nresolve max_file_size_kb, BSG config"]
    B5 --> B6["BathoDatabase(db_path)\ndb.create_run(run_uuid, git info)"]
    B6 --> B7["CodeGraphIndexer.build_graph(root, max_workers, ...)"]
    B7 --> B8{"entity_count == 0?"}
    B8 -- Yes --> B8E["db.fail_run()\nreturn BuildResult(success=False)"]
    B8 -- No --> B9["apply_rule_plugins(graph)"]
    B9 --> B10["indexer.get_unindexed_files()\nbuild opaque_snapshots list"]
    B10 --> B11["BSGMap.build(graph, root, opaque_snapshots)"]
    B11 --> B12["Group entities & rels by file\nbuild agent_view + storage_delta dicts"]
    B12 --> B13["db.insert_file_artifacts_batch()\nin chunks of 50 files"]
    B13 --> B14["db.resolve_dangling_references(run_id)"]
    B14 --> B15["_build_file_tracking(graph, indexer)\ndb.upsert_file_tracking()"]
    B15 --> B16["db.complete_run(run_uuid, counts)"]
    B16 --> B17["_compute_run_metrics(db, run_id, root)"]
    B17 --> B18["db.finalize_run_artifacts(context_overview,\ntelemetry, structural, artifact_payload)"]
    B18 --> B19["return BuildResult(success=True, counts, duration)"]
```

---

### `patch.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `FileChangeType` | class | Namespace constants for change classification: `ADDED`, `MODIFIED`, `DELETED` | patch | ✅ Used |
| `FileChange` | dataclass | Represents a single file change (path, change_type, old_hash, new_hash) | patch | ✅ Used |
| `PatchOptions` | dataclass | Input parameters for a patch run (`root`, `verbose`, `max_file_size_kb`) | patch | ✅ Used |
| `PatchResult` | dataclass | Outcome of a patch run — counts, timing, node-level diff stats, warnings | patch | ✅ Used |
| `_generate_run_id` | function | Generates `patch_<timestamp>_<8hex>` unique run identifier | patch | ✅ Used |
| `_hash_scan_changes` | function | Filesystem scan comparing known file-tracking records against current disk state; produces a list of `FileChange` objects. Uses mtime+size as cheap pre-filter before hashing. | patch | ✅ Used |
| `run_patch` | function | Main patch orchestrator; entry point from `cmd_patch()` | patch | ✅ Used |

#### Call-Flow Flowchart — `batho patch`

```mermaid
flowchart TD
    A["cmd_patch()"] --> B["run_patch(PatchOptions)"]
    B --> B1{"root exists\n& is dir?"}
    B1 -- No --> B1E["return PatchResult(success=False)"]
    B1 -- Yes --> B2["set_active_root(root)\nget_database(root)"]
    B2 --> B3{"db_path exists?"}
    B3 -- No --> B3E["return PatchResult(success=False, 'run batho build')"]
    B3 -- Yes --> B4["db.get_latest_run_id() → base_run_uuid\ndb.get_run_internal_id(base_run_uuid)"]
    B4 --> B5["db.get_all_file_tracking() → known_tracking"]
    B5 --> B6["_hash_scan_changes(root, known_tracking)\n(mtime+size pre-filter, hash on change)"]
    B6 --> B7{"changes list\nempty?"}
    B7 -- Yes --> B7W["return PatchResult(success=True, 'no changes')"]
    B7 -- No --> B8["db.create_run(patch_uuid, git info)\n→ run_internal_id"]
    B8 --> B9["Copy-on-write: SQL INSERT file_artifacts\nfor unchanged files from base run\nalso copy query_entities for unchanged files"]
    B9 --> B10["Split changes: added_or_modified vs deleted"]
    B10 --> B11["For each added/modified file:\nCodeGraphIndexer.build_graph(file_list=[file])"]
    B11 --> B12["BSGMap.build(single_graph)\nbuild agent_view + storage_delta dicts"]
    B12 --> B13["Append to write_batch\nFlush batch at 50 files →\ndb.insert_file_artifacts_batch()"]
    B13 --> B14["diff_file_nodes(old_entities, new_entities)\ndb.record_file_changelog(node_diffs)"]
    B14 --> B15["For deleted files:\ndb.delete_file_tracking(path)\ndiff_file_nodes(old_entities, [])"]
    B15 --> B16["db.upsert_file_tracking(added/modified)"]
    B16 --> B17["db.resolve_dangling_references(run_id)"]
    B17 --> B18["db.complete_run(patch_uuid, counts)"]
    B18 --> B19["_compute_run_metrics(db, run_id, root)\nbuild delta_stats dict"]
    B19 --> B20["db.finalize_run_artifacts(context_overview,\ntelemetry, delta_stats, ...)"]
    B20 --> B21["db.prune_file_changelog(max_runs)"]
    B21 --> B22["return PatchResult(success=True,\nadded/modified/deleted/node diff counts)"]

    B -- exception --> EX["db.fail_run(run_uuid)\nreturn PatchResult(success=False, exception)"]
```

---

### `export.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `ExportOptions` | dataclass | Input parameters for an export run (view, output, format, filter_pattern, category, index_id, token_budget, baseline_path, include_relationships) | export | ✅ Used |
| `ExportResult` | dataclass | Outcome of an export run (entity_count, file_count, output_path, errors) | export | ✅ Used |
| `VALID_VIEWS` | constant | Frozenset of allowed view names: `storage`, `agent`, `overview`, `files`, `symbols`, `dependencies`, `delta`, `rel` | export | ✅ Used |
| `VALID_CATEGORIES` | constant | Frozenset of allowed category filters: `source`, `test`, `doc`, `config`, `infra`, `all` | export | ✅ Used |
| `run_export` | function | Main export orchestrator; entry point from `cmd_export()` | export | ✅ Used |
| `_find_db_path` | function | Locates the `artifact_<dirname>.batho` file for the given root path | export | ✅ Used |
| `_load_bsg_map_from_db` | function | Loads file artifacts from the DB, reconstructs `by_file` entity map, relationships, and dependency graph; builds and returns a `BSGMap` instance | export | ✅ Used |
| `_apply_filters` | function | Applies optional glob `pattern` and `category` filters to a `BSGMap`; returns a new filtered `BSGMap` | export | ✅ Used |
| `_resolve_file_category` | function | Determines a file's category string (`SOURCE`, `TEST`, `CONFIG`, `DOC`, `INFRA`) from entity metadata or path heuristics | export | ✅ Used |
| `_generate_view` | function | Dispatcher — routes view name to the appropriate renderer; injects `relationships` blob if `include_relationships` is set | export | ✅ Used |
| `_generate_symbols_view` | function | Produces a flat symbol-index JSON view (`symbols` view type) | export | ✅ Used |
| `_generate_dependencies_view` | function | Produces a dependency graph JSON view with forward and reverse dependency edges (`dependencies` view type) | export | ✅ Used |
| `_generate_delta_view` | function | Loads a baseline export JSON file, calls `BSGMap.render_delta()`, and serializes the diff (`delta` view type) | export | ✅ Used |
| `_generate_relationships_view` | function | Produces a combined relationship + dependency JSON view (`rel` view type) | export | ✅ Used |
| `_serialize` | function | Converts a dict to compact or pretty-printed JSON string | export | ✅ Used |
| `_write_output` | function | Writes serialized JSON content to a file (creates parent directories as needed) | export | ✅ Used |

#### Call-Flow Flowchart — `batho export`

```mermaid
flowchart TD
    A["cmd_export()"] --> B["run_export(ExportOptions)"]
    B --> B1{"root exists\n& is dir?"}
    B1 -- No --> B1E["return ExportResult(success=False)"]
    B1 -- Yes --> B2["set_active_root(root)\nresolve output_path"]
    B2 --> B3{"view in\nVALID_VIEWS?"}
    B3 -- No --> B3E["return ExportResult(success=False, 'unknown view')"]
    B3 -- Yes --> B4{"category in\nVALID_CATEGORIES?"}
    B4 -- No --> B4E["return ExportResult(success=False, 'unknown category')"]
    B4 -- Yes --> B5["_find_db_path(root)\nlocate artifact_*.batho"]
    B5 --> B5A{"db found?"}
    B5A -- No --> B5E["return ExportResult(success=False, 'run batho build')"]
    B5A -- Yes --> B6["_load_bsg_map_from_db(db_path, index_id)"]
    B6 --> B6A{"bsg_map\nis None?"}
    B6A -- Yes --> B6E["return ExportResult(success=False, 'no BSG entries')"]
    B6A -- No --> B7["_apply_filters(bsg_map, filter_pattern, category)"]
    B7 --> B8["_generate_view(bsg_map, view, options)"]

    B8 --> V1["view='storage' →\nbsg_map.render_storage_view()"]
    B8 --> V2["view='agent' →\nbsg_map.render_agent_view(token_budget)"]
    B8 --> V3["view='overview' →\nbsg_map.render_overview_json()"]
    B8 --> V4["view='files' →\nbsg_map.render_files_json()"]
    B8 --> V5["view='symbols' →\n_generate_symbols_view()"]
    B8 --> V6["view='dependencies' →\n_generate_dependencies_view()"]
    B8 --> V7["view='delta' →\n_generate_delta_view(baseline_path)"]
    B8 --> V8["view='rel' →\n_generate_relationships_view()"]

    V1 & V2 & V3 & V4 & V5 & V6 & V7 & V8 --> B9{"include_relationships\n& view != 'rel'?"}
    B9 -- Yes --> B9A["inject 'relationships' blob into data dict"]
    B9 -- No --> B10

    B9A --> B10["_serialize(data, format)\njson.dumps compact or pretty"]
    B10 --> B11["_write_output(content, output_path)"]
    B11 --> B12["return ExportResult(success=True,\nentity_count, file_count, output_path)"]
```

---

## Unused Symbols Summary

All symbols in this module are reachable from the CLI. No unused symbols were identified:

- `_generate_run_id` in both `build.py` and `patch.py` — called directly inside `run_build` / `run_patch`.
- `_compute_run_metrics` in `build.py` — called by both `run_build` (build.py) and `run_patch` (patch.py, imported explicitly: `from batho.orchestrator.build import _compute_run_metrics`).
- `_build_file_tracking` in `build.py` — called inside `run_build`.
- `_hash_scan_changes` in `patch.py` — called inside `run_patch`.
- `FileChangeType` / `FileChange` in `patch.py` — used throughout `_hash_scan_changes` and `run_patch`.
- All helpers in `export.py` (`_find_db_path`, `_load_bsg_map_from_db`, `_apply_filters`, `_resolve_file_category`, `_generate_view`, `_generate_symbols_view`, `_generate_dependencies_view`, `_generate_delta_view`, `_generate_relationships_view`, `_serialize`, `_write_output`) — all called from `run_export`.
- `VALID_VIEWS` / `VALID_CATEGORIES` — used as validation sets in `run_export`.

> **Note on `ExportResult.stream_generator`:** The field is declared in `ExportResult` (type `Iterator[str] | None`) but is never populated by `run_export` in the current implementation. The streaming path was likely planned but not yet implemented. This field is **effectively dead code** in v1.1.0.

---

## Cross-Module Notes

### Copy-on-Write Design in `patch.py`
The patch orchestrator implements a **blob-level copy-on-write** strategy to avoid re-parsing unchanged files:
1. Unchanged file artifacts are bulk-copied from the base run via SQL `INSERT ... SELECT` (excluding changed file IDs).
2. `query_entities` rows for unchanged files are similarly copied, filtered by file path.
3. Only files in `added_or_modified` are re-parsed through `CodeGraphIndexer`.

This means the new run's `file_artifacts` table contains a complete, self-consistent snapshot without re-processing the entire codebase.

### Batch Write Strategy (Both `build.py` and `patch.py`)
Both orchestrators accumulate file artifacts into a `write_batch` list and flush to DB when the batch reaches **50 files** (via `db.insert_file_artifacts_batch()`). This amortizes SQLite transaction overhead over many files while keeping memory use bounded.

### `_compute_run_metrics` is Shared
`patch.py` imports `_compute_run_metrics` directly from `batho.orchestrator.build`, making it a shared utility despite being defined in `build.py`. Both commands produce identical context_overview / structural_metrics / artifact_payload JSON blobs for their run artifacts.

### View Router in `export.py`
The `_generate_view` function acts as a **strategy dispatcher** — the `view` string (one of 8 valid values) selects a renderer. The `rel` view returns early before the `include_relationships` injection step, since it already contains the full relationship blob natively.

### GC Command (`batho gc`)
The `gc` orchestrator provides storage maintenance:
- `gc run <run_uuid>` — deletes specific run and all artifacts
- `gc runs --older-than N` — deletes runs older than N days
- `gc vacuum` — runs SQLite VACUUM to reclaim disk space
- `gc status` — shows storage statistics (db size, run count, artifact counts)

Uses the wired-up deletion methods in `BathoDatabase` (`delete_run`, `delete_file_artifacts_for_run`, `delete_snapshots_for_run`, etc.).

### Git Metadata is Informational Only
Both `build.py` and `patch.py` query `is_git_repo()`, `get_head_commit()`, and `get_current_branch()` to attach git context to the run record. However, **change detection in `patch.py` is entirely hash-based** (via `_hash_scan_changes`). Git is not used for diff computation — the docstring explicitly states: *"Git is no longer used for change detection; it is only captured for metadata."*
