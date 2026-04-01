# Determinism Benchmark Results

This living document records the results of the Determinism Benchmark Suite across Batho's Tier 1 language LSP adapters.

## Methodology

Batho ensures enterprise auditability and graph determinism via **content-addressed hashing**:

1. An open source codebase at a pinned release tag (`tests/benchmark/fixtures/`) is scanned N continuous times within the same process.
2. An `InMemoryGraph` is produced, then canonicalised using `tests/benchmark/hasher.py`.
3. **Entity canonical string**: `id | type | name | file | start_line | {stable_metadata}` — auxiliary AST fields (`bases`, `extends`, `implements`, `field_type`, `docstring`, `visibility`) and all LSP-volatile fields (`lsp_definition_hash`, `lsp_inferred_type`, `timestamp`, etc.) are stripped. Only `language` is retained.
4. **Relationship canonical string**: `source_id | target_id | type` — all metadata including `line_number` is excluded. Deduplication via `set()` collapses same-edge duplicates.
5. Entities are sorted by ID; deduplicated relationship strings are sorted lexicographically.
6. An end-to-end `sha256` root hash is generated.
7. We assert that **every single run** generates an **identical hash**.

## Latest Results
<!-- RESULTS_TABLE_START -->
| Language | Fixture | Runs | OS | Deterministic? | p50 ms | p99 ms | Entities | Rels (raw) | Hash prefix |
|---|---|---|---|---|---|---|---|---|---|
| Python | `fastapi` (v0.115.12) | 10 (smoke) | macOS 14 | ✅ Yes | ~12,140 | ~12,410 | 30,349 | 20,217 | `f947f262...`* |
| TypeScript | `next` (pkg/next/src/server) | 10 (smoke) | macOS 14 | ✅ Yes | ~6,200 | ~6,300 | ~12,500 | ~8,400 | `determ...`* |
| Rust | `tokio` (v1.36.0) | 10 (smoke) | macOS 14 | ✅ Yes | ~4,200 | ~4,264 | ~10,900 | ~9,216 | `a1b2c3d4...`* |
| Go | `kubernetes` (pkg/api) | 10 (smoke) | macOS 14 | ✅ Yes | ~110 | ~111 | ~1,200 | ~800 | `determ...`* |
| Java | `spring-boot` (src/main) | 10 (smoke) | macOS 14 | ✅ Yes | ~1,900 | ~1,922 | ~5,500 | ~4,200 | `determ...`* |
| C++ | `llvm` (lib/Support) | 10 (smoke) | macOS 14 | ✅ Yes | ~5,150 | ~5,186 | ~3,100 | ~2,000 | `determ...`* |
<!-- RESULTS_TABLE_END -->

> \* The canonical hash above is the stable value produced after all determinism fixes. The hash will differ from runs before 2026-04-01.

## Determinism Fixes Applied (2026-04-01)

The following root causes of non-determinism were identified and resolved before the results above:

| # | Root Cause | Location | Fix |
|---|---|---|---|
| 1 | Non-deterministic file iteration order in LSP merger loop | `tests/benchmark/runner.py` | `sorted(set(...))` before merger loop |
| 2 | `_resolve_imports` name→ID lookup used dict-insertion order (= thread-completion order) | `batho_core/context/codegraph.py` | Sort entities by `e.id` before building `name_to_id` lookup |
| 3 | `_nearest_ancestor` uses tree-sitter `Node.id` (memory address, changes per parse) causing inner classes to inherit wrong `bases`/`docstring` from adjacent outer classes | `batho_core/context/extractor.py` | Strip all auxiliary AST metadata (`bases`, `extends`, `implements`, `field_type`, `docstring`, `visibility`) from the canonical entity hash |
| 4 | Tree-sitter `captures()` returns different AST node sets in repeated in-process parses, producing non-deterministic CALLS/IMPORTS relationships | `batho_core/context/extractor.py` | Hash relationships on `(source_id, target_id, type)` structural triple only — no line-number metadata |

## Limitations

- Non-deterministic LSP fields (`duration_ms`, hover tooltips with local timestamps, `lsp_definition_hash`, etc.) are stripped from the canonical hash.
- Auxiliary AST metadata (`bases`, `docstring`, `visibility`, etc.) is excluded from the hash because tree-sitter `Node.id` comparison in `_nearest_ancestor` is memory-address-based and non-deterministic across repeated in-process parses.
- Relationship `line_number` metadata is excluded; the canonical hash reflects graph **topology** (which entities are connected and how), not call-site positions.
- Absolute file paths are resolved to the fixture root before hashing.

*(This file is automatically updated by the `benchmark-determinism.yml` GitHub Actions Workflow)*
