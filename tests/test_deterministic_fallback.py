import pytest
import time
from pathlib import Path
import json
import asyncio
from unittest.mock import MagicMock

from batho.storage.engine import get_database, close_all_databases
from batho.bridge_core.deps import load_workspace_deps, WorkspaceDeps
from batho.bridge_core.services.search_engine import GraphSearchEngine
from batho.orchestrator.patch import run_patch, PatchOptions
from batho.bridge_core.transport.mcp import BathoMCPServer
from batho.utils.hash import generate_entity_id

# Generate the correct deterministic IDs that the Pydantic Entity model will compute
E1_ID = generate_entity_id("FUNCTION", "calculate_sum", "math.py")
E2_ID = generate_entity_id("CLASS", "Calculator", "math.py")
E3_ID = generate_entity_id("VARIABLE", "_private_val", "math.py")

@pytest.fixture
def temp_repo(tmp_path):
    repo_root = tmp_path / "test_repo"
    repo_root.mkdir()
    
    # Create DB
    db = get_database(repo_root)
    
    # Sample graph payload
    graph_data = {
        "entities": [
            {
                "id": E1_ID,
                "type": "FUNCTION",
                "name": "calculate_sum",
                "file": "math.py",
                "start_line": 5,
                "end_line": 8,
                "signature": "def calculate_sum(a, b)",
                "fqn": "math.calculate_sum",
            },
            {
                "id": E2_ID,
                "type": "CLASS",
                "name": "Calculator",
                "file": "math.py",
                "start_line": 1,
                "end_line": 4,
                "signature": "class Calculator",
                "fqn": "math.Calculator",
            },
            {
                "id": E3_ID,
                "type": "VARIABLE",
                "name": "_private_val",
                "file": "math.py",
                "start_line": 10,
                "end_line": 10,
                "signature": "_private_val = 10",
                "fqn": "math._private_val",
            }
        ],
        "relationships": []
    }
    
    r1_internal = db.create_run("run_1", root_path=str(repo_root), git_commit="1111111111111111111111111111111111111111")
    agent_view = {
        "entities": [
            {
                "id": e["id"],
                "type": e["type"],
                "name": e["name"],
                "start_line": e["start_line"],
                "end_line": e["end_line"],
                "signature": e["signature"],
                "fqn": e.get("fqn"),
            }
            for e in graph_data["entities"]
        ]
    }
    storage_delta = {
        "entities": [
            {
                "id": e["id"],
                "raw_content": "",
                "syntax_glue": {},
            }
            for e in graph_data["entities"]
        ],
    }
    db.insert_file_artifact(r1_internal, "math.py", "hash1", agent_view, storage_delta, [])
    db.complete_run("run_1", entity_count=3, rel_count=0, file_count=1)
    
    yield repo_root
    
    close_all_databases()

