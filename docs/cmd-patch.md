# `batho patch` — Incremental Index Update

## Overview

`batho patch` applies an **incremental update** to an existing `artifact_<dirname>.batho` database. It detects only the files that changed since the last build or patch, re-parses those files, and surgically updates the code graph, BSG map, context outputs, snapshot, and file tracking — without touching unchanged files.

Run this on every subsequent change after the initial [`batho build`](./cmd-build.md).

---

## Synopsis

```
batho patch [--root PATH] [--verbose] [--max-file-size-kb N]
            [--mode commit|staged|modified|auto]
```

---

## Flags & Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--root` | `Path` | `.` (cwd) | Repository root directory containing the `.batho` database |
| `--verbose` | flag | `false` | Enable verbose debug logging |
| `--max-file-size-kb` | `int` | `500` (from config) | Skip files exceeding this size during hash scan fallback |
| `--mode` | `enum` | `auto` | Change detection strategy (see table below) |

### `--mode` Values

| Mode | Strategy | When to Use |
|------|----------|-------------|
| `auto` | `staged` + `modified` (working tree) | Default — catches all uncommitted local changes |
| `staged` | Git index (`git diff --cached`) | Only changes staged for commit |
| `modified` | Working directory (`git diff`) | Only unstaged working-tree changes |
| `commit` | Snapshot vs HEAD commits | Changes in committed history since last snapshot |

> **Fallback:** If git is unavailable or returns no output for any mode, the engine falls back to a full hash-scan comparing current file hashes against the baseline snapshot.

---

## Execution Flow

