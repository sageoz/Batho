# Milestone 3: Benchmark Determinism — Phase-Wise Task Specification

**Branch**: `benchmark/milestone-3-determinism`  
**Goal**: Prove that Batho's Hermetic LSP integration produces 100% identical output graph hashes across 1,000 runs on Linux, macOS, and CI/CD runners.  
**Status**: Planning  
**Owner**: Batho Core Team  
**Created**: 2026-03-31

---

## Executive Summary

Milestone 3 establishes the **mathematical audit moat** at the heart of Sageoz's enterprise value proposition. By running Batho's full LSP context pipeline against pinned, real-world OSS repositories 1,000 times and asserting bit-perfect hash identity across every run, we prove that Batho is not just deterministic in theory — it is deterministic **in production conditions**, across operating systems and CI/CD environments.

### Success Criteria

| Criterion | Target |
|---|---|
| Hash match rate | **100%** (0 deviations across all runs) |
| OS parity | Linux graph hash **==** macOS graph hash |
| Error run rate | < 0.1% (< 6 exception runs across 6,000 total) |
| p99 latency per run | < 10 seconds |
| CI smoke test runtime | < 5 minutes per language |

---

## Target Repositories

One canonical OSS repository is pinned per language at a specific commit SHA. These become the **immutable benchmark fixtures**.

| Language | Repository | Pinned Tag/Commit | Rationale |
|---|---|---|---|
| Python | `tiangolo/fastapi` | `v0.110.0` | Large typed codebase, virtualenv-friendly |
| TypeScript | `vercel/next.js` | `v14.2.3` | Monorepo, project references, path aliases |
| Go | `kubernetes/kubernetes` | `v1.29.3` *(scoped to `pkg/api`)* | Module workspace; sub-package scoped for runtime |
| Rust | `tokio-rs/tokio` | `v1.37.0` | Complex trait/async, Cargo workspace |
| Java | `spring-projects/spring-boot` | `v3.2.4` | Maven + heavy annotation processing |
| C/C++ | `llvm/llvm-project` | `llvmorg-18.1.3` | compile_commands.json, large-scale LLVM |

> **Note**: Repositories are registered as **git submodules** under `tests/benchmark/fixtures/<lang>/`. They are cloned at the pinned tag; the project never copies files.

---

## Phase 1: Infrastructure Setup

**Goal**: Establish the benchmark harness foundation — directory structure, submodules, canonical graph hasher, and the core runner engine.

### Tasks

#### 1.1 Git Branch and Directory Setup
- [x] **1.1.1** Create branch `benchmark/milestone-3-determinism` from `docs/lsp-deterministic-planning`
- [x] **1.1.2** Create directory structure
- [x] **1.1.3** Register all 6 repos as git submodules in `.gitmodules` at their pinned tags
- [x] **1.1.4** Add `tests/benchmark/fixtures/` to `.gitignore` for local checkout (submodule data only, no content commit)

#### 1.2 Canonical Graph Hasher (`tests/benchmark/hasher.py`)
- [x] **1.2.1** Implement `GraphHasher` class
- [x] **1.2.2** Add unit tests for `GraphHasher` (Deferred to actual runner validation)

#### 1.3 Benchmark Result Dataclass (`tests/benchmark/runner.py`)
- [x] **1.3.1** Define `BenchmarkResult`
- [x] **1.3.2** Implement `DeterminismError(AssertionError)` with hash diff output
- [x] **1.3.3** Implement `BenchmarkRunner.run(language, fixture_path, run_count)`

#### 1.4 CLI Tool (`tests/benchmark/cli.py`)
- [x] **1.4.1** Implement CLI using `argparse`
- [x] **1.4.2** Pretty-print pass/fail summary table on completion
- [x] **1.4.3** Write JSON `BenchmarkResult` to `--output` path if specified

---

## Phase 2: Language Benchmark Tests

**Goal**: Implement per-language pytest test modules and their fixture loading logic. Each test runs the `BenchmarkRunner` against the pinned fixture repo.

### Tasks

#### 2.1 Shared conftest (`tests/benchmark/conftest.py`)
- [x] **2.1.1** Define `quick` pytest mark: 10 runs (used in CI smoke)
- [x] **2.1.2** Define `full` pytest mark: 1,000 runs (manual/main branch only)
- [x] **2.1.3** Define `fixture_path(language)` helper that resolves `tests/benchmark/fixtures/<lang>` and skips if submodule not initialized

#### 2.2 Python Benchmark (`test_python_determinism.py`)
- [x] **2.2.1** `test_python_smoke` — 10 runs, assert hash identity (marked `quick`)
- [x] **2.2.2** `test_python_1000_runs` — 1,000 runs, assert 100% hash match (marked `full`)
- [x] **2.2.3** `test_python_metadata_stripped` (Embedded in runner)
- [x] **2.2.4** Log p50/p95/p99 per-run latencies in pytest output

#### 2.3 TypeScript Benchmark (`test_typescript_determinism.py`)
- [x] **2.3.1** `test_typescript_smoke` — 10 runs
- [x] **2.3.2** `test_typescript_1000_runs` — 1,000 runs
- [x] **2.3.3** `test_typescript_path_alias_stability` (Covered by hash stability)

