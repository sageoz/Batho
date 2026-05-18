"""Tests for WorkspaceRegistry."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from batho.bridge.models import HubConfig, WorkspaceConfig
from batho.bridge.workspace_registry import WorkspaceRegistry


class TestWorkspaceRegistry:
    """Test WorkspaceRegistry functionality."""

    def test_load_empty_config_returns_defaults(self, tmp_path):
        """Loading empty config returns default values."""
        config_path = tmp_path / "mcp.yaml"
        config_path.touch()
        registry = WorkspaceRegistry(user_config_path=config_path)
        config = registry.load()
        assert config.schema_version == 1
        assert config.server.bind == "127.0.0.1"
        assert config.server.http_port == 8770
        assert config.residency.max_resident_workspaces == 32

    def test_load_valid_config(self, tmp_path):
        """Loading valid config parses correctly."""
        config_path = tmp_path / "mcp.yaml"
        config_data = {
            "schema_version": 1,
            "server": {"http_port": 9000},
            "workspaces": [
                {"id": "test-ws", "ctn_dir": "/tmp/ctn"}
            ]
        }
        config_path.write_text(yaml.dump(config_data))
        registry = WorkspaceRegistry(user_config_path=config_path)
        config = registry.load()
        assert config.server.http_port == 9000
        assert len(config.workspaces) == 1
        assert config.workspaces[0].id == "test-ws"

    def test_add_workspace(self, tmp_path):
        """Adding a workspace updates config."""
        config_path = tmp_path / "mcp.yaml"
        config_path.write_text(yaml.dump({"schema_version": 1}))
        registry = WorkspaceRegistry(user_config_path=config_path)
        ws = WorkspaceConfig(id="new-ws", ctn_dir="/tmp/ctn")
        config = registry.add(ws)
        assert len(config.workspaces) == 1
        assert config.workspaces[0].id == "new-ws"

    def test_remove_workspace(self, tmp_path):
        """Removing a workspace updates config."""
        config_path = tmp_path / "mcp.yaml"
        config_data = {
            "schema_version": 1,
            "workspaces": [
                {"id": "ws1", "ctn_dir": "/tmp/ctn1"},
                {"id": "ws2", "ctn_dir": "/tmp/ctn2"},
            ]
        }
        config_path.write_text(yaml.dump(config_data))
        registry = WorkspaceRegistry(user_config_path=config_path)
        config = registry.remove("ws1")
        assert len(config.workspaces) == 1
        assert config.workspaces[0].id == "ws2"

    def test_update_workspace(self, tmp_path):
        """Updating a workspace updates config."""
        config_path = tmp_path / "mcp.yaml"
        config_data = {
            "schema_version": 1,
            "workspaces": [
                {"id": "ws1", "ctn_dir": "/tmp/ctn1", "label": "Old Label"}
            ]
        }
        config_path.write_text(yaml.dump(config_data))
        registry = WorkspaceRegistry(user_config_path=config_path)
        config = registry.update("ws1", label="New Label")
        assert config.workspaces[0].label == "New Label"

    def test_get_workspace(self, tmp_path):
        """Getting a workspace returns correct config."""
        config_path = tmp_path / "mcp.yaml"
        config_data = {
            "schema_version": 1,
            "workspaces": [
                {"id": "ws1", "ctn_dir": "/tmp/ctn1", "label": "Test"}
            ]
        }
        config_path.write_text(yaml.dump(config_data))
        registry = WorkspaceRegistry(user_config_path=config_path)
        ws = registry.get("ws1")
        assert ws is not None
        assert ws.id == "ws1"
        assert ws.label == "Test"

    def test_list_workspaces(self, tmp_path):
        """Listing workspaces returns all configs."""
        config_path = tmp_path / "mcp.yaml"
        config_data = {
            "schema_version": 1,
            "workspaces": [
                {"id": "ws1", "ctn_dir": "/tmp/ctn1"},
                {"id": "ws2", "ctn_dir": "/tmp/ctn2"},
            ]
        }
        config_path.write_text(yaml.dump(config_data))
        registry = WorkspaceRegistry(user_config_path=config_path)
        workspaces = registry.list()
        assert len(workspaces) == 2
        assert {ws.id for ws in workspaces} == {"ws1", "ws2"}

    def test_invalid_workspace_id_rejected(self, tmp_path):
        """Invalid workspace ID is rejected."""
        config_path = tmp_path / "mcp.yaml"
        config_path.write_text(yaml.dump({"schema_version": 1}))
        registry = WorkspaceRegistry(user_config_path=config_path)
        ws = WorkspaceConfig(id="Invalid-ID!", ctn_dir="/tmp/ctn")
        with pytest.raises(ValueError, match="Invalid workspace ID"):
            registry.add(ws)

    def test_duplicate_workspace_id_rejected(self, tmp_path):
        """Duplicate workspace ID is rejected."""
        config_path = tmp_path / "mcp.yaml"
        config_data = {
            "schema_version": 1,
            "workspaces": [
                {"id": "ws1", "ctn_dir": "/tmp/ctn1"}
            ]
        }
        config_path.write_text(yaml.dump(config_data))
        registry = WorkspaceRegistry(user_config_path=config_path)
        ws = WorkspaceConfig(id="ws1", ctn_dir="/tmp/ctn2")
        with pytest.raises(ValueError, match="already exists"):
            registry.add(ws)

    def test_compute_diff(self, tmp_path):
        """Computing diff between configs works."""
        config_path = tmp_path / "mcp.yaml"
        config_path.write_text(yaml.dump({"schema_version": 1}))
        registry = WorkspaceRegistry(user_config_path=config_path)

        old_config = HubConfig(workspaces=[
            WorkspaceConfig(id="ws1", ctn_dir="/tmp/ctn1"),
            WorkspaceConfig(id="ws2", ctn_dir="/tmp/ctn2"),
        ])
        new_config = HubConfig(workspaces=[
            WorkspaceConfig(id="ws1", ctn_dir="/tmp/ctn1"),
            WorkspaceConfig(id="ws3", ctn_dir="/tmp/ctn3"),
        ])

        diff = registry.compute_diff(old_config, new_config)
        assert diff.removed == ["ws2"]
        assert len(diff.added) == 1
        assert diff.added[0].id == "ws3"
