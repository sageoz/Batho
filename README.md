<p align="center">
  <img src="https://raw.githubusercontent.com/sageoz/batho/main/assets/batho.svg" alt="Batho" width="200" height="200" />
</p>

<h1 align="center">B.A.T.H.O</h1>

<p align="center">
  Give your AI coding agent a map of your codebase — not the whole territory.<br>
  Reduce token spend 10x, eliminate hallucinations, and ship faster with graph-powered code intelligence.
</p>

<p align="center">
  <a href="https://pypi.org/project/batho/"><img src="https://img.shields.io/pypi/v/batho?color=blue" alt="PyPI"></a>
  <a href="https://github.com/sageoz/batho/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
  <a href="https://batho.sageoz.org"><img src="https://img.shields.io/badge/docs-batho.sageoz.org-green" alt="Documentation"></a>
  <a href="https://github.com/sageoz/batho/stargazers"><img src="https://img.shields.io/github/stars/sageoz/batho?style=flat" alt="Stars"></a>
  <a href="https://doi.org/10.5281/zenodo.21407508"><img src="https://img.shields.io/badge/DOI-10.5281/zenodo.21407508-blue" alt="DOI"></a>
</p>

<p align="center">
  <strong>Works with:</strong>
  Claude Code &middot; Cursor &middot; Windsurf &middot; Antigravity &middot; Gemini CLI &middot; Cline &middot; OpenCode &middot; Aider
</p>

---

## Quick Setup

The fastest way to set up Batho: **give the skill file to your AI agent** and let it do everything for you.

### 1. Download the skill file

```bash
curl -O https://raw.githubusercontent.com/sageoz/batho/main/SKILL.md
```

### 2. Give it to your AI agent

Paste this into your agent's chat (Claude Code, Cursor, Windsurf, or any agent that supports skills):

```
Read SKILL.md and set up Batho for this repo
```

### 3. Your agent handles the rest

- Installs Batho globally (pip / uv / pipx)
- Builds the code graph for your repository
- Auto-detects all installed AI clients (Claude Desktop, Cursor, Windsurf, VS Code)
- Configures MCP for each client
- Verifies the setup works end-to-end

No manual JSON editing. No config file hunting. Your agent does it all.

