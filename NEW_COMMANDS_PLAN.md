# Plan: `batho build` — Fresh Index Build for New Working Directories

The first new top-level command. Scope is intentionally narrow: **full build only**.
If a `.batho` database already exists, `build` exits early telling the user to run `batho patch` instead (implemented later).

---

## 1. Scope Boundary

| In Scope | Out of Scope (deferred) |
|----------|------------------------|
| Full index build for a directory with **no** existing `.batho` | Incremental patching (`batho patch`) |
| Creating `.batho` database + baseline snapshot | Doctor/verify workflows |
| Writing all artifacts to DB (entities, relationships, BSG, context) | Unsupported file tracking |
| CLI parser registration | Legacy `cmd_index` deprecation |

**Key rule:** If `.batho` exists at `root/.batho` and `--full` is not passed, print a message and exit 0:
```
.batho database already exists at <path>.
To update incrementally, run: batho patch --root <path>
To force a full rebuild, run: batho build --root <path> --full
```

---

## 2. CLI Interface

```bash
batho build --root DIR [--full] [--verbose] [--max-workers N] [--max-file-size-kb N]
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--root` | `Path` | `.` | Repository root to build |
| `--full` | `bool` | `False` | Force rebuild even if `.batho` exists (drops and recreates DB) |
| `--verbose` | `bool` | `False` | Debug-level logging |
| `--max-workers` | `int` | CPU count | Parallel parse workers |
| `--max-file-size-kb` | `int` | from config | Skip files exceeding this size |

### Hardcoded Optimized Defaults (no toggles)

- `storage_view = True` — always produce the storage view
- `with_gaps = True` — full byte coverage for reconstruction
- `snapshot = True` — baseline snapshot always created
- AST cache always enabled (unless `--full` clears it)

---

## 3. Architecture

```
batho/orchestrator/__init__.py
batho/orchestrator/build.py       ← all logic here
```

The CLI parser (in `batho_cli.py` or `batho/cli/build.py`) is a thin 30-line wrapper that calls `run_build()`.

### Public API

```python
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class BuildOptions:
    root: Path
    force_full: bool = False
    verbose: bool = False
    max_workers: int | None = None
    max_file_size_kb: int | None = None

@dataclass
class BuildResult:
    success: bool
    run_id: str
    entity_count: int
    relationship_count: int
    file_count: int
    bsg_file_count: int
    snapshot_id: str
    duration_ms: int
    warnings: list[str] = field(default_factory=list)

def run_build(options: BuildOptions) -> BuildResult:
    """Execute a full build for a new working directory."""
```

---

## 4. Detailed Logic Flow

```
run_build(options)
│
├─ 1. Resolve root = options.root.resolve()
│
├─ 2. Check existing DB
│     db_path = root / ".batho"
│     if db_path.exists() and NOT options.force_full:
│         → print "already built" message, return early
│     if options.force_full and db_path.exists():
│         → delete db_path (clean slate)
│
├─ 3. Load config (batho.yaml / defaults)
│     config = get_config_cached()
│     max_file_size = options.max_file_size_kb or config default
│
├─ 4. Initialize BathoDatabase
│     db = BathoDatabase(db_path, repo_root=root)
│     run_id = generate_run_id()  # e.g. uuid or timestamp-based
│     db.create_run(run_id, schema_version="batho-db.v1", root_path=str(root))
│
├─ 5. Full parse: build code graph
│     indexer = CodeGraphIndexer(cache_path=str(db_path), root=str(root))
│     graph = build_graph_parallel(
│         root=root,
│         max_workers=options.max_workers,
│         max_file_size_kb=max_file_size,
│         config=config,
│     )
│     → returns InMemoryGraph with entities + relationships
│
├─ 6. Persist entities & relationships to DB
│     db.insert_entities(run_id, [e.to_dict() for e in graph.entities])
│     db.insert_relationships(run_id, [r.to_dict() for r in graph.relationships])
│
├─ 7. Build BSG map & persist
│     bsg_map = BSGMap.build(graph, root)
│     for file_path, bsg_data in bsg_map.per_file_json():
│         db.insert_bsg_entries(run_id, [{
│             "file_path": file_path,
│             "view_type": "agent",
│             "bsg_json": bsg_data,
│             "node_count": ...,
│             "checksum": ...,
│         }])
│
├─ 8. Build context outputs (overview + files)
│     overview_json = build_context_overview(graph)
│     files_json = build_context_files(graph)
│     db.set_context_output(run_id, "overview", overview_json)
│     db.set_context_output(run_id, "files", files_json)
│
├─ 9. Create baseline snapshot
│     snapshot_id = create_snapshot(db, root, graph, run_id)
│     → stores snapshot record + file_snapshots in DB
│
├─ 10. Update file tracking
│      db.upsert_file_tracking([...all indexed files with hashes...])
│
├─ 11. Complete run
│      db.complete_run(run_id,
│          entity_count=len(graph.entities),
│          rel_count=len(graph.relationships),
│          file_count=graph.file_count,
│          duration_ms=elapsed)
│
└─ 12. Return BuildResult
```

---

## 5. Dependencies (core libraries only)

The orchestrator imports directly from these — **never** from `cmd_*` functions:

| Import | Purpose |
|--------|---------|
| `batho.storage.engine.BathoDatabase` | All persistence |
| `batho.context.codegraph.CodeGraphIndexer` | AST parsing → graph |
| `batho.context.pipeline.build_graph_parallel` | Parallel file processing |
| `batho.context.bsg_map.BSGMap` | BSG rendering |
| `batho.time_machine.create_snapshot` | Baseline snapshot |
| `batho.config.get_config_cached` | Config resolution |
| `batho.bsg.rules.apply_rule_plugins` | BSG plugin transforms |
| `batho.utils.logging.get_logger` | Structured logging |

---

## 6. Exit Behavior

| Condition | Exit Code | Message |
|-----------|-----------|---------|
| Success (fresh build) | 0 | Summary: entities, relationships, files, duration |
| `.batho` exists, no `--full` | 0 | "Already built. Use `batho patch` or `--full`" |
| `--full` rebuild success | 0 | Summary (same as fresh) |
| Parse failure (no files) | 1 | "No indexable files found in <root>" |
| Config error | 1 | Error details |

---

## 7. What comes next (out of scope for this PR)

1. **`batho patch --root DIR`** — incremental update using git-diff or file-hash scan against the baseline snapshot stored by `build`. Will be implemented after `build` is stable.
2. **`batho doctor --root DIR`** — integrity checks against the `.batho` database.
3. **Unsupported file tracking** — `FileSnapshot` sentinels for files without extractors.
4. **BSG storage view refresh on patch** — fix the bug where incremental path doesn't regenerate presentation artifacts.
5. **Legacy deprecation** — once build+patch are stable, deprecate `batho index`, `batho verify`, etc.
