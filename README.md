<p align="center">
  <img src="assets/batho.png" alt="Batho" width="220" height="220" />
</p>

<h1 align="center">B.A.T.H.O</h1>
<p align="center">
  <strong>Bidirectional AST Traversal & Hypergraph Orchestrator</strong><br>
  <b>BATHO</b> indexes your codebase, compresses the result for LLM context windows, and tracks changes over time.
</p>

<p align="center">
  <a href="https://pypi.org/project/batho/"><img src="https://img.shields.io/pypi/v/batho?color=blue" alt="PyPI"></a>
  <a href="https://github.com/sageoz/batho/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
  <a href="https://batho.sageoz.org"><img src="https://img.shields.io/badge/docs-batho.sageoz.org-green" alt="Documentation"></a>
</p>

<br>

## 📚 Official Documentation

For complete documentation, guides, and API reference, visit **[batho.sageoz.org](https://batho.sageoz.org)**.

## 🚀 Quick Start

```bash
# Install
pip install batho / uv add batho

# Build full repository index
batho build --root .

# Exports the latest Batho artifact into a transportable ZIP by default ("artifact_<dir>.batho").
batho export --root .

# Incrementally patch changed files (using native content hashes)
batho patch --root .

# Load a transport artifact ZIP (e.g. in CI)
batho load artifact_<dir>.batho

# Query granular node changes between runs or for a specific file/entity
batho diff --file batho/cli/build.py

# Verify artifact health and repair integrity anomalies
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
- **Arrow IPC Artifact Store** — Three-blob design (agent/storage/rel views) written to `.batho/artifact/` via `BathoBundle`; zero-copy memory-mapped reads
- **BSG Store** — Persistent entity/relationship graph in `.batho/bsg/current/` via `BsgScratchStore`; streaming flush + compaction for large repos
- **File Changelog** — Node-level diff history tracking per run
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

### 3. Export (`batho export`)
Exports the latest BSG artifact into a transportable ZIP by default (`<root>/artifact_<dir>.batho`). Use `--json` to export a JSON view instead (default: `<root>/batho_export.json`).
```bash
batho export --root .
```
- `--root <path>`: Repository root directory (default: `.`).
- `--json`: Export a JSON view instead of the default transport ZIP artifact.
- `--view <view>`: JSON view format (default: `storage` with `--json`): `storage`, `agent`, `overview`, `files`, `symbols`, `dependencies`, `delta`, `rel`.
- `--output <path>`: Custom file path.
- `--filter <glob>`: Narrow exported files (e.g. `src/**/*.py`).
- `--category <category>`: Filter by code category (`source`, `test`, `doc`, `config`, `infra`, `all`).
- `--token-budget <N>`: Maximum token budget for agent view.
- `--baseline <path>`: Baseline export file (required for `delta` view).
- `--rel`: Include relationship lists in the export.
- `--index-id <ID>`: Export a specific index run UUID (default: latest).
- `--format <format>`: JSON output format (`json` or `pretty`; default: `json`).

### 4. Load Artifact (`batho load`)
Unpacks a transport artifact ZIP (`artifact_<dir>.batho`) produced by `batho export --pack` into the repository's `.batho/artifact/` directory.
```bash
batho load artifact_<dir>.batho
```
- `--root <path>`: Repository root directory (default: `.`).
- `--force`: Overwrite existing bundle if present.

### 5. Database Integrity (`batho fix`)
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

### 6. Node History (`batho diff`)
Queries exact, granular changes across runs, files, or specific symbols.
```bash
batho diff --file batho/cli/build.py
```
- `--run <run_uuid>`: Changes made in a specific run.
- `--entity <entity_id>`: Full evolution history of a symbol.
- `--file <rel_path>`: All node-level changes in a file across runs.
- `--since <run_uuid>`: Bounded history start (only with `--entity`).
- `--json`: Format output as JSON.

### 7. Storage Maintenance (`batho gc`)
Manages database runs, prunes old history, and vacuums database pages.
```bash
batho gc vacuum
```
- `run <run_uuid>`: Delete a specific indexing run.
- `runs --older-than <days>`: Prune runs older than a threshold.
- `status`: Display storage metrics.
- `vacuum`: Reclaim disk space.

## ⚙️ Configuration

Batho works out of the box with zero config. For production use, configure with `./batho.yaml`:

```yaml
schema_version: batho-config.v1

logging:
  level: ERROR
  quiet: false

paths:
  artifact_dir: .batho/artifact   # Arrow IPC artifact store (override: BATHO_ARTIFACT_DIR)
  cache_dir: .batho/cache
  bsg_dir: .batho/bsg

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