"""
Rust Benchmark Determinism Tests.
"""
import pytest
from tests.benchmark.runner import BenchmarkRunner

@pytest.mark.asyncio
@pytest.mark.quick
async def test_rust_smoke(fixture_path):
    path = fixture_path("rust")
    runner = BenchmarkRunner("rust", path)
    res = await runner.run(10)
    print(f"p50: {res.p50_ms}ms, p95: {res.p95_ms}ms, p99: {res.p99_ms}ms")
    assert res.deterministic, "Rust 10-run smoke hash mismatch"
    assert res.error_runs == 0

@pytest.mark.asyncio
@pytest.mark.full
async def test_rust_1000_runs(fixture_path):
    path = fixture_path("rust")
    runner = BenchmarkRunner("rust", path)
    res = await runner.run(1000)
    assert res.deterministic, "Rust 1000-run full hash mismatch"
    assert res.error_runs == 0
