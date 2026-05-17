---
sidebar_position: 9
title: "storage, cache & invalidate"
description: "Storage, cache, and index management commands"
---

# `storage`, `cache` & `invalidate` Commands

## `invalidate`

Clear index file cache.

```bash
batho invalidate --root /path/to/repo
```

## `cache`

AST cache management.

```bash
# Show cache statistics
batho cache stats

# Invalidate matching patterns
batho cache invalidate "**/*.py"

# Clear all cache entries
batho cache clear
```

## `storage`

Persistent artifact registry tools.

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
