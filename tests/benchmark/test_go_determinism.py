"""
Go Benchmark Determinism Tests.
"""
import pytest
from tests.benchmark.runner import BenchmarkRunner

@pytest.mark.asyncio
@pytest.mark.quick
async def test_go_smoke(fixture_path):
    # Benchmark against subset of kubernetes to keep it fast
    path = fixture_path("go") / "pkg" / "api"
    # Fallback to root if the directory doesn't exist
    if not path.exists():
        path = fixture_path("go")
        
    runner = BenchmarkRunner("go", str(path))
    res = await runner.run(10)
    print(f"p50: {res.p50_ms}ms, p95: {res.p95_ms}ms, p99: {res.p99_ms}ms")
    assert res.deterministic, "Go 10-run smoke hash mismatch"
    assert res.error_runs == 0

@pytest.mark.asyncio
@pytest.mark.full
async def test_go_1000_runs(fixture_path):
    path = fixture_path("go") / "pkg" / "api"
    if not path.exists():
        path = fixture_path("go")
        
    runner = BenchmarkRunner("go", str(path))
    res = await runner.run(1000)
    assert res.deterministic, "Go 1000-run full hash mismatch"
    assert res.error_runs == 0
