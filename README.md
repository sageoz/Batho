<p align="center">
  <img src="assets/batho.svg" alt="Batho" width="160" height="160" />
</p>

<h1 align="center">Batho</h1>

<p align="center">
  <strong>Codebase Intelligence for AI-Powered Development</strong><br>
  Turn any codebase into structured knowledge your LLMs, agents, and tools can actually use.
</p>

<p align="center">
  <a href="https://test.pypi.org/project/batho/"><img src="https://img.shields.io/pypi/v/batho?color=blue" alt="PyPI"></a>
  <a href="https://github.com/sageoz/batho/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
  <a href="#supported-languages"><img src="https://img.shields.io/badge/languages-40+-orange" alt="Languages"></a>
</p>

<br>

> **Batho** indexes your codebase, compresses the result for LLM context windows, and tracks changes over time.


---
## Quick Start

Get running in 30 seconds:

```bash
# Install
uv add batho 
# or
pip install batho

# Index your project
batho index --root . --verbose --snapshot

# Generate compressed bsg for LLM injection
batho bsg --root . --mode compressed --budget 12000

# Create snapshot
batho index --root . --snapshot  

# Auto-detect and patch changes
batho patch --root . --scan

# Install Git hooks for automated checks
batho hooks install --all

# Show all commands
batho --help

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
| **Zero Code Execution** | Safe to run in CI, pre-commit, or on untrusted repos |
| **Caching** | mtime+SHA skips unchanged files — re-indexes in seconds |
| **Production Webhooks** | GitHub/GitLab integration with authentication and queueing |
| **CI/CD Pipeline Hooks** | Turnkey GitHub Actions and GitLab CI templates |
| **Automated Documentation** | Generate docs/context from your codebase |
| **Incremental patching** | 10-100x faster updates with complete lineage tracking |

## How It Works

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

### BSG (Batho Structured Graph) Compression

Transforms full code graphs into compact representations:

```bash

# Generate full bsg with signatures
batho bsg --root . --mode full

# Generate hierarchical directory view
batho bsg --root . --mode hierarchical

# Generate compressed bsg for LLM injection
batho bsg --root . --mode compressed --budget 12000

```

| Mode | Best for | Output File |
|------|----------|-------------|
| **Full** | Developer reference with signatures + line numbers | `bsg_full.json` |
| **Hierarchical** | Directory-tree overviews | `bsg_hierarchical.json` |
| **Compressed** | LLM prompt injection (4K–40K tokens) | `bsg_compressed.json` |


### Batho Time Machine

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

## Developer Setup (uv)

Use this section when you want to contribute to Batho locally, run tests, and verify the CLI from source.

### 1. Clone the repository

```bash
git clone https://github.com/sageoz/batho.git
cd batho
```

### 2. Install project dependencies for development and testing

```bash
uv sync --all-groups --all-extras
```

This creates and syncs the project environment with runtime, test, and dev dependencies.

### 3. Run tests

```bash
# Full suite
uv run pytest

# Optional: focused checks while iterating
uv run pytest tests/core/test_config.py -q
uv run pytest tests/utils/test_logging.py -q
```

### 4. Run the CLI directly from local source

This path is best during development because it always uses your current working tree.

```bash
uv run python -m batho_cli --help
uv run python -m batho_cli index --root .
```

### 5. Reinstall the global batho command from your local source

Use this when you want the plain batho command to reflect your latest local code.

```bash
uv tool install --reinstall .
hash -r
batho index --root .
```

### 6. Quick troubleshooting

If behavior differs between local and global runs, compare both paths:

```bash
uv run python -m batho_cli index --root .
batho index --root .
```

If they differ, reinstall the tool again:

```bash
uv tool install --reinstall .
hash -r
```

---

## CLI Reference

```bash
# Show all commands
batho --help

# Show command-specific help
batho <command> --help
```

### Command Matrix

| Command | Purpose |
|------|---------|
| `index` | Build/update graph + BSG artifacts for a repo |
| `stats` | Show current index metadata and health summary |
| `snapshots` | List stored snapshots |
| `diff-snapshots` | Diff two snapshots |
| `patch` | Apply incremental updates from scan/diff/files |
| `patches` | List patch operations |
| `patch-info` | Show patch operation details |
| `patch-chain` | Show chain of patches for a snapshot |
| `apply-patch` | Apply patch by diff file or patch id |
| `cherry-pick` | Apply a patch to another snapshot |
| `webhook` | Parse/process a webhook payload |
| `webhook-server` | Start webhook server from `batho.yaml` |
| `sync` | Sync pending artifacts to configured cloud endpoint |
| `hooks` | Git client-side hook management (install/remove/run) |
| `invalidate` | Clear index file cache |
| `cache` | AST cache management (`stats`, `invalidate`, `clear`) |
| `storage` | Persistent artifact registry tools (`backfill`, `verify`, `cleanup`, `stats`, `rebuild-indexes`) |
| `query` | Query persisted entity/relationship indexes |
| `bsg` | Render BSG outputs (`compressed`, `full`, `hierarchical`) |

### Indexing & Snapshots

```bash
# Full index
batho index --root /path/to/repo --verbose

