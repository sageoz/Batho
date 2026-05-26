import os
import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from batho.storage.engine import get_database, close_all_databases
from batho.bridge_core.global_registry import resolve_global_db_path, GlobalPlatformDeps
from batho.bridge_core.deps import get_global_deps, set_global_deps, current_deps, global_deps_var
from batho.bridge_core.handlers import dispatch
from batho.bridge_core.transport.http import BridgeHTTPServer
from batho.bridge_core.transport.mcp import BathoMCPServer, MCP_AVAILABLE
from batho.utils.hash import generate_entity_id

@pytest.fixture
def temp_fleet(tmp_path):
    # Create two temporary repos
    repo1_root = tmp_path / "repo1"
    repo1_root.mkdir()
    repo2_root = tmp_path / "repo2"
    repo2_root.mkdir()
    
    global_db_path = tmp_path / "global.batho"
    
    # Generate deterministic IDs
    e1_id = generate_entity_id("CLASS", "ServiceA", "service.py")
    e2_id = generate_entity_id("FUNCTION", "do_something", "service.py")
    e3_id = generate_entity_id("FUNCTION", "_private_func", "service.py")
    
    # Setup repo1 DB
    db1 = get_database(repo1_root)
    # repo1 exports a public CLASS "ServiceA" and FUNCTION "do_something"
    graph_data_1 = {
        "entities": [
            {
                "id": e1_id,
                "type": "CLASS",
                "name": "ServiceA",
                "file": "service.py",
                "start_line": 5,
                "end_line": 20,
            },
            {
                "id": e2_id,
                "type": "FUNCTION",
                "name": "do_something",
                "file": "service.py",
                "start_line": 25,
                "end_line": 30,
            },
            {
                "id": e3_id,
                "type": "FUNCTION",
                "name": "_private_func",
                "file": "service.py",
                "start_line": 35,
                "end_line": 40,
            }
        ],
        "relationships": []
    }
    r1_internal = db1.create_run("run_1", root_path=str(repo1_root))
    agent_view_1 = {
        "entities": [
            {
                "id": e["id"],
                "type": e["type"],
                "name": e["name"],
                "start_line": e["start_line"],
                "end_line": e["end_line"],
                "signature": "",
            }
            for e in graph_data_1["entities"]
        ]
    }
    storage_delta_1 = {
        "entities": [
            {
                "id": e["id"],
                "raw_content": "",
                "syntax_glue": {},
            }
            for e in graph_data_1["entities"]
        ],
    }
    db1.insert_file_artifact(r1_internal, "service.py", "hash1", agent_view_1, storage_delta_1, [])
    db1.complete_run("run_1", entity_count=3, rel_count=0, file_count=1)
    
    # Setup repo2 DB
    e4_id = generate_entity_id("FUNCTION", "caller_func", "app.py")
    e5_id = generate_entity_id("FUNCTION", "do_something", "app.py")
    
    db2 = get_database(repo2_root)
    # repo2 imports/calls "do_something"
    graph_data_2 = {
        "entities": [
            {
                "id": e4_id,
                "type": "FUNCTION",
                "name": "caller_func",
                "file": "app.py",
                "start_line": 1,
                "end_line": 10,
            },
            {
                "id": e5_id,
                "type": "FUNCTION",
                "name": "do_something", # Target reference
                "file": "app.py",
                "start_line": 1,
                "end_line": 1,
            }
        ],
        "relationships": [
            {
                "source_id": e4_id,
                "target_id": e5_id,
                "type": "CALLS"
            }
        ]
    }
    r2_internal = db2.create_run("run_2", root_path=str(repo2_root))
    agent_view_2 = {
        "entities": [
            {
                "id": e["id"],
                "type": e["type"],
                "name": e["name"],
                "start_line": e["start_line"],
                "end_line": e["end_line"],
                "signature": "",
            }
            for e in graph_data_2["entities"]
        ]
    }
    storage_delta_2 = {
        "entities": [
            {
                "id": e["id"],
                "raw_content": "",
                "syntax_glue": {},
            }
            for e in graph_data_2["entities"]
        ],
    }
    relationships_2 = graph_data_2["relationships"]
    db2.insert_file_artifact(r2_internal, "app.py", "hash2", agent_view_2, storage_delta_2, relationships_2)
    db2.complete_run("run_2", entity_count=2, rel_count=1, file_count=1)
    
    yield {
        "global_db_path": global_db_path,
        "repo1": repo1_root,
        "repo2": repo2_root,
        "artifact1": repo1_root / "artifact_repo1.batho",
        "artifact2": repo2_root / "artifact_repo2.batho"
    }
    
    # Reset contextvars so they don't leak to other tests
    current_deps.set(None)
    global_deps_var.set(None)
    close_all_databases()

