---
sidebar_position: 1
title: "CLI Reference Overview"
description: "Complete batho CLI command reference"
---

# CLI Reference

```bash
# Show all commands
batho --help

# Show command-specific help
batho <command> --help
```

## Command Matrix

| Command | Purpose |
|------|---------|
| `index` | Build/update graph + BSG artifacts for a repo |
| `stats` | Show current index metadata and health summary |
| `snapshots` | List stored snapshots |
| `diff-snapshots` | Diff two snapshots |
| `patch` | Apply incremental updates from scan/diff/files |
| `patches` | List patch operations |
| `patch-info` | Show patch operation details |
| `patch-chain` | Show chain of patches for a snapshot |
| `apply-patch` | Apply patch by diff file or patch id |
| `cherry-pick` | Apply a patch to another snapshot |
| `sync` | Sync pending artifacts to configured cloud endpoint |
| `hooks` | Git client-side hook management (install/remove/run) |
| `invalidate` | Clear index file cache |
| `cache` | AST cache management (`stats`, `invalidate`, `clear`) |
| `storage` | Persistent artifact registry tools (`backfill`, `verify`, `cleanup`, `stats`, `rebuild-indexes`, `compact`) |
| `query` | Query persisted entity/relationship indexes |
| `dashboard` | Launch the interactive web dashboard |
| `bsg` | Render BSG outputs (`compressed`, `full`, `hierarchical`) |

## Global Logging Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--log-level` | from config | Override logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) |
| `-q`, `--quiet` | from config | Suppress non-error CLI output and log events below `ERROR` |
| `--log-json` | off | Force JSON log output (useful in CI) |
| `--log-file` | from config | Write logs to the specified file path |
