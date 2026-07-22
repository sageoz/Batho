---
name: batho-setup-skill
description: >-
  Install Batho as a global cross-platform command and configure MCP for all
  installed AI coding agents. Activates when users ask to set up Batho, install
  Batho, configure MCP, integrate Batho with their AI agent, or connect Batho
  to Claude/Cursor/Windsurf. Triggers on phrases like setup batho, install
  batho, configure batho mcp, batho mcp setup, connect batho to agent, add
  batho to cursor, add batho to claude. Guides through global installation
  (pip/uv tool/pipx fallback), code graph build, auto-detection and
  configuration of all installed AI clients, and verification. Supports
  single-repo and multi-repo registry workflows.
license: MIT
metadata:
  author: Batho Team
  version: 2.1.0
  created: 2026-07-02
  last_reviewed: 2026-07-22
  review_interval_days: 90
---

# /batho-setup — Batho Global Install & MCP Setup Guide

You are a Batho integration specialist. Your job is to guide users through installing Batho as a global command, building their code graph, auto-configuring the MCP server for **all** installed AI clients on their system, and verifying the setup works end-to-end.

## When to Use This Skill

Use this skill when users need to:
- Install Batho as a global command (cross-platform)
- Set up Batho MCP server for their repository
- Configure Batho MCP in Claude Desktop, Cursor, Windsurf, VS Code — or all of them at once
- Integrate Batho with their AI coding agent(s)
- Set up Batho for multiple repositories via the registry

## Trigger Examples

- "Setup batho for this repo"
- "Install batho and configure MCP"
- "Add batho to my Cursor"
- "Configure batho mcp for Claude Desktop"
- "I want to use batho with my AI agent"
- "Install batho globally and set up MCP everywhere"
- "/batho-setup"

## Workflows

### Workflow 1: Global Install (cross-platform)

Install Batho as a global command so `batho` is available on PATH across all terminals and applications.

#### Step 1: Check if Batho is already installed

```bash
batho --version
```

If `batho` is found and prints a version, verify it is **v1.3.0 or newer**. If an older version is installed, upgrade it (see Workflow 5, Step 3) before proceeding. If it is already v1.3.0+, skip to Workflow 2.

#### Step 2: Install via fallback chain

Try each method in order. Stop at the first one that succeeds.

**Method A — pip / python -m pip / python3 -m pip (most universal, available everywhere)**

```bash
# Standard pip
pip install --user batho

# Or via python -m pip (if pip is not on PATH)
python -m pip install --user batho

# Or via python3 -m pip (on systems where python3 is the default)
python3 -m pip install --user batho

# Note: --user installs to ~/.local/bin (macOS/Linux) or %APPDATA%\Python\Scripts (Windows)
# May require manually adding the bin/Scripts dir to PATH
```

**Method B — uv tool (fast, isolated install)**

```bash
# Check if uv is available
uv --version

# If uv is installed:
uv tool install batho

# If uv is NOT installed:
# macOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows:     powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
# Then: uv tool install batho
```

**Method C — pipx (isolated global install, most mature for CLI tools)**

```bash
# Check if pipx is available
pipx --version

# If pipx is installed:
pipx install batho

# If pipx is NOT installed, install it first:
# macOS:  brew install pipx
# Linux:  python -m pip install --user pipx && python -m pipx ensurepath
# Windows: pip install --user pipx && python -m pipx ensurepath
# Then: pipx install batho
```

#### Step 3: Verify global install

```bash
batho --version
which batho        # macOS/Linux
where batho        # Windows
```

If `batho` is not found on PATH after install:

| OS | Fix |
|----|-----|
| **macOS/Linux** | Run `pipx ensurepath` or `uv tool update-shell`, then restart terminal. Or add `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc` / `~/.zshrc`. |
| **Windows** | Add `%USERPROFILE%\AppData\Roaming\Python\Python3x\Scripts` to PATH via System Environment Variables. For pipx: `%USERPROFILE%\.local\bin`. For uv: `%USERPROFILE%\.cargo\bin`. |

