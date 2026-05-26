"""Tests for bridge_core module.

These tests verify the new simplified bridge architecture.
"""

import pytest
from pathlib import Path


class TestBridgeCoreImports:
    """Test that all bridge_core modules can be imported."""
    
    def test_bridge_core_imports(self):
        """Test all public exports from bridge_core."""
        from batho.bridge_core import WorkspaceDeps, load_workspace_deps, BridgeServer
        assert WorkspaceDeps is not None
        assert load_workspace_deps is not None
        assert BridgeServer is not None
    
    def test_handlers_import(self):
        """Test handler dispatch."""
        from batho.bridge_core.handlers import dispatch, GET_HANDLERS, POST_HANDLERS
        assert dispatch is not None
        assert len(GET_HANDLERS) > 0
        assert len(POST_HANDLERS) > 0
    
    def test_transport_imports(self):
        """Test transport layer imports."""
        from batho.bridge_core.transport import BridgeHTTPServer, run_mcp_stdio
        assert BridgeHTTPServer is not None
        assert run_mcp_stdio is not None


class TestDashboardCoreImports:
    """Test that dashboard_core modules can be imported."""
    
    def test_dashboard_core_imports(self):
        """Test all public exports from dashboard_core."""
        from batho.dashboard_core import DashboardServer, serve_dashboard, find_dashboard_assets
        assert DashboardServer is not None
        assert serve_dashboard is not None
        assert find_dashboard_assets is not None


class TestNewHandlers:
    """Test new handlers migrated from bridge."""
    
    def test_file_handler_import(self):
        """Test file handler can be imported."""
        from batho.bridge_core.handlers.file import handle_file_content, safe_read_file, get_language_from_path
        assert handle_file_content is not None
        assert safe_read_file is not None
        assert get_language_from_path is not None
    
    def test_outline_handler_import(self):
        """Test outline handler can be imported."""
        from batho.bridge_core.handlers.outline import handle_file_outline, build_file_outline
        assert handle_file_outline is not None
        assert build_file_outline is not None
    
    def test_fs_handler_import(self):
        """Test FS browse handler can be imported."""
        from batho.bridge_core.handlers.fs import handle_fs_browse, browse_directory
        assert handle_fs_browse is not None
        assert browse_directory is not None
    
    def test_snippets_service_import(self):
        """Test agent snippets service can be imported."""
        from batho.bridge_core.services.snippets import AgentSnippetGenerator, handle_agent_snippet
        assert AgentSnippetGenerator is not None
        assert handle_agent_snippet is not None
    
    def test_amnesia_service_import(self):
        """Test amnesia analyzer service can be imported."""
        from batho.bridge_core.services.amnesia import ContextAmnesiaAnalyzer
        assert ContextAmnesiaAnalyzer is not None
    
    def test_engine_services_import(self):
        """Test engine services can be imported."""
        from batho.bridge_core.services.graph_projections import GraphProjectionEngine
        from batho.bridge_core.services.search_engine import GraphSearchEngine
        from batho.bridge_core.services.bsg_manager import BSGMemoryManager
        assert GraphProjectionEngine is not None
        assert GraphSearchEngine is not None
        assert BSGMemoryManager is not None


class TestHandlerSignatures:
    """Test that handlers have correct signatures."""
    
    def test_handler_signature(self):
        """Test handler function signatures."""
        from batho.bridge_core.handlers.graph import handle_hypergraph_l1
        from batho.bridge_core.deps import WorkspaceDeps
        import inspect
        
        sig = inspect.signature(handle_hypergraph_l1)
        params = list(sig.parameters.keys())
        
        assert "deps" in params
        assert "params" in params


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
