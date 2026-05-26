import pytest
import tempfile
import threading
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any
import contextvars
import json

from batho.storage.engine import BathoDatabase, get_database, close_all_databases
from batho.bridge_core.deps import (
    WorkspaceDeps,
    load_workspace_deps,
    get_current_deps,
    set_current_deps,
    current_deps,
    SnapshotCache,
    resolve_commit_to_run_id,
    get_snapshot_lineage,
    get_previous_snapshot,
    get_next_snapshot,
    list_all_snapshots,
)
from batho.bridge_core.handlers import dispatch
from batho.bridge_core.transport.http import BridgeHTTPServer, BridgeHTTPHandler
from batho.bridge_core.transport.mcp import BathoMCPServer, MCP_AVAILABLE

@pytest.fixture
def temp_repo(tmp_path):
    # Setup temporary repository
    repo_root = tmp_path / "test_repo"
    repo_root.mkdir()
    
    # Create DB
    db = get_database(repo_root)
    
    # Sample graph payload
    graph_data = {
        "entities": [
            {
                "id": "e1",
                "type": "FUNCTION",
                "name": "func_1",
                "file": "main.py",
                "start_line": 1,
                "end_line": 10,
            }
        ],
        "relationships": []
    }
    
    agent_view = {
        "entities": [
            {
                "id": "e1",
                "type": "FUNCTION",
                "name": "func_1",
                "start_line": 1,
                "end_line": 10,
                "signature": "",
            }
        ]
    }
    storage_delta = {
        "entities": [
            {
                "id": "e1",
                "raw_content": "",
                "syntax_glue": {},
            }
        ],
    }
    
    # Insert run 1
    r1_internal = db.create_run("run_1", root_path=str(repo_root), git_commit="1111111111111111111111111111111111111111")
    db.insert_file_artifact(r1_internal, "main.py", "hash1", agent_view, storage_delta, [])
    db.complete_run("run_1", entity_count=1, rel_count=0, file_count=1)
    
    # Sleep to ensure distinct timestamp
    time.sleep(0.05)
    
    # Insert run 2
    r2_internal = db.create_run("run_2", root_path=str(repo_root), git_commit="2222222222222222222222222222222222222222")
    db.insert_file_artifact(r2_internal, "main.py", "hash2", agent_view, storage_delta, [])
    db.complete_run("run_2", entity_count=1, rel_count=0, file_count=1)
    
    yield repo_root
    
    close_all_databases()

class TestTimeTravelResolution:
    def test_resolve_commit_to_run_id(self, temp_repo):
        db = get_database(temp_repo)
        
        # Test exact match
        assert resolve_commit_to_run_id(db, "1111111111111111111111111111111111111111") == "run_1"
        assert resolve_commit_to_run_id(db, "2222222222222222222222222222222222222222") == "run_2"
        
        # Test prefix match
        assert resolve_commit_to_run_id(db, "1111111") == "run_1"
        assert resolve_commit_to_run_id(db, "2222222") == "run_2"
        
        # Test invalid
        assert resolve_commit_to_run_id(db, "9999999") is None
        
    def test_lineage_and_navigation(self, temp_repo):
        db = get_database(temp_repo)
        
        lineage = get_snapshot_lineage(db, "run_2")
        assert len(lineage) == 2
        assert lineage[0]["run_id"] == "run_1"
        assert lineage[1]["run_id"] == "run_2"
        
        prev_snap = get_previous_snapshot(db, "run_2")
        assert prev_snap is not None
        assert prev_snap["run_id"] == "run_1"
        
        next_snap = get_next_snapshot(db, "run_1")
        assert next_snap is not None
        assert next_snap["run_id"] == "run_2"
        
        assert get_previous_snapshot(db, "run_1") is None
        assert get_next_snapshot(db, "run_2") is None
        
    def test_list_all_snapshots(self, temp_repo):
        db = get_database(temp_repo)
        snapshots = list_all_snapshots(db)
        assert len(snapshots) == 2
        assert snapshots[0]["run_id"] == "run_2"
        assert snapshots[1]["run_id"] == "run_1"
        
    def test_load_workspace_deps(self, temp_repo):
        # Default load should be latest (run_2)
        deps_latest = load_workspace_deps(temp_repo)
        assert deps_latest.run_id == "run_2"
        assert deps_latest.git_commit == "2222222222222222222222222222222222222222"
        
        # Load specific run_id
        deps_1 = load_workspace_deps(temp_repo, run_id="run_1")
        assert deps_1.run_id == "run_1"
        assert deps_1.git_commit == "1111111111111111111111111111111111111111"
        
        # Load specific commit_sha
        deps_1_sha = load_workspace_deps(temp_repo, commit_sha="1111111")
        assert deps_1_sha.run_id == "run_1"
        
        with pytest.raises(ValueError):
            load_workspace_deps(temp_repo, commit_sha="9999999")

class TestSnapshotCache:
    def test_cache_hits_and_eviction(self, temp_repo):
        cache = SnapshotCache(max_size=2)
        
        deps1 = cache.get(temp_repo, "run_1")
        deps2 = cache.get(temp_repo, "run_2")
        
        assert len(cache._cache) == 2
        
        # Hit
        deps1_again = cache.get(temp_repo, "run_1")
        assert deps1_again is deps1
        
        # Trigger eviction
        cache_small = SnapshotCache(max_size=1)
        d1 = cache_small.get(temp_repo, "run_1")
        assert "run_1" in cache_small._cache
        
        d2 = cache_small.get(temp_repo, "run_2")
        assert "run_2" in cache_small._cache
        assert "run_1" not in cache_small._cache

