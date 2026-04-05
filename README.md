<p align="center">
  <img src="assets/batho.svg" alt="Batho" width="160" height="160" />
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
  <a href="#-v100-launched"><img src="https://img.shields.io/badge/version-1.0.0-brightgreen" alt="Version 1.0.0 Launched"></a>
</p>

<br>

> **Batho** indexes 40+ programming languages via tree-sitter, compresses the result 10:1 for LLM context windows, and tracks changes over time — all without executing a single line of your code.
>
> **✨ Version 1.0.0 is now LAUNCHED!** Production-ready with enterprise features, webhooks, CI/CD integration, and automated documentation generation.

---

## Quick Start

Get running in 30 seconds:

```bash
# Install
pip install batho

# Index your project
batho index --root . --verbose

# Generate BSG in various formats
batho bsg --root . --mode compressed --budget 12000

# View results
batho stats --root .

# Create and manage snapshots
batho snapshots --root .
batho diff-snapshots --root . SNAP_A SNAP_B

# Incremental patching with tracking
batho patch --root . --scan
batho patches --root . --format timeline
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
| **Production webhooks** | GitHub/GitLab integration with authentication and queueing |
| **CI/CD pipeline hooks** | Turnkey GitHub Actions and GitLab CI templates |
| **Automated documentation** | Generate SRS and OWASP docs from your codebase |
| **Incremental patching** | 10-100x faster updates with complete lineage tracking |

---

## ✨ What's New in v1.0.0

- **🚀 Production Webhooks**: Full GitHub/GitLab integration with authentication and queueing
- **🔄 CI/CD Pipeline Hooks**: Turnkey templates for GitHub Actions and GitLab CI
- **📊 Automated Documentation**: Generate SRS and OWASP documentation
- **⚡ Enhanced Incremental Patching**: 10-100x faster updates with complete patch lineage tracking
- **🔒 Enterprise Security**: Memory monitoring, file locking, and path sanitization
- **📈 Comprehensive Testing**: 637 tests with 100% pass rate

---

## How It Works

```
Your Code → [tree-sitter AST] → Code Graph → BSG → LLM / Agent / IDE
```

1. **Parse** — tree-sitter extracts functions, classes, variables, imports with full signatures
2. **Graph** — Entities and relationships (IMPORTS, CALLS, USES, DEFINES) form a code graph
3. **Compress** — BSG renders the graph in multiple formats: compressed, full, JSON, hierarchical
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

### BSG Compression

Transforms full code graphs into compact representations via CLI:

```bash
# Generate compressed bsg for LLM injection
batho bsg --root . --mode compressed --budget 12000

# Generate full bsg with signatures
batho bsg --root . --mode full

# Generate hierarchical directory view
batho bsg --root . --mode hierarchical
```

| Mode | Best for | Output File |
|------|----------|-------------|
| **Compressed** | LLM prompt injection (4K–40K tokens) | `bsg_compressed.json` |
| **Full** | Developer reference with signatures + line numbers | `bsg_full.json` |
| **Hierarchical** | Directory-tree overviews | `bsg_hierarchical.json` |

### Time Machine

```bash
batho index --root . --snapshot                    # Create snapshot
batho snapshots --root .                           # List all snapshots
batho diff-snapshots --root . SNAP_A SNAP_B        # Compare versions
```

Versioned snapshots with UUID + timestamp, entity/relationship diffs, and staleness scoring for automated re-indexing.

### Incremental Patching with Tracking

```bash
# Auto-detect and patch changes
batho patch --root . --scan

# List all patch operations
batho patches --root . --format timeline

# Show detailed patch info
batho patch-info --root . --patch-id ID

# Apply patch from diff file
batho apply-patch --root . --base-snapshot ID --diff-file changes.diff

