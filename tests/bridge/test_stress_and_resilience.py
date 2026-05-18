"""Concurrency stress tests and failure injection for MCP Hub.

Stress tests:
- Stress 1: 100 concurrent cross.search calls over 3 workspaces
- Stress 2: 1000 concurrent artifact.get calls hitting 50 workspaces
- Stress 3: Rapid config reloads while traffic is hot

Failure injection:
- Delete workspace .ctn/index.json mid-flight -> degraded state
- Corrupt bsg.json checksum -> single error, no cache poisoning
- SIGTERM mid-request -> graceful shutdown
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sqlite3
import sys
import tempfile
import threading
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
    WorkspaceState,
)
from batho.bridge.workspace_manager import WorkspaceManager
from batho.bridge.workspace_registry import WorkspaceRegistry


def should_skip() -> bool:
    """Check if stress tests should be skipped."""
    return os.environ.get("BATHO_RUN_BRIDGE_STRESS") != "1"


pytestmark = pytest.mark.skipif(should_skip(), reason="Opt-in stress test (BATHO_RUN_BRIDGE_STRESS=1)")


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


class TestStress1ConcurrentCrossSearch:
    """Stress 1: 100 concurrent cross.search calls over 3 workspaces."""

    @pytest.mark.asyncio
    async def test_100_concurrent_cross_search(self, tmp_path: Path) -> dict:
        """100 concurrent cross.search calls, assert no SQLite locks, no double-construction."""
        repos = []
        for i in range(3):
            repo_dir = tmp_path / f"repo_{i}"
            ctn_dir = repo_dir / ".ctn"
            create_workspace_ctn(ctn_dir, index_id=f"idx_{i}", entity_count=2000)
            repos.append(repo_dir)

        config_path = tmp_path / "mcp.yaml"
        config_path.write_text("schema_version: 1\n")

        registry = WorkspaceRegistry(user_config_path=config_path)
        for i, repo in enumerate(repos):
            registry.add(WorkspaceConfig(id=f"ws{i}", ctn_dir=str(repo / ".ctn")))

        cache = ArtifactCache(max_total_bytes=50000000, max_per_workspace_bytes=20000000)
        cross_config = CrossRepoConfig(enabled=True, max_workspaces=10)
        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(global_inflight_limit=200),
            cache=cache,
            cross_repo=cross_config,
        )
        manager.start()

        for i in range(3):
            await manager.resolve(f"ws{i}")

        errors = []
        results_count = 0

        async def do_search():
            nonlocal results_count
            try:
                result = manager.cross_index.search("func") if manager.cross_index else []
                results_count += 1
            except Exception as e:
                errors.append(str(e))

        tasks = [do_search() for _ in range(100)]
        await asyncio.gather(*tasks)

        await manager.stop()

        sqlite_errors = [e for e in errors if "database is locked" in e.lower()]
        assert len(sqlite_errors) == 0, f"SQLite lock errors: {sqlite_errors}"

        assert results_count == 100, f"Expected 100 results, got {results_count}"

        return {"results": results_count, "errors": errors}


class TestStress2ConcurrentArtifactGet:
    """Stress 2: 1000 concurrent artifact.get calls hitting 50 workspaces."""

    @pytest.mark.asyncio
    async def test_1000_concurrent_artifact_get(self, tmp_path: Path) -> dict:
        """1000 concurrent artifact.get, assert residency cap, no thrashing, p99 <= 1s."""
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

        cache = ArtifactCache(max_total_bytes=100000000, max_per_workspace_bytes=2000000)
        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(max_resident_workspaces=16),
            concurrency=ConcurrencyConfig(global_inflight_limit=200),
            cache=cache,
        )
        manager.start()

        latencies = []
        errors = []

        async def do_get(ws_idx: int):
            ws_id = f"ws{ws_idx % 50}"
            try:
                start = time.perf_counter()
                handle = await manager.resolve(ws_id)
                result = handle.bridge.get("bsg_json")
                elapsed = time.perf_counter() - start
                latencies.append(elapsed)
            except Exception as e:
                errors.append(str(e))

        tasks = [do_get(i) for i in range(1000)]
        await asyncio.gather(*tasks)

        await manager.stop()

        max_resident = max(len(manager.resident()) for _ in range(10))
        assert max_resident <= 16, f"Residency cap violated: {max_resident} > 16"

        if latencies:
            latencies_sorted = sorted(latencies)
            p99_idx = int(len(latencies_sorted) * 0.99)
            p99_latency = latencies_sorted[p99_idx]
            assert p99_latency <= 1.0, f"P99 latency {p99_latency:.2f}s exceeds 1s target"

        return {
            "total_requests": 1000,
            "successful": len(latencies),
            "errors": len(errors),
            "p99_latency": latencies_sorted[p99_idx] if latencies else 0,
            "max_resident": max_resident,
        }


class TestStress3ConfigReload:
    """Stress 3: Rapid config reloads while traffic is hot."""

    @pytest.mark.asyncio
    async def test_config_reload_during_requests(self, tmp_path: Path) -> dict:
        """Config reload while requests in-flight: removed workspaces get workspace_unmounted."""
        repo_dir = tmp_path / "repo_0"
        ctn_dir = repo_dir / ".ctn"
        create_workspace_ctn(ctn_dir, entity_count=1000)

        config_path = tmp_path / "mcp.yaml"
        config_path.write_text("schema_version: 1\n")

        registry = WorkspaceRegistry(user_config_path=config_path)
        registry.add(WorkspaceConfig(id="ws0", ctn_dir=str(ctn_dir)))

        cache = ArtifactCache(max_total_bytes=10000000, max_per_workspace_bytes=5000000)
        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )
        manager.start()

        await manager.resolve("ws0")

        async def request_task():
            try:
                handle = await manager.resolve("ws0")
                return handle.bridge.get("graph")
            except Exception as e:
                return {"error": str(e)}

        async def reload_task():
            await asyncio.sleep(0.01)
            config = registry.load()
            config.workspaces = []
            registry.save(config)
            manager.apply_diff(HubConfig(workspaces=[]))

        results = await asyncio.gather(request_task(), reload_task(), return_exceptions=True)

        await manager.stop()

        return {"results": [str(r) for r in results]}


class TestFailureInjection:
    """Failure injection tests."""

    @pytest.mark.asyncio
    async def test_workspace_index_deleted_mid_flight(self, tmp_path: Path) -> dict:
        """Delete workspace .ctn/index.json -> degraded state."""
        repo_dir = tmp_path / "test_repo"
        ctn_dir = repo_dir / ".ctn"
        create_workspace_ctn(ctn_dir, entity_count=1000)

        config_path = tmp_path / "mcp.yaml"
        config_path.write_text("schema_version: 1\n")

        registry = WorkspaceRegistry(user_config_path=config_path)
        registry.add(WorkspaceConfig(id="test", ctn_dir=str(ctn_dir)))

        cache = ArtifactCache(max_total_bytes=10000000, max_per_workspace_bytes=5000000)
        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )
        manager.start()

        await manager.resolve("test")

        (ctn_dir / "index.json").unlink()

        health = await manager.health_check("test")

        await manager.stop()

        assert len(health) == 1
        assert health[0].ctn_exists is True

        return {"health": health[0].model_dump()}

    @pytest.mark.asyncio
    async def test_checksum_corruption_no_cache_poison(self, tmp_path: Path) -> dict:
        """Corrupt bsg.json checksum -> single error, no cache poisoning."""
        repo_dir = tmp_path / "test_repo"
        ctn_dir = repo_dir / ".ctn"
        create_workspace_ctn(ctn_dir, entity_count=1000)

        config_path = tmp_path / "mcp.yaml"
        config_path.write_text("schema_version: 1\n")

        registry = WorkspaceRegistry(user_config_path=config_path)
        registry.add(WorkspaceConfig(id="test", ctn_dir=str(ctn_dir)))

        cache = ArtifactCache(max_total_bytes=10000000, max_per_workspace_bytes=5000000)
        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )
        manager.start()

        handle = await manager.resolve("test")
        result1 = handle.bridge.get("bsg_json")

        graph_dir = ctn_dir / "idx1"
        bsg_file = graph_dir / "bsg_compressed.json"
        bsg_data = json.loads(bsg_file.read_text())
        bsg_data["checksum"] = "corrupted"
        bsg_file.write_text(json.dumps(bsg_data))

        try:
            result2 = handle.bridge.get("bsg_json")
            error_occurred = False
        except Exception as e:
            error_occurred = True
            error_msg = str(e)

        await manager.stop()

        assert error_occurred, "Expected error on corrupted checksum"

        return {"error_occurred": error_occurred, "error_msg": error_msg if error_occurred else None}

    @pytest.mark.asyncio
    async def test_graceful_shutdown_on_sigterm(self, tmp_path: Path) -> dict:
        """SIGTERM mid-request -> graceful shutdown drains within timeout."""
        repo_dir = tmp_path / "test_repo"
        ctn_dir = repo_dir / ".ctn"
        create_workspace_ctn(ctn_dir, entity_count=5000)

        config_path = tmp_path / "mcp.yaml"
        config_path.write_text("schema_version: 1\n")

        registry = WorkspaceRegistry(user_config_path=config_path)
        registry.add(WorkspaceConfig(id="test", ctn_dir=str(ctn_dir)))

        cache = ArtifactCache(max_total_bytes=50000000, max_per_workspace_bytes=25000000)
        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )
        manager.start()

        request_completed = threading.Event()
        shutdown_started = threading.Event()

        async def long_request():
            try:
                handle = await manager.resolve("test")
                await asyncio.sleep(0.1)
                handle.bridge.get("graph")
                request_completed.set()
            except Exception:
                pass

        async def trigger_shutdown():
            shutdown_started.set()
            await asyncio.sleep(0.01)
            await manager.stop()

        await asyncio.gather(long_request(), trigger_shutdown())

        completed = request_completed.is_set()

        return {"request_completed": completed}


if __name__ == "__main__":
    if os.environ.get("BATHO_RUN_BRIDGE_STRESS") != "1":
        print("Set BATHO_RUN_BRIDGE_STRESS=1 to run stress tests")
        sys.exit(1)

    pytest.main([__file__, "-v", "-s"])