# Force full rebuild (disable incremental path)
batho index --root /path/to/repo --full

# Force cache reset before indexing (clears file cache + AST cache)
batho index --root /path/to/repo --force

# Deterministic fresh parse run (bypass AST cache for this invocation)
batho index --root /path/to/repo --force --no-ast-cache --verbose

# Index and create snapshot
batho index --root /path/to/repo --snapshot --snapshot-label "release-candidate"

# Snapshot inspection
batho snapshots --root /path/to/repo
batho diff-snapshots --root /path/to/repo --snapshot-a SNAP_A --snapshot-b SNAP_B
```

### Patch Lifecycle

```bash
# Auto-detect file changes and patch
batho patch --root /path/to/repo --scan

# Patch from unified diff
batho patch --root /path/to/repo --diff /path/to/changes.diff

# Patch specific files
batho patch --root /path/to/repo src/a.py src/b.py

# Patch history and details
batho patches --root /path/to/repo --format timeline
batho patch-info --root /path/to/repo --patch-id PATCH_ID --format summary
batho patch-chain --root /path/to/repo --snapshot-id SNAP_ID --full

# Advanced patch operations
batho apply-patch --root /path/to/repo --base-snapshot SNAP_ID --diff-file /path/to/changes.diff
batho cherry-pick --root /path/to/repo --patch-id PATCH_ID --target-snapshot SNAP_ID
```

### BSG Rendering & Querying

```bash
# Render BSG formats
batho bsg --root /path/to/repo --mode compressed --budget 12000
batho bsg --root /path/to/repo --mode full
batho bsg --root /path/to/repo --mode hierarchical

# Query persisted graph indexes
batho query --root /path/to/repo --entity-type function --limit 50
batho query --root /path/to/repo --file-path src/api.py
batho query --root /path/to/repo --relationship-type calls --rebuild-index
```

### Cache & Storage Operations

```bash
# Index cache cleanup
batho invalidate --root /path/to/repo

# AST cache management
batho cache stats
batho cache invalidate "**/*.py"
batho cache clear

# Persistent storage management
batho storage backfill --root /path/to/repo
batho storage verify --root /path/to/repo --repair
batho storage cleanup --root /path/to/repo          # dry-run
batho storage cleanup --root /path/to/repo --apply  # execute cleanup
batho storage stats --root /path/to/repo
batho storage rebuild-indexes --root /path/to/repo
```

### Cloud Sync Operations

```bash
# Preview pending artifacts (no upload)
batho sync --root /path/to/repo --dry-run

# Sync pending artifacts to cloud endpoint
export BATHO_CLOUD_SYNC_ENABLED=true
export BATHO_CLOUD_ENDPOINT="https://sync.batho.dev/v1"
export BATHO_CLOUD_API_KEY="batho_live_xxxxx"
batho sync --root /path/to/repo

# Retry only failed artifact uploads
batho sync --root /path/to/repo --retry-failed

# Show local sync status summary
batho sync --root /path/to/repo --status
```

### Webhook Operations

```bash
# Parse/process one webhook payload
batho webhook --payload '{"event":"push"}' --headers '{"X-GitHub-Event":"push"}'

# Process webhook with repository context
batho webhook --root /path/to/repo --payload '{...}' --headers '{...}'

# Start webhook server from config
batho webhook-server --root /path/to/repo
```

### Git Hooks Management

YAML-driven Git client-side hook automation with enterprise reliability.

```bash
# List configured hooks and templates
batho hooks list --root /path/to/repo

# Check installation status
batho hooks status --hook pre-commit

# Install all enabled hooks (auto-bootstraps .batho/hooks.yaml if missing)
batho hooks install --all

# Install specific hook with force (overwrites unmanaged)
batho hooks install --hook pre-commit --force

# Remove managed hooks
batho hooks remove --all

