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
  <a href="https://github.com/sageoz/batho/releases/tag/v1.1.0"><img src="https://img.shields.io/badge/v1.1.0-release-orange" alt="v1.1.0"></a>
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
- **10x context compression** — Fit entire codebases into LLM context windows
- **Time Machine snapshots** — Track codebase evolution with incremental patching
- **BSG Plugin System v2** — 38 built-in plugins (28 foundation + 10 interceptors) for security, quality, and optimization
- **Single-Pass Extraction** — One parse per file; cross-file references emit contextual stubs (`EntityType.UNRESOLVED`) resolved post-extraction by ScopeManager
- **Deterministic IDs** — Position-based ID generation for stable entity tracking (no false positives from code movement)
- **Graph Optimization** — Cyclic dependency detection and orphan node pruning
- **Dependency-Aware Resolution** — CDEU module resolves stdlib and third-party symbols (pip, npm, cargo, go) via manifest parsing and live introspection
- **Symbol Resolution** — Cross-file symbol resolution with hierarchical encoding and SymbolRole tagging
- **SQLite Artifact Database** — Schema v1 with three-blob design (agent/storage/rel views) and symbol table storage
- **Query Engine** — Fast SQLite-index-first entity and relationship queries
- **File Changelog** — Node-level diff history with FTS5 full-text search
- **Integrity Verification** — Multi-stage fix command with auto-repair capabilities
- **Zero code execution** — Safe to run in CI or on untrusted repos

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
   - New: Single `batho.yaml` with all settings (indexer, bsg, rules, storage)
   - Action: Copy `batho.yaml.example` to `batho.yaml` and customize

2. **Artifact Database Schema** — v7 with three-blob design
   - Old: Flat entity tables
   - New: Compressed blobs (bsg_agent_view, bsg_storage_view, bsg_rel_view)
   - Action: Run `batho build --root . --full` to rebuild

3. **Config Schema** — Environment variable format changed
   - Old: `BATHO_LOG_LEVEL=INFO`
   - New: Uses nested config with `BATHO_LOG_LEVEL=INFO` (no change)
   - Action: No action needed

**New Defaults:**

- Symbol resolution is now **enabled by default** (can be disabled in config)
- Storage is **enabled by default** (SQLite backend with schema v7)
- BSG plugins are **enabled by default** (9 built-in security/quality interceptors)
- Parallel processing is **enabled by default** (16 workers)

**Recommended Migration Steps:**

```bash
# 1. Backup existing config
cp batho.yaml batho.yaml.backup

# 2. Copy new example config
cp batho.yaml.example batho.yaml

# 3. Migrate custom settings to new schema
# - Check batho.yaml.example for new structure

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
- Storage management
- Artifact database schema

Visit **[batho.sageoz.org](https://batho.sageoz.org)**

## �️ Roadmap & Backlog

### Backlog (Future Releases)

| Feature | Description | Status |
|---------|-------------|--------|
| **Fleet Intelligence** | Multi-repo discovery, symbol routing, cross-repo impact analysis | 0% — Not started |
| **MCP Hub** | Model Context Protocol server for AI agent integration | Not started |
| **Cloud Sync** | Remote artifact storage and synchronization | Not started |
| **Call-chain Analysis** | Analyze function call graphs and dependencies | Not started |

---

## �� Installation

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