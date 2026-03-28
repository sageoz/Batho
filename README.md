<p align="center">
  <img src="assets/logo.svg" alt="Batho" width="160" height="160" />
</p>

<h1 align="center">Batho</h1>

<p align="center">
  <strong>Open-Source Code Intelligence for AI-Powered Development</strong><br>
  Turn any codebase into structured knowledge your LLMs, agents, and tools can actually use.
</p>

<p align="center">
  <a href="https://pypi.org/project/batho/"><img src="https://img.shields.io/pypi/v/batho?color=blue" alt="PyPI"></a>
  <a href="https://github.com/batho-ai/batho/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
  <a href="#supported-languages"><img src="https://img.shields.io/badge/languages-40+-orange" alt="Languages"></a>
  <a href="https://github.com/batho-ai/batho/stargazers"><img src="https://img.shields.io/github/stars/batho-ai/batho?style=social" alt="Stars"></a>
</p>

<br>

> **Batho** indexes 40+ programming languages via tree-sitter, compresses the result 10:1 for LLM context windows, and tracks changes over time — all without executing a single line of your code.

---

## Quick Start

Get running in 30 seconds:

```bash
# Install
pip install batho

# Index your project
batho index --root . --verbose

# View results
batho stats --root .
```

That's it. Batho scans your codebase, extracts every function, class, import, and relationship, and writes structured output to `.ctn/`.

---

## Why Batho?

Modern AI tools need **structured code understanding** — not just raw file contents. Batho bridges that gap.

| What you get | Why it matters |
|---|---|
| **40+ language AST parsing** | One tool for polyglot repos — Python, TypeScript, Rust, Go, Java, and more |
| **10:1 context compression** | Fit entire codebases into LLM context windows |
| **Time Machine snapshots** | Track how your codebase evolves between releases |
| **Zero code execution** | Safe to run in CI, pre-commit, or on untrusted repos |
| **Enterprise-grade caching** | mtime+SHA skips unchanged files — re-indexes in seconds |

---

## How It Works

```
Your Code → [tree-sitter AST] → Code Graph → RepoMap → LLM / Agent / IDE
```

1. **Parse** — tree-sitter extracts functions, classes, variables, imports with full signatures
2. **Graph** — Entities and relationships (IMPORTS, CALLS, USES, DEFINES) form a code graph
3. **Compress** — RepoMap renders the graph in multiple formats: compressed, full, JSON, hierarchical
4. **Track** — Time Machine snapshots let you diff code intelligence over time

---

## Features

### Multi-Language AST Extraction