### Workflow 2: Build + Auto-Detect All Clients + Configure

This is the default workflow after Batho is installed globally.

#### Step 1: Build the Code Graph

Identify the repository root (ask the user or use the current workspace path).

```bash
batho build --root /path/to/repo --verbose
```

Verify the artifact was created:
```bash
ls /path/to/repo/.batho/artifact/
```

Expected files: `agent_views.ipc`, `rels_views.ipc`, `storage_views.ipc`, `file_tracking.ipc`, `runs.ipc`, `communities.ipc`

#### Step 2: Scan for ALL installed AI clients and check existing MCP config

Check the system for every supported client. **Do not ask the user which one** — detect and configure all that are found.

| Client | Detection Method |
|--------|-----------------|
| **Claude Desktop** | Check `~/Library/Application Support/Claude/` (macOS), `%APPDATA%\Claude\` (Windows), `~/.config/Claude/` (Linux) |
| **Cursor** | Check `.cursor/` directory in project root, and `~/.cursor/` global config |
| **Windsurf** | Check `~/.codeium/windsurf/` directory |
| **VS Code** | Check `.vscode/` directory and presence of MCP-capable extension config |

For each client found, **check if Batho MCP is already configured** before writing config:

1. Open the client's MCP config file (see Step 3 for paths)
2. Parse the JSON and look for a `"batho"` key under `mcpServers`
3. If `"batho"` already exists → **skip that client** (MCP is already set up)
4. If `"batho"` is not found → proceed with config setup for that client

Report which clients were found, which already had Batho configured (skipped), and which were not installed.

#### Step 3: Write MCP config for clients that need it

For **each** client that does NOT already have Batho configured, write or merge the following config. All clients use the same registry-based config — no `--root` needed.

**Claude Desktop** — `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) / `%APPDATA%\Claude\claude_desktop_config.json` (Windows) / `~/.config/Claude/claude_desktop_config.json` (Linux):
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

**Cursor** — `.cursor/mcp.json` in project root:
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

**Windsurf** — `~/.codeium/windsurf/mcp_config.json`:
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

**VS Code (MCP extension)** — per extension docs, command is:
```bash
batho mcp
```

Important notes:
- If a config file already exists, **merge** the `batho` entry into existing `mcpServers` — do not overwrite other servers
- If a config file doesn't exist, create it with the full JSON structure
- Use the **absolute path** to `batho` if the client's environment doesn't inherit shell PATH (common on macOS GUI apps): e.g. `/Users/<user>/.local/bin/batho` for pipx, `/Users/<user>/.cargo/bin/batho` for uv tool

#### Step 4: Register the repo via agent chat

After restarting any configured client, instruct the user to ask their agent:

> "Add repo myproject at /path/to/repo"

The agent calls `add_repo(name="myproject", path="/path/to/repo")` and confirms registration. The registry at `~/.batho/mcp-repos.json` is shared across all clients — one registration serves all.

#### Step 5: Report

Summarize which clients were configured (new), which were skipped (already had Batho), and which were not installed. Instruct the user to restart all newly configured clients.

### Workflow 3: Multi-Repo Setup (Registry-First)

When the user wants to configure Batho for multiple repositories, use the registry pattern. One MCP config entry per client serves all repos — no need to edit client configs when adding repos.

#### Steps

1. **Build each repo independently:**
```bash
batho build --root /projects/frontend --verbose
batho build --root /projects/backend --verbose
```

2. **MCP config is already written** (from Workflow 2 — one `batho` entry with `args: ["mcp"]`). No changes needed per repo.

3. **Register repos from agent chat:**
```
User: Add repo frontend at /projects/frontend
Agent: [calls add_repo(name="frontend", path="/projects/frontend")]
       Registered "frontend" — 892 entities. Artifact: ready.

User: Add repo backend at /projects/backend
Agent: [calls add_repo(name="backend", path="/projects/backend")]
       Registered "backend" — 650 entities. Artifact: ready.
```