class TestContextVarsInjection:
    def test_get_set_current_deps(self):
        deps = WorkspaceDeps(
            repo_root=Path("/fake"),
            graph=None,
            search_engine=None,
            projections=None,
            spatial=None,
            bsg_manager=None,
            telemetry=None,
            run_id="fake_run"
        )
        
        token = current_deps.set(deps)
        try:
            assert get_current_deps() is deps
        finally:
            current_deps.reset(token)
            
        with pytest.raises(RuntimeError):
            get_current_deps()
            
    def test_dispatch_compatibility(self):
        deps = WorkspaceDeps(
            repo_root=Path("/fake"),
            graph=None,
            search_engine=None,
            projections=None,
            spatial=None,
            bsg_manager=None,
            telemetry=None,
            run_id="fake_run"
        )
        # Mock telemetry
        class MockTelemetry:
            def track(self, name):
                class EmptyCM:
                    def __enter__(self): return self
                    def __exit__(self, *a): pass
                return EmptyCM()
        deps.telemetry = MockTelemetry()
        
        # Test dispatch without deps fallback
        token = current_deps.set(deps)
        try:
            from batho.bridge_core.handlers import GET_HANDLERS
            # Temporarily register a dummy handler
            def dummy_handler(d, params):
                return {"ok": True, "run_id": d.run_id}
            GET_HANDLERS["/api/dummy_test_dispatch"] = dummy_handler
            try:
                res = dispatch("GET", "/api/dummy_test_dispatch", deps=None)
                assert res["ok"] is True
                assert res["run_id"] == "fake_run"
            finally:
                del GET_HANDLERS["/api/dummy_test_dispatch"]
        finally:
            current_deps.reset(token)

class TestHttpTransportIntegration:
    def test_http_request_resolution(self, temp_repo):
        server = BridgeHTTPServer(temp_repo, port=12345)
        server.start()
        
        class DummyRequest:
            def makefile(self, *args, **kwargs):
                import io
                return io.BytesIO(b"")
                
        handler = BridgeHTTPHandler(DummyRequest(), ("127.0.0.1", 12345), server.server)
        
        captured_data = []
        def mock_send_json(data, status=200, headers=None):
            captured_data.append((status, data))
        handler._send_json_response = mock_send_json
        handler._send_error = lambda status, msg: captured_data.append((status, {"error": msg}))
        
        # Test GET /readyz (uses latest run_2 by default)
        handler.path = "/readyz"
        handler.command = "GET"
        handler.do_GET()
        
        assert len(captured_data) == 1
        status, res = captured_data[0]
        assert status == 200
        assert res["metadata"]["run_id"] == "run_2"
        assert res["metadata"]["git_commit"] == "2222222222222222222222222222222222222222"
        
        captured_data.clear()
        # Test GET /readyz?run_id=run_1
        handler.path = "/readyz?run_id=run_1"
        handler.do_GET()
        assert len(captured_data) == 1
        status, res = captured_data[0]
        assert status == 200
        assert res["metadata"]["run_id"] == "run_1"
        assert res["metadata"]["git_commit"] == "1111111111111111111111111111111111111111"
        
        captured_data.clear()
        # Test GET /readyz?commit_sha=1111111
        handler.path = "/readyz?commit_sha=1111111"
        handler.do_GET()
        assert len(captured_data) == 1
        status, res = captured_data[0]
        assert status == 200
        assert res["metadata"]["run_id"] == "run_1"
        
        captured_data.clear()
        # Test GET /readyz?commit_sha=9999999 (invalid)
        handler.path = "/readyz?commit_sha=9999999"
        handler.do_GET()
        assert len(captured_data) == 1
        status, res = captured_data[0]
        assert status == 400
        assert "Commit SHA" in res["error"]

class TestMcpTransportIntegration:
    @pytest.mark.asyncio
    async def test_mcp_tool_invocation(self, temp_repo):
        if not MCP_AVAILABLE:
            pytest.skip("mcp package not installed")
            
        cache = SnapshotCache()
        server = BathoMCPServer(cache, temp_repo)
        
        async def call_tool_json(tool_name, arguments):
            res_tuple = await server.mcp.call_tool(tool_name, arguments)
            return json.loads(res_tuple[0][0].text)
            
        # Call with defaults (latest -> run_2)
        res = await call_tool_json("hypergraph_neighborhood", {"node_id": "e1"})
        assert res["metadata"]["run_id"] == "run_2"
        
        # Call with run_id
        res_1 = await call_tool_json("hypergraph_neighborhood", {"node_id": "e1", "run_id": "run_1"})
        assert res_1["metadata"]["run_id"] == "run_1"
        
        # Call with commit_sha
        res_1_sha = await call_tool_json("hypergraph_neighborhood", {"node_id": "e1", "commit_sha": "1111111"})
        assert res_1_sha["metadata"]["run_id"] == "run_1"
        
        # Concurrent isolation test
        # Verify that context variables do not leak across concurrent executions
        @server.mcp.tool()
        async def check_isolation(run_id: str | None = None) -> str:
            deps = server._resolve_deps(run_id)
            token = current_deps.set(deps)
            try:
                import asyncio
                await asyncio.sleep(0.05)
                return get_current_deps().run_id
            finally:
                current_deps.reset(token)
                
        async def run_isolated_task(run_id_val):
            res_tuple = await server.mcp.call_tool("check_isolation", {"run_id": run_id_val})
            return res_tuple[0][0].text
            
        # Run both tasks concurrently
        results = await pytest.importorskip("asyncio").gather(
            run_isolated_task("run_1"),
            run_isolated_task("run_2")
        )
        assert results[0] == "run_1"
        assert results[1] == "run_2"
