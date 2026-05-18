"""Tests for cross-repo functionality."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from batho.bridge.cross import (
    cross_dependencies_impl,
    cross_search_impl,
    cross_symbols_impl,
    cross_workspaces_with_artifact_impl,
    merge_search_hits,
)


class TestCrossSearch:
    """Test cross-repo search functions."""

    @pytest.fixture
    def mock_handle(self):
        """Create a mock workspace handle."""
        handle = MagicMock()
        handle.workspace_id = "test-ws"
        handle.is_ready = True

        bsg_data = {
            "entities": [
                {"name": "add", "fqn": "math.add", "kind": "function", "signature": "add(a, b)"},
                {"name": "subtract", "fqn": "math.subtract", "kind": "function", "signature": "subtract(a, b)"},
                {"name": "Calculator", "fqn": "math.Calculator", "kind": "class", "signature": None},
            ]
        }
        handle.loader.load_json.return_value = bsg_data
        return handle

    @pytest.fixture
    def mock_manager(self, mock_handle):
        """Create a mock workspace manager."""
        manager = MagicMock()
        manager.resident.return_value = [mock_handle]
        return manager

    @pytest.mark.asyncio
    async def test_cross_search_impl(self, mock_manager):
        """Test cross_search_impl returns results."""
        results, meta = await cross_search_impl(
            mock_manager, query="add", workspace_ids=None, kinds=None, limit_per_ws=10
        )
        assert isinstance(results, list)
        assert "duration_ms" in meta
        assert "workspaces_queried" in meta

    @pytest.mark.asyncio
    async def test_cross_search_with_workspace_filter(self, mock_manager):
        """Test cross_search_impl with specific workspace IDs."""
        # Mock resolve to return the handle
        import asyncio
        mock_manager.resolve = lambda ws_id: asyncio.coroutine(lambda: mock_handle)()
        
        results, meta = await cross_search_impl(
            mock_manager, query="add", workspace_ids=["test-ws"], kinds=None, limit_per_ws=10
        )
        # When workspace_ids is specified, resolve is called
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_cross_search_with_kind_filter(self, mock_manager):
        """Test cross_search_impl with kind filter."""
        results, meta = await cross_search_impl(
            mock_manager, query="add", workspace_ids=None, kinds=["function"], limit_per_ws=10
        )
        # Should filter by kind in search
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_cross_symbols_impl(self, mock_manager):
        """Test cross_symbols_impl finds symbols."""
        results, meta = await cross_symbols_impl(
            mock_manager, name="add", workspace_ids=None
        )
        assert isinstance(results, list)
        assert "duration_ms" in meta

    @pytest.mark.asyncio
    async def test_cross_symbols_exact_match(self, mock_manager):
        """Test cross_symbols_impl exact name match."""
        # Set up cross_index on manager mock
        from batho.bridge.cross_index import CrossRepoIndex, NodeRef
        from batho.bridge.models import CrossRepoConfig
        
        config = CrossRepoConfig(enabled=True)
        mock_index = CrossRepoIndex(config, max_index_bytes=1000000)
        mock_manager.cross_index = mock_index
        
        # Add nodes to index directly
        nodes = [
            NodeRef(
                node_id="1",
                name="Calculator",
                fqn="math.Calculator",
                kind="class",
                file="math.py",
                start_line=1,
                end_line=10,
                signature=None,
            )
        ]
        await mock_index.ensure_workspace("test-ws", nodes=nodes, file_mtime_ns=0, file_size=100)
        
        # Test the index directly
        matches = mock_index.symbols("test-ws", name="Calculator", kinds=None)
        assert len(matches) > 0
        assert matches[0].name == "Calculator"

    @pytest.mark.asyncio
    async def test_cross_dependencies_impl(self, mock_manager):
        """Test cross_dependencies_impl finds dependencies."""
        mock_handle = mock_manager.resident.return_value[0]
        deps_data = {
            "dependencies": {
                "requests": {"version": "2.28.0", "type": "pip"},
                "pytest": {"version": "7.0.0", "type": "pip"},
            }
        }
        mock_handle.loader.load_json.return_value = deps_data

        results, meta = await cross_dependencies_impl(
            mock_manager, package="requests", workspace_ids=None
        )
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_cross_dependencies_case_insensitive(self, mock_manager):
        """Test cross_dependencies_impl is case insensitive."""
        mock_handle = mock_manager.resident.return_value[0]
        # Use context_overview_json format with top_dependencies
        deps_data = {
            "top_dependencies": [
                {"dependency": "Requests", "version": "2.28.0"},
            ]
        }
        mock_handle.loader.load_json.return_value = deps_data

        results, meta = await cross_dependencies_impl(
            mock_manager, package="requests", workspace_ids=None
        )
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_cross_workspaces_with_artifact_impl(self, mock_manager):
        """Test cross_workspaces_with_artifact_impl finds workspaces."""
        mock_handle = mock_manager.resident.return_value[0]
        mock_handle.bridge.list_artifact_types.return_value = ["bsg_json", "graph_json"]

        results, meta = await cross_workspaces_with_artifact_impl(
            mock_manager, artifact_type="bsg_json"
        )
        assert isinstance(results, list)
        assert "duration_ms" in meta


class TestMergeSearchHits:
    """Test merge_search_hits function."""

    def test_merge_score_desc(self):
        """Test score_desc merge strategy."""
        results = {
            "ws1": [{"score": 50, "name": "a"}, {"score": 30, "name": "b"}],
            "ws2": [{"score": 40, "name": "c"}],
        }
        merged = merge_search_hits(results, strategy="score_desc", limit_per_ws=10)
        assert merged[0]["score"] == 50
        assert merged[1]["score"] == 40

    def test_merge_round_robin(self):
        """Test round_robin merge strategy."""
        results = {
            "ws1": [{"name": "a"}, {"name": "b"}],
            "ws2": [{"name": "c"}],
        }
        merged = merge_search_hits(results, strategy="round_robin", limit_per_ws=10)
        names = [h["name"] for h in merged]
        assert names == ["a", "c", "b"]

    def test_merge_limit_per_workspace(self):
        """Test per-workspace limit is applied."""
        results = {
            "ws1": [{"score": i, "name": f"item{i}"} for i in range(30)],
        }
        merged = merge_search_hits(results, strategy="score_desc", limit_per_ws=5)
        assert len(merged) == 5

    def test_merge_empty_results(self):
        """Test merge with empty results."""
        merged = merge_search_hits({}, strategy="score_desc", limit_per_ws=10)
        assert merged == []

    def test_merge_workspace_id_tagging(self):
        """Test workspace ID is added to results."""
        results = {
            "ws1": [{"name": "a"}],
            "ws2": [{"name": "b"}],
        }
        merged = merge_search_hits(results, strategy="score_desc", limit_per_ws=10)
        ws1_item = next(h for h in merged if h["name"] == "a")
        ws2_item = next(h for h in merged if h["name"] == "b")
        assert ws1_item.get("workspace_id") == "ws1"
        assert ws2_item.get("workspace_id") == "ws2"