```mermaid
flowchart TD
    START([batho patch invoked]):::success

    subgraph VALIDATION["Phase 1: Validation"]
        CHECK_DB{artifact_*.batho\nexists?}
        EXIT_NO_DB["Exit 1: No artifact database found.\nRun: batho build --root ."]:::error
        OPEN_DB[Open BathoDatabase\nget_database]
        CHECK_SNAP{Snapshots\nexist in DB?}
        EXIT_NO_SNAP["Exit 1: No baseline snapshot.\nRun: batho build --root . --full"]:::error
        LOAD_SNAP[Sort snapshots by created_at\nLoad latest as base_snapshot]
        CHECK_SNAP_LOAD{Snapshot\nloaded OK?}
        EXIT_BAD_SNAP["Exit 1: Failed to load baseline snapshot"]:::error
    end

    subgraph DETECTION["Phase 2: Change Detection"]
        MODE{--mode}
        GIT_COMMIT[get_changed_file_status_since\nSnapshot vs commits]
        GIT_STAGED_MOD[get_changed_files_by_mode\nstaged / modified / auto]
        GIT_OK{Git entries\nreturned?}
        HASH_SCAN[FileChangeTracker.scan_for_changes\nHash-scan fallback vs base_snapshot]
        NO_CHANGES{changes\nlist empty?}
        EXIT_NO_CHANGES["Exit 0: No changes detected\nsince last build or patch"]:::success
    end

    subgraph PATCH["Phase 3: Incremental Patch"]
        CREATE_RUN[Create new run_id: patch_<ts>_<uuid>\nRecord git_commit + git_branch]
        RUN_PATCH[incremental_patch via time_machine\napply FileChange list to base snapshot]
        PATCH_OK{patch\nsucceeded?}
        EXIT_PATCH_FAIL["Exit 1: Incremental patch failed"]:::error
        LOAD_NEW_SNAP[Load newly created snapshot\nRebuild InMemoryGraph from snapshot]
        NEW_SNAP_OK{New snapshot\nloaded OK?}
        EXIT_NEW_SNAP_FAIL["Exit 1: Failed to load new snapshot"]:::error
    end

    subgraph BSG_REFRESH["Phase 4: BSG Refresh"]
        BUILD_BSG[BSGMap.build from patched graph\n+ opaque snapshots]
        COPY_BASE_BSG[Copy all bsg_entries\nfrom base run_id → new run_id]
        DELETE_CHANGED_BSG[DELETE bsg_entries for changed files\nunder new run_id]
        INSERT_NEW_BSG[INSERT new bsg_entries\nfor added/modified files]
    end

    subgraph CONTEXT_REFRESH["Phase 5: Context & Tracking Refresh"]
        REFRESH_CONTEXT[Rebuild overview + files\ncontext outputs]
        UPDATE_TRACKING[Update file_tracking\ndelete removed, upsert added/modified]
    end

    subgraph GRAPH_REFRESH["Phase 6: Graph Delta Persist"]
        COPY_BASE_GRAPH[Copy graph_entities + graph_relationships\nfrom base run_id → new run_id]
        DELETE_CHANGED_GRAPH[DELETE entities + relationships\nfor changed file paths]
        INSERT_NEW_GRAPH[INSERT new entities + relationships\nfrom patched graph]
        COMPLETE_RUN[complete_run\nentity_count + rel_count + file_count + duration_ms]
    end

    DONE(["Exit 0: Patched root\nN changes applied in Tms"]):::success

    START --> CHECK_DB
    CHECK_DB -->|No| EXIT_NO_DB
    CHECK_DB -->|Yes| OPEN_DB
    OPEN_DB --> CHECK_SNAP
    CHECK_SNAP -->|No| EXIT_NO_SNAP
    CHECK_SNAP -->|Yes| LOAD_SNAP
    LOAD_SNAP --> CHECK_SNAP_LOAD
    CHECK_SNAP_LOAD -->|Fail| EXIT_BAD_SNAP
    CHECK_SNAP_LOAD -->|OK| MODE

    MODE -->|commit| GIT_COMMIT
    MODE -->|staged/modified/auto| GIT_STAGED_MOD
    GIT_COMMIT --> GIT_OK
    GIT_STAGED_MOD --> GIT_OK
    GIT_OK -->|No| HASH_SCAN
    GIT_OK -->|Yes| NO_CHANGES
    HASH_SCAN --> NO_CHANGES
    NO_CHANGES -->|Yes| EXIT_NO_CHANGES
    NO_CHANGES -->|No| CREATE_RUN

    CREATE_RUN --> RUN_PATCH
    RUN_PATCH --> PATCH_OK
    PATCH_OK -->|Fail| EXIT_PATCH_FAIL
    PATCH_OK -->|OK| LOAD_NEW_SNAP
    LOAD_NEW_SNAP --> NEW_SNAP_OK
    NEW_SNAP_OK -->|Fail| EXIT_NEW_SNAP_FAIL
    NEW_SNAP_OK -->|OK| BUILD_BSG

    BUILD_BSG --> COPY_BASE_BSG
    COPY_BASE_BSG --> DELETE_CHANGED_BSG
    DELETE_CHANGED_BSG --> INSERT_NEW_BSG
    INSERT_NEW_BSG --> REFRESH_CONTEXT
    REFRESH_CONTEXT --> UPDATE_TRACKING
    UPDATE_TRACKING --> COPY_BASE_GRAPH
    COPY_BASE_GRAPH --> DELETE_CHANGED_GRAPH
    DELETE_CHANGED_GRAPH --> INSERT_NEW_GRAPH
    INSERT_NEW_GRAPH --> COMPLETE_RUN
    COMPLETE_RUN --> DONE

    classDef error fill:#fca5a5,stroke:#dc2626,color:#7f1d1d
    classDef success fill:#bbf7d0,stroke:#16a34a,color:#14532d
```

---

## Output

### Success

```
Patched /path/to/repo: 3 changes (1 added, 2 modified, 0 deleted) in 412ms
```

### No Changes

```
No changes detected since last build/patch
```

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success (including "no changes" early-exit) |
| `1` | Patch failed (no DB, no snapshot, engine error) |

---

## Error Cases

| Error | Cause | Resolution |
|-------|-------|-----------|
| `No artifact database found` | `batho build` has not been run | Run `batho build --root <path>` first |
| `No baseline snapshot found` | DB exists but snapshot table is empty | Run `batho build --root <path> --full` |
| `Failed to load baseline snapshot` | Snapshot record corrupted/missing from storage | Run `batho fix` then retry, or rebuild with `--full` |
| Incremental patch failed | Graph consistency error | Logged as warning (non-fatal); run `batho fix --deep` if issues persist |

---

## Examples

```bash
# Patch the current directory (default auto mode)
batho patch

# Patch a specific repository
batho patch --root /path/to/project

# Only pick up staged changes (pre-commit use case)
batho patch --mode staged

# Only pick up committed changes since last snapshot
batho patch --mode commit

# Patch with hash-scan fallback explicitly (non-git repo)
batho patch --mode modified

# Verbose output for debugging
batho patch --verbose
```
