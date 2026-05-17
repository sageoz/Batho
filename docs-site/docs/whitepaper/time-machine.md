---
sidebar_position: 6
title: "5. Time Machine & Incremental Patching"
description: "Snapshots, incremental patch lifecycle, and patch operations"
---

# 5. Time Machine & Incremental Patching

## 5.1 Snapshot Format

```json
{
  "snapshot_id": "batho_<uuid>_<timestamp>",
  "schema_version": "snapshot.v1",
  "root": "/path/to/repo",
  "created_at": "2026-05-17T12:00:00Z",
  "graph": { /* InMemoryGraph serialized */ },
  "bsg": { /* BSGMap serialized */ },
  "metadata": {
    "git_commit": "abc123",
    "entity_count": 15420,
    "relationship_count": 48230
  }
}
```

## 5.2 Incremental Patch Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Detected: File hash scan
    Detected --> Validated: Check patch limits
    Validated --> Applied: Apply to base snapshot
    Applied --> ConsistencyCheck: Validate graph
    ConsistencyCheck --> Snapshotted: Create new snapshot
    ConsistencyCheck --> Warning: Non-fatal inconsistency
    Warning --> Snapshotted: Continue with warning
    Applied --> RolledBack: Application failure
    RolledBack --> [*]: Log and exit
    Snapshotted --> [*]: Record PatchOperation
```

## 5.3 Patch Operation Record

| Field | Type | Description |
|-------|------|-------------|
| `operation_id` | UUID | Unique patch identifier |
| `base_snapshot_id` | string | Source snapshot |
| `new_snapshot_id` | string | Result snapshot |
| `changes_applied` | FileChange[] | Ordered change list |
| `patch_chain` | string[] | Lineage chain |
| `metrics` | object | Timing, token size, file counts |
| `checksum` | SHA-256 | Integrity hash |

## 5.4 CLI Commands

| Command | Purpose |
|---------|---------|
| `batho index --root . --snapshot` | Create snapshot |
| `batho snapshots --root .` | List snapshots |
| `batho diff-snapshots --root . A B` | Compare two snapshots |
| `batho patch --root . --scan` | Auto-detect and apply changes |
| `batho patches --root . --format timeline` | List patch history |
| `batho patch-info --root . --patch-id ID` | Show patch details |
| `batho apply-patch --root . --base-snapshot ID --diff-file changes.diff` | Apply from diff |
| `batho cherry-pick --root . --patch-id ID --target-snapshot ID` | Cross-snapshot cherry-pick |
