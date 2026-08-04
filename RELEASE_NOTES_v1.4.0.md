# Batho v1.4.0 — Release Notes

**Release date:** 2026-08-04
**Tag:** `v1.4.0`
**Version:** 1.4.0
**Test suite:** 864 tests passing
**Supported Python:** 3.12, 3.13

---

## Overview

Batho v1.4.0 is a minor release focused on **expanded language coverage**, **graph builder intelligence**, **BSG interceptor enrichment**, and **security/performance hardening**. This release expands stdlib symbol tables from 5 to 27 languages, introduces graph builder phases 4–5 (confidence scoring, conservative pruning, receiver-type inference, and lazy resolution), enhances all 9 BSG interceptor plugins, and fixes 13 review findings including 4 security issues.

---

## New Features

### Stdlib Expansion to 27 Languages

Standard library symbol tables now cover 27 languages (up from 5 in v1.3.2), enabling accurate external symbol resolution across polyglot codebases:

| Newly Added (22) | Previously Supported (5) |
|---|---|
| C, C++, Java, Ruby, C#, PHP, Kotlin, Swift, Scala, Dart, Haskell, Lua, R, Perl, Julia, Zig, Bash, Objective-C, Erlang, OCaml, Hack, Verilog | Python, JavaScript, TypeScript, Go, Rust |

Languages with lighter stdlib coverage (e.g. Bash, Verilog) register their built-in functions and pragmas so that imports are tracked even when full module hierarchies are not applicable.

### Multi-Ecosystem Dependency Introspection

Live introspection now supports **five package ecosystems** (previously Python-only):

| Ecosystem | Source | Method |
|-----------|--------|--------|
| Python | Active virtual environment | `dir()` + `inspect` in subprocess |
| npm | `node_modules/` directory | Parse `package.json` exports + `require()` probe |
| Cargo | `~/.cargo/registry/` | Parse crate metadata and public API |
| Go | `~/go/pkg/mod/` | Parse exported declarations from module source |
| Maven | `~/.m2/repository/` | Parse JAR class entries via `jar`/`unzip` listing |

All package/module/crate names are validated with `_is_safe_dependency_name` before any filesystem path is constructed, preventing traversal attacks outside the package cache.

### Graph Builder Phase 4 — Confidence Scoring & Conservative Pruning

Every resolved stub is now tagged with a `resolution_confidence` score (0.0–0.95) and a `resolution_strategy` label across 6 tiers, enabling downstream consumers (queries, visualizations, exports) to filter by confidence level:

| Strategy | Confidence | Description |
|----------|-----------|-------------|
| `exact_match` | 0.95 | Direct dotpath lookup |
| `stdlib_method` | 0.90 | Stdlib method / module prefix match |
| `import_map` | 0.85 | Import-map cross-file resolution |
| `parent_chain` | 0.75 | Parent stub chain building |
| `scope_qualified` | 0.70 | Caller-scope qualified path |
| `receiver_type` | 0.65 | Receiver-type inference (Phase 5) |

Unresolved stubs targeting common stdlib method names on unknown receiver types (e.g. `unwrap`, `map`, `then`, `append`) are conservatively **pruned** instead of left as false gaps, reducing graph noise significantly.

### Graph Builder Phase 5 — Receiver-Type Inference & Lazy Resolution

**Receiver-type inference** resolves method calls by inferring the receiver variable's declared type from scope, following the rust-analyzer two-phase method resolution pattern:

1. **Scope lookup**: Infer the receiver variable's type from local declarations, parameters, and assignments.
2. **Metadata hint**: Fall back to the `receiver_type` hint captured by tree-sitter queries.
3. **Resolution**: Resolve the method call to the corresponding method entity on that type.

**Lazy resolution mode** (`lazy=True`): Stubs remain pending and are resolved on-demand via `resolve_stub_on_demand()`, implementing the rust-analyzer/Pyright on-demand evaluation pattern — a significant performance win for large codebases where only a fraction of stubs are ever queried.

### BSG Interceptor Plugin Enhancements

All 9 BSG interceptor plugins have been enhanced with improved detection patterns:

