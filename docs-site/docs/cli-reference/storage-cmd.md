---
sidebar_position: 9
title: "storage"
description: "Persistent artifact registry management"
---

# `storage` Command

Persistent artifact registry tools for managing the SQLite-based artifact storage system.

## Usage

```bash
batho storage <subcommand> --root /path/to/repo
```

## Subcommands

| Subcommand | Purpose |
|-----------|---------|
| `backfill` | Register existing durable .ctn artifacts in the SQLite registry |
| `verify` | Verify registry consistency and optionally repair metadata drift |
| `cleanup` | Apply retention cleanup (dry-run by default) |
| `stats` | Show registry and persisted graph cache statistics |
| `rebuild-indexes` | Rebuild persisted query indexes from graph.json |
| `compact` | Deduplicate registry entries (dry-run by default) |

## Examples

```bash
# Backfill registry from existing artifacts
batho storage backfill --root /path/to/repo

# Verify and optionally repair artifacts
batho storage verify --root /path/to/repo --repair

# Clean old artifacts (dry-run)
batho storage cleanup --root /path/to/repo

# Execute cleanup
batho storage cleanup --root /path/to/repo --apply

# Show registry statistics
batho storage stats --root /path/to/repo

# Rebuild indexes
batho storage rebuild-indexes --root /path/to/repo

# Compact registry (dry-run)
batho storage compact --root /path/to/repo

# Execute compaction
batho storage compact --root /path/to/repo --apply
```

## Related Commands

- [cache](/docs/cli-reference/cache-cmd) - AST cache management
- [invalidate](/docs/cli-reference/invalidate-cmd) - Clear index file cache
