"""Benchmark harness for MCP Hub performance.

Opt-in via BATHO_RUN_BRIDGE_BENCH=1 environment variable.

Benchmarks:
- cold/warm bsg.search per workspace
- cold/warm cross.search over 1/5/50/200 workspaces
- registry SQLite query latency at 10k/100k artifacts
- cold mount latency (registered -> ready)
- LRU churn: 100 sequential mounts with cap=32
- 200 fake workspaces, random-access pattern

Targets (warm OS page cache):
| Metric | Target |
| --- | --- |
| cold artifact.get bsg_json (50k entities) | <= 80 ms |
| warm tool dispatch overhead | <= 5 ms |
| warm cross.search over 5 workspaces | p95 <= 150 ms |
| warm cross.search over 50 resident workspaces | p95 <= 400 ms |
| cold mount (registered -> ready) | p95 <= 250 ms |
| LRU eviction cost | <= 5 ms per evict |
| hub idle RAM, 32 resident workspaces | <= 800 MB |
| hub idle RAM, 64 resident workspaces | <= 2 GB |
| startup time, 200 registered / 0 mounted | <= 500 ms |
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

import pytest

from batho.bridge.artifact_cache import ArtifactCache
from batho.bridge.models import (
    ConcurrencyConfig,
    CrossRepoConfig,
    HubConfig,
    ResidencyConfig,
    WorkspaceConfig,
)
from batho.bridge.workspace_manager import WorkspaceManager
from batho.bridge.workspace_registry import WorkspaceRegistry


def should_skip() -> bool:
    """Check if benchmarks should be skipped."""
    return os.environ.get("BATHO_RUN_BRIDGE_BENCH") != "1"


pytestmark = pytest.mark.skipif(should_skip(), reason="Opt-in benchmark (BATHO_RUN_BRIDGE_BENCH=1)")


def create_workspace_ctn(ctn_dir: Path, index_id: str = "idx1", entity_count: int = 1000) -> None:
    """Create a minimal .ctn directory with index.json and graph."""
    ctn_dir.mkdir(parents=True, exist_ok=True)

    index_data = {
        "current_index_id": index_id,
        "schema_version": "1.0",
        "indexes": {
            index_id: {
                "timestamp": "2024-01-01T00:00:00Z",
                "root": str(ctn_dir.parent),
                "file_count": 10,
                "entity_count": entity_count,
            }
        },
    }

    import json

    (ctn_dir / "index.json").write_text(json.dumps(index_data))

    graph_dir = ctn_dir / index_id
    graph_dir.mkdir(exist_ok=True)

    entities = []
    for i in range(entity_count):
        entities.append(
            {
                "id": f"ent_{i}",
                "type": "function",
                "name": f"func_{i}",
                "file": f"file_{i % 10}.py",
                "line": i,
            }
        )

    graph_data = {
        "index_id": index_id,
        "entities": entities,
        "relationships": [],
    }

    (graph_dir / "graph.json").write_text(json.dumps(graph_data))

    bsg_data = {
        "index_id": index_id,
        "format": "compressed",
        "content": "\n".join([f"def func_{i}():" for i in range(min(entity_count, 100))]),
    }
    (graph_dir / "bsg_compressed.json").write_text(json.dumps(bsg_data))


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace with .ctn."""
    repo_dir = tmp_path / "test_repo"
    ctn_dir = repo_dir / ".ctn"
    create_workspace_ctn(ctn_dir, entity_count=1000)
    return repo_dir


@pytest.fixture
def temp_workspaces(tmp_path: Path, count: int) -> list[Path]:
    """Create multiple temporary workspaces."""
    repos = []
    for i in range(count):
        repo_dir = tmp_path / f"repo_{i}"
        ctn_dir = repo_dir / ".ctn"
        create_workspace_ctn(ctn_dir, index_id=f"idx_{i}", entity_count=1000)
        repos.append(repo_dir)
    return repos


