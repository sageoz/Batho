---
title: "batho gc"
description: "Garbage collection and database maintenance"
---

# `batho gc`

Clean up old runs, sweep orphaned files, and perform database maintenance to reduce artifact size.

## Description

The `gc` command frees storage space by removing outdated analysis states. It manages retention policies and deletes unreferenced files.

## Usage

```bash
batho gc [options] <Subcommand>
```

## Options

- `--root PATH`
  Repository root directory (default: current directory `.` ).
- `--verbose`
  Enable verbose debug logging.

## Subcommands

### `run <UUID>`
Deletes a specific index/patch run and all of its associated artifacts (blobs and database records).

### `runs --older-than N`
Deletes all index and patch runs older than `N` days.

### `vacuum`
Sweeps orphaned Arrow IPC generations and shrinks the database file size on disk using SQL `VACUUM`.

### `orphans`
Removes stale IPC files from the storage directories that are no longer referenced by any active generation in the database.

### `status`
Displays current storage statistics, including:
- Total bundle database size on disk.
- Number of active generations.
- Total number of registered runs.
