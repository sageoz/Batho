---
sidebar_position: 100
title: "Changelog"
description: "Batho release history"
---

# Changelog

## v1.4.1 — 2026-08-26

**Review hardening, thread safety, path sanitization, atomic writes, and documentation updates.**

### Bug Fixes

- **Thread safety in graph mutations**: `InMemoryGraph._lock` upgraded from `Lock` to `RLock`; `remove_entities_for_file` and `add_entities_for_file` now wrap mutations in `with graph._lock:` for atomic multi-entity updates without deadlocking.
- **Path sanitization in MCP tools**: Replaced naive `str.replace("\\", "/")` with `_canonicalize_untrusted_path()` in `graph_overview`, `graph_query`, `get_file_graph`, and `batho_diff` for proper canonicalization per the path sanitization ADR.
- **Config validation fail-fast**: `get_config_with_root` now raises `RuntimeError` on invalid config instead of silently backing up and overwriting the user's `batho.yaml`.
- **Atomic resolution cache writes**: `ResolutionCache` metadata writes now use `tempfile.mkstemp` + `os.replace` to prevent cache corruption on interruption.
- **AST cache mtime invalidation**: `AstCache.get` now accepts an optional `mtime` parameter to detect stale entries even when content hash matches.
- **Unicode identifier extraction**: `extractor.py` and `fallback_parser.py` regexes updated from `[a-zA-Z_]` to `[^\W0-9]` for PEP 3131 compliance, preserving non-ASCII identifiers.
- **Case-insensitive XML entity detection**: `manifest_parser.py` now uppercases content before checking for `<!ENTITY`/`<!DOCTYPE`, matching XML's case-insensitive grammar.
- **Unified cache field types**: `is_indexed` changed from `int` to `bool`; `last_run_id` renamed to `last_run_uuid` to match the actual schema.
- **Bundle reader zero-copy preservation**: Removed redundant sort in `BathoBundleReader` (writer already sorts by `file_id`); index now handles non-contiguous `file_id` ranges with multi-slice support.
- **Blob repairer memory**: `blob_repairer.py` now uses `pa.ipc.new_file` with a table directly instead of `to_pylist()`, avoiding unnecessary row materialization.

### Security Hardening

- **Tamper-evident audit log**: `FixContext` audit entries now include `previous_hash` and `hash` fields forming a SHA-256 chain, enabling tamper detection.
- **Security audit flag gating**: BSG plugin hit collection in `apply_bsg_rules_to_entities` is now guarded behind `security_audit_enabled`, avoiding unnecessary work when the flag is off.

### Performance

- **Early stream cleanup**: `store.cleanup_streams()` moved before community detection in `build.py` to free memory earlier in the pipeline.

### Other Changes

- `schema_version` in `Config` now uses `Literal["batho-config.v1"]` for stricter validation.
- Added error `hint` parameters to `_err()` calls in `batho_export`, `batho_diff`, `batho_gc`, and `batho_fix` MCP tools.
- Documentation: added `graph`, `community_detection`, and `memory` config sections; documented `watch`, `debounce_ms`, `max_file_size_kb` params for `add_repo`.
- Added `CITATION.cff` to the bump-version script's file list for future releases.
- Fixed `CHANGELOG_PATH` `NameError` in `generate_changelog_entry.py`.
- **966 tests** (up from 864).

---

## v1.4.0 — 2026-08-04

**Stdlib expansion, graph builder phases 4-5, BSG interceptors, and security/performance hardening.**

### New Features

