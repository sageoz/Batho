<p align="center">
  <img src="assets/batho.png" alt="Batho" width="200" height="200" />
</p>

<h1 align="center">B.A.T.H.O</h1>

<p align="center">
  Multi-language codebase indexer that turns source code into compressed, queryable code graphs — built for AI agents and CI/CD pipelines.
</p>

<p align="center">
  <a href="https://pypi.org/project/batho/"><img src="https://img.shields.io/pypi/v/batho?color=blue" alt="PyPI"></a>
  <a href="https://github.com/sageoz/batho/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
  <a href="https://batho.sageoz.org"><img src="https://img.shields.io/badge/docs-batho.sageoz.org-green" alt="Documentation"></a>
</p>

---

## Installation

```bash
pip install batho
# or
uv add batho
```

## Quick Start

```bash
# Build full repository index
batho build --root .

# Incrementally re-index only changed files
batho patch --root .

# Export a transportable artifact ZIP (artifact_<dir>.batho)
batho export --root .

# Restore a graph from an artifact ZIP (e.g. downloaded in CI)
batho load artifact_<dir>.batho

# Query node-level changes for a file across runs
batho diff --file src/main.py

# Verify and auto-repair artifact integrity
batho fix --deep
```

## How It Works

Batho parses every source file into an AST using tree-sitter, extracts entities and relationships into a BSG (Batho Semantic Graph), and persists the result as Apache Arrow IPC files. The transport artifact (`artifact_*.batho`) is a zstd-compressed ZIP of those IPC files, designed to be uploaded in CI and downloaded by AI agents — no local parsing required.

## Features

- **40+ language AST parsing** — Python, TypeScript, Rust, Go, Java, C/C++, and more
- **10x context compression** — fit entire codebases into LLM context windows
- **Incremental patching** — hash-based change detection; only modified files are re-parsed
- **Deterministic entity IDs** — position-based IDs prevent false positives from code movement
- **Cross-file symbol resolution** — hierarchical encoding with SymbolRole tagging via ScopeManager
- **Dependency-aware indexing** — CDEU resolves stdlib and third-party symbols (pip, npm, cargo, go) via manifest parsing and live introspection
- **BSG Plugin System v2** — 38 built-in plugins (security, quality, optimization) with custom rule support
- **Arrow IPC artifact store** — zero-copy memory-mapped reads; three-blob design (agent / storage / rel views)
- **Graph optimization** — cyclic dependency detection and orphan node pruning
- **Node-level diff history** — track codebase evolution across every indexed run
- **Multi-stage integrity verification** — auto-repair via `batho fix`
- **Zero code execution** — safe to run in CI or on untrusted repositories

## CLI Reference

| Command | Purpose | Key flags |
|---|---|---|
| `batho build` | Full index build from scratch | `--full`, `--max-workers N`, `--max-file-size-kb KB` |
| `batho patch` | Incremental re-index of changed files | `--max-file-size-kb KB` |
| `batho export` | Export artifact ZIP or JSON view | `--json`, `--view`, `--filter`, `--output`, `--token-budget N` |
| `batho load` | Restore graph from artifact ZIP | `--root`, `--force` |
| `batho diff` | Query node-level change history | `--file`, `--entity`, `--run`, `--since`, `--json` |
| `batho fix` | Verify and repair artifact integrity | `--deep`, `--dry-run`, `--target`, `--parallel` |
| `batho gc` | Prune old runs and vacuum storage | `vacuum`, `status`, `runs --older-than N` |

### Export views

When using `batho export --json --view <view>`, available views are:

`storage` · `agent` · `overview` · `files` · `symbols` · `dependencies` · `delta` · `rel`

## CI/CD Integration

Batho's CI/CD strategy is **incremental**: download the previous artifact → `batho load` → `batho patch` → `batho export` → upload. On first run (no artifact), it falls back to `batho build --full`.

### GitHub Actions — Composite Action (recommended)

The simplest integration. Add to any workflow:

```yaml
- name: Checkout
  uses: actions/checkout@v4
  with:
    fetch-depth: 0

- name: Run Batho
  uses: sageoz/batho@v1.1.0
  with:
    root: "."
    artifact-name: "batho-index"
    artifact-retention-days: "7"
```

