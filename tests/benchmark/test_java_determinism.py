"""
Java Benchmark Determinism Tests.
"""
import pytest
from tests.benchmark.runner import BenchmarkRunner

@pytest.mark.asyncio
@pytest.mark.quick
async def test_java_smoke(fixture_path):
    path = fixture_path("java") / "spring-boot-project" / "spring-boot" / "src" / "main"
    if not path.exists():
        path = fixture_path("java")
        
    runner = BenchmarkRunner("java", str(path))
    res = await runner.run(10)
    print(f"p50: {res.p50_ms}ms, p95: {res.p95_ms}ms, p99: {res.p99_ms}ms")
    assert res.deterministic, "Java 10-run smoke hash mismatch"
    assert res.error_runs == 0

@pytest.mark.asyncio
@pytest.mark.full
async def test_java_1000_runs(fixture_path):
    path = fixture_path("java")
    runner = BenchmarkRunner("java", path)
    res = await runner.run(1000)
    assert res.deterministic, "Java 1000-run full hash mismatch"
    assert res.error_runs == 0