- **Stdlib expansion to 27 languages**: Standard library symbol tables now cover 27 languages (up from 5), including C/C++, Java, Ruby, C#, PHP, Kotlin, Swift, Scala, Dart, Haskell, Lua, R, Perl, Julia, Zig, Bash, Objective-C, Erlang, OCaml, Hack, and Verilog.
- **Multi-ecosystem dependency introspection**: Live introspection now supports five package ecosystems — Python (venv), npm (`node_modules/`), Cargo (`~/.cargo/registry/`), Go modules (`~/go/pkg/mod/`), and Maven (`~/.m2/repository/`) — with package-name validation on all ecosystems to prevent path traversal.
- **Graph builder Phase 4 — Confidence scoring**: Every resolved stub is tagged with a `resolution_confidence` score (0.0–0.95) and `resolution_strategy` label across 6 tiers, enabling downstream consumers to filter by confidence level.
- **Graph builder Phase 4 — Conservative pruning**: Unresolved stubs targeting common stdlib method names on unknown receiver types are pruned instead of left as false gaps, reducing graph noise.
- **Graph builder Phase 5 — Receiver-type inference**: Method calls are resolved by inferring the receiver variable's declared type from scope, following the rust-analyzer two-phase resolution pattern.
- **Graph builder Phase 5 — Lazy resolution**: When `lazy=True`, stubs remain pending and are resolved on-demand via `resolve_stub_on_demand()`, avoiding unnecessary work for stubs that no query will ever reference.
- **9 BSG interceptor plugins enhanced**: API Contract Guardian, Auth Boundary Shield, Dependency Blast Radius, Hardcoded Secret Catcher, IaC Drift Sentinel, N+1 Query Catcher, Resource Leak Preventer, Schema Migration Enforcer, and Silent Failure Catcher updated with improved detection patterns.

### Security Hardening

- **Custom rules path sanitization**: `_resolve_custom_rules_path` now routes through `batho.utils.path_sanitizer.sanitize_path`, rejecting traversal and unsafe absolute paths.
- **Log file path sanitization**: `configure_logging` sanitizes the configured log file path before creating directories or opening a FileHandler.
- **Non-Python introspector validation**: All language introspectors (npm, Cargo, Go, Maven) now validate package names with `_is_safe_dependency_name` and use safe-join path construction.

### Bug Fixes

- **External symbol double-write**: Removed duplicate `EXTERNAL_SYMBOL` entity insertion in the build pipeline that inflated `entity_count` metrics and produced duplicate Arrow rows.
- **Atomic scope manager cache writes**: Scope manager cache IPC is now written to `.tmp` files and atomically `Path.replace`d into place, preventing partial writes on interruption.
- **Agent views filtering in patch**: `agent_views` table is now filtered with `pyarrow.compute` before `to_pylist()`, materializing only needed rows and reducing RSS on large repos.

### Other Changes

- Capped `structlog` dependency to `<26` to prevent breaking changes.
- Added stdlib resolution benchmark (`benchmarks/bench_stdlib_resolution.py`).
- Added 9 new test modules covering stdlib expansion, pipeline serialization, sentinel cache, graph phases 4-5, and incremental synthetic paths.
- **864 tests** (up from 609).

---

## v1.3.2 — 2026-07-27

- H2: Hardened path sanitization with shared canonicalization helper (`_canonicalize_untrusted_path`) to reject encoded, Unicode, and null-byte traversal vectors across `sanitize_path`, `safe_join`, `sanitize_diff_path`, and `is_safe_filename`.
- H5: Added Unicode identifier support for Python and JavaScript entities in extraction and hierarchical descriptors; fallback parser regexes now match PEP 3131-style identifiers.

## v1.3.1 — 2026-07-22

**Bug fixes and MCP UX improvements.**

### Bug Fixes

- **CLI root resolution crash**: `batho_cli.py` no longer crashes when `--root` is omitted or passed as a string. `args.root` is now wrapped in `Path()` and checked for `None` before calling `.resolve()`.
- **MCP test isolation**: `test_repos_resource_no_registry` now uses `registry_path=tmp_path` instead of reading the real `~/.batho/mcp-repos.json`, preventing failures when a local registry exists.

### MCP UX Improvements

- **Entity ID visibility**: `search_entities`, `format_concise`, and `format_detailed` markdown output now include entity_ids in backticks, enabling agents to copy-paste them into `get_entity` and `trace_path`.
- **Name-based lookup fallback**: `get_entity` and `trace_path` now accept display names as fallback when an exact entity_id is not found. If the name uniquely matches, it resolves automatically. If multiple matches exist, a disambiguation list with entity_ids is returned.

### Tests

- 9 new tests in `tests/mcp/test_entity_lookup.py` covering entity_id visibility and name-based lookup.
- Updated `tests/mcp/test_dual_output.py` to reflect that entity_ids are now intentionally included in markdown.
- Total: 609 tests passing.

## v1.3.0 — 2026-07-22

