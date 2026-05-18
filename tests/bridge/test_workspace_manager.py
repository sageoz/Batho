"""Tests for WorkspaceManager."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from batho.bridge.artifact_cache import ArtifactCache
from batho.bridge.models import (
    ConcurrencyConfig,
    HubConfig,
    ResidencyConfig,
    WorkspaceConfig,
    WorkspaceState,
)
from batho.bridge.workspace_handle import WorkspaceHandle
from batho.bridge.workspace_manager import WorkspaceManager
from batho.bridge.workspace_registry import WorkspaceRegistry


class TestWorkspaceManager:
    """Test WorkspaceManager functionality."""

    @pytest.fixture
    def temp_ctn(self, tmp_path):
        """Create a temporary .ctn directory."""
        ctn_dir = tmp_path / "test_repo" / ".ctn"
        ctn_dir.mkdir(parents=True)
        index_json = ctn_dir / "index.json"
        index_json.write_text('{"current_index_id": "idx1", "indexes": {"idx1": {"timestamp": "2024-01-01"}}}')
        return ctn_dir

    @pytest.fixture
    def registry(self, tmp_path):
        """Create a test registry."""
        config_path = tmp_path / "mcp.yaml"
        config_path.write_text("schema_version: 1\n")
        return WorkspaceRegistry(user_config_path=config_path)

    @pytest.fixture
    def cache(self):
        """Create a test cache."""
        return ArtifactCache(max_total_bytes=1000000, max_per_workspace_bytes=100000)

    @pytest.mark.asyncio
    async def test_start_registers_workspaces(self, registry, cache, temp_ctn):
        """Starting manager registers all workspaces."""
        ws_config = WorkspaceConfig(
            id="test-ws",
            ctn_dir=str(temp_ctn),
        )
        registry.add(ws_config)

        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )
        manager.start()

        workspaces = manager.list()
        assert len(workspaces) == 1
        assert workspaces[0].id == "test-ws"

        await manager.stop()

    @pytest.mark.asyncio
    async def test_mount_opens_workspace(self, registry, cache, temp_ctn):
        """Mounting a workspace opens resources."""
        ws_config = WorkspaceConfig(
            id="test-ws",
            ctn_dir=str(temp_ctn),
        )
        registry.add(ws_config)

        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )
        manager.start()

        handle = await manager.mount("test-ws")
        assert handle.is_ready
        assert handle.bridge is not None
        assert handle.loader is not None

        await manager.stop()

    @pytest.mark.asyncio
    async def test_unmount_closes_workspace(self, registry, cache, temp_ctn):
        """Unmounting a workspace closes resources."""
        ws_config = WorkspaceConfig(
            id="test-ws",
            ctn_dir=str(temp_ctn),
        )
        registry.add(ws_config)

        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )
        manager.start()

        await manager.mount("test-ws")
        await manager.unmount("test-ws", reason="test")

        handle = manager._handles["test-ws"]
        assert handle.state == WorkspaceState.REGISTERED

        await manager.stop()

    @pytest.mark.asyncio
    async def test_resolve_mounts_if_needed(self, registry, cache, temp_ctn):
        """Resolve mounts workspace if not already mounted."""
        ws_config = WorkspaceConfig(
            id="test-ws",
            ctn_dir=str(temp_ctn),
        )
        registry.add(ws_config)

        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )
        manager.start()

        handle = await manager.resolve("test-ws")
        assert handle.is_ready

        await manager.stop()

    @pytest.mark.asyncio
    async def test_list_returns_all_workspaces(self, registry, cache, temp_ctn):
        """List returns all registered workspaces."""
        for i in range(3):
            parent = temp_ctn.parent.parent
            ctn_dir = parent / f"repo{i}" / ".ctn"
            ctn_dir.mkdir(parents=True)
            (ctn_dir / "index.json").write_text('{"current_index_id": "idx1", "indexes": {"idx1": {}}}')
            ws_config = WorkspaceConfig(id=f"ws{i}", ctn_dir=str(ctn_dir))
            registry.add(ws_config)

        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )
        manager.start()

        workspaces = manager.list()
        assert len(workspaces) == 3

        await manager.stop()

    @pytest.mark.asyncio
    async def test_resident_returns_mounted(self, registry, cache, temp_ctn):
        """Resident returns only mounted workspaces."""
        ws_config = WorkspaceConfig(
            id="test-ws",
            ctn_dir=str(temp_ctn),
        )
        registry.add(ws_config)

        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )
        manager.start()

        resident = manager.resident()
        assert len(resident) == 0

        await manager.mount("test-ws")
        resident = manager.resident()
        assert len(resident) == 1

        await manager.stop()

    @pytest.mark.asyncio
    async def test_health_check(self, registry, cache, temp_ctn):
        """Health check returns correct status."""
        ws_config = WorkspaceConfig(
            id="test-ws",
            ctn_dir=str(temp_ctn),
        )
        registry.add(ws_config)

        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )
        manager.start()

        health = await manager.health_check("test-ws")
        assert len(health) == 1
        assert health[0].id == "test-ws"
        assert health[0].ctn_exists is True

        await manager.stop()

    @pytest.mark.asyncio
    async def test_refresh_invalidates_cache(self, registry, cache, temp_ctn):
        """Refresh invalidates workspace cache."""
        ws_config = WorkspaceConfig(
            id="test-ws",
            ctn_dir=str(temp_ctn),
        )
        registry.add(ws_config)

        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )
        manager.start()

        await manager.refresh("test-ws")

        await manager.stop()
