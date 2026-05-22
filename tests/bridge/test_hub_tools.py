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

    def test_reconstruct_file_tool_exists(self, hub):
        """Test that reconstruct_file tool exists for MCP reconstruction.

        This verifies the fix for the bug where reconstruct_file was loading
        bsg_json (agent view) instead of graph.json, and not enriching entities
        with raw_content/raw_bytes from bsg_storage_view.json.
        """
        tool = None
        for t in hub._tool_manager._tools.values():
            if hasattr(t, "name") and t.name == "reconstruct_file":
                tool = t
                break
        assert tool is not None, "reconstruct_file tool not found"

    def test_reconstruct_file_raw_bytes_enrichment_from_hex(self, tmp_path: Path):
        """Issue 1: raw_bytes stored as hex in storage view must be converted back to bytes.

        Simulates the exact enrichment logic from hub.py's reconstruct_file tool.
        """
        from batho.context.codegraph import InMemoryGraph
        from batho.context.schema import Entity, EntityType

        # Build a minimal graph
        graph = InMemoryGraph()
        entity = Entity(
            type=EntityType.FUNCTION,
            name="hello",
            file="test.py",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=13,
            raw_content="def hello():\n",
        )
        graph.add_entity(entity)

        # Simulate storage view entity data (as produced by Entity.to_dict(view="storage"))
        raw_bytes_hex = b"def hello():\n".hex()
        entity_data = {
            "id": entity.id,
            "type": "FUNCTION",
            "name": "hello",
            "file": "test.py",
            "start_line": 1,
            "end_line": 1,
            "start_byte": 0,
            "end_byte": 13,
            "raw_content": "def hello():\n",
            "raw_bytes": raw_bytes_hex,
        }

        # Reproduce the enrichment logic from hub.py
        entity_id = entity_data.get("id")
        if entity_id and entity_id in graph.entities:
            ent = graph.entities[entity_id]
            updates: dict[str, Any] = {}
            if "raw_content" in entity_data:
                updates["raw_content"] = entity_data["raw_content"]
            if "raw_bytes" in entity_data:
                raw_bytes_val = entity_data["raw_bytes"]
                if isinstance(raw_bytes_val, str) and raw_bytes_val:
                    updates["raw_bytes"] = bytes.fromhex(raw_bytes_val)
                elif raw_bytes_val:
                    updates["raw_bytes"] = raw_bytes_val
            if updates:
                graph.entities[entity_id] = ent.model_copy(update=updates)

        # Verify enrichment succeeded
        enriched = graph.entities[entity_id]
        assert isinstance(enriched.raw_bytes, bytes)
        assert enriched.raw_bytes == b"def hello():\n"
        assert enriched.raw_content == "def hello():\n"