Batho uses [tree-sitter](https://tree-sitter.github.io/tree-sitter/) for precise, language-aware parsing:

- **Functions** — name, signature, parameters, return type, docstring
- **Classes** — name, base classes, methods, attributes
- **Interfaces/Traits** — method signatures
- **Variables** — declarations, types, assignments
- **Imports** — module paths, selective imports

Relationships captured: `IMPORTS` · `CALLS` · `USES` · `DEFINES`

### RepoMap Compression

Transforms full code graphs into compact representations:

```python
repomap.render_compressed(budget=12000)  # → "main.py: login (function)..."
```

| Mode | Best for |
|------|----------|
| **Compressed** | LLM prompt injection (4K–40K tokens) |
| **Full** | Developer reference with signatures + line numbers |
| **JSON** | Programmatic access and tooling |
| **Hierarchical** | Directory-tree overviews |

### Time Machine

```bash
batho snapshots --root .                              # Create snapshot
batho diff-snapshots --root . SNAP_A SNAP_B           # Compare versions
```

Versioned snapshots with UUID + timestamp, entity/relationship diffs, and staleness scoring for automated re-indexing.

### Smart Indexing

- **mtime + SHA-256 cache** — unchanged files are skipped instantly
- **Parallel extraction** — auto-scaled threads (CPU × 2, capped at 32)
- **Binary detection** — magic bytes + entropy analysis
- **Ignore support** — `.gitignore` + `.bathoignore` via pathspec
- **Per-file isolation** — one bad file never aborts the scan

### Stack Detection

Automatically identifies your tech stack from config files:

**Python** (FastAPI, Django, Flask) · **Node.js** (React, Vue, Express, NestJS) · **Java** (Spring, Maven, Gradle) · **.NET** (ASP.NET, Entity Framework) · **Go** (Gin, Echo) · **Ruby** (Rails, Sinatra) · **Rust** (Cargo) · **Mobile** (Android, iOS) · **Data/ML** (PyTorch, TensorFlow, Pandas)

---

## Supported Languages

| Category | Languages |
|----------|-----------|
| **Web / Backend** | Python, TypeScript, JavaScript, Go, Java, Ruby, PHP, C#, Scala, Kotlin |
| **Systems** | Rust, C, C++, Zig, Objective-C |
| **Mobile** | Swift, Kotlin (Android), Objective-C (iOS) |
| **Functional** | Haskell, Erlang, OCaml, Elixir, Julia, Agda |
| **Scripting** | Bash, Perl, Lua, R |
| **Other** | Dart, Verilog, Hack |
| **Markup / Config** | JSON, YAML, TOML, HTML, CSS/SCSS/SASS/LESS, Markdown, HCL/Terraform |

> Parser availability depends on installed `tree_sitter_language_pack` grammars. Missing grammars are skipped gracefully.

---

## Installation

```bash
pip install batho          # pip
uv pip install batho       # uv
pip install -e .           # development (editable)
```

---

## CLI Reference

```bash
# Index a repository
batho index --root /path/to/repo --verbose

# View index stats
batho stats --root /path/to/repo

# Reindex changed files from a diff
batho patch --root /path/to/repo --diff /path/to/pr.diff

# Reindex specific files
batho patch --root /path/to/repo file1.py dir/file2.ts

# Snapshots & diff
batho snapshots --root /path/to/repo
batho diff-snapshots --root /path/to/repo SNAP_A SNAP_B

# Clear cache (force full re-parse)
batho invalidate --root /path/to/repo
```

### Index Options

| Flag | Default | Description |
|------|---------|-------------|
| `--max-workers` | `0` (auto) | Worker threads — 0 uses CPU × 2, capped at 32 |
| `--max-file-size-kb` | `500` | Skip files larger than this |
| `--budget-tokens` | `12000` | Token budget for compressed output |
| `--log-json` | off | JSON structured logs (useful in CI) |
| `--verbose` | off | Print progress to stdout |

---

## Output

```
.ctn/
├── index.json               # Index metadata + staleness score
├── file_cache.json          # mtime + SHA cache for fast re-runs
├── metrics.json             # Performance metrics
├── snapshots/               # Time Machine snapshots
│   └── batho_<uuid>_<ts>.json
└── <index_id>/
    ├── graph.json           # All entities + relationships
    ├── repomap.json         # Structured symbol index
    └── architecture.md      # Human-readable summary
```

<details>
<summary><strong>graph.json example</strong></summary>

```json
{
  "schema_version": "graph.v1",
  "entities": [
    {"id": "e1", "name": "login", "type": "function", "file": "auth.py", "start_line": 10, "end_line": 25}
  ],
  "relationships": [
    {"source_id": "e1", "target_id": "e2", "type": "IMPORTS"}
  ]
}
```

</details>

<details>
<summary><strong>repomap.json example</strong></summary>

```json
{
  "schema_version": "repomap.v1",
  "files": {
    "src/auth.py": [
      {"name": "login", "type": "function", "lines": [10, 25], "signature": "(username, password) -> bool"}
    ]
  },
  "dependencies": {
    "src/auth.py": ["os", "pathlib", "src/models.py"]
  }
}
```

</details>

---

## Configuration

Batho works out of the box with zero config. For advanced use, configure via environment variables or a config file.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BATHO_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `BATHO_CTN_DIR` | `.ctn` | Output directory |
| `BATHO_MAX_FILE_SIZE_KB` | `500` | Max file size to parse |
| `BATHO_MAX_INDEXED_FILES` | `200000` | Hard cap on indexed files |
| `BATHO_INDEX_WORKERS` | `0` | Worker threads (0 = auto) |
| `BATHO_REPOMAP_BUDGET_TOKENS` | `12000` | Default token budget |
| `BATHO_CONFIG_FILE` | — | Path to config file (JSON/YAML/TOML) |

### Config File

```yaml
# batho.yaml
logging:
  level: DEBUG
  json_format: true

indexer:
  max_file_size_kb: 1000
  max_workers: 16
  repomap_budget_tokens: 20000
  ignore_patterns:
    - "**/vendor/**"
    - "**/dist/**"

flags:
  strict: true
  fail_on_warning: true
```

---

## Using Batho with AI

Batho is built to power AI-assisted development. Here are common patterns:

### Feed LLM Context

```python
from batho_core.context.codegraph import CodeGraphIndexer
from batho_core.context.repomap import RepoMap

indexer = CodeGraphIndexer()
graph = indexer.build_graph(root="/path/to/repo")
repomap = RepoMap.build(graph, root="/path/to/repo")

# Compressed for LLM context window
compressed, stats = repomap.render_compressed(budget=12000)
# → Inject 'compressed' into your LLM prompt as codebase context
```

### Codebase Q&A

```python
# Find all functions that call 'authenticate'
for rel in graph.relationships:
    target = graph.get_entity(rel.target_id)
    if target and target.name == "authenticate":
        source = graph.get_entity(rel.source_id)
        print(f"{source.name} → authenticate  ({source.file})")
```

### Impact Analysis (Pre-Refactoring)

```python
# Find every caller of a function before changing it
for rel in graph.relationships:
    if rel.target_id == target_id and rel.type.name == "CALLS":
        caller = graph.get_entity(rel.source_id)
        print(f"  Will be affected: {caller.name} in {caller.file}")
```

### RAG / Vector Embedding

```bash
batho index --root /path/to/repo
# → Embed .ctn/*/repomap.json chunks into your vector DB
```

### Agentic AI

Autonomous agents can use Batho's structured graph to navigate codebases, resolve imports, and understand call chains — without reading every file.

---

## Integrations

### CI/CD (GitHub Actions)

```yaml
name: Code Index
on: [push, pull_request]
jobs:
  index:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install batho
      - run: batho index --root . --verbose --log-json
      - run: batho stats --root .
```

### Pre-commit Hook

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: batho-index
      name: Batho Code Index
      entry: batho index --root .
      language: system
      pass_filenames: false
      always_run: true
```

### VS Code Task

```json
{
  "version": "2.0.0",
  "tasks": [{
    "label": "Batho Index",
    "type": "shell",
    "command": "batho index --root ${workspaceFolder} --verbose"
  }]
}
```

---

## Security & Compliance

| Guarantee | Details |
|-----------|---------|
| **Parse-only** | Batho never executes your code — safe on untrusted repos |
| **Binary detection** | Magic bytes + Shannon entropy analysis |
| **Ignore rules** | Respects `.gitignore` and `.bathoignore` |
| **Atomic writes** | Temp file + rename — no partial outputs on crash |
| **Fully offline** | Zero network calls — runs air-gapped |

For regulated environments, add SBOM and license checks in CI:

```bash
pip install cyclonedx-bom && cyclonedx-py -o sbom.xml
pip install pip-licenses && pip-licenses --allow-only MIT
```

---

## Performance

| Repo Size | Workers (auto) | Typical Time |
|-----------|----------------|--------------|
| < 50 files | 4 | < 2s |
| 50–200 files | 8 | 2–5s |
| 200–1K files | 16 | 5–15s |
| 1K+ files | 32 | varies |

**Tips for large monorepos (2M+ LOC):**
- Run on fast local SSD
- Use `--log-json` to reduce console overhead
- Add build artifacts to `.bathoignore`:
  ```
  node_modules/
  vendor/
  dist/
  build/
  __pycache__/
  ```

---

## Architecture

```
batho/
├── batho.py                      # CLI entry point
└── batho_core/
    ├── config.py                 # Pydantic-validated configuration
    ├── time_machine.py           # Snapshots, diffs, staleness
    ├── context/
    │   ├── codegraph.py          # Parallel code graph indexer
    │   ├── repomap.py            # Multi-format RepoMap renderer
    │   ├── stack_detector.py     # Tech stack detection
    │   └── languages/            # Per-language tree-sitter extractors
    └── utils/
        ├── logging.py            # Structured logging (structlog)
        ├── hash.py               # SHA-256 utilities
        └── ignore.py             # .gitignore / .bathoignore
```

---

## Contributing

Batho is open source and welcomes contributions. Whether it's a bug report, a new language extractor, or a docs improvement — we'd love your help.

1. Fork the repo
2. Create a feature branch
3. Run the test suite: `uv run pytest`
4. Submit a pull request

---

## Roadmap

- [ ] Production incremental patching (webhook-driven)
- [ ] Monorepo-aware stack detection
- [ ] Snapshot diff fidelity improvements
- [ ] Enterprise telemetry and health checks
- [ ] Advanced compression policies
- [ ] MCP server integration

---

## License

MIT — see [LICENSE](LICENSE)

---

<p align="center">
  <a href="https://pypi.org/project/batho/">PyPI</a> · <a href="https://github.com/batho-ai/batho/issues">Issues</a> · <a href="https://github.com/batho-ai/batho/discussions">Discussions</a>
</p>