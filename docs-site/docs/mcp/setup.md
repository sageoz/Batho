---
sidebar_position: 2
title: "Setup Guide"
description: "Configure and start the Batho MCP server"
---

# MCP Setup Guide

> **Tip**  
> **Let your AI agent handle setup**  
>  
> Don't want to edit JSON configs manually? Give the [Batho Setup Skill](https://github.com/sageoz/batho/blob/main/SKILL.md) to your AI agent. It will auto-detect your clients and write the MCP config for you.  
> See: [Setup with AI Agent Skill](/docs/getting-started/skill-setup)


## Prerequisites

Before starting the MCP server, you need a pre-built Batho artifact:

```bash
# Install Batho (if not already installed)
pip install batho
# or
python -m pip install batho
# or
python3 -m pip install batho
# or (faster alternative)
uv pip install batho
# or (isolated global CLI install)
pipx install batho

# Build the code graph for your repository
batho build --root /path/to/your/repo --verbose
```

This creates Arrow IPC artifacts in `/path/to/your/repo/.batho/artifact/`. The MCP server reads these files — it does not parse source code at runtime.

## Starting the Server

### Default: Registry Mode

```bash
# Start MCP server — auto-loads ~/.batho/mcp-repos.json
batho mcp
```

The server runs on **stdio transport** — it reads JSON-RPC messages from stdin and writes responses to stdout. This is the standard MCP transport for local AI agent integration.

If `~/.batho/mcp-repos.json` exists and contains repo entries, the server starts in **multi-repo mode**. If not, it falls back to the `--root` flag or current working directory.

### Legacy: Single-Repo Mode

```bash
# Specify root explicitly (backward compat)
batho mcp --root /path/to/your/repo
```

Use this if you have a single repo and prefer not to use the registry.

### Repo Resolution

The MCP server resolves which repo to query in this order:

1. **`repo` tool parameter** — `graph_overview(repo="myapp")` (highest priority)
2. **Registry default** — First entry in `~/.batho/mcp-repos.json`
3. **`--root` flag** — `batho mcp --root /path/to/repo` (backward compat)
4. **Current working directory** — `cd /path/to/repo && batho mcp` (auto-detection)

If no artifact is found, tools will return an error message guiding the user to run `batho build` first.

### Multiple Sessions

Each `batho mcp` process is independent. In registry mode, a single process serves all registered repos:

```bash
# One process, multiple repos via registry
batho mcp
```

Multiple agents can connect to the same server process. Each process has its own memory-mapped reader cache.

## Client Configuration (One-Time)

Configure your AI client once. No `--root` needed — the agent manages repos via MCP tools.

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "batho": {
      "command": "batho",
      "args": ["mcp"]
    }
  }
}
```

Restart Claude Desktop. The Batho tools will appear in the tool list.

### Cursor

Create or edit `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "batho": {
      "command": "batho",
      "args": ["mcp"]
    }
  }
}
```

Cursor reads this file automatically. Reload the window to apply changes.

### Windsurf

Edit `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "batho": {
      "command": "batho",
      "args": ["mcp"]
    }
  }
}
```

Restart Windsurf or reload the MCP server list.

### VS Code (with Continue or MCP extension)

Configure per your MCP extension's documentation. The command is always:

```bash
batho mcp
```

## Registering Repos

After configuring your client, register repos from agent chat:

```
User: Add my project at /projects/myapp
Agent: [calls add_repo(name="myapp", path="/projects/myapp")]
       Registered "myapp" — 892 entities, 312 files. Artifact: ready.

User: What repos are available?
Agent: [calls list_repos()]
       - myapp: /projects/myapp (892 entities, ready)
```

The registry is stored at `~/.batho/mcp-repos.json` and persists across server restarts.

## Verification

After configuring your client, verify the MCP server is working:

1. **Check tool list** — Your AI agent should show 10 Batho tools: `list_repos`, `add_repo`, `remove_repo`, `graph_overview`, `graph_query`, `get_entity`, `trace_path`, `get_file_graph`, `search_entities`, `get_delta`

2. **Register a repo** — Ask your agent: "Add repo myapp at /path/to/repo." It should call `add_repo` and confirm registration.

3. **List repos** — Ask: "What repos are available?" The agent should call `list_repos` and show registered repos with status.

4. **Call `graph_overview`** — Ask: "Give me an overview of myapp." It should call `graph_overview(repo="myapp")` and return entity counts, file list, and community summaries.

5. **Search for a function** — Ask: "Find functions named `main` in myapp." The agent should use `search_entities` with `query="main"` and `repo="myapp"`.

6. **Check incremental updates** — After running `batho patch`, call `get_delta` to see what changed. The server serves the latest generation automatically — no restart needed.

## Troubleshooting

| Issue | Solution |
|-------|---------|
| "No Batho artifact found" | Run `batho build --root /path/to/repo` first |
| "No repos registered" | Call `add_repo(name, path)` from agent chat to register a repo |
| "Repo not found in registry" | Call `list_repos` to see available repos, then use the correct `repo` name |
| Tools not appearing in client | Restart the client application after editing config |
| Server crashes on startup | Check that `batho` is on PATH: `which batho` |
| Stale data after patch | The server auto-invalidates on new generations. If issues persist, restart the server. |
| High memory usage | Memory-mapped I/O is lazy — only loaded tables consume RSS. Large repos may use 30–50MB. |

## Next Steps

- [Single-Repo Guide](/docs/mcp/single-repo) — Complete walkthrough with examples
- [Multi-Repo Guide](/docs/mcp/multi-repo) — Configure multiple repositories
- [Tools Reference](/docs/mcp/tools-reference) — All 10 tools documented
