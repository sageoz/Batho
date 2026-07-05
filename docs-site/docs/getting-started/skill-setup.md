---
sidebar_position: 2
title: "Setup with AI Agent Skill"
description: "Let your AI coding agent set up Batho for you — no manual config needed"
---

# Setup with AI Agent Skill

The fastest way to get Batho running: **give the skill file to your AI agent** and let it handle everything — installation, code graph build, and MCP configuration for all detected clients.

## How It Works

1. You give your agent the `SKILL.md` file
2. Your agent reads the skill instructions
3. Your agent installs Batho, builds the graph, and configures MCP for all detected AI clients
4. You verify by asking your agent to query the graph

No manual JSON editing. No config file hunting. Your agent does it all.

## Step 1: Get the Skill File

Download the skill file from the repository:

```bash
curl -O https://raw.githubusercontent.com/sageoz/batho/main/SKILL.md
```

Or [view it on GitHub](https://github.com/sageoz/batho/blob/main/SKILL.md) and copy the contents.

## Step 2: Give It to Your Agent

Paste one of these prompts into your AI agent's chat:

### Claude Code

```
Read SKILL.md and set up Batho for this repo
```

### Cursor

```
Read the SKILL.md file in this project and follow the instructions to set up Batho
```

### Windsurf

```
Read SKILL.md and set up Batho for this repo
```

### Any MCP-compatible agent

```
Read SKILL.md and follow the setup instructions for Batho
```

## Step 3: What Your Agent Does

The skill guides your agent through these workflows:

1. **Global install** — Installs Batho via pip, uv, or pipx (tries each in order)
2. **Build the code graph** — Runs `batho build --root /path/to/repo`
3. **Auto-detect AI clients** — Scans for Claude Desktop, Cursor, Windsurf, and VS Code
4. **Configure MCP** — Writes or merges the Batho MCP config into each detected client
5. **Verify** — Checks that `batho` is on PATH and the artifact exists

Your agent will report which clients were configured, which were skipped (already had Batho), and which were not installed.

## Multi-Repo Setup

Your agent can register multiple repos via the MCP registry — one config entry serves all repos. No need to edit client configs when adding repos.

```
User: Add repo frontend at /projects/frontend
Agent: [calls add_repo(name="frontend", path="/projects/frontend")]
       Registered "frontend" — 892 entities. Artifact: ready.

User: Add repo backend at /projects/backend
Agent: [calls add_repo(name="backend", path="/projects/backend")]
       Registered "backend" — 650 entities. Artifact: ready.
```

See the [Multi-Repo Guide](/docs/mcp/multi-repo) for details.

## Verification

After setup, ask your agent:

- *"What repos are available?"* — should call `list_repos()` and show registered repos
- *"Give me an overview of myproject"* — should call `graph_overview(repo="myproject")`
- *"Find functions named `main`"* — should use `search_entities`

If verification fails, see the [Troubleshooting section in the MCP Setup Guide](/docs/mcp/setup#troubleshooting).

## Next Steps

- [MCP Server](/docs/mcp) — Learn about the 10 MCP tools
- [MCP Setup Guide](/docs/mcp/setup) — Manual setup if you prefer CLI
- [Multi-Repo Guide](/docs/mcp/multi-repo) — Configure multiple repositories
- [Tools Reference](/docs/mcp/tools-reference) — Complete parameter and response documentation
- [Quick Start (CLI)](/docs/getting-started/quick-start) — Manual CLI setup
