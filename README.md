<p align="center">
  <img src="assets/batho.svg" alt="Batho" width="220" height="220" />
</p>

<h1 align="center">B.A.T.H.O</h1>

<p align="center">
  <strong>Bidirectional AST Traversal & Hypergraph Orchestrator</strong><br>
  <b>BATHO</b> indexes your codebase, compresses the result for LLM context windows, and tracks changes over time.
</p>

<p align="center">
  <a href="https://pypi.org/project/batho/"><img src="https://img.shields.io/pypi/v/batho?color=blue" alt="PyPI"></a>
  <a href="https://github.com/sageoz/batho/releases/tag/v1.0.0"><img src="https://img.shields.io/badge/v1.0.0-release-orange" alt="v1.0.0"></a>
  <a href="https://github.com/sageoz/batho/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
  <a href="https://batho.sageoz.org"><img src="https://img.shields.io/badge/docs-batho.sageoz.org-green" alt="Documentation"></a>
</p>

<br>

## 📚 Official Documentation

For complete documentation, guides, and API reference, visit **[batho.sageoz.org](https://batho.sageoz.org)**.

## 🚀 Quick Start

```bash
# Install
pip install batho

# Launch the interactive Dashboard
batho dashboard --root .

# Index your project
batho index --root . --snapshot

# Generate compressed BSG for LLM injection
batho bsg --root . --mode compressed --budget 12000

# Start the Artifact Bridge (REST API + MCP server)
batho bridge serve --root .

# Auto-detect and patch changes
batho patch --root . --scan
```

## ✨ Key Features

- **40+ language AST parsing** — Python, TypeScript, Rust, Go, Java, and more
- **Interactive Web Dashboard (v1)** — Hypergraph visualization, file browser, search, metrics
- **10x context compression** — Fit entire codebases into LLM context windows
- **Time Machine snapshots** — Track codebase evolution with incremental patching
- **Git Hooks Enterprise** — YAML-driven client-side hook automation
- **Artifact Bridge** — REST API + MCP server for IDE integrations
- **SQLite-backed caching** — 95%+ cache hit rates for incremental updates
- **Zero code execution** — Safe to run in CI, pre-commit, or on untrusted repos

## 🆕 What's New in v1.0.0

The interactive **Dashboard** is the centerpiece of v1:

- **9 pages**: Overview, Hypergraph, Files, File Viewer, Relationships, Rules, Metrics, Snapshots, Search
- **Keyboard shortcuts**: `Ctrl/Cmd + K` for search, `Ctrl/Cmd + D` for dark mode, graph zoom controls
- **Export options**: PNG, SVG, JSON, CSV
- **Real-time code intelligence** with 859+ automated tests

**Artifact Bridge** enables IDE integrations:

- REST API server (`batho bridge serve`)
- MCP server for Claude, Cursor, and other AI tools
- Cloud sync capabilities

## 🔄 How It Works

1. **Parse** — tree-sitter extracts functions, classes, variables, imports with full signatures
2. **Graph** — Entities and relationships (IMPORTS, CALLS, USES, DEFINES) form a code graph
3. **Compress** — BSG renders the graph in multiple formats: compressed, full, JSON, hierarchical
4. **Visualize** — Dashboard renders interactive hypergraphs, file explorers, metrics, and snapshots
5. **Track** — Time Machine snapshots let you diff code intelligence over time

## 💡 Why Batho?

Modern AI tools need **structured code understanding** — not just raw file contents. Batho bridges that gap.

| What you get | Why it matters |
|---|---|
| **40+ language AST parsing** | One tool for polyglot repos — Python, TypeScript, Rust, Go, Java, and more |
| **Interactive Web Dashboard** | Explore your codebase visually with hypergraphs, file browser, and metrics |
| **10x context compression** | Fit entire codebases into LLM context windows |
| **Time Machine snapshots** | Track how your codebase evolves between releases |
| **Artifact Bridge** | REST API + MCP server for IDE integrations |
| **SQLite-backed caching** | 95%+ cache hit rates for incremental updates |
| **Zero code execution** | Safe to run in CI, pre-commit, or on untrusted repos |

## 📊 BSG Modes

Batho Structured Graph (BSG) can be rendered in multiple formats:

```bash
# Compressed for LLM injection (4K–40K tokens)
batho bsg --root . --mode compressed --budget 12000

# Full with signatures + line numbers
batho bsg --root . --mode full

# Hierarchical directory-tree view
batho bsg --root . --mode hierarchical
```

## 🕐 Time Machine

Track codebase evolution with versioned snapshots:

```bash
# Create snapshot
batho index --root . --snapshot --snapshot-label "release-candidate"

# List all snapshots
batho snapshots --root .

# Compare two snapshots
batho diff-snapshots --root . SNAP_A SNAP_B
```

## 🪝 Git Hooks

YAML-driven Git client-side hook automation:

```bash
# Install all enabled hooks
batho hooks install --all

# Run hook manually
batho hooks run --hook pre-commit
```

Configure in `.batho/hooks.yaml`:

```yaml
version: hooks.v1
hooks:
  pre-commit:
    enabled: true
    stages:
      - run: ruff check .
      - run: pytest --co -q
```

## 🔒 Security

| Guarantee | Details |
|-----------|---------|
| **Parse-only** | Never executes your code — safe on untrusted repos |
| **Binary detection** | Magic bytes + Shannon entropy analysis |
| **Ignore rules** | Respects `.gitignore` and `.bathoignore` |
| **Fully offline** | Zero network calls — runs air-gapped |

## 🌍 Supported Languages

| Category | Languages |
|----------|-----------|
| **Web / Backend** | Python, TypeScript, JavaScript, Go, Java, Ruby, PHP, C#, Scala, Kotlin |
| **Systems** | Rust, C, C++, Zig, Objective-C |
| **Mobile** | Swift, Kotlin, Objective-C |
| **Functional** | Haskell, Erlang, OCaml, Elixir, Julia |
| **Scripting** | Bash, Perl, Lua, R |
| **Markup / Config** | JSON, YAML, TOML, HTML, CSS, Markdown, HCL/Terraform |

## 📁 Output Structure

Batho stores all artifacts in `.ctn/` (CTN = Code Tracking Network):

```
.ctn/
├── index.json                   # Index metadata + staleness
├── artifact_registry.db         # SQLite artifact registry
├── file_cache.json              # File metadata cache
├── snapshots/                   # Time Machine snapshots
├── patches/                     # Incremental patch operations
└── <index_id>/
    ├── graph.json               # Entities + relationships
    ├── bsg_compressed.json      # LLM-ready compressed output
    ├── bsg_full.json            # Full textual BSG output
    └── bsg_hierarchical.json    # Hierarchical textual BSG output
```

## ⚙️ Configuration

Batho works out of the box with zero config. For production use, configure with `./batho.yaml`:

```yaml
logging:
  level: INFO
indexer:
  max_file_size_kb: 500
  max_workers: 16
bsg:
  cache:
    enabled: true
  storage:
    enabled: true
```

## 📖 Documentation

For complete documentation including:
- CLI reference and command guide
- Configuration options
- Architecture and deployment
- BSG plugin system
- Git hooks automation

Visit **[batho.sageoz.org](https://batho.sageoz.org)**

## 💻 Installation

```bash
pip install batho
```

**PyPI:** https://pypi.org/project/batho/

## 🛠️ Developer Setup

```bash
# Clone the repository
git clone https://github.com/sageoz/batho.git
cd batho

# Install dependencies
uv sync --all-groups --all-extras

# Run tests
uv run pytest

# Run CLI from source
uv run python -m batho_cli --help
```

## 📄 License

Apache License 2.0 - see [LICENSE](LICENSE) for details.