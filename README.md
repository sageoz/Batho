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

Batho exposes 10 MCP tools your AI agent can call:

| Tool | Purpose |
|------|---------|
| `graph_overview` | High-level codebase summary: entities, relationships, communities |
| `graph_query` | Filtered graph query by file, type, or name pattern |
| `get_entity` | Detailed info for a single entity + relationships |
| `trace_path` | Shortest path between two entities (BFS) |
| `get_file_graph` | All entities and relationships in a file |
| `search_entities` | Substring/regex search across entity names |
| `get_delta` | Incremental changes from the latest patch |
| `list_repos` | List all registered repos with status |
| `add_repo` | Register a repository in the MCP registry |
| `remove_repo` | Remove a repository from the registry |

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
- uses: sageoz/batho@v1.2.0
  with:
    root: "."
    artifact-name: "batho-index"
```

Full CI/CD guides (GitHub Actions, GitLab CI, reusable workflows): **[docs](https://batho.sageoz.org/docs/cicd)**

---

## Configuration

Batho runs with zero config. To customize, copy [`batho.yaml.example`](batho.yaml.example) to `./batho.yaml`.

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

---

## Acknowledgments

Co-authored with [Devin](https://devin.ai) — autonomous AI software engineer by Cognition.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.