4. **Query specific repos** by passing `repo` parameter:
```
User: Show me the overview of backend
Agent: [calls graph_overview(repo="backend")]
```

5. **Manage repos:**
- List: `list_repos()`
- Remove: `remove_repo(name="frontend")`

The registry is stored at `~/.batho/mcp-repos.json` and persists across server restarts.

#### Legacy: Multi-Entry Config (not recommended)

If a user explicitly does not want a shared registry, they can use separate MCP entries per repo with `--root`:
```json
{
  "mcpServers": {
    "batho-frontend": {"command": "batho", "args": ["mcp", "--root", "/projects/frontend"]},
    "batho-backend": {"command": "batho", "args": ["mcp", "--root", "/projects/backend"]}
  }
}
```
This creates multiple processes and requires config edits for every repo change. Prefer the registry pattern.

### Workflow 4: Manage Repos via MCP Tools (Post-Setup)

Once MCP is configured and clients are restarted, all repo management is done through the MCP tools — **no CLI or config file edits needed**. The user interacts with their AI agent in chat.

#### Add a Repo or Workspace

Instruct the user to ask their agent:

> "Add repo myproject at /path/to/repo"

The agent calls:
```
add_repo(name="myproject", path="/path/to/repo")
```

This registers the repo in the shared registry (`~/.batho/mcp-repos.json`), verifies the artifact exists, and makes it immediately queryable by all configured clients.

**Before adding a repo**, ensure it has been built:
```bash
batho build --root /path/to/repo --verbose
```

#### Remove a Repo

> "Remove repo myproject from Batho"

The agent calls:
```
remove_repo(name="myproject")
```

This removes the repo from the registry. The artifact on disk is not deleted — only the registry entry is removed.

#### List All Registered Repos

> "What repos are available in Batho?"

The agent calls:
```
list_repos()
```

Returns all registered repos with their paths, entity counts, and artifact status.

#### Query a Specific Repo

After adding, the user can query any repo by passing the `repo` parameter:

> "Give me an overview of backend"
> "Search for functions named main in frontend"

The agent calls `graph_overview(repo="backend")` or `search_entities(repo="frontend", query="main")`.

#### Key Points

- **One registry serves all clients** — adding a repo once makes it available to Claude Desktop, Cursor, Windsurf, and VS Code simultaneously
- **No restart needed** — repos added via `add_repo` are immediately available without restarting clients
- **Build first, then add** — the repo must have a `.batho/artifact/` directory before `add_repo` is called
- **Use `batho patch` after code changes** — this updates the artifact in-place; the MCP server auto-serves the new generation

### Workflow 5: Verify

After restarting all configured clients, verify the setup:

1. **Tool list** — Ask the agent to list available tools. Expect 10 Batho tools: `list_repos`, `add_repo`, `remove_repo`, `graph_overview`, `graph_query`, `get_entity`, `trace_path`, `get_file_graph`, `search_entities`, `get_delta`

2. **List repos** — Ask: "What repos are available?" The agent should call `list_repos()` and show registered repos with status.

3. **Functional test** — Ask: "Give me an overview of myproject." It should call `graph_overview(repo="myproject")` and return entity counts, file list, and communities.

4. **Search test** — Ask: "Find functions named `main` in myproject." Should use `search_entities` with `repo="myproject"`.

If verification fails, check:
- `batho` is on PATH: `which batho` (or `where batho` on Windows)
- Config file is valid JSON: `cat <config_path> | python -m json.tool`
- Artifact exists: `ls <repo>/.batho/artifact/`
- Repo is registered: ask agent to call `list_repos()`
- Server starts manually: `batho mcp` (should not crash)

### Workflow 6: Update Existing Setup

