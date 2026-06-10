---
title: "batho patch"
description: "Incremental patch of an existing artifact database"
---

# `batho patch`

Detect changes natively and apply incremental updates to an existing Batho artifact database.

## Description

Unlike legacy versions of Batho, `batho patch` detects changes natively using content hashing (SHA-256) of files against the Arrow `file_tracking` table, eliminating false positives from uncommitted files. It only parses modified or added files and removes references to deleted files, keeping the hypergraph up to date with minimal processing time.

## Usage

```bash
batho patch [options]
```

## Options

- `--root PATH`
  Repository root directory (default: current directory `.` ).
- `--verbose`
  Enable verbose debug logging.
- `--max-file-size-kb N`
  Skip files exceeding this size limit in kilobytes during the hash scan.

## Output Summary

If changes are detected, the command outputs a detailed summary of modified entities:

```
Patched /path/to/repo: 3 changes (2 added, 1 modified, 0 deleted) in 85ms
  Nodes: 4 added, 0 removed, 2 modified, 0 renamed
```

If no changes are detected since the last index/patch, it outputs:

```
No changes detected.
```
