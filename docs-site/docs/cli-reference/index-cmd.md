---
sidebar_position: 2
title: "index"
description: "Build and update graph + BSG artifacts"
---

# `index` Command

Build/update graph + BSG artifacts for a repository.

## Usage

```bash
batho index --root /path/to/repo --verbose
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--max-workers` | `0` (auto) | Worker threads — 0 uses CPU × 2, capped at 32 |
| `--max-file-size-kb` | `500` | Skip files larger than this |
| `--extensions` | all supported | Restrict indexing to selected extensions |
| `--full` | off | Disable incremental reuse and force full rebuild |
| `--force` | off | Clear AST cache before indexing |
| `--no-ast-cache` | off | Bypass AST cache for the current indexing run |
| `--base-snapshot` | `None` | Optional base snapshot ID for incremental indexing (auto-detects latest if omitted) |
| `--output-json` | none | Optional override path for graph JSON output |
| `--metrics-output` | from config | Write metrics JSON to explicit path |
| `--verbose` | off | Print progress to stdout |
| `--snapshot` | off | Create snapshot after indexing |
| `--snapshot-label` | none | Attach label to generated snapshot |

## Examples

```bash
# Full index
batho index --root /path/to/repo --verbose

# Force full rebuild (disable incremental path)
batho index --root /path/to/repo --full

# Force cache reset before indexing (clears file cache + AST cache)
batho index --root /path/to/repo --force

# Deterministic fresh parse run (bypass AST cache for this invocation)
batho index --root /path/to/repo --force --no-ast-cache --verbose

# Index and create snapshot
batho index --root /path/to/repo --snapshot --snapshot-label "release-candidate"
```