- **Hardcoded Secret Catcher** — API keys, tokens in string literals
- **Auth Boundary Shield** — Missing auth decorators on API route handlers
- **Silent Failure Catcher** — Bare `except:`, swallowed exceptions
- **Dependency Blast Radius** — High fan-out modules (>N dependents)
- **API Contract Guardian** — Backend API contract changes with downstream dependents
- **IaC Drift Sentinel** — Config drift between app env references and IaC definitions
- **N+1 Query Catcher** — Database execution patterns inside loop structures
- **Resource Leak Preventer** — Resource allocations without cleanup paths
- **Schema Migration Enforcer** — ORM/schema changes requiring migration companions

---

## Security Hardening

| Issue | Severity | Fix |
|-------|----------|-----|
| Custom rules path not sanitized | **High** | `_resolve_custom_rules_path` now routes through `batho.utils.path_sanitizer.sanitize_path`, rejecting traversal and unsafe absolute paths |
| Non-Python introspectors don't validate package names | Medium | All language introspectors (npm, Cargo, Go, Maven) now validate with `_is_safe_dependency_name` and use safe-join path construction |
| Log file path from config not sanitized | Medium | `configure_logging` sanitizes the configured log file path before creating directories or opening a FileHandler |

---

## Bug Fixes

| Issue | Impact | Fix |
|-------|--------|-----|
| External symbol entities written twice in build artifact | **High** — inflated `entity_count` metrics, duplicate Arrow rows | Removed duplicate `EXTERNAL_SYMBOL` insertion; legacy write path handles it once |
| Scope manager cache IPC written non-atomically | Medium — partial writes on interruption | Write to `.tmp` files, then `Path.replace` atomically into place (MVCC pattern) |
| Patch materializes full agent_views table via to_pylist | Medium — high RSS on large repos | Filter with `pyarrow.compute` before `to_pylist()`, materializing only needed rows |
| Patch community detection rebuild crashes on missing relationship id | Medium — community detection silently failed on every patch | Add deterministic `id` via `build_relationship_id()` to reconstructed relationship SimpleNamespace objects |

---

## Other Changes

- Capped `structlog` dependency to `<26` to prevent breaking changes from future major releases
- Added stdlib resolution benchmark (`benchmarks/bench_stdlib_resolution.py`) for I1/I9 metrics
- Added 9 new test modules (255 new tests):
  - `tests/modules/dependency/test_stdlib_expansion.py`
  - `tests/modules/extraction/test_pipeline_serialize.py`
  - `tests/modules/extraction/test_rust_go_contains.py`
  - `tests/modules/extraction/test_sentinel_cache.py`
  - `tests/modules/graph/test_phase4_pruning_confidence.py`
  - `tests/modules/graph/test_phase5_performance.py`
  - `tests/modules/graph/test_project_symbol_registration.py`
  - `tests/modules/graph/test_receiver_type_resolution.py`
  - `tests/modules/storage/arrow_bundle/test_incremental_synthetic_paths.py`
- Updated `batho.yaml.example` to reflect the full 27-language default stdlib/dependency introspection set
- Updated docs-site content: expanded stdlib table, multi-ecosystem introspector docs, graph builder phases 4–5 docs, v1.4.0 changelog entry, test count updated to 864

---

## Metrics

| Metric | v1.3.2 | v1.4.0 |
|--------|--------|--------|
| Stdlib languages | 5 | 27 |
| Dependency ecosystems | 1 (Python) | 5 (Python, npm, Cargo, Go, Maven) |
| BSG interceptor plugins | 9 | 9 (enhanced) |
| Total tests | 609 | 864 |
| Review findings fixed | — | 13 (4 security, 4 bugs, 5 other) |

---

## Upgrade Guide

```bash
# Upgrade via uv (recommended)
uv tool upgrade batho

# Verify version
batho --version  # should show 1.4.0
```

Restart any running MCP clients (Claude Desktop, Cursor, Windsurf, VS Code) after upgrading.

**Full Changelog:** https://github.com/sageoz/batho/blob/main/docs-site/docs/changelog.md
**Documentation:** https://batho.sageoz.org
**PyPI:** https://pypi.org/project/batho/
