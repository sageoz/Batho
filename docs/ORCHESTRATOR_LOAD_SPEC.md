# Batho Load (Transport ZIP Ingestion) Specification

`batho load` unpacks a transport artifact ZIP (produced by `batho export --pack`) into the repository's `.batho/artifact/` directory and optionally reconstructs the `.batho/bsg/current/` graph store. It is the standard mechanism for restoring a Batho artifact bundle in CI/CD pipelines after downloading a stored artifact.

---

## 1. Purpose

The `load` command bridges the gap between:
- **Export side:** `batho export --pack` produces `artifact_<dir>.batho` — a self-contained ZIP containing zstd-compressed Arrow IPC tables and a manifest.
- **Import side:** `batho load artifact_<dir>.batho` decompresses those tables back into the working directory's `.batho/artifact/` store, making the previous run's data available for `batho patch`.

This allows CI jobs to skip full re-indexing by restoring a previously built and uploaded artifact bundle, then performing an incremental patch over the changed files.

---

## 2. Transport ZIP Format

A transport ZIP is produced by `BathoBundleManager.export_artifact()` (see `STORAGE_ENGINE.md §3`).

**Filename convention:** `artifact_<dirname>.batho`

**Internal structure:**
```
artifact_<dirname>.batho  (ZIP)
  manifest.json                    — bundle metadata and table index
  runs.ipc.zst                     — zstd-compressed Arrow IPC stream
  file_tracking.ipc.zst
  file_changelog.ipc.zst
  run_artifacts.ipc.zst
  agents/<file_id>.ipc.zst         — per-file agent view blobs
  rels/<file_id>.ipc.zst           — per-file relationship blobs
  bsg/entities.ipc.zst             — (v1.1+) BSG entity table
  bsg/relationships.ipc.zst        — (v1.1+) BSG relationship table
  bsg/entity_dict.ipc.zst          — (v1.1+) entity key→id map
  bsg/dangling.ipc.zst             — (v1.1+) unresolved cross-file refs
```

**`manifest.json` structure:**
```json
{
  "schema_version": "batho-bundle.v1",
  "generation": 7,
  "last_run_uuid": "550e8400-e29b-41d4-a716-446655440000",
  "active_files": {
    "runs": "runs.ipc",
    "file_tracking": "file_tracking.ipc",
    "file_changelog": "file_changelog.ipc",
    "run_artifacts": "run_artifacts.ipc",
    "agent_views": "agent_views.ipc",
    "rels_views": "rels_views.ipc"
  },
  "bsg_files": ["bsg/entities.ipc.zst", "bsg/relationships.ipc.zst", ...]
}
```

| Field | Description |
|-------|-------------|
| `schema_version` | Must match `SCHEMA_VERSION` constant in `arrow_store/schemas.py`; checked during unpack |
| `generation` | Arrow generation counter at export time |
| `last_run_uuid` | UUID of the most recent completed run |
| `active_files` | Logical table name → filename mapping |
| `bsg_files` | List of BSG ZIP members (absent in ZIPs produced by pre-v1.1 batho) |

---

## 3. `LoadOptions` and `LoadResult` Dataclasses

**File:** `batho/orchestrator/load.py`

### `LoadOptions`

```python
@dataclass
class LoadOptions:
    root: Path          # Repository root path
    artifact_path: Path # Path to the .batho ZIP file
    force: bool = False # Overwrite existing bundle if present
    rebuild_bsg: bool = True  # Whether to reconstruct bsg/current/ after unpack
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `root` | `Path` | — | Repository root; must exist and be a directory |
| `artifact_path` | `Path` | — | Absolute or relative path to `artifact_*.batho` ZIP |
| `force` | `bool` | `False` | If `True`, deletes any existing bundle before unpacking |
| `rebuild_bsg` | `bool` | `True` | If `True`, reconstructs `.batho/bsg/current/` from unpacked data |

> [!NOTE]
> The CLI does not expose `--rebuild-bsg` in v1.1.0; it always defaults to `True`. The field exists for programmatic use.

### `LoadResult`

```python
@dataclass
class LoadResult:
    success: bool
    message: str = ""
    generation: int = 0
    tables_loaded: int = 0
    errors: list[str] = field(default_factory=list)
```

| Field | Type | Description |
|-------|------|-------------|
| `success` | `bool` | `True` if load completed without error |
| `message` | `str` | Human-readable summary or error description |
| `generation` | `int` | Arrow generation number from the manifest |
| `tables_loaded` | `int` | Count of logical tables restored (`len(manifest["active_files"])`) |
| `errors` | `list[str]` | Reserved for future partial-error accumulation (currently always `[]`) |

---

## 4. `run_load()` Step-by-Step

**Function:** `batho.orchestrator.load.run_load(options: LoadOptions) -> LoadResult`

```
run_load(options)
  │
  ├─ [1] Validate root and artifact_path
  │
  ├─ [2] Check for existing bundle; honour --force
  │
  ├─ [3] BathoBundleManager.unpack_artifact()
  │        └─ schema_version check
  │        └─ decompress .ipc.zst → plain .ipc
  │
  ├─ [4] BSG current/ reconstruction
  │        ├─ Fast path:  bsg_files present in ZIP → already extracted
  │        └─ Fallback:   reconstruct from agent_views + rels_views
  │
  └─ [5] Return LoadResult