def test_resolve_global_db_path(tmp_path):
    # 1. Env variable
    with patch.dict(os.environ, {"BATHO_GLOBAL_DB": str(tmp_path / "env_global.batho")}):
        assert resolve_global_db_path() == (tmp_path / "env_global.batho").resolve()
        
    # 2. Config setting (Mock get_config_cached)
    mock_config = {"paths": {"global_db_path": str(tmp_path / "cfg_global.batho")}}
    with patch("batho.config.get_config_cached", return_value=mock_config):
        with patch.dict(os.environ, {}):
            if "BATHO_GLOBAL_DB" in os.environ:
                del os.environ["BATHO_GLOBAL_DB"]
            assert resolve_global_db_path() == (tmp_path / "cfg_global.batho").resolve()
            
    # 3. Default path
    with patch.dict(os.environ, {}):
        if "BATHO_GLOBAL_DB" in os.environ:
            del os.environ["BATHO_GLOBAL_DB"]
        with patch("batho.config.get_config_cached", side_effect=Exception("No config")):
            path = resolve_global_db_path()
            assert path == Path("~/.batho/global.batho").expanduser().resolve()

def test_global_registry_registration_and_indexing(temp_fleet):
    global_db_path = temp_fleet["global_db_path"]
    
    registry = GlobalPlatformDeps(global_db_path)
    
    # Register workspaces
    repo1_id = registry.register_workspace("repo1", temp_fleet["repo1"])
    repo2_id = registry.register_workspace("repo2", temp_fleet["repo2"])
    
    assert repo1_id is not None
    assert repo2_id is not None
    assert repo1_id != repo2_id
    
    # Register artifacts (which triggers extraction and cross-repo edges rebuild)
    registry.register_artifact(repo1_id, temp_fleet["repo1"] / "artifact_repo1.batho")
    registry.register_artifact(repo2_id, temp_fleet["repo2"] / "artifact_repo2.batho")
    
    # Verify public symbols indexed (no private ones starts with _)
    symbols = registry.search_symbols_global("something")
    assert len(symbols) == 2
    assert any(s["repo_name"] == "repo1" for s in symbols)
    assert any(s["repo_name"] == "repo2" for s in symbols)
    
    # Test private function is not indexed
    assert len(registry.search_symbols_global("private")) == 0
    
    # Verify cross-repo edges
    overview = registry.get_fleet_overview()
    assert overview["metrics"]["total_repositories"] == 2
    assert overview["metrics"]["total_symbols"] == 4
    
    edges = overview["edges"]
    assert len(edges) == 1
    assert edges[0]["source_repo_id"] == repo2_id
    assert edges[0]["target_repo_id"] == repo1_id
    assert edges[0]["target_symbol"] == "do_something"
    assert edges[0]["dependency_type"] == "CALLS"

