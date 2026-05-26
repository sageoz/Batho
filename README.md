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
- **MCP Hub** — Multi-workspace context server with cross-repo search
- **BSG Plugin System v1** — 20+ foundation and interceptor plugins
- **Symbol Resolution** — Cross-file symbol resolution with fuzzy matching
- **Artifact Bridge** — REST API + MCP server for IDE integrations
- **Cloud Sync** — Artifact upload to cloud endpoint with retry logic
- **Storage Management** — SQLite registry with retention policies
- **Query Engine** — Fast queries on persisted graph indexes
- **Zero code execution** — Safe to run in CI, pre-commit, or on untrusted repos

## 🆕 What's New in v1.1.0 (In Development)

### 🚀 Breaking Changes

**Unified Configuration (No Backward Compatibility)**

- **Cache path migration**: Cache moved from `.ctn/local/cache.db` to `.ctn/local/cache/cache.db` for better organization

- Single `batho.yaml` file replaces all config — core, hooks, BSG, storage, cloud sync
- `.batho/hooks.yaml` is the source of truth for hook definitions
- `batho.yaml.example` provides complete configuration template
- Environment variable overrides supported for all settings
- Config schema validation on load

### ✨ Major New Features

**BSG Bidirectional Graph — Lossless File Reconstruction**

- **Full byte coverage**: Gap extraction (`SYNTAX_GLUE` entities) captures every byte between semantic entities, including whitespace, comments, and blank lines
- **Deterministic reconstruction**: `FileReconstructor` reassembles original files from BSG entities with integrity verification (SHA-256 hash matching)
- **Dual-view rendering**: Storage view (full fidelity with `raw_content`) for reconstruction; Agent view (compressed, excludes `SYNTAX_GLUE`) for LLM context
- **Backward-compatible schema**: Existing serialized graphs load without changes; new fields have safe defaults
- **CLI commands**: `batho reconstruct --file <path>` for file reconstruction, `batho verify --all` for bulk integrity checks, `batho export --bsg --file <path>` for export
- **CLI flags**: `--with-gaps` enables gap extraction during indexing, `--storage-view` persists raw content for reconstruction
- **CI integration**: `batho verify --all` can be added to any workflow to catch regressions in indexed artifacts
- **Config**: `bsg.bidirectional.enabled`, `bsg.bidirectional.include_gaps`, `bsg.bidirectional.storage_view`

```bash
# Index with gap extraction for reconstruction
batho index --root . --with-gaps --storage-view

# Verify integrity of all indexed files
batho verify --all --root . --report-json verify-report.json

# Reconstruct a single file from BSG entities
batho reconstruct src/main.py --root . --output /tmp/main.py

# Export a file as reconstructed output
batho export --bsg --file src/main.py --root . --output /tmp/main.py
```

**MCP Hub — Multi-Workspace Context Server**

- **Multi-workspace support**: Manage 100+ codebases from one endpoint
- **Cross-repo search**: Search across all workspaces simultaneously
- **Lazy mount + LRU residency**: Host many workspaces with minimal RAM
- **Prometheus telemetry**: Full observability with `/api/v1/metrics`
- **Structured logging**: Every tool call logged with latency and status
- **Stress-tested**: 1000 concurrent requests, failure injection
- **Workspace discovery**: Auto-detect `.ctn/` directories across projects
- **Pin/unpin workspaces**: Keep frequently-used workspaces resident
- **Connection pooling**: Efficient resource management with `ConnectionPool`
- **Writer pool**: Dedicated write operations pool for batch processing
- **Connection profiles**: Configurable workspace connection profiles

```bash
batho mcp serve --config ~/.batho/mcp.yaml
batho mcp list              # List all registered workspaces
batho mcp add /path/to/repo # Add new workspace
batho mcp pin my-project    # Pin to keep resident
```

**BSG Plugin System v1**