# Cherry-pick patch to different snapshot
batho cherry-pick --root . --patch-id ID --target-snapshot ID
```

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

# Generate BSG in various formats
batho bsg --root /path/to/repo --mode compressed --budget 12000
batho bsg --root /path/to/repo --mode full
batho bsg --root /path/to/repo --mode hierarchical

# View index stats
batho stats --root /path/to/repo

# Reindex changed files from a diff
batho patch --root /path/to/repo --diff /path/to/pr.diff

# Reindex specific files
batho patch --root /path/to/repo file1.py dir/file2.ts

# Snapshots & diff
batho index --root /path/to/repo --snapshot
batho snapshots --root /path/to/repo
batho diff-snapshots --root /path/to/repo SNAP_A SNAP_B

# Patch management
batho patches --root /path/to/repo --format timeline
batho patch-info --root /path/to/repo --patch-id ID
batho cherry-pick --root /path/to/repo --patch-id ID --target-snapshot ID

# Clear cache (force full re-parse)
batho invalidate --root /path/to/repo
```

### Index Options

| Flag | Default | Description |
|------|---------|-------------|
| `--max-workers` | `0` (auto) | Worker threads — 0 uses CPU × 2, capped at 32 |
| `--max-file-size-kb` | `500` | Skip files larger than this |
| `--log-json` | off | JSON structured logs (useful in CI) |
| `--verbose` | off | Print progress to stdout |
| `--snapshot` | off | Create snapshot after indexing |

### BSG Options

| Flag | Default | Description |
|------|---------|-------------|
| `--mode` | `compressed` | Rendering mode: compressed, full, hierarchical |
| `--budget` | `12000` | Token budget for compressed mode |

### Patch Options

| Flag | Default | Description |
|------|---------|-------------|
| `--scan` | off | Auto-scan for changes |
| `--dry-run` | off | Preview changes without applying |
| `--base-snapshot` | auto | Use specific snapshot as base |
| `--force-index-patch` | off | Force traditional index-based patching |

---

## Output

```
.ctn/
├── index.json               # Index metadata + staleness score
├── file_cache.json          # mtime + SHA cache for fast re-runs
├── metrics.json             # Performance metrics
├── snapshots/               # Time Machine snapshots
│   └── batho_<uuid>_<ts>.json
├── patches/                 # Patch operation history
│   └── patch_<uuid>_<ts>.json
└── <index_id>/
    ├── graph.json           # All entities + relationships
    ├── bsg.json             # Structured symbol index
    ├── bsg_compressed.json  # LLM-ready compressed view
    ├── bsg_full.json        # Complete symbol index with signatures
    ├── bsg_hierarchical.json # Directory tree view
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
<summary><strong>bsg.json example</strong></summary>

```json
{
  "schema_version": "bsg.v1",
  "nodes": [
    {
      "id": "e1",
      "type": "FUNCTION",
      "name": "login",
      "file": "src/auth.py",
      "start_line": 10,
      "end_line": 25
    }
  ],
  "edges": [],
  "indexes": {
    "nodes_by_file": {
      "src/auth.py": ["e1"]
    }
  }
}
```

</details>

---

## Configuration

Batho works out of the box with zero config. For advanced use, configure via environment variables and the unified root config file `./batho.yaml`.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BATHO_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `BATHO_CTN_DIR` | `.ctn` | Output directory |
| `BATHO_MAX_FILE_SIZE_KB` | `500` | Max file size to parse |
| `BATHO_MAX_INDEXED_FILES` | `200000` | Hard cap on indexed files |
| `BATHO_INDEX_WORKERS` | `0` | Worker threads (0 = auto) |
| `BATHO_RULES_ENABLED` | `false` | Enable BSG rule plugin stage |
| `BATHO_RULES_CUSTOM_RULES_PATH` | unset | YAML file containing custom BSG rules |
| `BATHO_RULES_BUILTIN_PLUGINS` | `bsg_core` | Comma-separated built-in plugin names |
| `BATHO_RULES_DISABLED_RULES` | unset | Comma-separated rule names to disable |

### Config File

```yaml
# ./batho.yaml
logging:
  level: DEBUG
  json_format: true

indexer:
  max_file_size_kb: 1000
  max_workers: 16
  ignore_patterns:
    - "**/vendor/**"
    - "**/dist/**"

flags:
  strict: true
  fail_on_warning: true

webhook:
  enabled: false