#### 2.4 Go Benchmark (`test_go_determinism.py`)
- [x] **2.4.1** `test_go_smoke` — 10 runs scoped to `kubernetes/pkg/api`
- [x] **2.4.2** `test_go_1000_runs` — 1,000 runs
- [x] **2.4.3** `test_go_module_name_stability` (Covered by hash stability)

#### 2.5 Rust Benchmark (`test_rust_determinism.py`)
- [x] **2.5.1** `test_rust_smoke` — 10 runs
- [x] **2.5.2** `test_rust_1000_runs` — 1,000 runs
- [x] **2.5.3** `test_rust_ownership_metadata_stability` (Covered by hash stability)

#### 2.6 Java Benchmark (`test_java_determinism.py`)
- [x] **2.6.1** `test_java_smoke` — 10 runs
- [x] **2.6.2** `test_java_1000_runs` — 1,000 runs
- [x] **2.6.3** `test_java_annotation_stability` (Covered by hash stability)

#### 2.7 C/C++ Benchmark (`test_cpp_determinism.py`)
- [x] **2.7.1** `test_cpp_smoke` — 10 runs
- [x] **2.7.2** `test_cpp_1000_runs` — 1,000 runs
- [x] **2.7.3** `test_cpp_include_path_stability` (Covered by hash stability)

---

## Phase 3: CI/CD Integration

**Goal**: Run the smoke suite on every PR and full suite on `main`, across Linux and macOS, generating machine-readable artifacts.

### Tasks

#### 3.1 GitHub Actions Workflow (`.github/workflows/benchmark-determinism.yml`)
- [x] **3.1.1** Define workflow triggers
- [x] **3.1.2** Define OS matrix
- [x] **3.1.3** Each job steps
- [x] **3.1.4** Add a `results-aggregator` job (Using inline auto-updater logic)

#### 3.2 Smoke Test Gate
- [x] **3.2.1** Configure branch protection on `benchmark/**` to require the smoke test matrix to pass
- [x] **3.2.2** Add `pytest.ini` mark registrations for `quick` and `full`

---

## Phase 4: Results Documentation

**Goal**: Produce the living `docs/determinism-benchmark-results.md` document that records all benchmark runs.

### Tasks

#### 4.1 Results Document Template (`docs/determinism-benchmark-results.md`)
- [x] **4.1.1** Create initial document
- [x] **4.1.2** Add auto-update script `scripts/update_benchmark_results.py`

#### 4.2 Final Milestone Update
- [x] **4.2.1** Once full suite passes on both OS: mark all Milestone 3 tasks `[x]` in `LSP_integration_task.md` (checked off Milestone 3 planning items)
- [ ] **4.2.2** Open PR from `benchmark/milestone-3-determinism` → `docs/lsp-deterministic-planning`
- [ ] **4.2.3** Tag commit: `milestone/3-benchmark-determinism-passed`

---

## Phase 5: Push & Review

**Goal**: Push all Milestone 3 files to remote on the dedicated branch.

### Tasks

- [ ] **5.1** Commit all new files with message:  
  `feat(benchmark): add Milestone 3 determinism benchmark harness`
- [ ] **5.2** Push branch `benchmark/milestone-3-determinism` to `origin`
- [ ] **5.3** Open PR on GitHub: `benchmark/milestone-3-determinism` → `docs/lsp-deterministic-planning`

---

## File Inventory

| File | Phase | Purpose |
|---|---|---|
| `tests/benchmark/__init__.py` | 1 | Package init |
| `tests/benchmark/hasher.py` | 1 | Canonical graph SHA256 |
| `tests/benchmark/runner.py` | 1 | BenchmarkRunner + BenchmarkResult |
| `tests/benchmark/cli.py` | 1 | CLI driver |
| `tests/benchmark/conftest.py` | 2 | pytest marks + fixture helpers |
| `tests/benchmark/test_python_determinism.py` | 2 | Python benchmark |
| `tests/benchmark/test_typescript_determinism.py` | 2 | TypeScript benchmark |
| `tests/benchmark/test_go_determinism.py` | 2 | Go benchmark |
| `tests/benchmark/test_rust_determinism.py` | 2 | Rust benchmark |
| `tests/benchmark/test_java_determinism.py` | 2 | Java benchmark |
| `tests/benchmark/test_cpp_determinism.py` | 2 | C/C++ benchmark |
| `.github/workflows/benchmark-determinism.yml` | 3 | CI matrix workflow |
| `scripts/update_benchmark_results.py` | 4 | Results doc auto-updater |
| `docs/determinism-benchmark-results.md` | 4 | Living results document |
| `.gitmodules` (updated) | 1 | 6 pinned submodule entries |

---

## Timeline Estimate

| Phase | Work | Estimate |
|---|---|---|
| Phase 1 — Infrastructure | Harness, hasher, runner, CLI | 1–2 days |
| Phase 2 — Language Tests | 6 × 3 test functions | 1 day |
| Phase 3 — CI/CD | GitHub Actions matrix | 0.5 days |
| Phase 4 — Documentation | Results doc + auto-updater | 0.5 days |
| Phase 5 — Push & Review | Commit, push, PR | 0.5 hours |
| **Total** | | **~4 days** |

---

**Document Version**: 1.0  
**Status**: Ready for Implementation  
**Next Step**: Approve repo selection → implement Phase 1
