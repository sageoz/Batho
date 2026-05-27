<p align="center">
  <img src="assets/batho.svg" alt="Batho" width="220" height="220" />
</p>

<h1 align="center">B.A.T.H.O</h1>
change
<p align="center">
  <strong>Bidirectional AST Traversal & Hypergraph Orchestrator</strong><br>
  <b>BATHO</b> indexes your codebase, compresses the result for LLM context windows, and tracks changes over time.
</p>

<p align="center">
  <a href="https://pypi.org/project/batho/"><img src="https://img.shields.io/pypi/v/batho?color=blue" alt="PyPI"></a>
  <a href="https://github.com/sageoz/batho/releases/tag/v1.1.0"><img src="https://img.shields.io/badge/v1.1.0-release-orange" alt="v1.1.0"></a>
  <a href="https://github.com/sageoz/batho/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
  <a href="https://batho.sageoz.org"><img src="https://img.shields.io/badge/docs-batho.sageoz.org-green" alt="Documentation"></a>
</p>

<br>
#changes
## 📚 Official Documentation

For complete documentation, guides, and API reference, visit **[batho.sageoz.org](https://batho.sageoz.org)**.

## 🚀 Quick Start

```bash
# Install
pip install batho

# Build full repository index (creates artifact_<dirname>.batho)
batho build --root .

# Incrementally patch changed files (using native content hashes)
batho patch --root .

# Export index to a JSON view (e.g., agent view for LLM context injection)
batho export --view agent --output context.json

# Query granular node changes between runs or for a specific file/entity
batho diff --file batho/cli/build.py

# Verify database health and repair integrity anomalies
batho fix --deep
```

## ✨ Key Features

- **40+ language AST parsing** — Python, TypeScript, Rust, Go, Java, and more
- **Interactive Web Dashboard (v1)** — Hypergraph visualization, file browser, search, metrics
- **10x context compression** — Fit entire codebases into LLM context windows
- **Time Machine snapshots** — Track codebase evolution with incremental patching
- **Git Hooks Enterprise** — YAML-driven client-side hook automation
- **MCP Hub** — Multi-workspace context server with cross-repo search
- **BSG Plugin System v1** — 20+ foundation and interceptor plugins
- **Symbol Resolution** — Cross-file symbol resolution with fuzzy matching
- **Artifact Bridge** — REST API + MCP server for IDE integrations
- **Cloud Sync** — Artifact upload to cloud endpoint with retry logic
- **Storage Management** — SQLite registry with retention policies
- **Query Engine** — Fast queries on persisted graph indexes
- **Zero code execution** — Safe to run in CI, pre-commit, or on untrusted repos

## 🛠️ CLI Commands & Usage

Batho provides a clean command-line interface:

### 1. Build Index (`batho build`)
Parses all repository source files and builds the initial AST code graph database.
```bash
batho build --root .
```
- `--full`: Force a full rebuild by deleting the existing database first.
- `--max-workers <N>`: Maximum parallel workers for parsing (defaults to CPU count).
- `--max-file-size-kb <KB>`: Skip files exceeding this size (default: 500 KB).

### 2. Incremental Patch (`batho patch`)
Scans the filesystem for modified/added files, re-parses them, and updates the index using copy-on-write database transactions.
```bash
batho patch --root .
```
- `--max-file-size-kb <KB>`: Skip files exceeding this size during hash scans.

### 3. Render Views (`batho export`)
Exports index datasets into structured JSON files (saves to `<root>/batho_export.json` by default).
```bash
batho export --view agent
```
- `--view <view>`: JSON view format (`storage`, `agent`, `overview`, `files`, `symbols`, `dependencies`, `delta`, `rel`).
- `--output <path>`: Custom file path.
- `--filter <glob>`: Narrow exported files (e.g. `src/**/*.py`).
- `--category <category>`: Filter by code category (`source`, `test`, `doc`, `config`, `infra`, `all`).
- `--token-budget <N>`: Maximum token budget for agent view.
- `--baseline <path>`: Baseline export file (required for `delta` view).
- `--rel`: Include relationship lists in the export.

### 4. Database Integrity (`batho fix`)
Performs multi-stage database verification (`db` → `state` → `blobs` → `graph`) and executes repair routines.
```bash
batho fix --deep
```
- `--deep`: Full validation (decompresses and checks zstd payload blobs).
- `--dry-run`: Diagnoses issues without committing repairs.
- `--target <target>`: Target a specific checker (`db`, `state`, `blobs`, `graph`, `all`).
- `--phase <1-4>`: Run a specific verification phase.
- `--parallel`: Run independent checks concurrently.
- `--format <text|json|csv>`: Report format.

### 5. Node History (`batho diff`)
Queries exact, granular changes across runs, files, or specific symbols.
```bash
batho diff --file batho/cli/build.py
```
- `--run <run_uuid>`: Changes made in a specific run.
- `--entity <entity_id>`: Full evolution history of a symbol.
- `--file <rel_path>`: All node-level changes in a file across runs.
- `--since <run_uuid>`: Bounded history start (only with `--entity`).
- `--json`: Format output as JSON.

### 6. Storage Maintenance (`batho gc`)
Manages database runs, prunes old history, and vacuums database pages.
```bash
batho gc vacuum
```
- `run <run_uuid>`: Delete a specific indexing run.
- `runs --older-than <days>`: Prune runs older than a threshold.
- `status`: Display storage metrics.
- `vacuum`: Reclaim disk space.

## 🔄 Migration from v1 to v1.1.0

**Breaking Changes:**

1. **Unified Configuration** — All config is now in a single `batho.yaml` file
   - Old: Multiple config files scattered across the codebase
   - New: Single `batho.yaml` with all settings (core, hooks, BSG, storage, cloud sync)
   - Action: Copy `batho.yaml.example` to `batho.yaml` and customize

2. **Git Hooks Config** — Hook definitions moved to `.batho/hooks.yaml`
   - Old: Hooks defined in batho.yaml
   - New: Hooks defined in `.batho/hooks.yaml` (source of truth)
   - Action: Move hook definitions to `.batho/hooks.yaml`

3. **Config Schema** — Environment variable format changed
   - Old: `BATHO_LOG_LEVEL=INFO`
   - New: `BATHO_LOGGING_LEVEL=INFO` (nested config)
   - Action: Update environment variables to match new schema

**New Defaults:**

- Symbol resolution is now **enabled by default** (can be disabled in config)
- Storage registry is **enabled by default** (SQLite backend)
- BSG plugins are **disabled by default** (enable via `rules.enabled: true`)

**Recommended Migration Steps:**

```bash
# 1. Backup existing config
cp batho.yaml batho.yaml.backup

# 2. Copy new example config
cp batho.yaml.example batho.yaml

# 3. Migrate custom settings to new schema
# - Check batho.yaml.example for new structure
# - Move hook definitions to .batho/hooks.yaml

# 4. Test configuration
batho build --root . --verbose

# 5. Rebuild database from scratch
batho build --root . --full
```

## ⚙️ Configuration

Batho works out of the box with zero config. For production use, configure with `./batho.yaml`:

```yaml
schema_version: batho-config.v1

logging:
  level: INFO
  quiet: false

paths:
  db_path: {root}

indexer:
  max_file_size_kb: 500
  ignore_patterns: []

flags:
  strict: false
  audit_log_enabled: true

bsg:
  cache:
    enabled: true
    max_size_mb: 1024
  symbol_resolution:
    enabled: true
  bidirectional:
    enabled: true
```

See `batho.yaml.example` for complete configuration options.

## 📖 Documentation

For complete documentation including:
- CLI reference and command guide
- Configuration options
- Architecture and deployment
- BSG plugin system
- Git hooks automation
- MCP Hub setup
- Storage management
- Cloud sync

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