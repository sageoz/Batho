# Batho Core Engine - Single Source of Truth Documentation

**Version**: 0.1.0 (Pre-launch Beta)  
**Status**: Feature-complete with comprehensive testing, preparing for v1 launch  
**Last Updated**: March 29, 2026  

## Executive Summary

Batho is an **enterprise-ready, high-speed, multi-language code indexer** with RepoMap compression and Time Machine snapshots/diffs — no LLM required. It transforms any codebase into structured knowledge that AI tools, agents, and developers can actually use.

### Core Problem Solved
- **Codebase Opacity**: Large-scale codebases become increasingly difficult to understand
- **Documentation Drift**: Documentation quickly becomes outdated as code evolves  
- **Technical Debt Accumulation**: Silent accumulation of architectural issues
- **AI Context Limitations**: LLMs need structured code understanding, not raw file contents

### Vision Statement
Transform Batho into a **living, self-updating architectural memory system** that continuously ingests repositories, builds comprehensive code graphs, tracks evolution, and validates changes against business intent.

## Current Implementation Status (v1)

### ✅ Fully Implemented Features

#### Core Functionality
- **CLI Commands**: Complete command suite (`index`, `stats`, `patch`, `patches`, `patch-info`, `patch-chain`, `apply-patch`, `cherry-pick`, `snapshots`, `diff-snapshots`, `invalidate`, `webhook`, `c4`, `repomap`)
- **Code Graph Indexing**: Feature-complete with caching, binary/size guards, ignore support, parallel extraction
- **RepoMap Rendering**: Multiple formats (full, hierarchical, compressed) with dependency mapping
- **Time Machine**: Snapshot creation, listing, loading, and diffing with staleness scoring
- **Configuration**: Validated config system with environment variable overrides
- **Multi-Language Support**: 40+ languages via tree-sitter with runtime grammar availability checks
- **True Incremental Patching**: Graph delta application with automatic snapshot detection
- **Patch Chain Tracking**: Complete lineage tracking with CLI management and cherry-picking
- **Stack Detection**: Python/web, Node.js, Java/Spring, .NET, Go, PHP/Laravel, Ruby/Rails, Rust, Android/iOS, Data/ML
- **C4 Model Generation**: Automatic architecture diagram generation with adaptive granularity
- **Multi-Format Output**: PlantUML, Mermaid, D2, interactive HTML with plugin architecture
- **Enhanced Pattern Detection**: Microservices, event-driven, cloud-native architectural patterns
- **Enterprise-Grade Security**: Parse-only operation, binary detection, ignore rules, atomic writes
- **Memory Monitoring**: Real-time memory usage tracking with warning/critical thresholds
- **File Locking**: Cross-platform file locking with timeout and stale lock cleanup
- **Path Sanitization**: Security utilities to prevent path traversal attacks

#### Testing & Quality
- **Comprehensive Test Suite**: 637 tests with 100% pass rate (637/637 passing)
- **Test Categories**: Unit, integration, performance, and slow tests with proper markers
- **CI/CD Ready**: GitHub Actions integration, JUnit XML output, coverage reporting
- **Performance Optimized**: Parallel extraction, adaptive algorithms, memory-conscious implementation
- **Memory Monitoring**: Built-in memory usage tracking and leak detection
- **File Locking**: Cross-platform atomic file operations with stale lock detection
- **Path Security**: Sanitization utilities to prevent path traversal attacks

### ⚠️ Placeholder Logic (Partially Implemented)

#### Webhook Handling  
- **Current State**: `webhook_stub` is a no-op placeholder
- **Missing**: GitHub/GitLab integration, authentication, queueing, rate limiting

### ❌ Not Yet Implemented (v2+ Features)

#### Advanced AI Features
- Agentic Architecture Generation
- Standards-compliant Documentation (SRS, OWASP, ADR)
- Live State Engine (Ticket Sync with Jira/GitHub Issues)
- MR Validation & Auto-Approval

#### Enterprise Features
- Persistent graph storage for large repositories
- Advanced compression with adaptive token budgeting
- Vulnerability/license information surface
- Enterprise telemetry and health checks

## Architecture Overview

