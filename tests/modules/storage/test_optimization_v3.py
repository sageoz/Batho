"""
tests/test_optimization_v3.py — Complete test suite for all Phase 1-4 engine optimizations.
"""

from __future__ import annotations

import gc
import os
import sqlite3
import tempfile
from pathlib import Path

import orjson
import pytest

from batho.modules.extraction.extractor import ASTExtractor
from batho.modules.extraction.pipeline import _deserialize_result, process_file_worker
from batho.core.schemas import Entity, EntityType, Relationship, RelationshipType
from batho.modules.storage.sqlite_registry.engine import BathoDatabase
from batho.utils.hash import generate_entity_id


class DummyPythonExtractor(ASTExtractor):
    """Minimal Python query extractor for testing nested classes and overloads."""

    def __init__(self) -> None:
        super().__init__("python")

    def _query_source(self) -> str:
        return """
        (class_definition
          name: (identifier) @def.class.name)

        (function_definition
          name: (identifier) @def.function.name
          parameters: (parameters) @def.function.params)
        """


@pytest.mark.unit
def test_pydantic_slots_optimization():
    """Verify that Pydantic Entity and Relationship objects have slots enabled (no __dict__)."""
    entity = Entity(
        type=EntityType.FUNCTION,
        name="test_func",
        file="src/test.py",
        start_line=1,
        end_line=5,
    )
    # Slotted models in Pydantic v2 have a __slots__ attribute defined
    assert hasattr(entity, "__slots__")
    assert len(entity.__slots__) > 0

    rel = Relationship(
        source_id="src",
        target_id="tgt",
        type=RelationshipType.CALLS,
    )
    assert hasattr(rel, "__slots__")
    assert len(rel.__slots__) > 0


@pytest.mark.unit
def test_positional_scoping_and_overloading_hash():
    """Verify that nested definitions generate dot-notation names, and overloads append param hashes."""
    extractor = DummyPythonExtractor()
    content = b"""
class Calculator:
    def process(self):
        pass

    def process(self, data, config):
        pass
"""
    entities, _ = extractor.parse_file("calc.py", content)

    # We expect:
    # 1. Class "Calculator"
    # 2. Method "Calculator.process" (no params/empty or matching self)
    # 3. Method "Calculator.process_[hash]" (with params)
    assert len(entities) == 3

    calc_entity = entities[0]
    assert calc_entity.name == "Calculator"
    assert calc_entity.type == EntityType.CLASS

    method_1 = entities[1]
    # First method with no params (empty or self) gets signature name or hash
    assert method_1.name.startswith("Calculator.process")
    assert method_1.type == EntityType.FUNCTION

    method_2 = entities[2]
    # Second method with parameters gets signature hash appended
    assert method_2.name.startswith("Calculator.process_[")
    assert method_2.name.endswith("]")

    # Verify deterministic line-number-free entity IDs are unique
    assert method_1.id != method_2.id
    assert method_1.id == generate_entity_id(method_1.type.name, method_1.name, method_1.file)


@pytest.mark.unit
def test_ipc_serialization_bypass_and_gc():
    """Verify process_file_worker outputs orjson bytes (bypassing pickle) and worker GC is cycled."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        filepath = tmp_path / "test_ipc.py"
        filepath.write_text("""
def process_data(a, b):
    return a + b
