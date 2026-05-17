---
sidebar_position: 3
title: "snapshots"
description: "List stored Time Machine snapshots"
---

# `snapshots` Command

List all stored Time Machine snapshots with their IDs, timestamps, and metadata.

## Usage

```bash
batho snapshots --root /path/to/repo
```

## Examples

```bash
# List all snapshots
batho snapshots --root .

# List snapshots for specific project
batho snapshots --root /path/to/project
```

## Output

The command outputs a list of snapshots with:
- Snapshot ID (format: `batho_<project>_<sha>_<timestamp>Z`)
- Timestamp (ISO 8601)
- Label (optional user-defined label)
- File path

## Related Commands

- [diff-snapshots](/docs/cli-reference/diff-snapshots-cmd) - Compare two snapshots
- [patch](/docs/cli-reference/patch-cmd) - Apply incremental patches
- [patch-chain](/docs/cli-reference/patch-chain-cmd) - Show patch chain for a snapshot
