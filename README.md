<p align="center">
  <img src="https://raw.githubusercontent.com/sageoz/batho/main/assets/batho.svg" alt="Batho" width="200" height="200" />
</p>

<h1 align="center">B.A.T.H.O</h1>

<p align="center">
Code intelligence engine for AI agents<br>
  Transform your codebase into a Knowledge Graph. Your agent gets a map of your codebase, enabling precise, context-aware coding assistance.
</p>

<p align="center">
  <a href="https://pypi.org/project/batho/"><img src="https://img.shields.io/pypi/v/batho?color=blue" alt="PyPI"></a>
  <a href="https://github.com/sageoz/batho/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
  <a href="https://batho.sageoz.org"><img src="https://img.shields.io/badge/docs-batho.sageoz.org-green" alt="Documentation"></a>
  <a href="https://github.com/sageoz/batho/stargazers"><img src="https://img.shields.io/github/stars/sageoz/batho?style=flat" alt="Stars"></a>
  <a href="https://doi.org/10.5281/zenodo.21407508"><img src="https://img.shields.io/badge/DOI-10.5281/zenodo.21407508-blue" alt="DOI"></a>
</p>

<p align="center">
Graph grounded answers instead of grepping and guessing.<br>

---

## Quick Setup
<details>
<summary>Prerequisites</summary>
<ul>
<li><strong>Python 3.12+</strong> — Verify: <code>python --version</code></li>
<li><strong>uv</strong> — Verify: <code>uv --version</code><br>
  If not installed:
  <ul>
    <li>macOS/Linux: <code>curl -LsSf https://astral.sh/uv/install.sh | sh</code></li>
    <li>Windows: <code>powershell -c "irm https://astral.sh/uv/install.ps1 | iex"</code></li>
  </ul>
</li>
</ul>
</details>

```bash
# Install Batho
uv tool install batho

# One command: installs the skill pack AND registers the MCP server
# with every detected coding-agent client (Claude Desktop, Claude Code,
# Cursor, Devin, VS Code, Codex, Gemini CLI, OpenCode, Copilot and more)
batho install
```
<details>
<summary>Manual Setup (CLI)</summary>

### macOS / Linux

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Batho
uv tool install batho

# One command: installs the skill pack AND registers the MCP server
# with every detected coding-agent client (Claude Desktop, Claude Code,
# Cursor, Windsurf, VS Code, Codex, Gemini CLI, OpenCode, Copilot)
batho install

# Build the code graph
batho build --root . --verbose
```

### Windows

```powershell
# Install uv (if not already installed)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Install Batho
uv tool install batho

# One command: installs the skill pack AND registers the MCP server
# with every detected coding-agent client (Claude Desktop, Claude Code,
# Cursor, Windsurf, VS Code, Codex, Gemini CLI, OpenCode, Copilot)
batho install

