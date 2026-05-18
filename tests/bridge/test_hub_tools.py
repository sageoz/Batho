"""Tests for MCP hub tools."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from batho.bridge.artifact_cache import ArtifactCache
from batho.bridge.hub import create_hub
from batho.bridge.models import (
    ConcurrencyConfig,
    HubConfig,
    ResidencyConfig,
    WorkspaceConfig,
)
from batho.bridge.workspace_manager import WorkspaceManager
from batho.bridge.workspace_registry import WorkspaceRegistry


class TestHubTools:
    """Test MCP hub tool functions."""

    @pytest.fixture
    def temp_ctn(self, tmp_path):
        """Create a temporary .ctn directory with index.json."""
        ctn_dir = tmp_path / "test_repo" / ".ctn"
        ctn_dir.mkdir(parents=True)
        index_json = ctn_dir / "index.json"
        index_json.write_text(
            json.dumps(
                {
                    "current_index_id": "idx1",
                    "indexes": {
                        "idx1": {
                            "timestamp": "2024-01-01T00:00:00Z",
                            "root": str(ctn_dir),
                            "file_count": 10,
                            "entity_count": 50,
                        }
                    },
                }
            )
        )
        return ctn_dir

    @pytest.fixture
    def registry(self, tmp_path, temp_ctn):
        """Create a test registry with a workspace."""
        config_path = tmp_path / "mcp.yaml"
        registry = WorkspaceRegistry(user_config_path=config_path)
        ws_config = WorkspaceConfig(id="test-ws", ctn_dir=str(temp_ctn))
        registry.add(ws_config)
        return registry

    @pytest.fixture
    def manager(self, registry):
        """Create a test workspace manager."""
        cache = ArtifactCache(
            max_total_bytes=1000000, max_per_workspace_bytes=100000
        )
        manager = WorkspaceManager(
            registry=registry,
            residency=ResidencyConfig(),
            concurrency=ConcurrencyConfig(),
            cache=cache,
        )
        manager.start()
        yield manager
        import asyncio

        asyncio.run(manager.stop())

    @pytest.fixture
    def hub(self, manager):
        """Create a test MCP hub."""
        return create_hub(manager)

    def test_workspace_list_tool(self, hub):
        """Test workspace_list tool returns registered workspaces."""
        tool = None
        for t in hub._tool_manager._tools.values():
            if hasattr(t, "name") and t.name == "workspace_list":
                tool = t
                break
        assert tool is not None, "workspace_list tool not found"

    def test_workspace_health_tool(self, hub):
        """Test workspace_health tool exists."""
        tool = None
        for t in hub._tool_manager._tools.values():
            if hasattr(t, "name") and t.name == "workspace_health":
                tool = t
                break
        assert tool is not None, "workspace_health tool not found"

    def test_index_list_tool(self, hub):
        """Test index_list tool exists."""
        tool = None
        for t in hub._tool_manager._tools.values():
            if hasattr(t, "name") and t.name == "index_list":
                tool = t
                break
        assert tool is not None, "index_list tool not found"

    def test_artifact_get_tool(self, hub):
        """Test artifact_get tool exists."""
        tool = None
        for t in hub._tool_manager._tools.values():
            if hasattr(t, "name") and t.name == "artifact_get":
                tool = t
                break
        assert tool is not None, "artifact_get tool not found"

    def test_bsg_search_tool(self, hub):
        """Test bsg_search tool exists."""
        tool = None
        for t in hub._tool_manager._tools.values():
            if hasattr(t, "name") and t.name == "bsg_search":
                tool = t
                break
        assert tool is not None, "bsg_search tool not found"

    def test_file_read_tool(self, hub):
        """Test file_read tool exists."""
        tool = None
        for t in hub._tool_manager._tools.values():
            if hasattr(t, "name") and t.name == "file_read":
                tool = t
                break
        assert tool is not None, "file_read tool not found"

    def test_cross_search_tool(self, hub):
        """Test cross_search tool exists."""
        tool = None
        for t in hub._tool_manager._tools.values():
            if hasattr(t, "name") and t.name == "cross_search":
                tool = t
                break
        assert tool is not None, "cross_search tool not found"

    def test_cross_symbols_tool(self, hub):
        """Test cross_symbols tool exists."""
        tool = None
        for t in hub._tool_manager._tools.values():
            if hasattr(t, "name") and t.name == "cross_symbols":
                tool = t
                break
        assert tool is not None, "cross_symbols tool not found"

    def test_hub_has_expected_tools(self, hub):
        """Test that hub has all expected tools."""
        tool_names = {t.name for t in hub._tool_manager._tools.values()}
        expected = {
            "workspace_list",
            "workspace_health",
            "workspace_stats",
            "index_list",
            "index_get",
            "artifact_list",
            "artifact_get",
            "artifact_get_by_path",
            "artifact_search",
            "file_read",
            "file_list",
            "bsg_get",
            "bsg_search",
            "context_overview",
            "context_files",
            "graph_get",
            "patches_list",
            "patches_get",
            "snapshot_diff",
            "cross_search",
            "cross_symbols",
            "cross_dependencies",
            "cross_workspaces_with_artifact",
        }
        assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"