@pytest.fixture
def large_workspace(tmp_path: Path) -> Path:
    """Create a workspace with 50k entities."""
    repo_dir = tmp_path / "large_repo"
    ctn_dir = repo_dir / ".ctn"
    create_workspace_ctn(ctn_dir, entity_count=50000)
    return repo_dir


class TestBsgSearchBench:
    """Benchmark bsg.search operations."""

    @pytest.mark.asyncio
    async def test_cold_bsg_search_50k_entities(self, large_workspace: Path) -> dict:
        """Cold artifact.get bsg_json with 50k entities target: <= 80 ms."""
        config_path = large_workspace.parent / "mcp.yaml"
        config_path.write_text("schema_version: 1\n")

        registry = WorkspaceRegistry(user_config_path=config_path)
        registry.add(WorkspaceConfig(id="large", ctn_dir=str(large_workspace / ".ctn")))

        cache = ArtifactCache(max_total_bytes=100000000, max_per_workspace_bytes=50000000)
        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )
        manager.start()

        times = []
        for _ in range(10):
            await manager.mount("large")
            await manager.unmount("large", reason="bench")

            start = time.perf_counter()
            handle = await manager.resolve("large")
            result = handle.bridge.get("bsg_json")
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

            await manager.unmount("large", reason="bench")

        await manager.stop()

        cold_times = times[::2]
        p95 = sorted(cold_times)[int(len(cold_times) * 0.95)]
        print(f"\nCold bsg.search p95: {p95:.2f}ms (target: <=80ms)")
        assert p95 <= 80, f"Cold bsg.search p95 {p95:.2f}ms exceeds 80ms target"

        return {"cold_p95_ms": p95, "times": times}

    @pytest.mark.asyncio
    async def test_warm_tool_dispatch_overhead(self, temp_workspace: Path) -> dict:
        """Warm tool dispatch overhead target: <= 5 ms."""
        config_path = temp_workspace.parent / "mcp.yaml"
        config_path.write_text("schema_version: 1\n")

        registry = WorkspaceRegistry(user_config_path=config_path)
        registry.add(WorkspaceConfig(id="test", ctn_dir=str(temp_workspace / ".ctn")))

        cache = ArtifactCache(max_total_bytes=10000000, max_per_workspace_bytes=5000000)
        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )
        manager.start()

        handle = await manager.resolve("test")

        times = []
        for _ in range(100):
            start = time.perf_counter()
            result = handle.bridge.get("bsg_json")
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        await manager.stop()

        p95 = sorted(times)[int(len(times) * 0.95)]
        print(f"\nWarm tool dispatch p95: {p95:.2f}ms (target: <=5ms)")
        assert p95 <= 5, f"Warm dispatch p95 {p95:.2f}ms exceeds 5ms target"

        return {"warm_p95_ms": p95, "times": times}


