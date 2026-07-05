---
title: "batho mcp"
description: "Start the Batho MCP server"
---

# `batho mcp`

Start the Batho MCP (Model Context Protocol) server on stdio transport. AI agents connect via MCP to query pre-built code graph artifacts.

## Description

The `mcp` subcommand starts a stdio-based MCP server that reads pre-built `.batho` Arrow IPC artifacts. It uses zero-copy memory-mapped I/O for sub-millisecond query latency. The server auto-loads `~/.batho/mcp-repos.json` at startup and exposes 10 tools: `list_repos`, `add_repo`, `remove_repo`, `graph_overview`, `graph_query`, `get_entity`, `trace_path`, `get_file_graph`, `search_entities`, and `get_delta`.

## Usage

```bash
batho mcp [options]
```

## Options

- `--root PATH`
  Repository root directory containing the `.batho/artifact/` directory. Defaults to the current working directory. **Optional** — if `~/.batho/mcp-repos.json` contains repo entries, the server starts in multi-repo mode and `--root` is not needed.

## Repo Resolution

The server resolves which repo to query in this order:

1. **`repo` tool parameter** — `graph_overview(repo="myapp")` (highest priority)
2. **Registry default** — First entry in `~/.batho/mcp-repos.json`
3. **`--root` flag** — `batho mcp --root /path/to/repo` (backward compat)
4. **Current working directory** — `cd /path/to/repo && batho mcp` (auto-detection)

If no artifact is found, the server logs a warning but still starts. Tool calls will return an error guiding the user to run `batho build` first.

## Examples

```bash
# Registry mode (recommended) — auto-loads ~/.batho/mcp-repos.json
batho mcp

# Legacy: specify root explicitly
batho mcp --root /path/to/my/project

# Use in MCP client config (Claude Desktop, Cursor, Windsurf)
# "args": ["mcp"]
```

## Multiple Sessions

Each `batho mcp` invocation starts an independent process. In registry mode, a single process serves all registered repos:

```bash
# One process, multiple repos via registry
batho mcp
```

Multiple agents can connect to the same or different server processes. Each process has its own memory-mapped reader cache.

## Artifact Requirements

The server requires pre-built artifacts. Run `batho build` before starting the server:

```bash
batho build --root /path/to/repo --verbose
batho mcp
```

After `batho patch`, the server automatically serves the new generation on the next tool call — no restart needed.

## See Also

- [MCP Setup Guide](/docs/mcp/setup) — Client configuration for Claude Desktop, Cursor, Windsurf
- [Single-Repo Guide](/docs/mcp/single-repo) — Complete walkthrough
- [Multi-Repo Guide](/docs/mcp/multi-repo) — Multiple repositories
- [Tools Reference](/docs/mcp/tools-reference) — All 10 tools documented
