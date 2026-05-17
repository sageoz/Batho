---
sidebar_position: 20
title: "patch-chain"
description: "Show patch chain for a snapshot"
---

# `patch-chain` Command

Display the chain of patches that lead to a specific snapshot, showing the evolution of code intelligence over time.

## Usage

```bash
batho patch-chain --root /path/to/repo --snapshot-id SNAPSHOT_ID [options]
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--root` | required | Path to repository root |
| `--snapshot-id` | required | Target snapshot ID |
| `--full` | off | Show full details for each patch |

## Finding Snapshot IDs

```bash
# List all snapshots to find IDs
batho snapshots --root .
```

## Examples

```bash
# Show patch chain summary
batho patch-chain --root . --snapshot-id batho_project_def456_20260517T120000Z.json

# Show full details for each patch
batho patch-chain --root . --snapshot-id batho_project_def456_20260517T120000Z.json --full

# Use short snapshot ID
batho patch-chain --root . --snapshot-id def456_20260517
```

## Output

### Summary Format (default)

```
Snapshot: batho_project_def456_20260517T120000Z.json
Base: batho_project_abc123_20260501T100000Z.json

Patch Chain (3 patches):
  1. batho_uuid1_20260516T100000Z - incremental (8 files, +25/-5 entities)
  2. batho_uuid2_20260516T183000Z - diff (3 files, +12/-2 entities)
  3. batho_uuid3_20260517T120000Z - incremental (15 files, +42/-8 entities)
```

### Full Format (--full)

Includes complete details for each patch in the chain:

```
Snapshot: batho_project_def456_20260517T120000Z.json
Base: batho_project_abc123_20260501T100000Z.json

Patch Chain (3 patches):

1. batho_uuid1_20260516T100000Z
   Type: incremental
   Time: 2026-05-16T10:00:00Z
   Files: 8 changed
   Entities: +25 added, -5 removed
   Duration: 1.8s

2. batho_uuid2_20260516T183000Z
   Type: diff
   Time: 2026-05-16T18:30:00Z
   Files: 3 changed
   Entities: +12 added, -2 removed
   Duration: 0.9s

3. batho_uuid3_20260517T120000Z
   Type: incremental
   Time: 2026-05-17T12:00:00Z
   Files: 15 changed
   Entities: +42 added, -8 removed
   Duration: 2.3s
```

## Use Cases

- **Lineage tracking**: Understand how a snapshot was built
- **Impact analysis**: See cumulative changes over time
- **Rollback planning**: Identify which patches to reverse
- **Audit**: Document the evolution of code intelligence

## Related Commands

- `snapshots` - List all snapshots
- `patches` - List all patch operations
- `patch-info` - Show details for a specific patch
