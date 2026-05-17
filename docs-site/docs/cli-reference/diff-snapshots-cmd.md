---
sidebar_position: 17
title: "diff-snapshots"
description: "Diff two snapshots"
---

# `diff-snapshots` Command

Compare two Time Machine snapshots to see how code intelligence has changed over time.

## Usage

```bash
batho diff-snapshots --root /path/to/repo --snapshot-a SNAP_A --snapshot-b SNAP_B
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--root` | required | Path to repository root |
| `--snapshot-a` | required | First snapshot ID (baseline) |
| `--snapshot-b` | required | Second snapshot ID (comparison) |

## Finding Snapshot IDs

```bash
# List all snapshots to find IDs
batho snapshots --root .
```

## Output

The diff output shows:

- **Entities added**: New functions, classes, variables
- **Entities removed**: Deleted code elements
- **Entities modified**: Changed signatures or metadata
- **Relationship changes**: New/removed imports, calls, uses
- **File changes**: Files added, removed, or modified

## Examples

```bash
# Compare two specific snapshots
batho diff-snapshots --root . \
  --snapshot-a batho_project_abc123_20260501T100000Z.json \
  --snapshot-b batho_project_def456_20260517T120000Z.json

# Use short snapshot IDs (first 12 chars)
batho diff-snapshots --root . \
  --snapshot-a abc123_20260501 \
  --snapshot-b def456_20260517
```

## Use Cases

- **Release analysis**: Compare code changes between versions
- **Impact assessment**: Understand what changed in a feature branch
- **Audit trail**: Track code evolution over time
- **Debugging**: Identify when a specific change was introduced

## Related Commands

- `snapshots` - List all available snapshots
- `patch` - Apply incremental changes
- `patch-chain` - Show patch history for a snapshot
