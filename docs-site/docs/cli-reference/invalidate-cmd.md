---
sidebar_position: 16
title: "invalidate"
description: "Clear AST cache"
---

# `invalidate` Command

Clear the AST (Abstract Syntax Tree) cache to force a full re-parse on the next index operation.

## Usage

```bash
batho invalidate --root /path/to/repo
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--root` | required | Path to repository root |

## What It Does

The `invalidate` command deletes the AST cache database at `.ctn/local/cache/cache.db`. This cache stores parsed tree-sitter AST results to avoid re-parsing unchanged files.

Clearing this cache forces Batho to re-parse all files on the next `index` operation, even if they haven't changed.

## When to Use

Use `invalidate` when:

- You suspect the AST cache is corrupted
- Parser behavior changed (e.g., after a Batho update)
- You want to force a complete re-parse without using `--full`
- Debugging parser or indexing issues

## Examples

```bash
# Clear file cache for current directory
batho invalidate --root .

# Clear file cache for specific project
batho invalidate --root /path/to/project

# Then re-index with fresh scan
batho index --root . --verbose
```

## Difference from `--full`

| Command | What it clears | When to use |
|---------|----------------|-------------|
| `invalidate` | AST cache database | Suspected cache corruption, parser issues |
| `index --full` | Disables incremental reuse | Complete rebuild needed |
| `cache clear` | AST cache database (same as `invalidate`) | Parser issues, language version changes |

## Related Commands

- `cache clear` - Clear AST parser cache
- `cache invalidate` - Invalidate AST entries by pattern
- `index --force` - Clear both caches before indexing
