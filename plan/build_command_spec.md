# Specification: `batho build` — Fresh Index Build

This document defines the implementation spec for `batho build`. Scope is **fresh full build only**.
If `.batho` already exists, the command exits early directing the user to `batho patch` (implemented separately).

---

## 1. CLI Interface

```bash
batho build --root DIR [--full] [--verbose] [--max-workers N] [--max-file-size-kb N]
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--root` | `Path` | `.` | Repository root directory |
| `--full` | `bool` | `False` | Force rebuild (deletes existing `.batho` and rebuilds from scratch) |
| `--verbose` | `bool` | `False` | Debug-level structured logging |
| `--max-workers` | `int` | CPU count | Parallel parse worker limit |
| `--max-file-size-kb` | `int` | config | Skip files exceeding this size |

### Hardcoded Defaults (replaces legacy toggles)

| Setting | Value | Rationale |
|---------|-------|-----------|
| `storage_view` | `True` | Storage view is the product |
| `with_gaps` | `True` | Full byte coverage for reconstruction |
| `snapshot` | `True` | Baseline required for future patching |
| AST cache | `True` (cleared on `--full`) | Performance |

---

## 2. Module Layout

```
batho/orchestrator/__init__.py      (empty, package marker)
batho/orchestrator/build.py         (orchestrator logic)
batho/cli/build.py                  (argparse wrapper, ~30 lines)
```

---

## 3. Public API

```python
# batho/orchestrator/build.py

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
    """Execute a full index build for a working directory.

    If .batho already exists and force_full is False, returns early
    with success=True and a warning indicating patch should be used.
    """
```

---

## 4. Logic Flow

```
run_build(options)
│
├─ 1. Resolve root
│     root = options.root.resolve()
│     db_path = root / ".batho"
│
├─ 2. Guard: existing database
│     if db_path.exists() and NOT options.force_full:
│         log "Already built. Use batho patch or --full."
│         return BuildResult(success=True, warnings=["already_built"], ...)
│     if options.force_full and db_path.exists():
│         db_path.unlink()   # clean slate
│
├─ 3. Load config
│     config = get_config_cached()
│     max_file_size = options.max_file_size_kb or config["index"]["max_file_size_kb"]
│
├─ 4. Initialize database
│     db = BathoDatabase(db_path, repo_root=root)
│     run_id = generate_run_id()
│     db.create_run(run_id, schema_version="batho-db.v1", root_path=str(root))
│
├─ 5. Build code graph (full parse)
│     graph = build_graph_parallel(
│         root, max_workers, max_file_size, config,
│         cache_path=str(db_path), with_gaps=True
│     )
│
├─ 6. Persist graph to DB
│     db.insert_entities(run_id, [e.to_dict() for e in graph.entities])
│     db.insert_relationships(run_id, [r.to_dict() for r in graph.relationships])
│
├─ 7. Apply BSG plugin rules
│     apply_rule_plugins(graph, config.get("rules", {}))
│
├─ 8. Build & persist BSG map
│     bsg_map = BSGMap.build(graph, root)
│     entries = bsg_map.to_db_entries()  # [{file_path, view_type, bsg_json, ...}]
│     db.insert_bsg_entries(run_id, entries)
│
├─ 9. Build & persist context outputs
│     db.set_context_output(run_id, "overview", build_overview(graph))
│     db.set_context_output(run_id, "files", build_files(graph))
│
├─ 10. Create baseline snapshot
│      snapshot_id = create_snapshot(db, root, graph, run_id, label="baseline")
│
├─ 11. Persist file tracking (hashes for future patch detection)
│      db.upsert_file_tracking(graph.file_tracking_records())
│
├─ 12. Complete run
│      db.complete_run(run_id,
│          entity_count=..., rel_count=...,
│          file_count=..., duration_ms=elapsed)
│
└─ 13. Return BuildResult(success=True, ...)
```

---

## 5. Dependencies

All imports come from core libraries. **No** `cmd_*` functions are called.

| Module | Used For |
|--------|----------|
| `batho.storage.engine.BathoDatabase` | All DB persistence |
| `batho.context.pipeline.build_graph_parallel` | Parallel AST parsing |
| `batho.context.codegraph.CodeGraphIndexer` | Graph construction |
| `batho.context.bsg_map.BSGMap` | BSG rendering |
| `batho.bsg.rules.apply_rule_plugins` | Plugin transforms |
| `batho.time_machine.create_snapshot` | Baseline snapshot |
| `batho.config.get_config_cached` | Config loading |
| `batho.utils.logging.get_logger` | Structured logging |

---

## 6. Exit Behavior

| Condition | Exit | Output |
|-----------|------|--------|
| Fresh build success | `0` | `Built <root>: N entities, M relationships, F files in Xms` |
| `.batho` exists, no `--full` | `0` | `.batho already exists. Use batho patch --root <path> or batho build --root <path> --full` |
| `--full` rebuild success | `0` | Same as fresh build |
| No indexable files | `1` | `No indexable files found in <root>` |
| Config/IO error | `1` | Error message |

---

## 7. Relationship to `batho patch` (future)

`batho build` creates the **baseline state** that `batho patch` operates against:
- The snapshot stored at step 10 becomes the base for incremental diffing
- File tracking records (step 11) provide hash-scan fallback when git is unavailable
- BSG entries provide the cached state that patch will selectively update

When `batho patch` is implemented, `batho build` will not call it. The two commands are peers:
- `build` = create from nothing (or `--full` to recreate)
- `patch` = update existing `.batho` incrementally

---

## 8. Implementation Checklist

- [ ] Create `batho/orchestrator/__init__.py`
- [ ] Create `batho/orchestrator/build.py` with `BuildOptions`, `BuildResult`, `run_build()`
- [ ] Create `batho/cli/build.py` with argparse subcommand registration
- [ ] Wire `batho build` into the CLI entry point
- [ ] Verify: fresh build on a test repo produces valid `.batho` with all expected data
- [ ] Verify: re-running without `--full` exits early with guidance message
- [ ] Verify: `--full` deletes and rebuilds successfully