> **Multi-repo?** Your agent can register multiple repos via the MCP registry — one config serves all. See the [Multi-Repo Guide](https://batho.sageoz.org/docs/mcp/multi-repo).

<details>
<summary>Manual Setup (CLI)</summary>

Prefer the terminal? Batho works with zero config:

```bash
# Install
pip install batho

# Build the code graph
batho build --root . --verbose

# Start the MCP server
batho mcp
```

Then add to your agent's MCP config:

```json
{
  "mcpServers": {
    "batho": { "command": "batho", "args": ["mcp"] }
  }
}
```

Full setup guide: **[docs](https://batho.sageoz.org/docs/mcp/setup)**

</details>

---

## Why Batho?

AI coding agents are powerful — but they burn tokens reading files and hallucinate when context is thin. Batho gives your agent a structured code graph so it works smarter, not harder.

- **Slash token costs** — Your agent queries a graph instead of reading entire files. 10x fewer tokens per task — no more dumping your repo into the LLM.
- **Eliminate hallucinations** — Deterministic, tree-sitter-parsed relationships. Your agent gets facts, not guesses — zero hallucinations on structural queries.
- **Agent superpowers** — Bug tracking, security audits, refactoring, code review — your agent handles more, accurately. When cost and quality are solved, automation widens with imagination.

---

## MCP Tools

Batho exposes **19 MCP tools** organized into three tiers. By default, **15 tools** are available to your AI agent — the 4 administrative tools are disabled to keep the agent's tool surface focused on retrieval and diagnostics (matching the Sourcegraph/Cursor/CodeGraph pattern where indexing is a background process and the agent is a pure consumer).

### Tier 1 — Read-only (always enabled, 13 tools)

| Tool | Purpose |
|------|---------|
| `list_repos` | List all registered repos with status |
| `add_repo` | Register a repository in the MCP registry |
| `remove_repo` | Remove a repository from the registry |
| `graph_overview` | High-level codebase summary: entities, relationships, communities |
| `graph_query` | Filtered graph query by file, type, or name pattern |
| `get_entity` | Detailed info for a single entity + relationships |
| `trace_path` | Shortest path between two entities (BFS) |
| `get_file_graph` | All entities and relationships in a file |
| `search_entities` | Substring/regex search across entity names |
| `get_delta` | Incremental changes from the latest patch |
| `batho_status` | Artifact status, generation, and run info for a repo |
| `batho_list_runs` | List all build/patch runs with metadata |
| `batho_diff` | Node-level changes across runs, entities, or files |

### Tier 2 — Destructive (always enabled, 2 tools)

These modify the artifact but are useful for agent self-recovery. MCP clients should prompt for confirmation via `destructiveHint=True`.

| Tool | Purpose |
|------|---------|
| `batho_patch` | Incremental update of an existing artifact after file edits |
| `batho_fix` | Verify and repair artifact database integrity |

### Tier 3 — Administrative (disabled by default, 4 tools)

These are expensive or setup/CI operations. The agent should detect when they're needed and instruct the user to run them in the terminal — not call them mid-conversation.

| Tool | Purpose |
|------|---------|
| `batho_build` | Full index build (first-time setup or forced rebuild) |
| `batho_export` | Export a JSON view or Pack artifact to disk |
| `batho_load` | Unpack a transport `.batho` ZIP into an artifact |
| `batho_gc` | Garbage collection and database maintenance |

### Enabling Tier 3 tools

Three ways to opt in — pick whichever fits your workflow:

<details>
<summary>Config file (batho.yaml)</summary>

```yaml
mcp:
  enabled: true
  tools:
    disabled: []          # empty list = all 19 tools enabled
    # Or enable specific tools only:
    # disabled: [batho_build, batho_load]  # keeps export + gc enabled
    enabled: null           # optional allowlist (overrides disabled if set)
```

</details>

<details>
<summary>Environment variable</summary>

```bash
# Enable all tools
BATHO_MCP_TOOLS_DISABLED="" batho mcp

# Or disable specific tools only
BATHO_MCP_TOOLS_DISABLED="batho_build,batho_gc" batho mcp

# Or use an allowlist (only these tools will be registered)
BATHO_MCP_TOOLS_ENABLED="list_repos,graph_overview,search_entities" batho mcp
```

</details>

<details>
<summary>CLI flag (one-off)</summary>

```bash
# Enable a single tool for this session
batho mcp --enable-tool batho_build

# Enable multiple tools (repeatable)
batho mcp --enable-tool batho_build --enable-tool batho_gc
```

</details>

> **Why disable them by default?** A full rebuild takes seconds to minutes and blocks the conversation. Export/load/gc are administrative operations that belong in the terminal or CI, not in an agent's tool list where they add selection noise and risk accidental invocation.

Full reference: **[docs](https://batho.sageoz.org/docs/mcp/tools-reference)**

---

## Features

- **40+ languages** — Python, TypeScript, Rust, Go, Java, C/C++ and more via tree-sitter
- **10x token compression** — your agent uses a fraction of the context window
- **Zero hallucinations** — deterministic AST-parsed relationships, not embeddings or guesses
- **Fast incremental updates** — hash-based change detection re-parses only modified files
- **Cross-file symbol resolution** — your agent sees how functions, classes, and dependencies connect
- **38 built-in analysis plugins** — security, quality, and optimization rules with custom rule support
- **Time-machine** — node-level diff history across every indexed run
- **Zero code execution** — safe to run in CI or on untrusted repositories
- **MCP-native** — works with 8 AI coding agents out of the box

---

## CI/CD

Batho's CI/CD strategy is **incremental**: download the previous artifact → `batho load` → `batho patch` → `batho export` → upload.

**GitHub Actions composite action:**

```yaml
- uses: sageoz/batho@v1.4.0
  with:
    root: "."
    artifact-name: "batho-index"
```

Full CI/CD guides (GitHub Actions, GitLab CI, reusable workflows): **[docs](https://batho.sageoz.org/docs/cicd)**

---

## Configuration

Batho runs with zero config. To customize, copy [`batho.yaml.example`](batho.yaml.example) to `./batho.yaml`.

### MCP

The `mcp` category controls the MCP server and which tools the agent can see.

```yaml
mcp:
  enabled: true
  tools:
    disabled: [batho_build, batho_export, batho_load, batho_gc]
    enabled: null
```

- `disabled`: blocklist of tool names to hide. Set to `[]` to expose all 19 tools.
- `enabled`: optional allowlist. If set, only these tools are registered and `disabled` is ignored.

#### Step 1 — Pick a tool set

```yaml
# Allowlist: only these tools are available
mcp:
  tools:
    enabled: [list_repos, graph_overview, search_entities, get_entity]

# Blocklist: hide only the listed tools
mcp:
  tools:
    disabled: [batho_build, batho_gc]

# Expose every tool
mcp:
  tools:
    disabled: []
```

#### Step 2 — Override per session

CLI flags:

```bash
batho mcp --enable-tool batho_build --enable-tool batho_gc
batho mcp --no-watch
batho mcp --root /path/to/repo
```

Environment variables:

```bash
BATHO_MCP_TOOLS_DISABLED="batho_build,batho_gc" batho mcp
BATHO_MCP_TOOLS_ENABLED="list_repos,graph_overview" batho mcp
```

#### Step 3 — Connect your agent

Add Batho to your agent's MCP config:

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

See the full [MCP setup guide](https://batho.sageoz.org/docs/mcp/setup) for client-specific file locations.

Full configuration reference: **[docs](https://batho.sageoz.org/docs/getting-started/configuration)**

---

## Developer Setup

```bash
git clone https://github.com/sageoz/batho.git
cd batho
uv sync --all-groups --all-extras
uv run pytest
uv run python batho_cli.py --help
```

---

## Documentation

- [Quick Start](https://batho.sageoz.org/docs/getting-started/quick-start) — CLI setup guide
- [Setup with AI Agent Skill](https://batho.sageoz.org/docs/getting-started/skill-setup) — Let your agent set up Batho
- [MCP Server](https://batho.sageoz.org/docs/mcp) — Connect AI agents to your code graph
- [Whitepaper](https://batho.sageoz.org/docs/whitepaper) — Deep technical reference
- [CLI Reference](https://batho.sageoz.org/docs/cli-reference) — Complete command documentation
- [CI/CD](https://batho.sageoz.org/docs/cicd) — GitHub Actions, GitLab CI, and more
- [Changelog](https://batho.sageoz.org/docs/changelog) — Release history and version notes
- [Releases](https://github.com/sageoz/batho/releases) — Detailed release notes for each version

---

## Acknowledgments

Co-authored with [Devin](https://devin.ai) — autonomous AI software engineer by Cognition.

---
Citation

If you use Batho in your research, please cite it as:

```bibtex
@misc{Sharma_Batho_2026,
  author = {Sharma, Rishiraj},
  doi = {10.5281/zenodo.21407508},
  month = {7},
  title = {Batho: Deterministic Code Intelligence Engine},
  url = {https://pypi.org/project/batho/},
  year = {2026}
}
```

You can also find the citation metadata in [`CITATION.cff`](CITATION.cff) or use GitHub's **"Cite this repository"** button.

---

## 
## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.