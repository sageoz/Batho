<p align="center">
  <img src="assets/batho.png" alt="Batho" width="200" height="200" />
</p>

<h1 align="center">B.A.T.H.O</h1>

<p align="center">
  Reduce token spend and hallucinations by indexing your codebase into a graph your AI agents can navigate — without dumping whole repositories into the Context.fgf
</p>

<p align="center">
  <a href="https://pypi.org/project/batho/"><img src="https://img.shields.io/pypi/v/batho?color=blue" alt="PyPI"></a>
  <a href="https://github.com/sageoz/batho/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
  <a href="https://batho.sageoz.org"><img src="https://img.shields.io/badge/docs-batho.sageoz.org-green" alt="Documentation"></a>
</p>

---

## Why Batho?

Companies are reducing AI usage because token spend is getting pricey — before even accounting for hallucinations that erode result quality. Batho fixes both.

- **Lower token costs** — Your AI agent traverses a graph of entities and relationships instead of reading entire source files. Feed the LLM only what it needs, not the whole repository.
- **Fewer hallucinations** — Batho extracts deterministic, tree-sitter-parsed syntax relationships from your code. No guessing, no embeddings — your agent works with facts.
- **More use cases** — When cost is under control and results are trustworthy, the range of what you can automate widens with imagination.

## Use Cases

- **Bug tracking** — Map bug reports to the exact functions and dependencies involved
- **Security checks** — Trace data flows and identify vulnerable code paths across files
- **Code review automation** — Surface relevant context and relationships for every PR
- **Multi-repo navigation** — Index multiple repositories into one large context graph
- **Any AI workflow** — If your agent needs to understand code, Batho gives it the map

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

Batho parses your source files into a structured graph of entities and relationships, then packages it into a transportable artifact your AI agent can query. No local parsing required — just build, export, and let your agent navigate the graph.

<details>
<summary>Technical details</summary>

Batho uses tree-sitter for AST parsing, extracts entities and relationships into a BSG (Batho Semantic Graph), and persists the result as Apache Arrow IPC files. The transport artifact (`artifact_*.batho`) is a zstd-compressed ZIP of those IPC files, designed for zero-copy memory-mapped reads.

</details>

## Features

- **Spend less on tokens** — 10x compression means your agent uses a fraction of the context window
- **Works with your stack** — 40+ languages including Python, TypeScript, Rust, Go, Java, C/C++
- **No hallucinations** — deterministic, tree-sitter-parsed relationships, not embeddings or guesses
- **Fast incremental updates** — hash-based change detection re-parses only modified files
- **Cross-file symbol resolution** — your agent sees how functions, classes, and dependencies connect
- **38 built-in analysis plugins** — security, quality, and optimization rules with custom rule support
- **Track codebase evolution** — node-level diff history across every indexed run
- **Zero code execution** — safe to run in CI or on untrusted repositories

## CLI Reference

| Command | Purpose |
|---|---|
| `batho build` | Full index build from scratch |
| `batho patch` | Incremental re-index of changed files |
| `batho export` | Export transportable artifact ZIP or JSON view |
| `batho load` | Restore graph from an artifact ZIP |
| `batho diff` | Query node-level change history |
| `batho fix` | Verify and repair artifact integrity |
| `batho gc` | Prune old runs and vacuum storage |

Full CLI flags and export views: **[docs](https://batho.sageoz.org/docs/cli-reference)**

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

### GitHub Actions — Manual Workflow

For full control, add `.github/workflows/batho-ci.yml`:

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

Full CI/CD guides for GitLab CI, reusable workflows, and AI agent access patterns: **[docs](https://batho.sageoz.org)**

## Configuration

Batho runs with zero config. To customize, copy [`batho.yaml.example`](batho.yaml.example) to `./batho.yaml`:

```yaml
schema_version: batho-config.v1

logging:
  level: ERROR

indexer:
  max_file_size_kb: 500
  ignore_patterns: []
  max_workers: 0

bsg:
  cache:
    enabled: true
    max_size_mb: 1024
  symbol_resolution:
    enabled: true

flags:
  audit_log_enabled: true
```

See [`batho.yaml.example`](batho.yaml.example) for the full reference.

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