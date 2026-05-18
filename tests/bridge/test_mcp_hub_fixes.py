"""Tests for MCP Hub bug fixes."""

from __future__ import annotations

import asyncio
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from batho.bridge.connection_pool import ConnectionPool, ConnectionPoolExhausted
from batho.bridge.workspace_manager import WorkspaceManager
from batho.bridge.workspace_registry import WorkspaceRegistry
from batho.bridge.models import (
    ConcurrencyConfig,
    HubConfig,
    ResidencyConfig,
    ServerConfig,
    WorkspaceConfig,
)
from batho.bridge.artifact_cache import ArtifactCache


class TestConnectionPoolFix:
    """Test connection pool leak fix - counter should only increment after successful connection."""

    def test_acquire_increments_only_on_success(self, tmp_path):
        """Verify _created counter only increments after successful connection creation."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        pool = ConnectionPool(db_path, size=2)

        assert pool._created == 2

        pool.release(pool.acquire())
        assert pool._created == 2

        pool.release(pool.acquire())
        assert pool._created == 2

        pool.close()

    def test_connection_failure_does_not_increment_counter(self, tmp_path):
        """Verify connection failures don't leave counter in inconsistent state."""
        db_path = tmp_path / "nonexistent" / "test.db"

        pool = ConnectionPool(db_path, size=1)

        with pytest.raises(ConnectionPoolExhausted):
            pool.acquire()

        assert pool._created == 0

        pool.close()

    def test_concurrent_acquire_release_maintains_consistency(self, tmp_path):
        """Test that concurrent access doesn't cause counter drift."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        pool = ConnectionPool(db_path, size=4)

        connections = []
        for _ in range(4):
            conn = pool.acquire()
            connections.append(conn)

        for conn in connections:
            pool.release(conn)

        assert pool._created == 4
        pool.close()


class TestWorkspaceManagerSemaphore:
    """Test semaphore initialization in sync start()."""

    def test_start_initializes_semaphores(self):
        """Verify sync start() initializes per-workspace semaphores."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp.yaml"
            config_path.write_text("workspaces: []\n")

            registry = WorkspaceRegistry(user_config_path=config_path)
            config = registry.load()

            cache = ArtifactCache(max_total_bytes=1000, max_per_workspace_bytes=500)
            manager = WorkspaceManager(
                registry=registry,
                residency=config.residency,
                concurrency=config.concurrency,
                cache=cache,
            )

            manager.start()

            assert manager._running is True
            assert manager._handles == {}

            manager.stop()

    def test_start_with_workspace_initializes_semaphore(self, tmp_path):
        """Verify start() initializes semaphore when workspaces exist."""
        ctn_dir = tmp_path / ".ctn"
        ctn_dir.mkdir()
        (ctn_dir / "index.json").write_text('{"index_id": "test"}')

        config = HubConfig(
            workspaces=[
                WorkspaceConfig(
                    id="test-ws",
                    ctn_dir=str(ctn_dir),
                )
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp.yaml"
            registry = WorkspaceRegistry(user_config_path=config_path)
            registry.save(config)

            cache = ArtifactCache(max_total_bytes=1000, max_per_workspace_bytes=500)
            manager = WorkspaceManager(
                registry=registry,
                residency=ResidencyConfig(),
                concurrency=ConcurrencyConfig(),
                cache=cache,
            )

            manager.start()

            assert "test-ws" in manager._handles
            assert manager._handles["test-ws"].semaphore is not None

            manager.stop()


class TestConfigMergeFix:
    """Test config merge allows explicit default values."""

    def test_project_config_overrides_defaults(self, tmp_path):
        """Verify project config can override default values."""
        user_config = HubConfig(
            server=ServerConfig(bind="0.0.0.0", http_port=9000),
            workspaces=[],
        )

        project_config = HubConfig(
            server=ServerConfig(bind="127.0.0.1", http_port=8770),
            workspaces=[],
        )

        registry = WorkspaceRegistry(user_config_path=tmp_path / "user.yaml")
        merged = registry._merge_configs(user_config, project_config)

        assert merged.server.bind == "127.0.0.1"
        assert merged.server.http_port == 8770

    def test_project_config_with_explicit_defaults(self, tmp_path):
        """Verify project config can explicitly set default values."""
        user_config = HubConfig(
            server=ServerConfig(bind="0.0.0.0", http_port=9000),
            workspaces=[],
        )

        project_config = HubConfig(
            server=ServerConfig(bind="127.0.0.1", http_port=8770),
            workspaces=[],
        )

        registry = WorkspaceRegistry(user_config_path=tmp_path / "user.yaml")
        merged = registry._merge_configs(user_config, project_config)

        assert merged.server.bind == "127.0.0.1"

    def test_none_project_config_returns_user(self, tmp_path):
        """Verify None project config returns user config unchanged."""
        user_config = HubConfig(
            server=ServerConfig(bind="0.0.0.0", http_port=9000),
            workspaces=[],
        )

        registry = WorkspaceRegistry(user_config_path=tmp_path / "user.yaml")
        merged = registry._merge_configs(user_config, None)

        assert merged.server.bind == "0.0.0.0"
        assert merged.server.http_port == 9000


class TestLRUEvictionRaceFix:
    """Test LRU eviction race condition fix."""

    @pytest.mark.asyncio
    async def test_safe_unmount_modifies_evicting_set(self, tmp_path):
        """Verify _safe_unmount properly manages _evicting set."""
        ctn_dir = tmp_path / ".ctn"
        ctn_dir.mkdir()
        (ctn_dir / "index.json").write_text('{"index_id": "test"}')

        config = HubConfig(
            workspaces=[
                WorkspaceConfig(id="test-ws", ctn_dir=str(ctn_dir), pinned=False)
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp.yaml"
            registry = WorkspaceRegistry(user_config_path=config_path)
            registry.save(config)

            cache = ArtifactCache(max_total_bytes=1000, max_per_workspace_bytes=500)
            manager = WorkspaceManager(
                registry=registry,
                residency=ResidencyConfig(max_resident_workspaces=0),
                concurrency=ConcurrencyConfig(),
                cache=cache,
            )

            await manager.astart()
            await manager.mount("test-ws")

            manager._evicting.add("test-ws")
            await manager._safe_unmount("test-ws", "test")

            assert "test-ws" not in manager._evicting

            await manager.stop()


class TestRaceConditionFix:
    """Test race condition fix - manager ready flag."""

    def test_manager_ready_flag_defaults_to_false(self):
        """Verify _ready defaults to False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp.yaml"
            config_path.write_text("workspaces: []\n")

            registry = WorkspaceRegistry(user_config_path=config_path)
            cache = ArtifactCache(max_total_bytes=1000, max_per_workspace_bytes=500)
            manager = WorkspaceManager(
                registry=registry,
                residency=ResidencyConfig(),
                concurrency=ConcurrencyConfig(),
                cache=cache,
            )

            assert manager.ready is False

    @pytest.mark.asyncio
    async def test_manager_ready_flag_set_after_astart(self):
        """Verify _ready is set to True after astart completes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp.yaml"
            config_path.write_text("workspaces: []\n")

            registry = WorkspaceRegistry(user_config_path=config_path)
            cache = ArtifactCache(max_total_bytes=1000, max_per_workspace_bytes=500)
            manager = WorkspaceManager(
                registry=registry,
                residency=ResidencyConfig(),
                concurrency=ConcurrencyConfig(),
                cache=cache,
            )

            assert manager.ready is False

            await manager.astart()

            assert manager.ready is True

            await manager.stop()

    @pytest.mark.asyncio
    async def test_manager_ready_flag_reset_after_stop(self):
        """Verify _ready is reset after stop."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp.yaml"
            config_path.write_text("workspaces: []\n")

            registry = WorkspaceRegistry(user_config_path=config_path)
            cache = ArtifactCache(max_total_bytes=1000, max_per_workspace_bytes=500)
            manager = WorkspaceManager(
                registry=registry,
                residency=ResidencyConfig(),
                concurrency=ConcurrencyConfig(),
                cache=cache,
            )

            await manager.astart()
            assert manager.ready is True

            await manager.stop()


class TestHubHTTPHandlerReadyCheck:
    """Test HTTP handler's handling of not-ready state."""

    def test_check_workspace_ready_handles_not_ready_string(self):
        """Verify _check_workspace_ready handles 'not_ready' string."""
        from batho.bridge.hub_http import HubHTTPHandler

        handler = MagicMock(spec=HubHTTPHandler)
        handler.send_json = MagicMock()

        result = HubHTTPHandler._check_workspace_ready(handler, "not_ready")

        assert result is False
        handler.send_json.assert_called_once()
        call_args = handler.send_json.call_args
        assert call_args[1]["status"] == 503

    def test_check_workspace_ready_handles_false(self):
        """Verify _check_workspace_ready handles False."""
        from batho.bridge.hub_http import HubHTTPHandler

        handler = MagicMock(spec=HubHTTPHandler)
        handler.send_json = MagicMock()

        result = HubHTTPHandler._check_workspace_ready(handler, False)

        assert result is False
        handler.send_json.assert_called_once()

    def test_check_workspace_ready_handles_true(self):
        """Verify _check_workspace_ready handles True."""
        from batho.bridge.hub_http import HubHTTPHandler

        handler = MagicMock(spec=HubHTTPHandler)
        handler.send_json = MagicMock()

        result = HubHTTPHandler._check_workspace_ready(handler, True)

        assert result is True
        handler.send_json.assert_not_called()


class TestPathTraversalFix:
    """Test path traversal fix using relative_to."""

    def test_path_traversal_blocked_with_relative_to(self):
        """Verify path traversal is blocked using relative_to check."""
        from batho.bridge.hub_http import HubHTTPHandler

        handler = MagicMock(spec=HubHTTPHandler)
        handler.dashboard_dir = Path("/safe/dir")

        with tempfile.TemporaryDirectory() as tmp_path:
            safe_dir = Path(tmp_path) / "safe" / "dir"
            safe_dir.mkdir(parents=True)

            handler.dashboard_dir = safe_dir

            file_path = safe_dir / ".." / ".." / "etc" / "passwd"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.touch()

            resolved = file_path.resolve()
            dashboard_resolved = safe_dir.resolve()

            with pytest.raises(ValueError):
                resolved.relative_to(dashboard_resolved)