def test_impact_analysis(temp_fleet):
    global_db_path = temp_fleet["global_db_path"]
    registry = GlobalPlatformDeps(global_db_path)
    
    repo1_id = registry.register_workspace("repo1", temp_fleet["repo1"])
    repo2_id = registry.register_workspace("repo2", temp_fleet["repo2"])
    registry.register_artifact(repo1_id, temp_fleet["repo1"] / "artifact_repo1.batho")
    registry.register_artifact(repo2_id, temp_fleet["repo2"] / "artifact_repo2.batho")
    
    # Find downstream impact of do_something
    impact = registry.get_cross_repo_impact(repo1_id, "do_something")
    assert len(impact) == 1
    assert impact[0]["source_repo_name"] == "repo2"
    assert impact[0]["source_symbol"] == "caller_func"

def test_fleet_handlers_and_dispatch(temp_fleet):
    global_db_path = temp_fleet["global_db_path"]
    registry = GlobalPlatformDeps(global_db_path)
    
    repo1_id = registry.register_workspace("repo1", temp_fleet["repo1"])
    repo2_id = registry.register_workspace("repo2", temp_fleet["repo2"])
    registry.register_artifact(repo1_id, temp_fleet["repo1"] / "artifact_repo1.batho")
    registry.register_artifact(repo2_id, temp_fleet["repo2"] / "artifact_repo2.batho")
    
    set_global_deps(registry)
    try:
        # Test fleet overview handler
        res = dispatch("GET", "/api/v1/fleet/overview", deps=None)
        assert res["ok"] is True
        assert res["data"]["metrics"]["total_repositories"] == 2
        
        # Test global search handler
        res = dispatch("GET", "/api/v1/search/global", deps=None, params={"q": "ServiceA"})
        assert res["ok"] is True
        assert len(res["data"]["results"]) == 1
        assert res["data"]["results"][0]["symbol_name"] == "ServiceA"
        
        # Test fleet impact handler
        res = dispatch("GET", "/api/v1/fleet/impact", deps=None, params={
            "repo_id": str(repo1_id),
            "symbol_name": "do_something"
        })
        assert res["ok"] is True
        assert len(res["data"]["impact"]) == 1
        assert res["data"]["impact"][0]["source_repo_name"] == "repo2"
    finally:
        # Clean context
        current_deps.set(None)
        global_deps_var.set(None)

@pytest.mark.asyncio
async def test_mcp_fleet_tools(temp_fleet):
    if not MCP_AVAILABLE:
        pytest.skip("mcp package is not installed")
        
    global_db_path = temp_fleet["global_db_path"]
    registry = GlobalPlatformDeps(global_db_path)
    
    repo1_id = registry.register_workspace("repo1", temp_fleet["repo1"])
    repo2_id = registry.register_workspace("repo2", temp_fleet["repo2"])
    registry.register_artifact(repo1_id, temp_fleet["repo1"] / "artifact_repo1.batho")
    registry.register_artifact(repo2_id, temp_fleet["repo2"] / "artifact_repo2.batho")
    
    from batho.bridge_core.deps import SnapshotCache
    cache = SnapshotCache()
    
    server = BathoMCPServer(cache, temp_fleet["repo1"], global_deps=registry)
    
    async def call_tool_json(tool_name, arguments):
        res_tuple = await server.mcp.call_tool(tool_name, arguments)
        return json.loads(res_tuple[0][0].text)
        
    try:
        # Call list_fleet_workspaces
        res = await call_tool_json("list_fleet_workspaces", {})
        assert res["metrics"]["total_repositories"] == 2
        
        # Call search_fleet_symbols
        res_search = await call_tool_json("search_fleet_symbols", {"query": "ServiceA"})
        assert len(res_search["results"]) == 1
        assert res_search["results"][0]["symbol_name"] == "ServiceA"
        
        # Call get_cross_repo_impact
        res_impact = await call_tool_json("get_cross_repo_impact", {"repo_name": "repo1", "symbol_name": "do_something"})
        assert len(res_impact["impact"]) == 1
        assert res_impact["impact"][0]["source_repo_name"] == "repo2"
    finally:
        # Clear server context setup
        current_deps.set(None)
        global_deps_var.set(None)