rules:
  enabled: true
  builtin_plugins: [bsg_core]
  disabled_rules: []
  custom_rules_path: ./bsg-rules.yaml
  custom_rules_inline:
    - name: payment-cluster
      entity_types: ["function", "method"]
      name_patterns: ["*payment*", "*invoice*"]
      metadata:
        bsg.cluster_hint: billing

  # Validation controls
  strict_validation: false
  fail_on_rule_error: false
```

### BSG Rule Plugins

Batho now applies BSG rules through internal plugin modules, not the root rules folder.

- Built-in rules are loaded from packaged plugins (default: `bsg_core`).
- Custom rules can be defined inline in `batho.yaml` via `rules.custom_rules_inline`.
- Custom rules can also be loaded from `rules.custom_rules_path` YAML files.
- Rule actions currently focus on deterministic metadata enrichment for graph entities (for example `bsg.category`, `bsg.scope_tier`, `bsg.service_tag`).

Custom rules YAML accepts either a top-level list or a `rules:` list.

```yaml
rules:
  - name: mark-test-files
    file_patterns: ["tests/**", "**/*_test.py"]
    metadata:
      bsg.category: TEST

  - name: derive-service-tag
    file_patterns: ["services/*/**"]
    actions:
      derive_service_tag: true
```

---

## Using Batho with AI

Batho is built to power AI-assisted development. Here are common patterns:

### Feed LLM Context

```bash
# Generate compressed bsg for LLM injection
batho bsg --root . --mode compressed --budget 12000
# → Output saved to .ctn/{index_id}/bsg_compressed.json
# → Load and inject into your LLM prompt as codebase context
```

Or programmatically:

```python
import json
from pathlib import Path

# Load compressed bsg generated by CLI
with open('.ctn/{index_id}/bsg_compressed.json', 'r') as f:
    data = json.load(f)
    compressed_text = data['compressed_text']
    stats = data['stats']
# → Inject 'compressed_text' into your LLM prompt as codebase context
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
batho bsg --root /path/to/repo --mode compressed
# → Embed .ctn/*/bsg_compressed.json chunks into your vector DB
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
      - run: batho index --root . --verbose --log-json --snapshot
      - run: batho stats --root .
      - uses: actions/upload-artifact@v4
        with:
          name: batho-output
          path: .ctn/
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
    - id: batho-patch
      name: Batho Incremental Patch
      entry: batho patch --root . --scan
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
    "command": "batho index --root ${workspaceFolder} --verbose --snapshot"
  },
  {
    "label": "Batho Patch",
    "type": "shell",
    "command": "batho patch --root ${workspaceFolder} --scan"
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
    │   ├── bsg_map.py            # Multi-format BSG renderer
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

### v1.1 (In Development)
- [ ] Advanced AI features and agentic architecture generation
- [ ] Live state integration with Jira/GitHub Issues
- [ ] Persistent graph storage for large repositories
- [ ] Enterprise telemetry and health checks

### v1.2 (Planned)
- [ ] Advanced compression with adaptive token budgeting
- [ ] Vulnerability scanning and license detection
- [ ] Complete MR validation with policy engine
- [ ] Full standards compliance (SRS/OWASP/ADR)

### Past Releases
- [x] **v1.0.0** - Production launch with webhooks, CI/CD, and automated docs
- [x] **v0.1.0** - Beta release with core functionality

---

## License

MIT — see [LICENSE](LICENSE)

---

## 🎉 Thank You!

Batho v1.0.0 is here thanks to our amazing community of contributors and users. We're excited to see what you'll build with it!

**Ready to get started?** [Install Batho](#installation) and index your first project in 30 seconds.

---

<p align="center">
  <strong>🚀 Batho v1.0.0 - Code Intelligence for the AI Era</strong><br>
  <a href="https://pypi.org/project/batho/">PyPI</a> · <a href="https://github.com/batho-ai/batho/issues">Issues</a> · <a href="https://github.com/batho-ai/batho/discussions">Discussions</a> · <a href="https://github.com/batho-ai/batho/blob/main/docs/updated.md">Full Documentation</a>
</p>