# Build the code graph
batho build --root . --verbose
```

### MCP Configuration

Add to your agent's MCP config (if not auto-detected):

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

AI coding agents are powerful, but they burn tokens reading files and hallucinate when context is thin. Batho gives your agent a structured code graph so it works smarter, not harder.

- **Grounded answers** — structural questions resolved from the graph, not string search
- **Blast radius first** — impact analysis before every change drives risk-tiered task plans
- **Fresh by construction** — graph builds on first use, patches as you work, staleness-gated reads
- **Supply-chain safe** — deterministic, checksummed, SLSA-attested release artifacts

---

---

### Core Capabilities

| Capability | Description |
|---|---|
| [**Batho CLI**](#batho-cli) | Command-line interface for building, patching, exporting, and querying the code graph |
| [**Batho Structured Graph (BSG)**](#batho-structured-graph-bsg) | Tree-sitter-parsed semantic graph capturing functions, classes, modules, and their relationships — calls, imports, inheritance, and overrides |
| [**MCP Server**](#mcp-server) | Exposes 20 tools for structural queries (`get_entity`, `trace_path`, `search_entities`, and more) with built-in file watcher for incremental patching |
| [**Batho Skill Pack**](#batho-skill-pack) | 6 pre-configured skills for AI coding agents — one-command install across 22 agents, full spec→implement→review lifecycle |
| **40+ Language Support** | Python, TypeScript, Rust, Go, Java, C/C++, and more via tree-sitter grammars |
| **38 Built-in Analysis Plugins** | Security, quality, and optimization rules with custom rule support |
| **Cross-File Symbol Resolution** | Resolves how functions, classes, and dependencies connect across files |
| **Hash-Based Incremental Patching** | Fast change detection re-parses only modified files |
| **Time-Machine** | Node-level diff history across every indexed run for tracking code evolution |
| **CI/CD Integration** | GitHub Actions, GitLab CI, and reusable workflows for indexing and incremental patching |

---

## Core Capabilities in Depth

### Batho CLI

The command-line interface — the entry point for building, patching, and maintaining the code graph. Eleven subcommands cover the full lifecycle from first index to CI handoff.

| Command | Purpose |
|---|---|
| `batho build` | Build the initial AST code graph (first-time setup or `--full` rebuild) |
| `batho patch` | Incremental update — re-parses only changed files via hash detection |
| `batho diff` | Node-level change history across runs, files, or specific symbols |
| `batho export` | Export JSON views (8 types) or a `.batho` transport pack for CI/CD |
| `batho load` | Ingest a `.batho` transport ZIP — pair with `patch` for incremental CI |
| `batho fix` | Multi-stage integrity check + repair (db, state, blobs, graph) |
| `batho gc` | Storage maintenance — prune old runs, vacuum, status |
| `batho mcp` | Run the MCP server (the agent-facing surface; see [MCP Tools](#mcp-tools)) |
| `batho install` | One-command setup — installs the skill pack + registers MCP across detected agents |
| `batho plugins` | Validate, list, and apply `bsg-plugin.v2` custom rule plugins |
| `batho communities` | Post-build community operations — list and (optional) LLM-label communities |

**Most used:**

```bash
batho build --root . --verbose   # first index
batho patch                      # incremental update after edits
```

**Safe by default** — static analysis only; never executes target code. All commands accept `--root <path>` and `--verbose`.

Full reference: **[CLI docs](https://batho.sageoz.org/docs/cli-reference)**

---

### Batho Structured Graph (BSG)

The semantic graph layer of Batho — entities and relationships parsed deterministically using tree-sitter ASTs. Every structural answer is grounded here, not guessed.

#### Overview

| Aspect | Description |
|---|---|
| **Entities** | Functions, classes, modules, methods, properties, variables (28 types) |
| **Relationships** | Calls, imports, inheritance, overrides, uses (17 structural + 4 annotation) |
| **Parsing** | Deterministic tree-sitter ASTs — no embeddings or LLM guesses |
| **Storage** | Full-fidelity JSON (`bsg.v2`) in Arrow IPC |
| **Agent view** | Token-capped compact summary (~10x compression) |
| **Citable** | Every claim backed by `entity_id` + `file:line` |

<details>
<summary>Entity Types</summary>

| Category | Types |
|---|---|
| **Code** (19) | `FUNCTION`, `METHOD`, `CLASS`, `STRUCT`, `INTERFACE`, `TRAIT`, `ENUM`, `TYPE_ALIAS`, `FIELD`, `CONSTANT`, `VARIABLE`, `MODULE`, `NAMESPACE`, `ENTRY_POINT`, `PROPERTY`, `CONSTRUCTOR`, `ENUM_MEMBER`, `PARAMETER`, `TYPE_PARAMETER` |
| **External** (1) | `EXTERNAL_SYMBOL` |
| **Infrastructure** (2) | `INFRASTRUCTURE_CONFIG`, `ENVIRONMENT_VARIABLE` |
| **Markup** (4) | `SETTING`, `SECTION`, `ELEMENT`, `DOCUMENT` |
| **Structural** (2) | `SYNTAX_GLUE`, `COMMENT_BLOCK` |

</details>

<details>
<summary>Relationship Types</summary>

**Structural (17)** — extracted from ASTs:

| Relationship | Meaning |
|---|---|
| `CALLS` | Function/method invocation |
| `IMPORTS` | Import/module dependency |
| `INHERITS` | Class inheritance |
| `IMPLEMENTS` | Interface/trait implementation |
| `USES` | Generic use dependency |
| `CONTAINS` | Lexical containment (parent → child) |
| `READS` / `WRITES` | Variable access |
| `DEFINES` | Definition binding |
| `OVERRIDES` | Method override |
| `WRAPPED_BY` | Decorator/wrapper |
| `DEPENDS_ON_API` | External API dependency |
| `STACK_BOUNDARY` | Async/FFI call-stack boundary |
| `HAS_ATTRIBUTE` / `LINKS_TO` / `IMPORTS_STYLE` | Markup relationships |
| `RATIONALE_FOR` | Comment → symbol it explains |

**Annotation (4)** — derived by calibration:

| Edge | Source | Confidence |
|---|---|---|
| `RATIONALE_FOR` | Enclosing/nearest symbol match | 0.75 |
| `SEMANTICALLY_SIMILAR_TO` | Same-family top-K pairs | 0.65–0.80 |
| `TESTED_BY` | `test_<stem>` naming + link affinity | 0.65–0.85 |
| `REFERS_TO` | Explicit `bsg.edge_hints` | 0.75 |

</details>

<details>
<summary>Entity Metadata (from calibration)</summary>

| Key | Purpose |
|---|---|
| `bsg.scope_tier` | `PUBLIC` / `INTERNAL` / `PRIVATE` |
| `bsg.category` | `SOURCE` / `TEST` / `CONFIG` / `DOCS` / `GENERATED` / `VENDOR` |
| `bsg.service_tag` | Service attribution (API, auth, DB…) |
| `bsg.domain` | Domain tier for communities |
| `bsg.noise` / `bsg.quarantined` | Hide from search/overview |
| `bsg.semantic_family` | Family tag for similarity edges |
| `bsg.edge_hints` | Declarative annotation targets |

</details>

#### Why BSG over grep and embeddings?

| Dimension | Batho Structured Graph (BSG) | Grep | Embeddings |
|---|---|---|---|
| **What it finds** | Exact entities + relationships from ASTs | Substring/regex matches in text | Approximate semantic similarity |
| **"Who calls X?"** | Resolved `CALLS` edges with `entity_id` + `file:line` | Lists lines containing `X(` — misses aliases, indirection, cross-file resolution | Returns similar-looking code, not actual callers |
| **Cross-file resolution** | Stubs → FQNs → files; stdlib vs third-party vs internal | None — each file is independent | None — chunks are independent |
| **Accuracy** | Deterministic, auditable — every claim citable | Exact for strings; blind to structure | Fuzzy nearest-neighbor — may hallucinate |
| **Inheritance / overrides** | `INHERITS`, `IMPLEMENTS`, `OVERRIDES` edges | Cannot detect | Cannot detect |
| **Impact / blast radius** | `trace_path` (BFS) + `file_connectivity` | Manual tracing across files | Not available |
| **Token cost** | Low — ~10x compression, agent view is token-capped | High — agent reads raw files to understand context | Medium — embeddings + retrieval overhead |
| **Freshness** | Hash-based `patch` re-parses only changed files | Always current (reads live files) | Requires re-embedding on change |
| **Trust level** | Deterministic (AST-grounded facts) | Raw text (no semantic claims) | Probabilistic (similarity scores) |
| **Best for** | Structural queries, impact analysis, grounded answers | Exact string search, find-and-replace | "Find code like this" exploration |

- **Grep** answers: *"Where does this string appear?"*
- **Embeddings** answers: *"What code looks similar?"*
- **BSG** answers: *"How does this code actually connect?"* — the question agents need answered to make safe edits.

Learn more: **[Whitepaper](https://batho.sageoz.org/docs/whitepaper)**

---

### MCP Server

Exposes the code graph to AI agents over the Model Context Protocol — retrieval instead of grep. The server reads pre-built `.batho` Arrow IPC artifacts and serves 20 tools, 7 workflow prompts, and 2 resources over stdio transport.

| Field | Detail |
|---|---|
| Transport | stdio (MCP standard) |
| Tools | **20 total** — 16 enabled by default, 4 admin tools disabled |
| Prompts | 7 workflow prompts with explicit tool routing |
| Resources | 2 (`batho://schema`, `batho://repos`) |
| File watcher | `--watch` auto-patches on edits (2s debounce, 60s max staleness, 300-file flush threshold) |
| Multi-repo | `list_repos` / `add_repo` / `remove_repo` registry — one server, many repos |
| Server instructions | Injected via MCP `initialize` — guides agents to query Batho before grep/read |
| Learn more | [MCP docs](https://batho.sageoz.org/docs/mcp) · [MCP Tools](#mcp-tools) |

#### Tool tiers

| Tier | Count | Default | Learn more |
|---|---|---|---|
| **Read-only** | 14 | Always enabled | [MCP Tools](#mcp-tools) |
| **Destructive** | 2 | Enabled (agent self-recovery) | [MCP Tools](#mcp-tools) |
| **Administrative** | 4 | **Disabled** — run in terminal | [Enabling Tier 3](#enabling-tier-3-tools) |

Admin tools are disabled by default because a full rebuild blocks the conversation, and export/load/gc are terminal or CI operations. Three ways to opt in: `batho.yaml` config, environment variables, or `--enable-tool` CLI flags. See [Enabling Tier 3 tools](#enabling-tier-3-tools) below.

---

## MCP Tools

Batho exposes **20 MCP tools** organized into three tiers. By default, **16 tools** are available to your AI agent — the 4 administrative tools are disabled to keep the agent's tool surface focused on retrieval and diagnostics (matching the Sourcegraph/Cursor/CodeGraph pattern where indexing is a background process and the agent is a pure consumer).

### All 20 tools

| Tool | Tier | Toolset | Default | Purpose |
|---|---|---|---|---|
| `list_repos` | Read-only | registry | Enabled | List all registered repos with status |
| `add_repo` | Read-only | registry | Enabled | Register a repository in the MCP registry |
| `remove_repo` | Read-only | registry | Enabled | Remove a repository from the registry |
| `graph_overview` | Read-only | retrieval | Enabled | High-level codebase summary: entities, relationships, communities |
| `graph_query` | Read-only | retrieval | Enabled | Filtered graph query by file, type, or name pattern |
| `get_entity` | Read-only | retrieval | Enabled | Detailed info for a single entity + relationships |
| `trace_path` | Read-only | retrieval | Enabled | Shortest path between two entities (BFS) |
| `get_file_graph` | Read-only | retrieval | Enabled | All entities and relationships in a file |
| `file_connectivity` | Read-only | retrieval | Enabled | File-level dependency picture in both directions for impact assessment |
| `search_entities` | Read-only | retrieval | Enabled | Substring/regex search across entity names |
| `get_delta` | Read-only | retrieval | Enabled | Incremental changes from the latest patch |
| `batho_status` | Read-only | diagnostics | Enabled | Artifact status, generation, and run info for a repo |
| `batho_list_runs` | Read-only | diagnostics | Enabled | List all build/patch runs with metadata |
| `batho_diff` | Read-only | diagnostics | Enabled | Node-level changes across runs, entities, or files |
| `batho_patch` | Destructive | admin | Enabled | Incremental update of an existing artifact after file edits |
| `batho_fix` | Destructive | admin | Enabled | Verify and repair artifact database integrity |
| `batho_build` | Administrative | admin | **Disabled** | Full index build (first-time setup or forced rebuild) |
| `batho_export` | Administrative | admin | **Disabled** | Export a JSON view or Pack artifact to disk |
| `batho_load` | Administrative | admin | **Disabled** | Unpack a transport `.batho` ZIP into an artifact |
| `batho_gc` | Administrative | admin | **Disabled** | Garbage collection and database maintenance |

**Tier 2 (Destructive)** tools modify the artifact but are useful for agent self-recovery. MCP clients should prompt for confirmation via `destructiveHint=True`.

**Tier 3 (Administrative)** tools are expensive or setup/CI operations. The agent should detect when they're needed and instruct the user to run them in the terminal — not call them mid-conversation.

#### Workflow prompts

Each prompt provides explicit tool routing and negative guidance to prevent hallucination — agents follow the optimal tool sequence instead of guessing.

| Prompt | Answers | Tool sequence |
|---|---|---|
| `explore_codebase` | "What does this codebase do?" | `list_repos` → `graph_overview` → `graph_query` → `get_file_graph` |
| `understand_function` | "What does X do / how does X work?" | `search_entities` → `get_entity` → `trace_path` |
| `analyze_file` | "What's in file X?" | `get_file_graph` → `get_entity` |
| `trace_dependency` | "How does A reach B?" | `search_entities` × 2 → `trace_path` |
| `review_changes` | "What changed in the last patch?" | `get_delta` → `get_entity` → `graph_overview` |
| `impact_analysis` | "What breaks if I change X?" | `search_entities` → `get_entity` → `trace_path` → `get_file_graph` |
| `architecture_overview` | "Quick orientation to an unfamiliar repo" | `graph_overview` (single call, ~200–500 tokens) |

#### Resources

| Resource | URI | Returns |
|---|---|---|
| Schema | `batho://schema` | Entity types, relation types, categories, response formats, change kinds |
| Repos | `batho://repos` | Registered repos with name, path, artifact status |

#### File watcher

The watcher (`--watch`, on by default) monitors watched repos for filesystem events and auto-patches the artifact:

- **Debounce**: 2s trailing-edge (configurable per-repo via `debounce_ms`)
- **Max staleness**: 60s bound — a patch fires even if events keep arriving
- **Flush threshold**: 300 pending files triggers immediate patch
- **Git sentinel**: watches `.git` for stage/commit/checkout/merge/rebase boundaries — flushes at logical change points
- **Catch-up**: on server start, patches any files that changed while the server was down
- **Hash-diff source of truth**: filesystem events are only hints — `IncrementalEngine.scan_changes` hash comparison remains the source of truth, so lost events are recovered by the next patch

### Enabling Tier 3 tools

Three ways to opt in — pick whichever fits your workflow:

<details>
<summary>Config file (batho.yaml)</summary>

```yaml
mcp:
  enabled: true
  tools:
    disabled: [] # empty list = all 20 tools enabled
    # Or enable specific tools only:
    # disabled: [batho_build, batho_load]  # keeps export + gc enabled
    enabled: null # optional allowlist (overrides disabled if set)
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

### Batho Skill Pack

Six pre-configured skills that let any coding agent self-install Batho and drive a graph-grounded spec→implement→review lifecycle. Distributed via the [batho-skills](https://github.com/sageoz/batho-skills) repo — one command installs all 6 skills across 22 supported agents.

| Field | Detail |
|---|---|
| Skills | 6 (`batho`, `batho-setup`, `batho-specs`, `batho-execute`, `batho-review`, `batho-calibrate`) |
| Agents | 22 supported out of the box (Claude Code, Cursor, Copilot, Codex, Gemini CLI, Windsurf, Devin, + 15 more) |
| Install | `npx skills add sageoz/batho-skills` — auto-detects installed agents |
| Format | Agent Skills format (`skills/<name>/SKILL.md`) — [agentskills.io](https://agentskills.io) |
| Canonical path | `~/.agents/skills/` (global) or `.agents/skills/` (project) |
| Supply chain | Deterministic, checksummed, SLSA-attested release artifacts |
| Learn more | [batho-skills repo](https://github.com/sageoz/batho-skills) · [Skill setup docs](https://batho.sageoz.org/docs/getting-started/skill-setup) |

#### The 6 skills

| Skill | Role | When it runs |
|---|---|---|
| `batho` | Router + artifact lifecycle — builds/refreshes the graph, routes questions to MCP tools, routes work to lifecycle skills | First in every session; the only skill that builds/patches |
| `batho-setup` | Install the `batho` CLI, register the MCP server, install the skill pack | One-time setup; when MCP tools are missing |
| `batho-specs` | Graph-grounded specifications — every claim cites entities (`entity_id` + `file:line`) | When the user describes something to build or change |
| `batho-execute` | Spec-driven implementation — dependency-ordered tasks with pre-edit grounding + post-edit delta verification | When the user says "execute spec" or approves a spec |
| `batho-review` | Graph-verified review — per-criterion PASS/FAIL with structural delta reports | After `batho-execute` finishes; before closing a task/PR |
| `batho-calibrate` | Graph calibration via custom rule plugins — quarantine noise, classify entities, derive annotation edges | When the user asks to calibrate/enrich the graph or fix gaps |

#### The SDLC loop

```
batho-setup  →  install CLI + MCP + skills (one-time)
      ↓
batho        →  build/refresh graph, route questions (every session)
      ↓
batho-specs  →  grounded spec (every claim cites entities)
      ↓
batho-execute →  dependency-ordered tasks (pre-edit grounding, post-edit delta)
      ↓
batho-review →  per-criterion PASS/FAIL against the graph's change record
      ↓
batho-calibrate →  rule plugins that quarantine noise + enrich the graph
```

Each stage is a graph-grounded handoff: specs cite entities, execution grounds edits in current signatures, review verifies against the graph's change record, and calibration enriches the graph for the next cycle. Human approval gates sit between specs→execute and execute→review.

#### 22 supported agents

Canonical copies land in `~/.agents/skills/` (global) or `.agents/skills/` (project). Agents that don't read that path natively get mirrors — only when detected.

| | | |
|---|---|---|
| Claude Code | Cursor | GitHub Copilot |
| OpenAI Codex | Gemini CLI | OpenCode |
| Windsurf | Devin | Amp |
| Roo Code | Cline | Zed |
| Kiro | Factory Droid | Trae |
| Google Antigravity | JetBrains Junie | Goose |
| Warp | Pi | Continue |
| Kilo Code | | |

Full per-agent discovery table: [agent-paths.json](https://github.com/sageoz/batho-skills/blob/main/agent-paths.json)

#### Install

```bash
# One command — auto-detects installed agents and writes each skill
# where that agent looks
npx skills add sageoz/batho-skills
```

<details>
<summary>Other install methods</summary>

**Claude Code (plugin marketplace):**

```bash
/plugin marketplace add sageoz/batho-skills
/plugin install batho@batho
```

**curl installer (macOS / Linux):**

```bash
curl -fsSL https://github.com/sageoz/batho-skills/releases/latest/download/install.sh | sh
```

**PowerShell (Windows):**

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -c "irm https://github.com/sageoz/batho-skills/releases/latest/download/install.ps1 | iex"
```

**Manual:** copy `skills/<name>` into `~/.agents/skills/` or `.agents/skills/`.

</details>

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
- uses: sageoz/batho@v1.4.3
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

- `disabled`: blocklist of tool names to hide. Set to `[]` to expose all 20 tools.
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