# Run hook manually (supports custom hooks for CI/CD)
batho hooks run --hook enterprise-nightly --verbose
```

Configuration in `.batho/hooks.yaml`:

```yaml
version: hooks.v1
defaults:
  shell: /bin/sh
  timeout: 60
hooks:
  pre-commit:
    enabled: true
    stages:
      - run: ruff check .
      - run: pytest --co -q
  pre-push:
    enabled: true
    stages:
      - run: pytest -x --tb=short
```

Enable in `batho.yaml`:

```yaml
hooks:
  enabled: true
  include: true
```

### Index Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--max-workers` | `0` (auto) | Worker threads — 0 uses CPU × 2, capped at 32 |
| `--max-file-size-kb` | `500` | Skip files larger than this |
| `--extensions` | all supported | Restrict indexing to selected extensions |
| `--full` | off | Disable incremental reuse and force full rebuild |
| `--force` | off | Clear index file cache and AST cache before indexing |
| `--no-ast-cache` | off | Bypass AST cache for the current indexing run |
| `--base-snapshot` | auto | Prefer this snapshot for incremental indexing |
| `--output-json` | none | Optional override path for graph JSON output |
| `--metrics-output` | from config | Write metrics JSON to explicit path |
| `--verbose` | off | Print progress to stdout |
| `--snapshot` | off | Create snapshot after indexing |
| `--snapshot-label` | none | Attach label to generated snapshot |

### Global Logging Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--log-level` | from config | Override logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) |
| `-q`, `--quiet` | from config | Suppress non-error CLI output and log events below `ERROR` |
| `--log-json` | off | Force JSON log output (useful in CI) |
| `--log-file` | from config | Write logs to the specified file path |

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
| `--diff` | none | Apply patch from unified diff |
| `files...` | none | Patch explicit changed files |

---

## Output

```
.ctn/
├── index.json                   # Index metadata + staleness + persistence model
├── artifact_registry.db         # SQLite artifact registry (durable outputs)
├── file_cache.json              # Index file cache
├── file_hashes.json             # Content-hash tracker for incremental scans
├── metrics.json                 # Optional metrics output
├── interception_stats.json      # Rule interception matrix
├── evolution_ledger.json        # Failure synthesis ledger
├── snapshots/                   # Time Machine snapshots
│   └── batho_<project>_<sha>_<ts>.json
├── patches/                     # Patch operation history
│   ├── index.json
│   └── patch_<operation_id>.json
└── <index_id>/
    ├── graph.json               # Entities + relationships
    ├── bsg.json                 # Structured symbol graph
    ├── bsg_compressed.json      # LLM-ready compressed output
    ├── bsg_full.json            # Full textual BSG output
    ├── bsg_hierarchical.json    # Hierarchical textual BSG output
    └── context/
        ├── overview.md
        ├── architecture.md
        ├── tests.md
        ├── docs.md
        └── config.md
```

Default AST cache database location: `~/.batho/ast_cache.db` (configured by `bsg.cache.path`).

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

Batho works out of the box with zero config. For production use, configure with the unified root config file `./batho.yaml` (or start from `batho.yaml.example`) plus optional environment overrides.

Configuration precedence:

1. Built-in defaults
2. `./batho.yaml`
3. Environment variables (override file values)
4. CLI flags (override for a specific run)

Output behavior:

- User-facing command output is written to stdout.
- Warnings/errors and operational logs are written to stderr.

### Core Config Areas

| Area | Keys | What it controls |
|----------|------|------------------|
| `logging` | `level`, `json_format`, `quiet`, `file`, `format` | Process-wide logging and CLI verbosity behavior |
| `paths` | `ctn_dir` | Artifact output directory |
| `indexer` | `max_file_size_kb`, `max_workers`, `max_indexed_files`, `ignore_*`, `metrics_output` | Base indexing limits and outputs |
| `rules` | `enabled`, `builtin_plugins`, `custom_rules_*`, `strict_validation` | Rule plugins and metadata enrichment |
| `bsg.parallel` | `enabled`, `max_workers`, `chunk_size` | Parallel file extraction |
| `bsg.ignore` | `enabled`, `file` | `.bathoignore` integration |
| `bsg.cache` | `enabled`, `path`, `max_size_mb`, `ttl_days` | AST cache behavior |
| `bsg.incremental` | `enabled`, `fallback_to_full`, `auto_detect_git` | Incremental indexing strategy |
| `bsg.symbol_resolution` | `enabled`, `fuzzy_matching`, `cache_symbols` | Cross-file symbol resolution |
| `bsg.serialization` | `method`, `compression`, `batch_size` | BSG render strategy |
| `bsg.parsing` | `error_recovery`, `partial_parsing`, `max_file_size_mb`, `skip_comments` | Parser behavior |
| `bsg.query` | `enabled`, `index_on_write`, `cache_enabled`, `cache_size`, `default_limit`, `query_timeout_ms` | Persistent query indexes |
| `bsg.storage` | `enabled`, `backend`, `registry_path`, `content_scope`, `cloud_sync_ready`, `mmap_enabled`, `retention.*` | Durable artifact registry and retention |
| `webhook` | `enabled`, `server.*`, `repository.*`, `processing.*`, `rate_limit.*` | Webhook server + event processing |
| `hooks` | `enabled`, `include` | Git client-side hook automation pointer |

