"""
Python Benchmark Determinism Tests.
"""
import pytest
from tests.benchmark.runner import BenchmarkRunner

@pytest.mark.asyncio
@pytest.mark.quick
async def test_python_smoke(fixture_path):
    path = fixture_path("python")
    runner = BenchmarkRunner("python", path)
    res = await runner.run(10)
    print(f"p50: {res.p50_ms}ms, p95: {res.p95_ms}ms, p99: {res.p99_ms}ms")
    assert res.deterministic, "Python 10-run smoke hash mismatch"
    assert res.error_runs == 0

@pytest.mark.asyncio
@pytest.mark.full
async def test_python_1000_runs(fixture_path):
    path = fixture_path("python")
    runner = BenchmarkRunner("python", path)
    res = await runner.run(1000)
    assert res.deterministic, "Python 1000-run full hash mismatch"
    assert res.error_runs == 0