- **20+ foundation plugins**: Categorization, framework detection, graph enrichment, token optimization
- **10+ interceptor plugins**: API contract guardian, secret catcher, resource leak preventer, N+1 query catcher, IaC drift sentinel, schema migration enforcer, auth boundary shield
- **Custom rules**: Inline or file-based rule definitions
- **Plugin validation**: Schema validation before indexing
- **Fixture runner**: Test plugins against sample codebases

```bash
batho plugins list --root . --verbose
batho plugins validate custom-plugin.yaml
batho plugins fixture-runner --plugin bsg_hardcoded_secret_catcher --test-dir tests/
```

**Symbol Resolution**

- **Cross-file symbol resolution**: Resolve imports, function calls, class references across files
- **Fuzzy matching**: Optional fuzzy matching for similar symbol names
- **Symbol caching**: Persistent symbol index for fast lookups
- **Configurable**: Enable/disable via `bsg.symbol_resolution.enabled`

**Patch Management (Time Machine v4)**

- **patches**: List all patch operations with filters (type, snapshot)
- **patch-info**: Show detailed patch operation information
- **patch-chain**: Show patch chain for a snapshot
- **apply-patch**: Apply patch from diff file or cherry-pick
- **cherry-pick**: Apply patch to different base snapshot
- **Dry-run support**: Preview changes before applying

```bash
batho patches --root . --format timeline
batho patch-info --root . --patch-id abc123
batho patch-chain --root . --snapshot-id xyz789 --full
batho apply-patch --root . --base-snapshot xyz789 --diff-file changes.diff
batho cherry-pick --root . --patch-id abc123 --target-snapshot def456
```

**Storage Management**

- **backfill**: Register existing durable `.ctn/` artifacts in SQLite registry
- **verify**: Verify registry consistency and repair metadata drift
- **cleanup**: Apply retention cleanup (TTL-based)
- **stats**: Show registry and persisted graph cache statistics
- **rebuild-indexes**: Rebuild query indexes from graph.json
- **compact**: Deduplicate registry entries

```bash
batho storage backfill --root .
batho storage verify --root . --repair
batho storage cleanup --root . --apply
batho storage stats --root .
batho storage rebuild-indexes --root .
batho storage compact --root . --apply
```

**Dashboard CLI**

- **serve**: Start the web-based dashboard server
- **Configurable port**: Default port 8080 with `--port` option
- **Live reload**: Frontend assets with CTN loader improvements

```bash
batho dashboard --root . --port 8080
```

**Cache Management**

- **stats**: Show cache statistics
- **invalidate**: Invalidate cache entries by pattern
- **clear**: Clear entire cache
- **cleanup**: Remove old cache files after migration

```bash
batho cache stats --root .
batho cache invalidate --root . "tests/**"
batho cache clear --root .
batho cache cleanup --root . --dry-run
```

**Cloud Sync**

- **sync**: Upload artifacts to cloud endpoint
- **Dry-run**: Preview uploads without executing
- **Retry failed**: Retry previously failed uploads
- **Filter by type**: Sync specific artifact types
- **Status**: Show sync status

```bash
batho sync --root . --dry-run
batho sync --root . --type graph --type bsg
batho sync --root . --retry-failed --verbose
```

**Query Engine**

- **query**: Query persisted graph indexes
- **Filters**: Entity type, file path, relationship type
- **Rebuild index**: Force rebuild from graph.json
- **Limit**: Result limit control

```bash
batho query --root . --entity-type function --limit 100
batho query --root . --file-path "src/main.py" --relationship-type CALLS
```

**Git Hooks Enterprise**

- **YAML-driven configuration**: `.batho/hooks.yaml` as source of truth
- **Install/remove**: Manage hook scripts in `.git/hooks/`
- **Run manually**: Execute hooks by name for testing
- **Status**: Show installation status
- **Custom hooks**: Arbitrary custom hook names supported
- **Enterprise templates**: Pre-built templates for common workflows

```bash
batho hooks install --all
batho hooks run --hook pre-commit --dry-run
batho hooks status --hook pre-commit
batho hooks remove --all
```

### 🔧 Improvements

**Incremental Patching**