**Arrow graph backend, build metrics accuracy, memory optimization, and documentation cleanup.**

### New Features

- **Arrow Graph Backend**: Columnar memory-mapped graph storage (`ArrowGraph`) as an alternative to the default `InMemoryGraph`, enabling streaming compaction for large codebases without holding the entire graph in RAM.
- **Graph Backend Auto-Selection**: Heuristic-based backend resolution using file count and estimated entity count thresholds (`auto_threshold_files=500`, `auto_threshold_entities=30,000`). Automatically selects Arrow for large repos.
- **Graph Backend Protocol**: Formal `GraphBackend` protocol defining the contract between in-memory and Arrow backends.
- **Public API Exports**: `ArrowGraph` and `create_graph` now exported from `batho` top-level package.

### Bug Fixes

- **`symbol_index_size` reporting**: Added `ScopeManager.global_symbol_count` property to accurately report total global symbols across all partitions instead of reporting 0.
- **Unresolved stub resolution counts**: `resolve_contextual_stubs` now returns `(resolved_count, unresolved_count)` tuple, propagated to `build_stats` for accurate metrics.
- **Self-loop cycle detection false positives**: `find_cycles` now skips self-loops only for `IMPORTS` relationships (where they're noise), preserving `INHERITS` self-loop detection (which indicates real circular inheritance).
- **Negative RSS recovery logging**: `gc.collect()` that increases RSS now logs a warning instead of info, with a descriptive message about memory pressure.

### Performance

- **Memory optimization in extraction pipeline**: `agent_blob` and `storage_blob` are stripped from `raw_results` after being streamed via `result_callback`, preventing ~1.6 GB of redundant blob retention during graph materialization on large repos.
- **Worker log suppression**: `load_effective_rules` accepts `quiet=True` to suppress info-level logging in worker processes, eliminating log spam during parallel extraction.
- **RSS flush log spam reduction**: `rss_flush_released_memory` now only logs when memory was actually recovered (`> 0`) or when RSS increased (`< 0`), silencing no-op `gc.collect()` calls that recovered 0 MB.

### Configuration

- **Updated default memory thresholds**: `warning_threshold_mb` raised to 800 MB, `critical_threshold_mb` to 1,500 MB, `rss_flush_threshold_mb` to 1,000 MB — better suited for large codebase indexing.

### Documentation

- **Stale SQLite references cleanup**: Replaced all legacy "SQLite" references in docstrings and comments with accurate terminology ("AST cache (flat-file msgpack)", "Arrow Bundle") across 15 source and test files.

### Tests

- **600 tests** (up from 507) — new tests for Arrow graph backend, graph factory, backend config validation, and graph consistency.

---

## v1.2.1 — 2026-07-20

**Bug fixes, concurrency safety, and documentation alignment.**

### Bug Fixes

- **Critical: `patch.py` NameError on delete-only runs** — `indexer` variable was only defined inside the `if added_or_modified:` block; delete-only patch runs crashed with `NameError`. Fixed by initializing `indexer = None` and guarding the `getattr` call.
- **`RepoRegistry` race condition** — `add()` and `remove()` performed load→mutate→save without locking. Concurrent MCP tool calls could lose entries. Fixed with `threading.Lock` and atomic file writes.
- **`ResolutionCache` non-atomic writes** — `put_symbols()` and `_save_index()` wrote directly to cache files without temp+rename. Crash during write could corrupt the cache. Fixed with `tempfile.mkstemp` + `os.replace` pattern.

### Improvements

- **`graph_overview` truncation indicator** — Truncated output now appends a visible notice to the markdown, matching `graph_query` and `get_file_graph` behavior.
- **`get_file_graph` cross-file ref performance** — Replaced per-entity `pc.equal()` loop with single `pc.is_in()` batch filter.
- **`graph_overview` file entity counts** — Fixed hardcoded `entities: 0` in file list; now computes actual entity counts per file from the agent table.
- **Dependency introspector input validation** — Added package name regex validation before subprocess execution.
- **Git subprocess hardening** — Added `GIT_PAGER=cat` to environment to prevent pager invocation.

### Documentation

- Updated all version references from `v1.2.0` to `v1.2.1` across whitepaper, CI/CD, configuration, and test docs.

---

## v1.2.0 — 2026-07-05

**MCP server, multi-repo registry, and community detection — Batho becomes an AI agent platform.**

### New Features & Enhancements

- **MCP Server** (`batho mcp`): FastMCP-based stdio server exposing 10 tools for AI agents to query the code graph:
  - `graph_overview` — high-level codebase summary with entity counts, relationships, and communities
  - `graph_query` — filtered graph query by file, entity type, relation type, or name pattern
  - `get_entity` — detailed info for a single entity with relationships and optional source code
  - `trace_path` — shortest dependency path between two entities (BFS traversal)
  - `get_file_graph` — all entities and relationships within a single file
  - `search_entities` — substring/regex search across entity names
  - `get_delta` — incremental changes from the latest patch
  - `list_repos` / `add_repo` / `remove_repo` — multi-repo registry management
- **Multi-Repo Registry**: JSON-based registry at `~/.batho/mcp-repos.json` — one MCP config entry serves all repos. Register repos at runtime via `add_repo` tool.
- **Community Detection**: Greedy modularity clustering via `networkx` — automatically groups related entities into communities for codebase overview.
- **Dual-Output Architecture**: All MCP tools return both markdown `content` (model-facing, ~34% fewer tokens) and JSON `structuredContent` (machine-facing).
- **Token Budget Truncation**: Configurable `max_tokens` parameter on graph tools with automatic truncation and reporting.
- **MCP Prompts**: Workflow-specific prompt templates for agent onboarding (`explore_codebase`, `understand_function`, `analyze_file`, `trace_dependency`, `review_changes`, `impact_analysis`, `architecture_overview`).
- **MCP Resources**: Static schema and dynamic repo-list resources accessible via URI references.
- **Structured Error Handling**: Typed errors (`CLIENT_ERROR`, `EXTERNAL_ERROR`) with retry hints and actionable messages.
- **SKILL.md**: AI agent setup skill file for automated global install, MCP configuration across Claude Desktop, Cursor, Windsurf, and VS Code.
- **GitHub Actions Fleet Indexer**: Automated code graph indexing workflow with incremental patching on every push/PR.
- **New CLI Command**: `batho mcp` — starts the MCP server (8th CLI command).
- **New Dependencies**: `fastmcp>=3.4.0`, `networkx>=3.0`, `watchdog>=6.0.0`

### Tests

- **507 tests** (up from 381) — 126 new MCP tests covering tools, prompts, resources, registry, community detection, token budget, and error handling.

---

## v1.1.0 — 2026-06-10

**Refactored v1.1.0 release focusing on unified configuration, performance, and CLI simplicity.**

### New Features & Enhancements

- **Unified Configuration**: All settings consolidated into a single `./batho.yaml` (see `batho.yaml.example` for the complete schema).
- **Arrow IPC Bundle Storage**: Relational data and symbol indices are serialized in high-performance Arrow IPC table formats directly in the `.batho/artifact/` directory.
- **Lossless Bidirectional Traversal**: Graph-to-code reconstruction supported via `SYNTAX_GLUE` entity preservation and cryptographic hash validation.
- **Simplified CLI Interface**: Restructured the toolchain into exactly 7 command entrypoints:
  - `build` — baseline repository builds.
  - `patch` — native content-hash-based incremental indexing.
  - `export` — JSON and pack ZIP exports.
  - `fix` — database diagnostic and auto-repair routines.
  - `diff` — node-level evolution history.
  - `gc` — garbage collection, Sweeping, and vacuums.
  - `load` — unpack transport ZIPs.

### Removals

- **Subsystem Removal**: Removed the legacy Web Dashboard, REST API Bridge, MCP Hub Context Server, and client-side Git Hook automation to focus exclusively on high-performance developer command-line workflows.

---

## v1.0.0 — 2026-05-17

**Initial pre-refactor production baseline.**

### Features

- Multi-language AST extraction (40+ languages via tree-sitter).
- In-memory hypergraph with cross-file symbol resolution.
- BSG compression with token-budgeted rendering.
- Time Machine snapshots with incremental patching.
- Pre-refactor subsystems (legacy dashboard, REST bridge, MCP server, git hooks).
- 381 automated tests.
