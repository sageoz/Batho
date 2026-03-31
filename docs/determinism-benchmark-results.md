# Determinism Benchmark Results

This living document records the results of the 1,000-run Determinism Benchmark Suite across Batho's Tier 1 language LSP adapters.

## Methodology

Batho ensures enterprise auditability and graph determinism via **content-addressed hashing**:
1. An open source codebase at a pinned release tag (`tests/benchmark/fixtures/`) is scanned 1,000 continuous times.
2. An `InMemoryGraph` is produced and canonicalised using `tests/benchmark/hasher.py`.
3. The graph iteration ignores timestamp/profiling metadata and sorts entities/relationships by ID.
4. An end-to-end `sha256` root hash is generated.
5. We assert that every single run (out of 1,000) generates an **identical hash**.

## Latest Results
<!-- RESULTS_TABLE_START -->
| Language | OS | Deterministic? | p50 latency | p99 latency | Hash |
|---|---|---|---|---|---|
<!-- RESULTS_TABLE_END -->

## Limitations

- Non-deterministic LSP fields (such as dynamic `duration_ms` or hover tooltips that embed local timestamps directly) are stripped.
- The `timestamp` property stored in entities is stripped from the canonical graph hash.
- Absolute paths are strictly constrained / validated out prior to the hashing step, relying only on workspace-relative paths.

*(This file is automatically updated by the `benchmark-determinism.yml` GitHub Actions Workflow)*
