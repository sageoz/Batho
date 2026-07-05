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
|---------|---------|
| [`build`](/docs/cli-reference/build-cmd) | Build a complete code graph, BSG map, and baseline snapshot for a repository. |
| [`patch`](/docs/cli-reference/patch-cmd) | Detect changes natively and apply incremental updates to an existing database. |
| [`export`](/docs/cli-reference/export-cmd) | Export BSG artifacts as JSON views or package them into a transport ZIP bundle. |
| [`load`](/docs/cli-reference/load-cmd) | Unpack a transport ZIP bundle (`.batho` file) into the target repository's artifact directory. |
| [`fix`](/docs/cli-reference/fix-cmd) | Verify structural consistency and automatically repair database integrity issues. |
| [`diff`](/docs/cli-reference/diff-cmd) | Track granular node evolution and print node-level diff history across runs, files, or entities. |
| [`gc`](/docs/cli-reference/gc-cmd) | Clean up old runs, sweep orphaned files, and vacuum the Arrow IPC database. |
| [`mcp`](/docs/cli-reference/mcp-cmd) | Start the Batho MCP server for AI agent integration. |

## Global CLI Flags

The following flags are shared across all `batho` subcommands:

| Flag | Default | Description |
|------|---------|-------------|
| `--root PATH` | `.` | Repository root directory to scan or target. |
| `--verbose` | `false` | Enable verbose debug logging to standard error. |
| `-h`, `--help` | - | Show the help message for `batho` or a specific subcommand. |
