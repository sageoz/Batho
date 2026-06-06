# Batho Storage Management (GC) Specification

Batho's garbage-collection subsystem (`batho gc`) provides housekeeping operations for the Arrow IPC artifact store. It can delete individual runs, prune runs older than a given age, vacuum orphaned IPC files, and report storage metrics. All operations are coordinated by the `run_gc()` function in `batho/orchestrator/gc.py`, which is exposed to the CLI through `batho/cli/gc.py`.

---

## 1. Overview

| Layer | File | Responsibility |
|-------|------|---------------|
| CLI adapter | `batho/cli/gc.py` | Argument parsing, exit-code mapping |
| Orchestrator | `batho/orchestrator/gc.py` | Command dispatch, bundle interaction |
| Storage | `batho/modules/storage/arrow_bundle/` | Run/artifact deletion, GC, stats |

The orchestrator always resolves `root` to an absolute path and validates that:
1. The repository root directory exists.
2. A `meta.json` sentinel is present inside the resolved `bundle_dir`, confirming an active artifact bundle.

---

## 2. `GCOptions` Dataclass

**File:** `batho/orchestrator/gc.py`

```python
@dataclass
class GCOptions:
    root: Path           # Repository root path (resolved to absolute)
    command: str         # Subcommand: "run" | "runs" | "vacuum" | "orphans" | "status"
    run_uuid: str | None = None   # Required for "run" subcommand
    older_than: int | None = None # Required for "runs" subcommand (days)
    verbose: bool = False
```

| Field | Type | Description |
|-------|------|-------------|
| `root` | `Path` | Repository root — must exist and be a directory |
| `command` | `str` | One of `run`, `runs`, `vacuum`, `orphans`, `status` |
| `run_uuid` | `str \| None` | UUID of the run to delete; only used by `run` subcommand |
| `older_than` | `int \| None` | Age threshold in days; only used by `runs` subcommand |
| `verbose` | `bool` | Reserved for future verbose output (passed from `--verbose` flag) |

### Return Value

`run_gc()` returns a plain `dict[str, Any]` with the following keys:

| Key | Type | Description |
|-----|------|-------------|
| `success` | `bool` | `True` if the operation succeeded |
| `message` | `str` | Human-readable status or error message |

> [!NOTE]
> Unlike `run_load()`, the GC orchestrator returns a plain dict rather than a typed dataclass. The CLI layer inspects `result["success"]` to determine the process exit code.

---

## 3. Subcommands

### 3.1 `batho gc run <run_uuid>`

**Purpose:** Delete a single run record and all its associated file artifacts.

**CLI registration:**
```
batho gc run <run_uuid>
```

**Orchestrator logic:**
1. Looks up the run by UUID via `db.get_run(run_uuid)`.
2. If not found, returns `{"success": False, "message": "Run not found: <uuid>"}`.
3. Calls `db.delete_run(run_uuid)` to perform the full delete cascade (see §4).
4. Returns `{"success": True, "message": "Successfully deleted run <uuid>."}`.

**Example:**
```sh
batho gc run 550e8400-e29b-41d4-a716-446655440000
```

---

### 3.2 `batho gc runs --older-than <days>`

**Purpose:** Batch-delete all runs whose `started_at` timestamp is older than *N* days.

**CLI registration:**
```
batho gc runs --older-than <N>
```

`--older-than` is **required**. Negative values are rejected.

**Orchestrator logic:**
1. Computes `threshold_date = UTC now − timedelta(days=older_than)` and converts to ISO 8601 string.
2. Fetches all run records via `db._reader.get_all_runs()`.
3. Filters records where `r["started_at"] < threshold_str` (lexicographic ISO comparison).
4. If no matching runs, returns early with a success message.
5. Calls `db.delete_run(run_uuid)` for each matching UUID.
6. Returns a summary message listing deleted UUIDs.

**Example:**
```sh
batho gc runs --older-than 30   # Delete runs started more than 30 days ago
```

**Timestamp comparison note:** The comparison is performed lexicographically on ISO 8601 strings (e.g., `"2025-01-01T00:00:00+00:00"`). Because ISO 8601 with a consistent timezone suffix sorts correctly as a string, this is functionally equivalent to a numeric UTC comparison.

---

### 3.3 `batho gc status`

**Purpose:** Display a human-readable storage summary for the current repository's artifact bundle.

**CLI registration:**
```
batho gc status
```

**Output format:**
```
Storage Status for artifact:
  Total artifact size: 12.34 MB
  Arrow generation:    7
  Total runs:          42
  File tracking:       3810
  Run artifacts:       42
  Last run:            <uuid>
```

**Orchestrator logic:**
1. Calls `db.get_stats()` which returns a dict with:
   - `tables` — per-table stats (`rows`, `size_bytes`).
   - `generation` — current Arrow generation counter.
   - `last_run_uuid` — UUID of the most recent run.
2. Sums `size_bytes` across all tables to produce `total_mb`.
3. Extracts row counts from the `runs`, `file_tracking`, and `run_artifacts` tables.

**`get_stats()` table structure:**

| Key | Description |
|-----|-------------|
| `tables.runs.rows` | Number of run records |
| `tables.file_tracking.rows` | Number of tracked file entries |
| `tables.run_artifacts.rows` | Number of run artifact entries |
| `tables.<table>.size_bytes` | On-disk size of the IPC file |
| `generation` | Current Arrow generation counter |
| `last_run_uuid` | UUID of the latest run (`"none"` if empty) |

