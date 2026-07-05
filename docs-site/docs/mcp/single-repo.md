---
sidebar_position: 3
title: "Single-Repo Guide"
description: "Step-by-step guide to setting up Batho MCP for a single repository"
---

# Single-Repository Setup

This guide walks through setting up Batho MCP for one repository, from installation to your first AI agent query.

## Step 1: Install Batho

```bash
# Via pip
pip install batho

# Via uv
uv pip install batho

# Verify installation
batho --version
```

## Step 2: Build the Code Graph

```bash
cd /path/to/your/project

# Full build — parses all files, extracts entities and relationships
batho build --root . --verbose
```

Output:
```
Built /path/to/your/project: 1542 entities, 4823 relationships, 312 files in 1245ms
```

This creates `.batho/artifact/` containing Arrow IPC files:
- `agent_views.ipc` — entities (functions, classes, methods, imports)
- `rels_views.ipc` — relationships (calls, imports, inherits, defines)
- `storage_views.ipc` — source code snippets
- `file_tracking.ipc` — file metadata
- `runs.ipc` — build run history
- `communities.ipc` — Leiden community detection results

## Step 3: Start the MCP Server

```bash
# Start MCP server — auto-loads ~/.batho/mcp-repos.json registry
batho mcp
```

The server starts on stdio and waits for MCP protocol messages. No `--root` flag needed — repos are managed via the registry.

## Step 4: Configure Your AI Client (One-Time)

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

### Cursor

Create `.cursor/mcp.json` in your project root:

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

Restart your client after saving the config. This is a **one-time setup** — no need to edit config again when adding repos.

## Step 5: Register the Repo and Verify

In your AI agent chat:

> "Add repo myproject at /path/to/your/project"

The agent calls `add_repo(name="myproject", path="/path/to/your/project")` and confirms registration.

Then ask:

> "Give me an overview of myproject."

The agent should call `graph_overview(repo="myproject")` and return:

```markdown
# Codebase Overview

**Stats:** 1542 entities, 4823 relationships, 312 files
**Run:** abc-123-def | commit: a1b2c3d | branch: main

## Entity Breakdown
- function: 892
- class: 124
- method: 387
- import: 139

## Communities
1. **UserService** — 45 entities across 8 files
2. **ApiClient** — 32 entities across 5 files
3. **DataPipeline** — 28 entities across 6 files
...
```

## Step 6: Incremental Updates

After making code changes, update the graph without a full rebuild:

```bash
batho patch --root /path/to/your/project --verbose
```

Then ask your agent:

> "What changed in myproject since the last update?"

The agent calls `get_delta(repo="myproject")` and shows added/removed/modified entities. The MCP server automatically serves the new generation — **no restart needed**.

## Example Workflow

Here's a typical development session:

```bash
# 1. Initial build (once per repo)
batho build --root /path/to/project --verbose

# 2. Start MCP server (keep running)
batho mcp
```

In your AI agent:

```
User: Add repo myproject at /path/to/project
Agent: [calls add_repo(name="myproject", path="/path/to/project")]
       Registered "myproject" — 1542 entities, 312 files.

User: What does the authentication module look like?
Agent: [calls graph_overview(repo="myproject") → graph_query(repo="myproject", file_path="auth/")]
       The auth module contains 23 entities across 4 files...
       Key classes: AuthManager, TokenValidator, SessionHandler

User: What calls AuthManager.validate_token?
Agent: [calls get_entity(entity_id="auth.AuthManager.validate_token", repo="myproject")]
       5 callers found:
       - api.middleware.AuthMiddleware.check
       - api.routes.login.handle_login
       ...

User: How does login.handle_login reach SessionHandler.create?
Agent: [calls trace_path(source_entity_id="...", target_entity_id="...", repo="myproject")]
       Path (3 hops):
       login.handle_token → [CALLS] AuthManager.validate_token → [CALLS] SessionHandler.create

User: What changed since my last commit?
Agent: [calls get_delta(repo="myproject")]
       3 added, 1 modified, 0 removed
       + auth/oauth.py: OAuthHandler (function)
       ~ auth/manager.py: AuthManager.validate_token (modified)
```

## Tips

- **Start with `list_repos`** — Check which repos are registered before querying.
- **Use `repo` parameter** — Pass `repo="myproject"` to any tool to specify the target repo. If omitted, the first registered repo is used.
- **Start with `graph_overview`** — Always ask for an overview first when exploring an unfamiliar codebase.
- **Use entity IDs from results** — `get_entity` and `trace_path` accept entity IDs returned by other tools.
- **After `batho patch`, call `get_delta`** — The server serves the latest data automatically; just ask what changed.
- **Token budgets** — Default is 25K tokens per response. Use `max_tokens` parameter to adjust for large queries.
- **Pagination** — `graph_query` supports `offset` and `limit` for paginating through large result sets.

## Next Steps

- [Multi-Repo Guide](/docs/mcp/multi-repo) — Configure Batho MCP for multiple repositories
- [Tools Reference](/docs/mcp/tools-reference) — Complete tool parameter documentation
- [CLI Reference](/docs/cli-reference/mcp-cmd) — `batho mcp` command flags