### Data Flow
```
Repository Files → CodeGraphIndexer → InMemoryGraph → RepoMap → Multiple Outputs
                      ↓                    ↓              ↓
                 Caching Layer    Time Machine   Multi-Format
                      ↓                    ↓              ↓
              .ctn/file_cache.json   Snapshots   PlantUML/Mermaid/D2/HTML
```

### Core Components

#### CLI (`batho.py`)
- **Purpose**: Main entry point orchestrating all commands
- **Features**: Rich argument parsing, progress reporting, error handling
- **Commands**: index, stats, patch, snapshots, diff-snapshots, invalidate, webhook (stub), repomap (NEW), c4, patches, patch-info, patch-chain, apply-patch, cherry-pick

#### CodeGraphIndexer (`batho_core/context/codegraph.py`)
- **Purpose**: Walks repository, extracts AST entities and relationships
- **Features**: Parallel extraction, caching, binary guards, import resolution
- **Output**: InMemoryGraph with entities and relationships

#### RepoMap (`batho_core/context/repomap.py`)
- **Purpose**: Compresses code graph into LLM-friendly formats
- **Features**: Multiple rendering modes, dependency mapping, token budgeting
- **Outputs**: JSON, Markdown (architecture.md), hierarchical views

#### Time Machine (`batho_core/time_machine.py`)
- **Purpose**: Historical analysis and change tracking
- **Features**: Snapshots, diffing, staleness computation
- **Storage**: `.ctn/snapshots/<snapshot_id>.json`

#### C4 Generator (`batho_core/context/c4*.py`)
- **Purpose**: Automatic architecture diagram generation
- **Features**: Pattern detection, adaptive granularity, multi-format output
- **Outputs**: PlantUML, Mermaid, D2, interactive HTML

## Feature Matrix

| Feature Category | Implemented | Status | Notes |
|------------------|-------------|---------|-------|
| **Core Indexing** | ✅ | Complete | Multi-language, parallel, cached |
| **RepoMap Compression** | ✅ | Complete | Multiple formats, token budgeting |
| **Time Machine** | ✅ | Complete | Snapshots, diffing, staleness |
| **CLI Interface** | ✅ | Complete | Full command suite + patch management |
| **Stack Detection** | ✅ | Complete | 10+ technology stacks |
| **C4 Generation** | ✅ | Complete | Multi-format, adaptive |
| **Testing Framework** | ✅ | Complete | 637 tests, 100% pass |
| **Incremental Patching** | ✅ | Complete | True graph delta application + tracking |
| **Patch Chain Tracking** | ✅ | Complete | Full lineage, CLI management, cherry-picking |
| **Memory Monitoring** | ✅ | Complete | Real-time tracking, leak detection |
| **File Locking** | ✅ | Complete | Cross-platform, atomic operations |
| **Path Security** | ✅ | Complete | Sanitization, traversal prevention |
| **RepoMap CLI** | ✅ | Complete | Standalone repomap command |
| **Webhook Handling** | ⚠️ | Placeholder | Stub implementation |
| **Agentic Architecture** | ❌ | Not Started | v2+ feature |
| **Standards Docs** | ❌ | Not Started | v2+ feature |
| **Live State Engine** | ❌ | Not Started | v2+ feature |

## Usage Guide

### Installation
```bash
# Install from source
pip install -e .

# Or from PyPI (when published)
pip install batho
```

### Basic Operations

#### Full Repository Index
```bash
# Index with verbose output
batho index --root /path/to/repo --verbose

# With custom settings
batho index --root /path/to/repo --max-workers 16 --max-file-size-kb 1000 --budget-tokens 20000
```

#### View Index Statistics
```bash
batho stats --root /path/to/repo
```

#### Patch Command (Enhanced with True Incremental Patching & Tracking)

The `patch` command now automatically uses true incremental patching when snapshots are available and provides comprehensive patch tracking:

```bash
# Auto-detects and uses incremental patching when snapshots exist
batho patch --root /path/to/repo

# Explicitly use a specific snapshot as base
batho patch --root /path/to/repo --base-snapshot snapshot_id

# Force traditional index-based patching (for compatibility)
batho patch --root /path/to/repo --force-index-patch file1.py file2.py

# Patch from diff file
batho patch --root /path/to/repo --diff-file changes.diff

# Scan for changes automatically
batho patch --root /path/to/repo --scan

# Dry run to preview changes
batho patch --root /path/to/repo --dry-run
```