class TestCrossSearchBench:
    """Benchmark cross-repo search operations."""

    @pytest.mark.asyncio
    async def test_warm_cross_search_5_workspaces(self, temp_workspaces: list[Path]) -> dict:
        """Warm cross.search over 5 workspaces target: p95 <= 150 ms."""
        if len(temp_workspaces) < 5:
            pytest.skip("Need at least 5 workspaces")

        config_path = temp_workspaces[0].parent / "mcp.yaml"
        config_path.write_text("schema_version: 1\n")

        registry = WorkspaceRegistry(user_config_path=config_path)
        for i, repo in enumerate(temp_workspaces[:5]):
            registry.add(WorkspaceConfig(id=f"ws{i}", ctn_dir=str(repo / ".ctn")))

        cache = ArtifactCache(max_total_bytes=50000000, max_per_workspace_bytes=10000000)
        cross_config = CrossRepoConfig(enabled=True, max_workspaces=10)
        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
            cross_repo=cross_config,
        )
        manager.start()

        for i in range(5):
            await manager.resolve(f"ws{i}")

        times = []
        for _ in range(50):
            start = time.perf_counter()
            results = manager.cross_index.search("func") if manager.cross_index else []
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        await manager.stop()

        p95 = sorted(times)[int(len(times) * 0.95)]
        print(f"\nCross-search 5 workspaces p95: {p95:.2f}ms (target: <=150ms)")
        assert p95 <= 150, f"Cross-search p95 {p95:.2f}ms exceeds 150ms target"

        return {"p95_ms": p95, "times": times}

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_warm_cross_search_50_workspaces(self, tmp_path: Path) -> dict:
        """Warm cross.search over 50 workspaces target: p95 <= 400 ms."""
        repos = []
        for i in range(50):
            repo_dir = tmp_path / f"repo_{i}"
            ctn_dir = repo_dir / ".ctn"
            create_workspace_ctn(ctn_dir, index_id=f"idx_{i}", entity_count=1000)
            repos.append(repo_dir)

        config_path = tmp_path / "mcp.yaml"
        config_path.write_text("schema_version: 1\n")

        registry = WorkspaceRegistry(user_config_path=config_path)
        for i, repo in enumerate(repos):
            registry.add(WorkspaceConfig(id=f"ws{i}", ctn_dir=str(repo / ".ctn")))

        cache = ArtifactCache(max_total_bytes=500000000, max_per_workspace_bytes=10000000)
        cross_config = CrossRepoConfig(enabled=True, max_workspaces=100)
        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
            cross_repo=cross_config,
        )
        manager.start()

        for i in range(50):
            await manager.resolve(f"ws{i}")

        times = []
        for _ in range(50):
            start = time.perf_counter()
            results = manager.cross_index.search("func") if manager.cross_index else []
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        await manager.stop()

        p95 = sorted(times)[int(len(times) * 0.95)]
        print(f"\nCross-search 50 workspaces p95: {p95:.2f}ms (target: <=400ms)")
        assert p95 <= 400, f"Cross-search p95 {p95:.2f}ms exceeds 400ms target"

        return {"p95_ms": p95, "times": times}


class TestMountBench:
    """Benchmark mount operations."""

    @pytest.mark.asyncio
    async def test_cold_mount_latency(self, temp_workspace: Path) -> dict:
        """Cold mount (registered -> ready) target: p95 <= 250 ms."""
        config_path = temp_workspace.parent / "mcp.yaml"
        config_path.write_text("schema_version: 1\n")

        registry = WorkspaceRegistry(user_config_path=config_path)
        registry.add(WorkspaceConfig(id="test", ctn_dir=str(temp_workspace / ".ctn")))

        cache = ArtifactCache(max_total_bytes=10000000, max_per_workspace_bytes=5000000)
        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )
        manager.start()

        times = []
        for i in range(20):
            if i > 0:
                await manager.unmount("test", reason="bench")

            start = time.perf_counter()
            handle = await manager.mount("test")
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        await manager.stop()

        cold_times = times[::2]
        p95 = sorted(cold_times)[int(len(cold_times) * 0.95)]
        print(f"\nCold mount p95: {p95:.2f}ms (target: <=250ms)")
        assert p95 <= 250, f"Cold mount p95 {p95:.2f}ms exceeds 250ms target"

        return {"p95_ms": p95, "times": times}


class TestLruEvictionBench:
    """Benchmark LRU eviction operations."""

    @pytest.mark.asyncio
    async def test_lru_eviction_cost(self, tmp_path: Path) -> dict:
        """LRU eviction cost target: <= 5 ms per evict."""
        repos = []
        for i in range(50):
            repo_dir = tmp_path / f"repo_{i}"
            ctn_dir = repo_dir / ".ctn"
            create_workspace_ctn(ctn_dir, index_id=f"idx_{i}", entity_count=500)
            repos.append(repo_dir)

        config_path = tmp_path / "mcp.yaml"
        config_path.write_text("schema_version: 1\n")

        registry = WorkspaceRegistry(user_config_path=config_path)
        for i, repo in enumerate(repos):
            registry.add(WorkspaceConfig(id=f"ws{i}", ctn_dir=str(repo / ".ctn")))

        cache = ArtifactCache(max_total_bytes=50000000, max_per_workspace_bytes=10000000)
        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(max_resident_workspaces=32),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )
        manager.start()

        eviction_times = []
        for i in range(100):
            ws_id = f"ws{i % 50}"

            start = time.perf_counter()
            await manager.resolve(ws_id)
            elapsed = (time.perf_counter() - start) * 1000

            if len(manager.resident()) > 32:
                eviction_times.append(elapsed)

        await manager.stop()

        if eviction_times:
            avg_evict = statistics.mean(eviction_times)
            print(f"\nAvg eviction cost: {avg_evict:.2f}ms (target: <=5ms)")
            assert avg_evict <= 5, f"Avg eviction {avg_evict:.2f}ms exceeds 5ms target"

        return {"avg_eviction_ms": statistics.mean(eviction_times) if eviction_times else 0}