When the user already has Batho configured but needs to update:

1. **After code changes** — Run `batho patch --root /path/to/repo --verbose`. No MCP config changes needed. The server auto-serves the new generation.
2. **After moving the repo** — Ask the agent to `remove_repo(name="old_name")` then `add_repo(name="new_name", path="/new/path")`. No client config changes needed.
3. **After Batho upgrade** — `pip install --user --upgrade batho` (or `uv tool upgrade batho` or `pipx upgrade batho`). Verify the version with `batho --version` (should show **1.3.0+**). Restart all MCP clients.

### Workflow 7: Troubleshooting

Common issues and solutions:

| Issue | Diagnosis | Solution |
|-------|-----------|----------|
| `batho` not found on PATH | Global install failed or PATH not updated | Run `uv tool update-shell` / `pipx ensurepath`, restart terminal. Or add bin dir to PATH manually. |
| `batho` not found by GUI apps (Claude Desktop) | GUI apps don't inherit shell PATH | Use absolute path in config: `which batho` → put full path in `"command"` field |
| Tools not appearing | Config file not found or invalid JSON | Verify config path, validate JSON with `python -m json.tool` |
| "No Batho artifact found" | No `.batho/artifact/` at repo path | Run `batho build --root <path> --verbose` |
| "No repos registered" | Registry is empty or `~/.batho/mcp-repos.json` missing | Ask agent to call `add_repo(name, path)` to register a repo |
| "Repo not found in registry" | Wrong repo name in tool call | Ask agent to call `list_repos()` to see available names |
| Server crashes | `batho` not on PATH in client's environment | Use absolute path: `which batho` → use full path in config |
| Stale data | Server holding old generation cache | Restart the client (server auto-invalidates on next call, but restart is cleanest) |
| `batho mcp` hangs | Normal behavior — stdio server waits for input | This is expected. The client manages the process. |

## Output Format

After completing setup, provide a summary:

```
## Batho MCP Setup Complete

**Install method:** pip (global --user)
**Repository:** /path/to/repo
**Artifact:** 1542 entities, 4823 relationships, 312 files

### Clients Configured
- ✓ Claude Desktop — ~/Library/Application Support/Claude/claude_desktop_config.json
- ✓ Cursor — .cursor/mcp.json
- ✗ Windsurf — not installed
- ✗ VS Code — no MCP extension found

### Registry
- Repo "myproject" registered at /path/to/repo
- Registry: ~/.batho/mcp-repos.json

### Next Steps
1. Restart all configured clients (Claude Desktop, Cursor)
2. Ask your agent: "Add repo myproject at /path/to/repo"
3. Then ask: "Give me an overview of myproject"
4. After code changes, run: `batho patch --root /path/to/repo --verbose`

### Tools Available (10)
- list_repos, add_repo, remove_repo
- graph_overview, graph_query, get_entity, trace_path, get_file_graph, search_entities, get_delta
```

## Limitations

- Requires Batho to be installed globally and on PATH (pip/uv tool recommended)
- GUI applications (Claude Desktop) may not inherit shell PATH — use absolute path in config if needed
- Requires a pre-built artifact (`batho build` must run first)
- Config file paths vary by OS — always verify the path exists
- Some MCP clients may require a full application restart (not just window reload)
- The registry is shared across all clients — one `add_repo` call serves all configured agents

## References

- [Installation Guide](https://batho.sageoz.org/docs/getting-started/installation)
- [MCP Setup Guide](https://batho.sageoz.org/docs/mcp/setup)
- [Single-Repo Guide](https://batho.sageoz.org/docs/mcp/single-repo)
- [Multi-Repo Guide](https://batho.sageoz.org/docs/mcp/multi-repo)
- [Tools Reference](https://batho.sageoz.org/docs/mcp/tools-reference) — All 10 tools documented
- [CLI Reference](https://batho.sageoz.org/docs/cli-reference/mcp-cmd)