---

### 3.4 `batho gc vacuum`

**Purpose:** Sweep and remove orphaned Arrow IPC generation files that are no longer referenced by the active generation.

**CLI registration:**
```
batho gc vacuum
```

**Orchestrator logic:**
1. Calls `db.garbage_collect()`, which scans the artifact directory for `.ipc` files from stale generations.
2. Returns a count of deleted files.
3. Returns `{"success": True, "message": "GC complete — <N> orphaned IPC generation(s) removed."}`.

---

### 3.5 `batho gc orphans`

**Purpose:** Remove stale IPC files not referenced by the active generation (alias for `vacuum` with a different message).

**CLI registration:**
```
batho gc orphans
```

**Orchestrator logic:** Identical to `vacuum` — calls `db.garbage_collect()` internally. The return message reads `"Orphan sweep complete — <N> stale IPC file(s) removed."` to distinguish it from the `vacuum` message.

> [!NOTE]
> Both `vacuum` and `orphans` call the same underlying `BathoBundle.garbage_collect()` method. They are separate subcommands for ergonomic reasons — `vacuum` is the canonical name while `orphans` provides an alias familiar to users coming from other tools.

---

## 4. Delete Cascade

When `db.delete_run(run_uuid)` is called, the following sequence occurs inside `BathoBundle`:

```
delete_run(run_uuid)
  │
  ├─ Remove run record from runs.ipc
  │
  ├─ Look up run_internal_id from the run record
  │
  ├─ Remove all run_artifacts rows matching run_internal_id
  │
  ├─ For each (file_id) in file_tracking associated with this run:
  │    ├─ Delete agents/<file_id>.ipc  (agent view blob)
  │    └─ Delete rels/<file_id>.ipc    (relationship rows blob)
  │
  └─ Commit updated tables via BathoBundleManager (MVCC generation bump)
```

**What is deleted:**

| Item | Location | Format |
|------|----------|--------|
| Run record | `artifact/runs.ipc` | Arrow IPC row |
| Run artifact row | `artifact/run_artifacts.ipc` | Arrow IPC row |
| Per-file agent view | `artifact/agents/<file_id>.ipc` | Arrow IPC File |
| Per-file relationship blob | `artifact/rels/<file_id>.ipc` | Arrow IPC File |

**What is NOT deleted:**

- `file_tracking.ipc` entries — file metadata is retained and may be shared across runs.
- `file_changelog.ipc` entries — historical change log is preserved.
- `bsg/current/` graph files — the entity/relationship graph is NOT modified by GC; it reflects the most recent completed run regardless of prior run deletions.

> [!IMPORTANT]
> Deleting the most recent run does not automatically rebuild `bsg/current/`. Run `batho patch` or `batho build` to refresh the graph after aggressive GC.

---

## 5. Vacuum Implementation

**`db.garbage_collect()`** (inside `BathoBundle` / `BathoBundleManager`) performs:

1. **Generation sweep:** Identifies all `.ipc` files in the artifact directory whose generation suffix does not match the current active generation.
2. **Orphan file removal:** Deletes each stale generation file. The active `.ipc` files (as listed in `manifest.json → active_files`) are never touched.
3. **Returns:** Count of deleted files (integer).

**Arrow IPC compaction model:**

Each write goes through MVCC:
```
<table>.ipc        ← active (memory-mappable)
<table>.<gen>.ipc  ← previous generation (orphan after commit)
```

`garbage_collect()` removes all `<table>.<gen>.ipc` files where `<gen>` is not the current active generation.

---

## 6. Status Output Format

`batho gc status` computes metrics from `BathoBundle.get_stats()` and produces human-readable text directly to `stdout`. No JSON mode is available for `gc status` in v1.1.0.

**Metric derivation:**

| Displayed Field | Derived From |
|----------------|-------------|
| Total artifact size (MB) | `sum(tables[t]["size_bytes"] for t in tables) / 1024 / 1024` |
| Arrow generation | `stats["generation"]` |
| Total runs | `tables["runs"]["rows"]` |
| File tracking | `tables["file_tracking"]["rows"]` |
| Run artifacts | `tables["run_artifacts"]["rows"]` |
| Last run | `stats["last_run_uuid"]` (or `"none"`) |

---

## 7. Safety Guarantees

| Guarantee | Detail |
|-----------|--------|
| Root validation | `run_gc()` returns `success=False` immediately if `root` does not exist or is not a directory |
| Bundle sentinel check | Returns `success=False` if `bundle_dir/meta.json` is absent (no bundle initialized) |
| UUID existence check | `gc run` looks up the run before calling `delete_run`; returns error if not found |
| Non-negative age | `gc runs` rejects `older_than < 0` with `success=False` |
| Atomic commits | All IPC table writes go through `BathoBundleManager`'s MVCC rename — no partial state is written |
| `bsg/current/` untouched | GC operations never modify the graph store; only the artifact store is affected |

---

## 8. Exit Codes

| Exit Code | Condition |
|-----------|-----------|
| `0` | Operation succeeded (`result["success"] == True`) |
| `1` | Operation failed (`result["success"] == False`); error message printed to `stderr` |

The CLI adapter (`cmd_gc` in `batho/cli/gc.py`) maps the `success` flag to exit codes and routes messages:
- Success messages → `stdout` via `print(result["message"])`.
- Error messages → `stderr` via `print(f"error: {result['message']}", file=sys.stderr)`.

---

*Generated for Batho v1.1.0*