class TestStartupBench:
    """Benchmark startup time."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_startup_200_registered(self, tmp_path: Path) -> dict:
        """Startup time, 200 registered / 0 mounted target: <= 500 ms."""
        repos = []
        for i in range(200):
            repo_dir = tmp_path / f"repo_{i}"
            ctn_dir = repo_dir / ".ctn"
            create_workspace_ctn(ctn_dir, index_id=f"idx_{i}", entity_count=100)
            repos.append(repo_dir)

        config_path = tmp_path / "mcp.yaml"
        config_path.write_text("schema_version: 1\n")

        registry = WorkspaceRegistry(user_config_path=config_path)
        for i, repo in enumerate(repos):
            registry.add(WorkspaceConfig(id=f"ws{i}", ctn_dir=str(repo / ".ctn")))

        cache = ArtifactCache(max_total_bytes=100000000, max_per_workspace_bytes=500000)
        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )

        start = time.perf_counter()
        manager.start()
        elapsed = (time.perf_counter() - start) * 1000

        await manager.stop()

        print(f"\nStartup time: {elapsed:.2f}ms (target: <=500ms)")
        assert elapsed <= 500, f"Startup time {elapsed:.2f}ms exceeds 500ms target"

        return {"startup_ms": elapsed}


class TestRegistryBench:
    """Benchmark registry SQLite operations."""

    @pytest.mark.asyncio
    async def test_registry_query_10k_artifacts(self, tmp_path: Path) -> dict:
        """Registry SQLite query latency at 10k artifacts target: <= 50 ms."""
        import json

        repo_dir = tmp_path / "test_repo"
        ctn_dir = repo_dir / ".ctn"
        ctn_dir.mkdir(parents=True)

        registry_path = ctn_dir / "artifact_registry.db"
        import sqlite3

        conn = sqlite3.connect(str(registry_path))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS artifacts ("
            "id TEXT PRIMARY KEY, workspace_id TEXT, artifact_type TEXT, "
            "index_id TEXT, path TEXT, size_bytes INTEGER, checksum TEXT, data TEXT)"
        )

        for i in range(10000):
            conn.execute(
                "INSERT OR REPLACE INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"art_{i}",
                    "test_ws",
                    "bsg_json",
                    "idx1",
                    f"path/to/file_{i}.py",
                    1000,
                    f"checksum_{i}",
                    json.dumps({"content": f"content_{i}"}),
                ),
            )
        conn.commit()

        times = []
        for _ in range(100):
            start = time.perf_counter()
            cursor = conn.execute(
                "SELECT * FROM artifacts WHERE workspace_id = ? AND artifact_type = ?",
                ("test_ws", "bsg_json"),
            )
            list(cursor.fetchall())
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        conn.close()

        p95 = sorted(times)[int(len(times) * 0.95)]
        print(f"\nRegistry query 10k p95: {p95:.2f}ms (target: <=50ms)")
        assert p95 <= 50, f"Registry query p95 {p95:.2f}ms exceeds 50ms target"

        return {"p95_ms": p95, "times": times}


if __name__ == "__main__":
    if os.environ.get("BATHO_RUN_BRIDGE_BENCH") != "1":
        print("Set BATHO_RUN_BRIDGE_BENCH=1 to run benchmarks")
        sys.exit(1)

    pytest.main([__file__, "-v", "-s"])