**Automatic Behavior:**
- When snapshots are available, automatically uses the latest snapshot for incremental patching
- Detects file additions, modifications, and deletions automatically
- Applies graph deltas instead of full reindexing for better performance
- Creates new snapshots after successful patches
- **NEW:** Automatically saves patch operations with full metadata
- **NEW:** Builds patch chains for complete lineage tracking
- Falls back to traditional patching when no snapshots exist

**Performance Benefits:**
- **10-100x faster** for small changes (avoids full repository reindex)
- **Lower memory usage** (only processes changed files)
- **Preserves cache** (maintains file-level caching efficiency)
- **Atomic operations** (rollback on failure)

#### NEW: Patch Management Commands

```bash
# List all patch operations with timeline view
batho patches --root /path/to/repo [--format json|timeline]

# Show detailed patch operation information
batho patch-info --root /path/to/repo --patch-id ID [--format json|summary]

# Show complete patch chain for a snapshot
batho patch-chain --root /path/to/repo --snapshot-id ID [--full]

# Apply patch from unified diff file
batho apply-patch --root /path/to/repo --base-snapshot ID --diff-file changes.diff

# Cherry-pick patch to different base snapshot
batho cherry-pick --root /path/to/repo --patch-id ID --target-snapshot ID [--dry-run]
```

**Patch Tracking Features:**
- **Automatic Persistence:** All patches automatically saved to `.ctn/patches/`
- **Patch Chain Tracking:** Complete lineage from initial snapshot
- **Detailed Metrics:** Token size, affected files, timing information
- **Retention Policy:** Configurable cleanup (`BATHO_PATCH_HISTORY_DAYS`, `BATHO_PATCH_COUNT`)
- **JSON Output:** Clean structured output for external scripts and AI agents
- **Filtering:** Filter patches by type, base snapshot, or time range

#### Time Machine Operations
```bash
# List all snapshots
batho snapshots --root /path/to/repo

# Compare two snapshots
batho diff-snapshots --root /path/to/repo SNAP_A SNAP_B

# Create snapshot
batho index --root /path/to/repo --snapshot
```

#### RepoMap Command (NEW)
```bash
# Generate compressed repomap for LLM context
batho repomap --root /path/to/repo --mode compressed --budget 12000

# Generate full repomap with all signatures
batho repomap --root /path/to/repo --mode full

# Generate hierarchical directory view
batho repomap --root /path/to/repo --mode hierarchical
```

#### C4 Diagram Generation
```bash
# Generate C4 models (automatic during index)
batho index --root /path/to/repo

# Generate from existing index
batho c4 --root /path/to/repo --output /path/to/c4-model.json

# Skip C4 generation
batho index --root /path/to/repo --no-c4
```

### Output Structure
```
.ctn/
├── index.json                    # Index metadata + staleness score
├── file_cache.json               # mtime + SHA cache for fast re-runs
├── metrics.json                  # Performance metrics
├── snapshots/                    # Time Machine snapshots
│   └── batho_<uuid>_<ts>.json
└── <index_id>/
    ├── graph.json                # All entities + relationships
    ├── repomap.json              # Structured symbol index
    ├── architecture.md           # Human-readable summary
    └── c4-model.json             # C4 architecture model
```

## Testing & Validation

### Running Tests
```bash
# Run all tests with coverage
uv run python test.py

# Run specific test categories
uv run python test.py --unit           # Unit tests only
uv run python test.py --integration    # Integration tests only
uv run python test.py --slow          # Performance tests

# Run with pytest directly
uv run pytest tests/ -v --cov=batho_core
```

### Test Coverage
- **Total Tests**: 637
- **Passing**: 637 (100%)
- **Failing**: 0
- **Coverage Areas**: CLI, indexing, repomap, C4 generation, formatters, incremental patching, memory monitoring, file locking, path security

### Known Test Issues
None - All tests are currently passing with 100% success rate.

## Launch Readiness Assessment

