# `batho patch` — Incremental Index Update

## Overview

`batho patch` applies an **incremental update** to an existing `artifact_<dirname>.batho` database. It detects only the files that changed since the last build or patch, re-parses those files, and uses **blob-level copy-on-write** to produce a new run — copying unchanged file blobs directly in SQL and re-inserting only changed ones. No unchanged data is re-parsed or re-compressed.

Run this on every subsequent change after the initial [`batho build`](./cmd-build.md).

---

## Synopsis

```
batho patch [--root PATH] [--verbose] [--max-file-size-kb N]
```

---

## Flags & Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--root` | `Path` | `.` (cwd) | Repository root directory containing the `.batho` database |
| `--verbose` | flag | `false` | Enable verbose debug logging |
| `--max-file-size-kb` | `int` | `500` (from config) | Skip files exceeding this size during hash scan |

---

## Execution Flow

```mermaid
flowchart TD
    START([batho patch invoked]):::success

    subgraph VALIDATION["Phase 1: Validation"]
        CHECK_DB{artifact_*.batho\nexists?}
        EXIT_NO_DB["Exit 1: No artifact database found.\nRun: batho build --root ."]:::error
        OPEN_DB[Open BathoDatabase\nget_database]
        CHECK_RUN{Latest completed\nrun exists?}
        EXIT_NO_RUN["Exit 1: No completed run found.\nRun: batho build --root ."]:::error
    end

    subgraph DETECTION["Phase 2: Change Detection"]
        HASH_SCAN[Hash-scan change detection\nget_all_file_tracking vs filesystem]
        NO_CHANGES{changes\nlist empty?}
        EXIT_NO_CHANGES["Exit 0: No changes detected"]:::success
    end

    subgraph REPARSE["Phase 3: Re-parse Changed Files"]
        CREATE_RUN[Create new run_id: patch_<ts>_<uuid>\nRecord git_commit + git_branch]
        COPY_BLOBS[INSERT INTO file_artifacts SELECT ...\nCopy all unchanged rows from base run]
        PARSE_CHANGED[CodeGraphIndexer\nParse added + modified files]
        INSERT_NEW_BLOBS[insert_file_artifact per changed file\nbsg_agent_view + bsg_storage_view + bsg_rel_view\nzstd-compressed]
    end

    subgraph NODEDIFF["Phase 4: Node-Level Diff"]
        FETCH_OLD[get_agent_entities_for_file\nfrom base run bsg_agent_view blob]
        DIFF_NODES[diff_file_nodes\nfast-path: content_hash compare\ndeep: TRACKED_FIELDS diff\nrename: content_hash match heuristic]
        RECORD_CL[record_file_changelog\nresolve string_dict IDs\nzstd-compress node_changes\nbulk INSERT into file_changelog]
        PRUNE_CL[prune_file_changelog\ndelete entries older than N runs]
    end

    subgraph CONTEXT_REFRESH["Phase 5: Context & Tracking"]
        UPDATE_TRACKING[delete removed files from file_tracking\nupsert added + modified]
        COMPLETE_RUN[complete_run\nentity_count + rel_count + file_count + duration_ms]
    end

    DONE(["Exit 0: Patched root\nN changes applied in Tms\nNodes: A added, R removed, M modified, X renamed"]):::success

    START --> CHECK_DB
    CHECK_DB -->|No| EXIT_NO_DB
    CHECK_DB -->|Yes| OPEN_DB
    OPEN_DB --> CHECK_RUN
    CHECK_RUN -->|No| EXIT_NO_RUN
    CHECK_RUN -->|Yes| HASH_SCAN
    HASH_SCAN --> NO_CHANGES
    NO_CHANGES -->|Yes| EXIT_NO_CHANGES
    NO_CHANGES -->|No| CREATE_RUN

    CREATE_RUN --> COPY_BLOBS
    COPY_BLOBS --> PARSE_CHANGED
    PARSE_CHANGED --> INSERT_NEW_BLOBS
    INSERT_NEW_BLOBS --> FETCH_OLD
    FETCH_OLD --> DIFF_NODES
    DIFF_NODES --> RECORD_CL
    RECORD_CL --> PRUNE_CL
    PRUNE_CL --> UPDATE_TRACKING
    UPDATE_TRACKING --> COMPLETE_RUN
    COMPLETE_RUN --> DONE

    classDef error fill:#fca5a5,stroke:#dc2626,color:#7f1d1d
    classDef success fill:#bbf7d0,stroke:#16a34a,color:#14532d
```

---

## Output

### Success

```
Patched /path/to/repo: 3 changes (1 added, 2 modified, 0 deleted) in 412ms
  Nodes: 5 added, 2 removed, 8 modified, 1 renamed
```

The node summary line only appears when at least one node change was recorded. All node diffs are queryable afterward via `batho diff`.

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

## File Changelog Configuration

The `file_changelog` table is pruned after each patch run. The default retention window is 100 runs. To customize, add to `batho.yaml`:

```yaml
indexer:
  file_changelog_max_runs: 50  # keep last 50 patch runs of node history
```

Query node history at any time with:

```bash
batho diff --entity <entity_id>       # evolution of one node
batho diff --run <run_id>             # all changes in one patch run
batho diff --file src/module.py       # all node changes in a file
```

---

## Error Cases

| Error | Cause | Resolution |
|-------|-------|-----------|
| `No artifact database found` | `batho build` has not been run | Run `batho build --root <path>` first |
| `No completed run found` | DB exists but no successful build has completed | Run `batho build --root <path>` first |
| Schema version mismatch | Database built with older Batho version | Run `batho build --root <path> --full` to rebuild |
| Patch exits with 0 changes | All detected changes map to unindexable files | Expected — `batho export` will still reflect the prior run |

---

## Examples

```bash
# Patch the current directory
batho patch

# Patch a specific repository
batho patch --root /path/to/project

# Verbose output for debugging
batho patch --verbose
```