### Environment Variables (Common)

| Variable | Default | Description |
|----------|---------|-------------|
| `BATHO_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `BATHO_LOG_JSON` | `null` | Force JSON logs (`true`) or leave auto mode (`unset`) |
| `BATHO_LOG_QUIET` | `false` | Suppress non-error output globally |
| `BATHO_LOG_FILE` | unset | Optional log file path |
| `BATHO_CTN_DIR` | `.ctn` | Output directory |
| `BATHO_MAX_FILE_SIZE_KB` | `500` | Max file size to parse |
| `BATHO_MAX_INDEXED_FILES` | `200000` | Hard cap on indexed files |
| `BATHO_INDEX_WORKERS` | `0` | Worker threads (0 = auto) |
| `BATHO_METRICS_OUTPUT` | `.ctn/metrics.json` | Metrics output path |
| `BATHO_RULES_ENABLED` | config value | Enable BSG rule plugin stage |
| `BATHO_RULES_CUSTOM_RULES_PATH` | unset | YAML file containing custom BSG rules |
| `BATHO_RULES_BUILTIN_PLUGINS` | `bsg_core` | Comma-separated built-in plugin names |
| `BATHO_RULES_DISABLED_RULES` | unset | Comma-separated rule names to disable |
| `BATHO_BSG_STORAGE_ENABLED` | `true` | Enable durable artifact registry |
| `BATHO_BSG_STORAGE_REGISTRY_PATH` | `.ctn/artifact_registry.db` | Registry database path |
| `BATHO_BSG_STORAGE_MMAP_ENABLED` | `false` | Enable mmap reads for large persisted JSON |
| `BATHO_BSG_QUERY_INDEX_ON_WRITE` | `true` | Build query index at write time |
| `BATHO_BSG_QUERY_CACHE_SIZE` | `256` | Query service cache size |

> For the complete env override set, see `batho/config.py`.

### Config File

```yaml
# ./batho.yaml
logging:
  level: DEBUG
  json_format: true
  quiet: false
  file: .ctn/batho.log
  format: "%(message)s"

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

bsg:
  parallel:
    enabled: true
    max_workers: 16
    chunk_size: 50
  cache:
    enabled: true
    path: ~/.batho/ast_cache.db
    max_size_mb: 1024
    ttl_days: 30
  query:
    enabled: true
    index_on_write: true
    cache_enabled: true
    cache_size: 256
    default_limit: 200
  storage:
    enabled: true
    backend: sqlite
    registry_path: .ctn/artifact_registry.db
    content_scope: durable
    cloud_sync_ready: true
    mmap_enabled: false
    retention:
      enabled: true
      snapshot_ttl_days: 90
      patch_ttl_days: 90
      metrics_ttl_days: 30
      context_ttl_days: 90
```

### Scenario Playbooks

#### 1) Local Dev (fast feedback)

```yaml
indexer:
  max_workers: 0
  max_file_size_kb: 500
bsg:
  incremental:
    enabled: true
  cache:
    enabled: true
```

```bash
batho index --root .
batho patch --root . --scan
batho bsg --root . --mode compressed --budget 12000
```

#### 2) Large Monorepo (throughput)

```yaml
indexer:
  max_file_size_kb: 2000
bsg:
  parallel:
    enabled: true
    max_workers: 16
  ignore:
    enabled: true
    file: .bathoignore
  storage:
    mmap_enabled: true
```

```bash
batho index --root /repo --snapshot
batho storage stats --root /repo
batho query --root /repo --relationship-type calls --limit 200
```

#### 3) CI/CD (deterministic + observable)

```yaml
logging:
  level: INFO
  json_format: true
indexer:
  metrics_output: .ctn/metrics.json
bsg:
  storage:
    enabled: true