**Inputs:** `root` · `python-version` · `batho-ref` · `verbose` · `max-workers` · `max-file-size-kb` · `artifact-name` · `artifact-retention-days` · `upload-artifact` · `summary`

**Outputs:** `zip-path` · `output-dir` · `index-id`

### GitHub Actions — Reusable Workflow

Call the reusable workflow from any consumer repository:

```yaml
jobs:
  batho:
    uses: sageoz/batho/.github/workflows/batho-index.yml@v1.1.0
    with:
      root: "."
      artifact-name: "batho-index"
      artifact-retention-days: "7"
```

### GitHub Actions — Manual Workflow

For full control, add `.github/workflows/batho-ci.yml` to your repository:

```yaml
name: Batho Index

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  actions: read
  contents: read

jobs:
  update-code-graph:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install Batho
        run: pip install batho

      - name: Download previous artifact
        uses: dawidd6/action-download-artifact@v6
        with:
          name: batho-database
          workflow: batho-ci.yml
          branch: ${{ github.ref_name }}
        continue-on-error: true

      - name: Build or patch index
        run: |
          if ls artifact_*.batho 1>/dev/null 2>&1; then
            batho load --root . artifact_*.batho --force
            batho patch --root .
          else
            batho build --root . --full
          fi
          batho export --root .

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: batho-database
          path: artifact_*.batho
          retention-days: 90
```

### GitLab CI

Add to `.gitlab-ci.yml`:

```yaml
stages:
  - index

batho-indexer:
  stage: index
  image: python:3.12
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
  before_script:
    - apt-get update -qq && apt-get install -y -qq unzip curl
    - pip install batho
  script:
    - |
      curl --fail --location \
        --header "JOB-TOKEN: $CI_JOB_TOKEN" \
        "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/jobs/artifacts/${CI_COMMIT_REF_NAME}/download?job=batho-indexer" \
        --output artifacts.zip || true
      [ -f artifacts.zip ] && unzip -o artifacts.zip || true
      if ls artifact_*.batho 1>/dev/null 2>&1; then
        batho load --root . artifact_*.batho --force
        batho patch --root .
      else
        batho build --root . --full
      fi
      batho export --root .
  artifacts:
    paths:
      - artifact_*.batho
    expire_in: 90 days
```

### AI Agent Access

Agents can download and restore a pre-built graph without local indexing:

```bash
# GitHub — download latest artifact from main
gh api /repos/{owner}/{repo}/actions/artifacts \
  --jq '.artifacts[] | select(.name=="batho-database") | .id' \
  | xargs -I {} gh api /repos/{owner}/{repo}/actions/artifacts/{}/zip \
  --output batho-database.zip
unzip batho-database.zip
batho load --root . artifact_*.batho

# GitLab
curl --header "JOB-TOKEN: $CI_JOB_TOKEN" \
  "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/jobs/artifacts/main/download?job=batho-indexer" \
  --output batho-database.zip
unzip batho-database.zip
batho load --root . artifact_*.batho
```

## Configuration

Batho runs with zero config. To customize, copy [`batho.yaml.example`](batho.yaml.example) to `./batho.yaml`:

```yaml
schema_version: batho-config.v1

logging:
  level: ERROR          # DEBUG | INFO | WARNING | ERROR

indexer:
  max_file_size_kb: 500
  ignore_patterns: []   # additional gitignore-style patterns
  max_workers: 0        # 0 = auto (CPU count)

bsg:
  cache:
    enabled: true
    max_size_mb: 1024
  symbol_resolution:
    enabled: true

flags:
  audit_log_enabled: true
```

See [`batho.yaml.example`](batho.yaml.example) for the full reference including dependency indexing, graph options, artifact blob control, and BSG plugin configuration.

## Developer Setup

```bash
git clone https://github.com/sageoz/batho.git
cd batho
uv sync --all-groups --all-extras
uv run pytest
uv run python batho_cli.py --help
```

## Documentation

Full documentation, API reference, and guides: **[batho.sageoz.org](https://batho.sageoz.org)**

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.