class TestDeterministicFallback:
    def test_sqlite_search_exact_match(self, temp_repo):
        db = get_database(temp_repo)
        results = db.search_entities("run_1", "calculate_sum")
        assert len(results) == 1
        assert results[0]["id"] == E1_ID
        assert results[0]["name"] == "calculate_sum"
        assert results[0]["kind"] == "FUNCTION"
        assert results[0]["file"] == "math.py"
        assert results[0]["line"] == 5

    def test_sqlite_search_prefix_match(self, temp_repo):
        db = get_database(temp_repo)
        results = db.search_entities("run_1", "calc")
        assert len(results) == 2
        names = {r["name"] for r in results}
        assert "calculate_sum" in names
        assert "Calculator" in names

    def test_sqlite_search_fqn_match(self, temp_repo):
        db = get_database(temp_repo)
        results = db.search_entities("run_1", "math.Calculator")
        assert len(results) == 1
        assert results[0]["id"] == E2_ID
        assert results[0]["name"] == "Calculator"

    def test_sqlite_search_kind_filtering(self, temp_repo):
        db = get_database(temp_repo)
        # Search prefix with FUNCTION filter
        results = db.search_entities("run_1", "calc", kinds=["FUNCTION"])
        assert len(results) == 1
        assert results[0]["id"] == E1_ID

    def test_graph_search_engine_fallback(self, temp_repo):
        # Resolve dependencies
        deps = load_workspace_deps(temp_repo, run_id="run_1")
        search_engine = deps.search_engine
        
        # Exact match via SQLite
        results = search_engine.search("calculate_sum")
        assert len(results) == 1
        assert results[0]["id"] == E1_ID
        
        # Test fallback to in-memory: query a value NOT in SQLite, but we manually inject it in the in-memory graph
        from batho.context.schema import Entity, EntityType
        new_entity = Entity(
            id="e_in_mem",
            name="in_memory_only",
            type=EntityType.FUNCTION,
            file="math.py",
            start_line=20,
            end_line=25,
            signature="def in_memory_only()",
            fqn="math.in_memory_only",
        )
        # Add to the in-memory graph directly
        search_engine.graph.entities["e_in_mem"] = new_entity
        # Re-build index (normally done on init)
        search_engine._build_indexes()
        
        # Search for it. SQLite won't find it, so it should fallback to in-memory search and find it.
        results = search_engine.search("in_memory_only")
        assert len(results) == 1
        assert results[0]["id"] == "e_in_mem"

    def test_cascade_delete(self, temp_repo):
        db = get_database(temp_repo)
        # Verify entities exist
        results = db.search_entities("run_1", "calculate_sum")
        assert len(results) == 1
        
        # Delete run
        with db.connection() as conn:
            conn.execute("DELETE FROM index_runs WHERE run_uuid = 'run_1'")
            conn.commit()
            
        # Verify query_entities got cascade deleted
        with db.connection(read_only=True) as conn:
            row = conn.execute("SELECT count(*) as cnt FROM query_entities WHERE run_id = 1").fetchone()
            assert row["cnt"] == 0

    def test_incremental_patch_query_entities(self, temp_repo):
        db = get_database(temp_repo)
        
        # Create a new file in temp_repo so patch detects it as added
        extra_file = temp_repo / "utils.py"
        extra_file.write_text("def extra_func(): pass")
        
        # Run patch.py run_patch
        options = PatchOptions(root=temp_repo)
        result = run_patch(options)
        assert result.success is True
        
        # Get the new run ID
        new_run_id = result.run_id
        assert new_run_id != "run_1"
        
        # Verify that math.py query_entities were copied over from run_1 to new_run_id (CoW)
        results = db.search_entities(new_run_id, "calculate_sum")
        assert len(results) == 1
        assert results[0]["id"] == E1_ID
        assert results[0]["file"] == "math.py"

    @pytest.mark.asyncio
    async def test_mcp_tools_with_sqlite_first(self, temp_repo):
        deps = load_workspace_deps(temp_repo, run_id="run_1")
        
        # Mock MCP server
        from batho.bridge_core.deps import SnapshotCache
        cache = SnapshotCache()
        server = BathoMCPServer(cache, temp_repo)
        
        # Since _resolve_deps in BathoMCPServer uses cache, we can inject our deps
        server.cache.get = MagicMock(return_value=deps)
        
        # Mock deps.search_engine.search to spy on calls
        original_search = deps.search_engine.search
        deps.search_engine.search = MagicMock(side_effect=original_search)
        
        # Run search_entities via call_tool
        res_tuple = await server.mcp.call_tool("search_entities", {"query": "calculate_sum", "run_id": "run_1"})
        data = json.loads(res_tuple[0][0].text)
        assert len(data.get("results", [])) == 1
        
        # Verify search was called without use_sqlite_first passed (so defaults to True)
        deps.search_engine.search.assert_called_with("calculate_sum", kinds=None, limit=50)
        
        # Reset mock
        deps.search_engine.search.reset_mock()
        
        # Run hypergraph_neighborhood via call_tool
        res_neighborhood_tuple = await server.mcp.call_tool("hypergraph_neighborhood", {"node_id": "calculate_sum", "run_id": "run_1"})
        res_neighborhood = json.loads(res_neighborhood_tuple[0][0].text)
        assert "center" in res_neighborhood
        assert res_neighborhood["center"]["id"] == E1_ID
        
        # Since "calculate_sum" was not directly in the graph as a node_id, it is resolved
        # using search_engine.search("calculate_sum", use_sqlite_first=False)
        deps.search_engine.search.assert_called_with("calculate_sum", use_sqlite_first=False)
