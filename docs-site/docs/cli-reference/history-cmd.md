---
title: "batho history"
description: "List indexing runs and query node-level changes across runs, entities, or files"
---

# `batho history`

List recent indexing runs and track granular node evolution over time.

## Description

The `history` command is the time-machine surface of the artifact bundle. Run without arguments it lists the most recent runs (newest first); with a target flag it prints node-level change history — a specific run's changes, one entity's evolution, or one file's history across runs.

## Usage

```bash
batho history [Target Option] [options]
```

### Target Options (Mutually Exclusive)

- *(none)*
  List recent runs — default page size 10.
- `--run UUID`
  Show all node-level changes applied in a specific patch run UUID.
- `--entity ID`
  Show the evolution history of a specific entity ID (default: last 10 entries).
- `--file PATH`
  Show node-level changes in a specific file across runs (default: last 10 transitions; specify path relative to repository root).

## Options

- `--root PATH`
  Repository root directory (default: current directory `.` ).
- `--verbose`
  Enable verbose debug logging.
- `--last N`
  Page size / cap: number of runs in list mode, history entries with `--entity`, transitions with `--file`. Ignored with `--run`.
- `--since UUID`
  Bounded history start run ID (only applicable with `--entity`).
- `--json`
  Output the results in machine-readable JSON format instead of human-readable text.

## Example Output

```bash
batho history --last 5
```

```
patch_1790934134_46a508e9  patch          completed  2026-10-02T09:42:14+00:00  files=3  entities=1241  95ms  commit=a1b2c3d4
build_1790915075_2c9dd23a  build          completed  2026-10-02T09:31:05+00:00  files=3  entities=1237  412ms  commit=-

showing 2 of 2 runs (--last N to adjust)
```

```bash
batho history --run patch_1790934134_46a508e9
```

```
Run: patch_1790934134_46a508e9 (base: patch_1790934102_2b4f3fd2)

Modified nodes:
  - [method] create in src/services/user.py (ID: UserService.create, fields: signature)
```

> **Renamed**: this command was previously `batho diff`. The old name no longer exists.
