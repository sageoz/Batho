---
title: "batho build"
description: "Full index build for a repository"
---

# `batho build`

Build a complete code graph, BSG map, and baseline snapshot for a repository. If the artifact bundle already exists, the command will exit with guidance to use `batho patch` for incremental updates.

## Description

The `build` subcommand performs a full analysis of the codebase. It discovers files (respecting `.gitignore`), parses them using tree-sitter, extracts entities and relationships, resolves cross-file symbols, and serializes the result into an Arrow IPC Bundle saved in the `.batho/artifact/` directory.

## Usage

```bash
batho build [options]
```

## Options

- `--root PATH`
  Repository root directory (default: current directory `.` ).
- `--verbose`
  Enable verbose debug logging.
- `--full`
  Force a full rebuild. This will delete any existing database and rebuild the entire graph from scratch.
- `--max-workers N`
  Maximum parallel worker threads for parsing files (default: automatically matches the CPU thread count).
- `--max-file-size-kb N`
  Skip files exceeding this size limit in kilobytes during indexing.

## Output Summary

Upon a successful build, the command outputs a summary formatted as follows:

```
Built /path/to/repo: 1542 entities, 4823 relationships, 312 files in 1245ms
```
