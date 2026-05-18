"""Tests for hub HTTP REST API."""

from __future__ import annotations

import json
import tempfile
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from batho.bridge.hub_http import HubHTTPHandler


class TestHubHTTPHandler:
    """Test HubHTTPHandler REST endpoints."""

    @pytest.fixture
    def mock_manager(self):
        """Create a mock workspace manager."""
        manager = MagicMock()
        manager.list.return_value = []
        manager.resident.return_value = []
        return manager

    def test_handler_class_attributes(self):
        """Test that HubHTTPHandler has expected class attributes."""
        assert hasattr(HubHTTPHandler, "manager")
        assert hasattr(HubHTTPHandler, "default_workspace")

    def test_get_workspace_id_from_path(self):
        """Test workspace ID extraction from path."""
        handler = object.__new__(HubHTTPHandler)
        handler.default_workspace = "default-ws"
        # Path should be like /workspaces/test-ws/indexes (after stripping /api/v1/)
        handler.path = "/workspaces/test-ws/indexes"

        ws_id, remaining = handler.get_workspace_id(handler.path)
        assert ws_id == "test-ws"
        assert remaining == "/indexes"

    def test_get_workspace_id_legacy_bridge(self):
        """Test legacy /api/v1/bridge path handling."""
        handler = object.__new__(HubHTTPHandler)
        handler.default_workspace = "default-ws"
        # Path should be like /bridge/indexes (after stripping /api/v1/)
        handler.path = "/bridge/indexes"

        ws_id, remaining = handler.get_workspace_id(handler.path)
        assert ws_id == "default-ws"
        assert remaining == "/indexes"

    def test_get_workspace_id_no_workspace(self):
        """Test path without workspace."""
        handler = object.__new__(HubHTTPHandler)
        handler.default_workspace = None
        handler.path = "/healthz"

        ws_id, remaining = handler.get_workspace_id(handler.path)
        assert ws_id is None

    def test_send_json_method_exists(self):
        """Test send_json method exists."""
        assert hasattr(HubHTTPHandler, "send_json")

    def test_log_message_method_exists(self):
        """Test log_message method exists."""
        assert hasattr(HubHTTPHandler, "log_message")

    def test_do_get_method_exists(self):
        """Test do_GET method exists."""
        assert hasattr(HubHTTPHandler, "do_GET")