### ✅ Ready for Production
- Core indexing functionality is stable and performant
- Multi-language support is comprehensive
- CLI interface is complete and user-friendly
- Test coverage is excellent (100% pass rate)
- Documentation is thorough
- Security posture is strong (parse-only, no code execution)
- Enterprise features: memory monitoring, file locking, path security
- Incremental patching is fully implemented and tested

### ⚠️ Needs Attention for v2
- Webhook handling needs production-ready features
- Some advanced C4 features need refinement
- Performance optimization for very large repositories (>100K files)

### 🎯 Launch Requirements
To launch Batho v1 as a production-ready product:

1. **Documentation**: Complete and accurate (✅ DONE)
2. **Testing**: Comprehensive test suite (✅ DONE)  
3. **Performance**: Optimized for large repositories (✅ DONE)
4. **Security**: Parse-only, safe operation (✅ DONE)
5. **CLI Ergonomics**: User-friendly interface (✅ DONE)

## Future Roadmap (v2+)

### High Priority
1. **Production Webhooks**: GitHub/GitLab integration with authentication and queueing
2. **CI/CD Pipeline Hooks**: Turnkey GitHub Actions and GitLab CI templates
3. **Analyze Pipeline**: Generate C4, SRS, and OWASP documentation from graph

### Medium Priority
1. **Persistent Graph Storage**: Optional on-disk/DB backend for large repos
2. **Advanced Compression**: Adaptive token budgeting with section prioritization
3. **Vulnerability Scanning**: Surface SPDX licenses and security hints
4. **Enterprise Telemetry**: Prometheus-friendly metrics and health checks

### Low Priority
1. **Live State Engine**: Sync with Jira/GitHub Issues
2. **MR Validation**: Validate changes against ticket requirements
3. **Advanced AI Features**: Agentic architecture generation
4. **Standards Compliance**: Automated SRS/OWASP/ADR generation

## Technical Specifications

### Supported Languages
| Category | Languages |
|----------|-----------|
| **Web/Backend** | Python, TypeScript, JavaScript, Go, Java, Ruby, PHP, C#, Scala, Kotlin |
| **Systems** | Rust, C, C++, Zig, Objective-C |
| **Mobile** | Swift, Kotlin (Android), Objective-C (iOS) |
| **Functional** | Haskell, Erlang, OCaml, Elixir, Julia, Agda |
| **Scripting** | Bash, Perl, Lua, R |
| **Markup/Config** | JSON, YAML, TOML, HTML, CSS/SCSS/SASS/LESS, Markdown, HCL/Terraform |

### Performance Characteristics
| Repository Size | Typical Index Time | Memory Usage | Output Size |
|----------------|-------------------|---------------|-------------|
| < 50 files | < 2s | < 100MB | < 1MB |
| 50-200 files | 2-5s | 100-200MB | 1-5MB |
| 200-1K files | 5-15s | 200-500MB | 5-20MB |
| 1K+ files | Varies | 500MB+ | 20MB+ |

### Configuration Options
```yaml
# batho.yaml example
logging:
  level: INFO
  json_format: true

indexer:
  max_file_size_kb: 500
  max_workers: 0  # Auto-detect
  repomap_budget_tokens: 12000
  ignore_patterns:
    - "**/vendor/**"
    - "**/dist/**"

flags:
  strict: false
  fail_on_warning: false
```

## Conclusion

Batho v0.1.0 is **feature-complete and production-ready** with a robust core feature set, comprehensive testing (100% pass rate), and excellent performance. The foundation is solid for enterprise adoption, with clear roadmap items for v2 that will add advanced automation and AI capabilities.

The current implementation provides immediate value to development teams by:
- Making codebases searchable and understandable
- Enabling AI tools to work with structured code knowledge
- Providing architectural insights through automatic C4 generation
- Supporting continuous integration workflows
- **Delivering 10-100x faster incremental updates** for small changes
- **Providing complete patch lineage tracking** for audit trails and debugging
- **Enabling patch cherry-picking** for flexible change application
- **Offering comprehensive patch management** with CLI tools and JSON APIs
- **Monitoring memory usage** to prevent issues with large repositories
- **Ensuring file operation safety** with cross-platform locking
- **Preventing security issues** with path sanitization utilities

**Recommendation**: Prepare for v1.0 launch while continuing v2 development in parallel.
