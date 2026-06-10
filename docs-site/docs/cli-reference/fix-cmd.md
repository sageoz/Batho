---
title: "batho fix"
description: "Verify and repair database integrity"
---

# `batho fix`

Verify structural consistency and repair issues within the Batho artifact database.

## Description

The `fix` command runs structural validation routines on the Arrow database, state indices, cache blobs, and graphs. Detections of corrupt records or broken relation chains will be repaired automatically unless running in check-only mode.

## Usage

```bash
batho fix [options]
```

## Options

- `--root PATH`
  Repository root directory (default: current directory `.` ).
- `--verbose`
  Enable verbose debug logging.
- `--dry-run`
  Check for issues only; do not modify any files or write repairs to the database.
- `--deep`
  Decompress and validate the integrity of every individual blob stored in the database (slower check).
- `--target {db,state,blobs,graph,all}`
  Target a specific validation checker. Default: `all`.
- `--phase {1,2,3,4}`
  Run only a specific checker phase (1-4).
- `--parallel`
  Execute independent target checkers concurrently.
- `--format {text,json,csv}`
  The format of the integrity report. Default: `text`.
- `--output PATH`
  Write the integrity report to a file instead of stdout.

## Integrity Verification Workflow

1. **Phase 1: Database Check** — Verifies Arrow file markers and checks schema version integrity.
2. **Phase 2: State Validation** — Validates baseline configurations and tracking timelines.
3. **Phase 3: Blob Check** — Verifies hash checksums of file snapshots and compressed payloads.
4. **Phase 4: Graph Consistency** — Validates symbol mappings, parent-child links, and dangling edges.