```

### Step 1 — Validate Inputs

```python
root = options.root.resolve()
if not root.exists() or not root.is_dir():
    return LoadResult(success=False, message="Repository root does not exist: ...")

artifact_path = options.artifact_path.resolve()
if not artifact_path.exists():
    return LoadResult(success=False, message="Artifact file not found: ...")
```

Both `root` and `artifact_path` are resolved to absolute paths. Early returns produce a `LoadResult(success=False)` with a descriptive message.

---

### Step 2 — Existing Bundle Check

```python
bundle_dir = resolve_bundle_dir(root)   # typically root/.batho/artifact/
meta_path = bundle_dir / "meta.json"

if meta_path.exists() and not options.force:
    return LoadResult(success=False,
        message="Artifact bundle already exists. Use --force to overwrite.")

if meta_path.exists() and options.force:
    shutil.rmtree(bundle_dir, ignore_errors=True)   # wipe entire bundle_dir

bundle_dir.mkdir(parents=True, exist_ok=True)
```

If a bundle already exists at `bundle_dir` and `force=False`, the command fails immediately. With `force=True`, the entire `bundle_dir` is removed before the fresh unpack begins.

> [!CAUTION]
> `--force` performs a recursive delete (`shutil.rmtree`) of the entire artifact directory. All previous run history, file tracking data, and IPC blobs are permanently destroyed.

---

### Step 3 — `BathoBundleManager.unpack_artifact()`

```python
manager = BathoBundleManager(bundle_dir)
manifest = manager.unpack_artifact(
    artifact_path,
    bsg_target_dir=bsg_current_dir if options.rebuild_bsg else None,
)
```

Inside `unpack_artifact()`:

1. Opens the ZIP file.
2. Reads and parses `manifest.json`.
3. **Schema version check:** Compares `manifest["schema_version"]` against the module-level `SCHEMA_VERSION` constant. Raises an exception on mismatch.
4. For each `.ipc.zst` member:
   - Decompresses zstd stream.
   - Writes plain Arrow IPC File to `bundle_dir/<table>.ipc`.
5. If `bsg_target_dir` is provided and the ZIP contains `bsg/` members, extracts them to `bsg_target_dir`.
6. Returns the parsed `manifest` dict.

**Decompression format:**
```
<table>.ipc.zst  (Arrow IPC Stream + zstd)
    ↓  unpack_artifact()
