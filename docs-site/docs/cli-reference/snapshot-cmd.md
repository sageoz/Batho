---
sidebar_position: 3
title: "snapshots & diff-snapshots"
description: "Time Machine snapshot commands"
---

# `snapshots` & `diff-snapshots` Commands

## `snapshots`

List stored snapshots.

```bash
batho snapshots --root /path/to/repo
```

## `diff-snapshots`

Compare two snapshots.

```bash
batho diff-snapshots --root /path/to/repo --snapshot-a SNAP_A --snapshot-b SNAP_B
```

## Examples

```bash
# List all snapshots
batho snapshots --root .

# Compare two snapshots
batho diff-snapshots --root . SNAP_A SNAP_B
```
