---
sidebar_position: 14
title: "cache"
description: "AST cache management"
---

# `cache` Command

Manage the AST (Abstract Syntax Tree) cache for improved indexing performance.

## Usage

```bash
batho cache <subcommand> [options]
```

## Subcommands

| Subcommand | Purpose |
|-----------|---------|
| `stats` | Show cache statistics |
| `invalidate` | Invalidate cache entries matching a pattern |
| `clear` | Clear entire cache |

## `cache stats`

Display cache statistics including size, hit rate, and entry counts.

```bash
batho cache stats
```

### Output

```
📊 AST Cache Statistics
  Cache path: .ctn/local/cache/cache.db
  Entry count: 1523
  Total size: 45.2 MB
  Oldest entry: 2026-05-10T08:30:00Z
  Newest entry: 2026-05-17T12:00:00Z
```

## `cache invalidate`

Invalidate cache entries matching a glob pattern.

```bash
# Invalidate all Python files
batho cache invalidate "**/*.py"

# Invalidate specific directory
batho cache invalidate "src/**"

# Invalidate without pattern (shows usage)
batho cache invalidate
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `pattern` | No | Glob pattern to match files for invalidation |

### Common Patterns

| Pattern | Matches |
|---------|---------|
| `**/*.py` | All Python files recursively |
| `src/**/*.ts` | All TypeScript files in src/ |
| `**/*.min.js` | All minified JavaScript files |

## `cache clear`

Clear the entire AST cache database.

```bash
batho cache clear
```

**Warning**: This will force a full re-parse on the next index operation. Use `invalidate` for selective clearing.

## Cache Behavior

The AST cache stores parsed tree-sitter results to avoid re-parsing unchanged files. Cache entries are keyed by:

- File content SHA-256 hash
- Tree-sitter language version
- Parser configuration

Cache is automatically invalidated when:
- File content changes (detected via mtime + hash)
- Batho version changes (parser updates)
- Explicit `invalidate` or `clear` commands

## Use Cases

- **Performance**: Maintain >95% cache hit rate for fast incremental indexing
- **Debugging**: Clear cache when investigating parser issues
- **Selective updates**: Invalidate specific file types after language version changes
- **Maintenance**: Monitor cache size and hit rate for capacity planning