<table>.ipc      (Arrow IPC File — memory-mappable, at-rest format)
```

---

### Step 4 — BSG `current/` Reconstruction

After unpacking, `run_load()` ensures `.batho/bsg/current/` contains valid IPC files and a `meta.json` so that `batho patch` can perform copy-on-write from this base.

**`bsg_current_dir` = `root/.batho/bsg/current/`**

#### Fast Path (v1.1+ ZIPs)

If `manifest["bsg_files"]` is non-empty, the ZIP already contained `bsg/*.ipc.zst` members, which were extracted by `unpack_artifact()` to `bsg_current_dir`. The orchestrator calls `_write_bsg_meta()` to write `meta.json`:

```python
def _write_bsg_meta(bsg_current_dir, manifest):
    # Reads entity_count from entities.ipc (if present)
    # Reads rel_count from relationships.ipc (if present)
    meta = {
        "schema_version": SCHEMA_VERSION,
        "run_uuid": manifest["last_run_uuid"] or "loaded",
        "run_internal_id": manifest["generation"],
        "entity_count": entity_count,
        "rel_count": rel_count,
        "dangling_count": 0,
    }
    (bsg_current_dir / "meta.json").write_text(json.dumps(meta, indent=2))
```

#### Fallback Path (pre-v1.1 ZIPs)

If `manifest["bsg_files"]` is absent or empty, the orchestrator calls `_reconstruct_bsg_current()`:

```python
def _reconstruct_bsg_current(root, bundle_dir, manifest):
    # 1. Resolve agent_views.ipc, rels_views.ipc, file_tracking.ipc paths
    # 2. Build file_id → file_path lookup from file_tracking
    # 3. Initialize BsgScratchStore(run_uuid, batho_dir, run_internal_id=generation)
    # 4. Read agent_views.ipc → map entity rows → store.append_entities()
    # 5. Read rels_views.ipc → map relationship rows → store.append_relationships()
    # 6. write_empty_dangling(store.dangling_path)
    # 7. store.compact()  → writes entities.ipc, relationships.ipc, entity_dict.ipc
```

**Entity mapping from `agent_views`:**

| `agent_views` column | Maps to entity tuple field |
|---------------------|---------------------------|
| `entity_id` (str) | `key_map[entity_id]` (int) via `bulk_get_or_create_entity_keys` |
| `name` | entity name |
| `entity_type` | entity type string |
| `fqn` | fully-qualified name |
| `file_id` → `file_id_to_path[file_id]` | file path string |
| `start_line` | start line number |
| `signature` | signature string |
| `is_exported` | export flag (bool) |

**Relationship mapping from `rels_views`:**

| `rels_views` column | Maps to relationship tuple field |
|--------------------|----------------------------------|
| `source_id` (str) | `key_map[source_id]` (int) |
| `target_id` (str) | `key_map[target_id]` (int) |
| `relation_type` | relation type string |
| `metadata_json` | metadata JSON string |
| *(generation)* | current run generation counter |

> [!NOTE]
> The fallback reconstruction path silently skips missing tables. If both `agent_views` and `rels_views` are absent, a warning is logged and `bsg/current/` is left empty. `batho patch` will fall back to a full re-index in this case.

---

### Step 5 — Return `LoadResult`

```python
return LoadResult(
    success=True,
    message=f"Loaded artifact into {bundle_dir} (generation {generation}, {tables_loaded} tables)",
    generation=generation,     # from manifest["generation"]
    tables_loaded=tables_loaded,  # len(manifest["active_files"])
)
```

---

## 5. Error Handling

| Error Condition | Behaviour |
|----------------|-----------|
| `root` does not exist | `LoadResult(success=False, message="Repository root does not exist: ...")` |
| `artifact_path` does not exist | `LoadResult(success=False, message="Artifact file not found: ...")` |
| Bundle exists and `force=False` | `LoadResult(success=False, message="Artifact bundle already exists. Use --force to overwrite.")` |
| Missing `manifest.json` in ZIP | `unpack_artifact()` raises exception → caught → `LoadResult(success=False, message=str(exc))` |
| Schema version mismatch | `unpack_artifact()` raises exception → caught → `LoadResult(success=False, message=str(exc))` |
| Corrupt ZIP / decompression error | `unpack_artifact()` raises exception → caught → `LoadResult(success=False, message=str(exc))` |
| `agent_views`/`rels_views` missing | Warning logged; fallback skipped; `bsg/current/` left empty (non-fatal) |
| BSG reconstruction failure | Warning logged via `LOGGER.warning("load_bsg_current_rebuild_failed", ...)`; load still succeeds |

All exceptions from `unpack_artifact()` are caught by a broad `except Exception as exc:` handler, which logs the error and returns a failed `LoadResult`. BSG reconstruction failures are treated as warnings and do not fail the overall load.

---

## 6. CI/CD Workflow Positioning

```
┌─────────────────────────────────────────────────────────────────┐
│ CI Job N (producer)                                             │
│                                                                 │
│  batho build                                                    │
│    └─ indexes all files → .batho/artifact/ + .batho/bsg/current/│
│                                                                 │
│  batho export --pack                                            │
│    └─ produces: artifact_<repo>.batho                          │
│                                                                 │
│  upload-artifact artifact_<repo>.batho                          │
└─────────────────────────────────────────────────────────────────┘
                         │
                    [artifact store]
                         │
┌─────────────────────────────────────────────────────────────────┐
│ CI Job N+1 (consumer)                                           │
│                                                                 │
│  download-artifact artifact_<repo>.batho                        │
│         ↓                                                       │
│  batho load artifact_<repo>.batho          ← THIS COMMAND       │
│    └─ unpacks .ipc tables to .batho/artifact/                   │
│    └─ reconstructs .batho/bsg/current/                          │
│         ↓                                                       │
│  batho patch                                                    │
│    └─ re-indexes only changed files (copy-on-write from base)   │
│         ↓                                                       │
│  [downstream tools: batho query, batho check, etc.]             │
└─────────────────────────────────────────────────────────────────┘
```

`batho load` **must** run before `batho patch`. Running `batho patch` against a missing or empty `.batho/artifact/` directory will cause a full re-index (no bundle found), defeating the incremental indexing benefit.

---

## 7. CLI Usage

```
batho load <artifact>         [--force] [--root <path>] [--verbose]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `artifact` | positional `Path` | — | Path to `artifact_<dir>.batho` ZIP |
| `--force` | flag | `False` | Overwrite an existing bundle |
| `--root` | `Path` | CWD | Repository root (inherited from base parser) |
| `--verbose` | flag | `False` | Enable verbose logging (inherited from base parser) |

**Examples:**
```sh
# Standard load (fails if bundle exists)
batho load ./artifact_myrepo.batho

# Overwrite existing bundle
batho load ./artifact_myrepo.batho --force

# Load into a specific repository root
batho load /tmp/artifact_myrepo.batho --root /workspace/myrepo
```

---

## 8. Exit Codes

| Exit Code | Condition |
|-----------|-----------|
| `0` | Load succeeded (`result.success == True`) |
| `1` | Load failed (`result.success == False`); error message printed to `stderr` |

The CLI adapter (`cmd_load` in `batho/cli/load.py`) maps `result.success` to exit codes:
- On success: `print(result.message)` to `stdout`, returns `0`.
- On failure: `print(f"error: {result.message}", file=sys.stderr)`, returns `1`.

---

*Generated for Batho v1.1.0*