```

```bash
batho index --root . --log-json --snapshot
batho stats --root .
batho storage verify --root .
```

#### 4) Webhook Runtime

```yaml
webhook:
  enabled: true
  server:
    host: 0.0.0.0
    port: 8080
  repository:
    name: your-org/your-repo
    platform: github
    secret: ${WEBHOOK_SECRET}
```

```bash
batho webhook-server --root .
```

#### 5) Persistent Storage Hygiene (cloud-sync-ready v1)

```bash
# register existing artifacts
batho storage backfill --root .

# verify and repair drift
batho storage verify --root . --repair

# inspect registry + graph cache health
batho storage stats --root .

# rebuild query indexes
batho storage rebuild-indexes --root .

# retention dry-run / apply
batho storage cleanup --root .
batho storage cleanup --root . --apply
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
---
## Use Batho as a Python Library (Custom Scripts)

Batho is not only a CLI. You can import it as a Python library to build custom automation scripts, CI workflows, and internal developer tools.

### Public Python API

The `batho` package exports core APIs directly:

- Indexing and graph: `CodeGraphIndexer`, `InMemoryGraph`, `BSGMap`
- Time Machine: `create_snapshot`, `list_snapshots`, `load_snapshot`, `diff_snapshots`
- Incremental patching: `FileChange`, `FileChangeType`, `FileChangeTracker`, `incremental_patch`
- Git-aware change discovery: `get_changed_file_status_since`
- Query layer: `QueryService`
- Webhook processing: `WebhookConfig`, `WebhookProcessor`, `WebhookServer`, `parse_webhook_event`

### Example: Index + Snapshot from a Script

```python
from pathlib import Path

from batho import BSGMap, CodeGraphIndexer, create_snapshot

root = Path(".").resolve()
ctn_dir = root / ".ctn"
ctn_dir.mkdir(parents=True, exist_ok=True)

indexer = CodeGraphIndexer(cache_path=str(ctn_dir / "file_cache.json"), root=str(root))
graph = indexer.build_graph(root=str(root), snapshot_id="script-run")

bsg = BSGMap.build(graph, root=str(root))
snapshot_id = create_snapshot(ctn_dir, root, graph, bsg, label="nightly-script")

print({"entities": len(graph.entities), "relationships": len(graph.relationships), "snapshot": snapshot_id})
```

### Example: Incremental Patch in Automation

```python
from pathlib import Path

from batho import FileChangeTracker, incremental_patch

root = Path(".").resolve()
ctn_dir = root / ".ctn"
base_snapshot_id = "<existing_snapshot_id>"

tracker = FileChangeTracker(root)
hash_cache_path = ctn_dir / "file_hashes.json"
tracker.load(hash_cache_path)
changes = tracker.scan_for_changes(max_file_size_kb=500)
tracker.save(hash_cache_path)

if changes:
    result = incremental_patch(ctn_dir, base_snapshot_id, changes)
    print(result)
else:
    print("No changes detected")
```

### Example: Query Indexed Data Programmatically

```python
from pathlib import Path

from batho import QueryService

ctn_dir = Path(".ctn")
query = QueryService(ctn_dir)

functions = query.entities_by_type("function", limit=20)
for row in functions:
    print(f"{row['name']} -> {row['file']}")
```


---
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
├── batho_cli.py                  # CLI command entrypoints
└── batho/
    ├── __init__.py               # Public Python API exports
    ├── config.py                 # Configuration and env overrides
    ├── time_machine.py           # Snapshots, diffs, incremental patching
    ├── context/
    │   ├── codegraph.py          # Graph indexing and extraction pipeline
    │   ├── pipeline.py           # Parallel worker orchestration
    │   ├── bsg_map.py            # Multi-format BSG renderer
    │   ├── query.py              # Query service over persisted artifacts
    │   └── languages/            # Per-language tree-sitter extractors
    ├── webhook/                  # Webhook parsing, processing, queue/server
    └── utils/
        ├── logging.py            # Structured logging
        ├── hash.py               # SHA-256 helpers
        └── ignore.py             # .gitignore / .bathoignore handling
```

---

## Contributing

Batho is open source and welcomes contributions. Whether it's a bug report, a new language extractor, or a docs improvement — we'd love your help.

1. Fork the repo
2. Create a feature branch
3. Run the test suite: `uv run pytest`
4. Submit a pull request

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
  <a href="https://pypi.org/project/batho/">PyPI</a> · <a href="https://github.com/sageoz/batho/issues">Issues</a> · <a href="https://github.com/sageoz/batho/discussions">Discussions</a> · <a href="https://github.com/sageoz/batho/blob/main/docs/updated.md">Full Documentation</a>
</p># test
