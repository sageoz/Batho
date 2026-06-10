---
title: "batho diff"
description: "Query node-level changes across runs, entities, or files"
---

# `batho diff`

Track granular node evolution and print node-level diff history.

## Description

The `diff` command queries differences across database snapshots at the level of specific functions, classes, and variables. Diffs can be scoped by target run IDs, specific entities, or file paths.

## Usage

```bash
batho diff <Target Option> [options]
```

### Target Options (Mutually Exclusive - Exactly One Required)

- `--run UUID`
  Show all node-level changes applied in a specific patch run UUID.
- `--entity ID`
  Show the full evolution history of a specific entity ID.
- `--file PATH`
  Show all node-level changes in a specific file across all runs (specify path relative to repository root).

## Options

- `--root PATH`
  Repository root directory (default: current directory `.` ).
- `--verbose`
  Enable verbose debug logging.
- `--since UUID`
  Bounded history start run ID (only applicable when querying history via `--entity`).
- `--json`
  Output the results in machine-readable JSON format instead of human-readable text.

## Example Output

```bash
batho diff --run 2f4d6d63-549b-4ffc-a3c3-882f099c27e8
```

```
Run: 2f4d6d63-549b-4ffc-a3c3-882f099c27e8 (base: 1a8c886a-72ef-4573-9828-9ea0ef50d75a)

Modified nodes:
  - [method] create in src/services/user.py (ID: UserService.create)
    signature  def create(self, name: str) -> User: → def create(self, name: str, email: str) -> User:
```
