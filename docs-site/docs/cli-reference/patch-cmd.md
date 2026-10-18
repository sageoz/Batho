---
title: "batho patch"
description: "Incremental patch of an existing artifact database"
---

# `batho patch`

Detect changes natively and apply incremental updates to an existing Batho artifact database.

## Description

Unlike legacy versions of Batho, `batho patch` detects changes natively using content hashing (SHA-256) of files against the Arrow `file_tracking` table, eliminating false positives from uncommitted files. It only parses modified or added files and removes references to deleted files, keeping the hypergraph up to date with minimal processing time.

When the plugin fingerprint differs from the previous run (a plugin was added, removed, or reconfigured), the change set escalates to every tracked file — a full-repo re-extraction so entities on unchanged files are re-stamped under the current plugin set. Controlled by `plugins.reextract_on_drift` (default `true`; set `false` for warn-only). Escalated runs log a `patch_drift_escalation` warning with tracked/scanned/synthesized counts and scale extraction workers up to `bsg.parallel.max_workers` (a single worker when `bsg.parallel.enabled` is `false`). Synthesized entries respect the patch ignore spec and repository containment, and the AST cache is cleared wholesale so no stale entries survive the plugin change.

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
- `--no-progress`
  Disable progress bars (also: `BATHO_NO_PROGRESS=1`).

## Progress Output

Phase progress renders on **stderr** in the same pytest style as `batho build`:

```
  detect    done (0.3s)
  extract   [ 45%] 18/41
  persist   done (0.2s)
✓ patched in 2.8s — 41 changes (1 added, 40 modified, 0 deleted)
```

- The live `[ NN%]` bar appears only when at least 25 files changed and the phase runs longer
  than 2 seconds; smaller patches complete with timing lines only.
- When stderr is not a terminal (piped output, CI), one completion line per phase is printed
  instead of an animated bar.
- `NO_COLOR` disables color but keeps the bar.

### Disabling progress

```bash
batho patch --no-progress
# or
BATHO_NO_PROGRESS=1 batho patch
```

## Output Summary

If changes are detected, the command outputs a detailed summary of modified entities:

```
✓ patched in 2.8s — 41 changes (1 added, 40 modified, 0 deleted)
  Nodes: 4 added, 0 removed, 2 modified, 0 renamed
```

If no changes are detected since the last index/patch, it outputs:

```
No changes detected.
```

## Limitations

Derived cross-file edges — `OVERRIDES` (from `CONTAINS`+`INHERITS`) and doc→module
`RATIONALE_FOR` (markdown path mentions) — are computed over the patch batch only.
A changed doc that mentions an *unchanged* module, or an override spanning a changed
file and an unchanged file, emits no edge until the next full `batho build`, which
re-derives them over the complete entity set. Run a periodic full build to refresh
these annotation edges.