- **Snapshot-based**: True incremental patching using snapshot diff
- **Auto-detect**: Automatically use snapshots when available
- **Force index-patch**: Fallback to traditional reindexing
- **Timeout**: Configurable timeout for patch operations
- **Max changes**: Configurable limit for number of changes

```bash
batho patch --root . --scan --snapshot
batho patch --root . --base-snapshot xyz789 --force-index-patch
```

**Graph Consistency**

- **Relaxed validation**: Permissive module-style target validation
- **Non-fatal warnings**: Graph consistency warnings don't block operations
- **Relationship deduplication**: Silent discard of duplicate relationships

**BSG Token Optimization**

- **JSON/YAML rollup**: Array content rolled into parent metadata
- **Markdown rollup**: List content rolled into headers
- **HTML attributes**: Attributes in element metadata
- **Docstring truncation**: Configurable max docstring length

**Default Ignore Patterns**

- Built-in YAML with common ignore patterns (node_modules, .venv, .git, etc.)
- Configurable via `indexer.default_patterns_file`
- Extensible via `indexer.ignore_patterns`

**Storage & Retention Policies**

- **TTL-based cleanup**: Configurable TTL for snapshots, patches, metrics, context
- **Max limits**: Configurable max snapshots, max patches
- **Content scope**: Durable vs all artifact tracking
- **Cloud sync ready**: Track content IDs for cloud sync

**Dashboard**

- **Local static server**: Serve dashboard from local assets
- **Dual-root serving**: Serve dashboard + project artifacts
- **Bridge API integration**: Direct API access from dashboard
- **9 pages**: Overview, Hypergraph, Files, File Viewer, Relationships, Rules, Metrics, Snapshots, Search
- **Keyboard shortcuts**: `Ctrl/Cmd + K` for search, `Ctrl/Cmd + D` for dark mode
- **Export options**: PNG, SVG, JSON, CSV

```bash
batho dashboard --root . --port 8080
```

## 🤖 MCP Server

Batho exposes an MCP (Model Context Protocol) server for AI tool integration:

```bash
# Start MCP server
batho mcp serve

# Or via REST API
batho bridge serve
```

**Configure in `~/.batho/mcp.yaml`:**

```yaml
server:
  host: "127.0.0.1"
  port: 8765

workspaces:
  - id: "my-project"
    ctn_dir: "/path/to/project/.ctn"
```

**Tools available:**
- `workspace_list`, `workspace_health`, `workspace_stats`
- `artifact_get`, `artifact_list`, `artifact_search`
- `file_read`, `file_list`, `file_outline`
- `graph_get`, `graph_search`, `graph_relationships`
- `cross_search`, `cross_symbols`, `cross_dependencies`

See [MCP Documentation](https://batho.sageoz.org/docs/mcp) for full reference.

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
| **Ignore rules** | Respects `.gitignore` and default patterns |
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
- Cloud sync is **disabled by default** (enable via `cloud_sync.enabled: true`)

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
batho index --root . --verbose

# 5. Run storage backfill (if upgrading from v1)
batho storage backfill --root .
```

## ⚙️ Configuration

Batho works out of the box with zero config. For production use, configure with `./batho.yaml`:

```yaml
logging:
  level: INFO
  json_format: null
  quiet: false

indexer:
  max_file_size_kb: 500
  max_workers: 16
  ignore_patterns: []
  default_patterns_file: null

bsg:
  cache:
    enabled: true
    path: .ctn/local/cache/cache.db
  symbol_resolution:
    enabled: true
    fuzzy_matching: false
    cache_symbols: true
  storage:
    enabled: true
    backend: sqlite

rules:
  enabled: false
  builtin_plugins:
    - bsg_core
    - bsg_silent_failure_catcher
    - bsg_hardcoded_secret_catcher
  custom_rules_path: null

hooks:
  enabled: true
  include: true

cloud_sync:
  enabled: false
  endpoint: https://sync.batho.dev/v1
  api_key: ${BATHO_CLOUD_API_KEY}
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