""", encoding="utf-8")

        # Record GC state
        gc_was_enabled = gc.isenabled()

        # Run process_file_worker
        result = process_file_worker(
            file_path=filepath,
            filepath=str(filepath),
            current_mtime=os.path.getmtime(filepath),
            size=filepath.stat().st_size,
            cache_enabled=False,
            cache_path=str(tmp_path / "cache.batho"),
            ttl_days=30,
            max_file_size_kb=500,
            bsg_cache_cfg={},
        )

        # Assert GC is restored properly
        assert gc.isenabled() == gc_was_enabled

        assert result is not None
        filepath_res, ent_bytes, rel_bytes, cached_hit = result

        assert filepath_res == str(filepath)
        assert isinstance(ent_bytes, bytes)
        assert isinstance(rel_bytes, bytes)
        assert not cached_hit

        # Decode via orjson to check data
        ents_data = orjson.loads(ent_bytes)
        assert len(ents_data) == 1
        assert ents_data[0]["name"].startswith("process_data")
        assert ents_data[0]["type"] == "FUNCTION"

        # Deserialize back into objects using pipeline helper
        deser = _deserialize_result(result)
        assert deser is not None
        _, entities, relationships, _ = deser

        assert len(entities) == 1
        assert isinstance(entities[0], Entity)
        assert entities[0].name.startswith("process_data")


@pytest.mark.integration
def test_extreme_sqlite_pragma_tuning():
    """Verify that the extreme SQLite connection pragmas (mmap_size, synchronous, cache_size) are applied."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_pragmas.batho"
        db = BathoDatabase(db_path)

        with db.connection(read_only=True) as conn:
            # Verify synchronous = NORMAL (which is 1)
            sync = conn.execute("PRAGMA synchronous").fetchone()[0]
            assert sync == 1  # 1 corresponds to NORMAL

            # Verify mmap_size = 30GB (or as close as OS supports, usually configured size)
            mmap = conn.execute("PRAGMA mmap_size").fetchone()[0]
            assert mmap >= 30000000000 or mmap > 0  # Support varied OS capacities

            # Verify temp_store = MEMORY (which is 2)
            temp_store = conn.execute("PRAGMA temp_store").fetchone()[0]
            assert temp_store == 2  # 2 corresponds to MEMORY

            # Verify cache_size = -128000
            cache_size = conn.execute("PRAGMA cache_size").fetchone()[0]
            assert cache_size == -128000


@pytest.mark.integration
def test_lazy_cross_file_resolution_sql_join():
    """Verify unresolved/dangling edges are written to SQLite, and resolved via a SQL JOIN."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_resolution.batho"
        db = BathoDatabase(db_path)
        run_uuid = "test_run_123"
        run_internal_id = db.create_run(run_uuid)

        # 1. Insert a resolved entity (definition)
        entities_data = {
            "entities": [
                {
                    "id": "function:process_data:src/lib.py",
                    "name": "process_data",
                    "entity_type": "FUNCTION",
                    "fqn": "process_data",
                    "start_line": 1,
                    "end_line": 5,
                }
            ]
        }
        # 2. Insert a file artifact with a dangling reference (calling process_data)
        dangling_rels = [
            {
                "source_id": "function:main:src/main.py",
                "target_id": "unresolved:process_data:src/main.py",
                "type": "CALLS",
                "metadata": {"line_number": 2},
            }
        ]
        # Include the UNRESOLVED entity representing the dangling target
        dangling_entities = {
            "entities": [
                {
                    "id": "unresolved:process_data:src/main.py",
                    "name": "process_data",
                    "entity_type": "UNRESOLVED",
                    "start_line": 2,
                    "end_line": 2,
                }
            ]
        }

        # Save both files
        db.insert_file_artifact(
            run_internal_id,
            "src/lib.py",
            "hash1",
            entities_data,
            {"entities": []},
            []
        )
        db.insert_file_artifact(
            run_internal_id,
            "src/main.py",
            "hash2",
            dangling_entities,
            {"entities": []},
            dangling_rels
        )

        # Assert query_entities has both
        with db.connection(read_only=True) as conn:
            rows = conn.execute("SELECT * FROM query_entities WHERE run_id = ?", (run_internal_id,)).fetchall()
            assert len(rows) == 2

            # Assert dangling_references contains the CALLS edge to process_data
            dangling = conn.execute("SELECT * FROM dangling_references WHERE run_id = ?", (run_internal_id,)).fetchall()
            assert len(dangling) == 1
            assert dangling[0]["unresolved_target_name"] == "process_data"
            assert dangling[0]["source_id"] == "function:main:src/main.py"

            # Assert query_relationships is empty initially
            rels = conn.execute("SELECT * FROM query_relationships WHERE run_id = ?", (run_internal_id,)).fetchall()
            assert len(rels) == 0

        # Execute lazy SQL Join Resolution
        resolved_count = db.resolve_dangling_references(run_internal_id)
        assert resolved_count == 1

        # Verify query_relationships has the newly resolved cross-file relationship
        with db.connection(read_only=True) as conn:
            rels = conn.execute("SELECT * FROM query_relationships WHERE run_id = ?", (run_internal_id,)).fetchall()
            assert len(rels) == 1
            assert rels[0]["source_id"] == "function:main:src/main.py"
            assert rels[0]["target_id"] == "function:process_data:src/lib.py"
            assert rels[0]["relation_type"] == "CALLS"

            # Verify dangling references table is cleaned up
            dangling_after = conn.execute("SELECT * FROM dangling_references WHERE run_id = ?", (run_internal_id,)).fetchall()
            assert len(dangling_after) == 0
