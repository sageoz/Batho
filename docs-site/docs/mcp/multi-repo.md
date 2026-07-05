---
sidebar_position: 4
title: "Multi-Repo Guide"
description: "Configure Batho MCP for multiple repositories and multi-agent workflows"
---

# Multi-Repository Setup

Batho MCP supports multiple repositories through a single server process with a JSON-based repo registry. One MCP client config entry serves all your repos — no need to edit client config when adding or removing repos. This guide covers the registry pattern, legacy single-repo mode, and monorepo strategies.

## Pattern 1: Registry Mode (Recommended)

The registry is a JSON file at `~/.batho/mcp-repos.json` that maps repo names to filesystem paths. The MCP server auto-loads it at startup. The AI agent can add, list, and remove repos via MCP tools — no client config changes needed.

### One-Time Client Config

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

### Registering Repos from Agent Chat

```
User: Add my frontend repo at /projects/frontend
Agent: [calls add_repo(name="frontend", path="/projects/frontend")]
       Registered "frontend" — 892 entities, 180 files. Artifact: ready.

User: Add my backend repo at /projects/backend
Agent: [calls add_repo(name="backend", path="/projects/backend")]
       Registered "backend" — 650 entities, 95 files. Artifact: ready.

User: What repos are available?
Agent: [calls list_repos()]
       - frontend: /projects/frontend (892 entities, ready)
       - backend: /projects/backend (650 entities, ready)
```

### Querying Specific Repos

Pass the `repo` parameter to any tool:

```
User: Show me the overview of backend
Agent: [calls graph_overview(repo="backend")]
       650 entities, 1200 relationships, 95 files...

User: Search for validate in frontend
Agent: [calls search_entities(query="validate", repo="frontend")]
       3 matches found in frontend...
```

If `repo` is omitted, the first registered repo is used as default.

### Removing Repos

```
User: Remove the frontend repo
Agent: [calls remove_repo(name="frontend")]
       Removed "frontend" from registry.
```

### Registry File Format

`~/.batho/mcp-repos.json`:
```json
{
  "repos": [
    {"name": "frontend", "path": "/projects/frontend"},
    {"name": "backend", "path": "/projects/backend"}
  ]
}
```

The registry persists across server restarts. Adding a new repo is as simple as `batho build` + `add_repo` from agent chat.

### When to Use

- You work on multiple independent projects
- You want one-time client config — no edits when adding repos
- You want the AI agent to manage repos autonomously

## Pattern 2: Legacy Single-Repo Mode

For backward compatibility, you can still use `--root` to serve a single repo:

```bash
batho mcp --root /path/to/your/repo
```

This bypasses the registry entirely. Use this if you have a single repo and prefer explicit root specification.

### When to Use

- Single repo setup with no need for registry
- Existing configs that already use `--root`

## Pattern 3: Monorepo

For a monorepo where all code lives under one root:

```bash
# Single build covers the entire monorepo
batho build --root /projects/my-monorepo --verbose

# Register as a single repo
batho mcp
# Then in agent: add_repo(name="monorepo", path="/projects/my-monorepo")
```

The agent can query specific packages using `file_path` filters:

```
User: Show me everything in packages/auth/
Agent: [calls graph_query(file_path="packages/auth/", repo="monorepo")]
```

### When to Use

- All code shares a single `.batho/` artifact directory
- You want cross-package relationship traversal (e.g., `trace_path` from frontend to backend)
- Community detection should see the full dependency graph

## Multi-Agent Workflows

Multiple AI agents can connect to the same Batho MCP server process:

```
Agent A (Cursor)   →  batho mcp  (process 1, serves all repos)
Agent B (Claude)   →  batho mcp  (process 2, serves all repos)
Agent C (Windsurf) →  batho mcp  (process 3, serves all repos)
```

- **Same server, multiple agents**: Each agent gets its own MCP server process. All read the same registry and Arrow IPC files (memory-mapped, read-only). No conflicts.
- **After `batho patch`**: All server processes auto-detect the new generation on their next tool call. No restart needed.

## Managing Builds Across Repos

```bash
# Build each repo independently
batho build --root /projects/frontend --verbose
batho build --root /projects/backend --verbose

# Patch each repo after changes
batho patch --root /projects/frontend --verbose
batho patch --root /projects/backend --verbose
```

Each repo maintains its own:
- `.batho/artifact/` directory
- Run history and changelog
- Community detection results
- Generation counter

## Token Budget Considerations

Each tool call returns up to 25K tokens by default. When querying multiple repos, strategies to manage token usage:

| Strategy | How |
|----------|-----|
| **Reduce per-call budget** | Set `max_tokens=10000` for overview calls |
| **Use `response_format: "summary"`** | Summary format is the most compact |
| **Query one repo at a time** | Ask "show me the backend overview" instead of "show me all overviews" |
| **Use `graph_query` with filters** | Filter by file_path or entity_types to reduce result size |

## Configuration Matrix

| Setup | Config Files | Processes | Best For |
|-------|-------------|-----------|----------|
| Registry (multi-repo) | One MCP config entry | 1 | Multiple repos, one-time setup |
| Legacy (single repo) | One config with `--root` | 1 | Single repo, explicit root |
| Monorepo | One config entry | 1 | All code under one root |
| Multi-agent | Same config, multiple clients | N (one per agent) | Team collaboration |

## Next Steps

- [Tools Reference](/docs/mcp/tools-reference) — Complete tool documentation
- [Setup Guide](/docs/mcp/setup) — Client configuration details
- [CLI Reference](/docs/cli-reference/mcp-cmd) — `batho mcp` command flags
