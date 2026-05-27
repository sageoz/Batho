"""Smoke tests for Batho Storage v2.0 architecture."""

from __future__ import annotations

import zlib
import json
from pathlib import Path

import pytest
from batho.modules.storage.sqlite_registry.engine import _DB_CACHE, _DB_CACHE_LOCK

def close_all_databases():
    with _DB_CACHE_LOCK:
        for db in list(_DB_CACHE.values()):
            db.close()
        _DB_CACHE.clear()


class TestSchemaV4:
    """Verify the v4 schema creates the correct 6-table structure and split view columns."""

    def test_tables_created(self, tmp_path):
        import sqlite3
        from batho.modules.storage.sqlite_registry.engine import BathoDatabase

        db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
        conn = sqlite3.connect(str(tmp_path / "test.batho"))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(file_artifacts)"
            ).fetchall()
        }
        conn.close()
        db.close()

        assert "db_meta" in tables
        assert "string_dict" in tables
        assert "index_runs" in tables
        assert "file_artifacts" in tables
        assert "file_tracking" in tables
        assert "run_artifacts" in tables
        assert "artifacts" not in tables
        
        # Verify split view columns are present and legacy columns are removed
        assert "bsg_agent_view" in columns
        assert "bsg_storage_view" in columns
        assert "bsg_rel_view" in columns
        assert "graph_blob" not in columns
        assert "bsg_blob" not in columns

    def test_schema_version_stored(self, tmp_path):
        from batho.modules.storage.sqlite_registry.engine import BathoDatabase, SCHEMA_VERSION

        db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
        assert db.get_meta("schema_version") == SCHEMA_VERSION
        db.close()


class TestDictionaryEncoding:
    """Verify string_dict global encoding."""

    def test_get_or_create_string_id(self, tmp_path):
        from batho.modules.storage.sqlite_registry.engine import BathoDatabase

        db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
        sid = db.get_or_create_string_id("src/main.py")
        assert isinstance(sid, int)
        assert sid > 0

        sid2 = db.get_or_create_string_id("src/main.py")
        assert sid == sid2

        sid3 = db.get_or_create_string_id("src/other.py")
        assert sid3 != sid
        db.close()

    def test_round_trip(self, tmp_path):
        from batho.modules.storage.sqlite_registry.engine import BathoDatabase

        db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
        val = "batho/storage/engine.py"
        sid = db.get_or_create_string_id(val)
        assert db.get_string_val(sid) == val
        db.close()


class TestIndexRuns:
    """Verify index run lifecycle."""

    def test_create_and_complete_run(self, tmp_path):
        from batho.modules.storage.sqlite_registry.engine import BathoDatabase

        db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
        run_uuid = "build_test_001"
        run_id = db.create_run(run_uuid, root_path=str(tmp_path))
        assert isinstance(run_id, int)

        run = db.get_run(run_uuid)
        assert run is not None
        assert run["status"] == "running"

        db.complete_run(run_uuid, entity_count=5, rel_count=3, file_count=2)
        run = db.get_run(run_uuid)
        assert run["status"] == "completed"
        assert run["entity_count"] == 5

        assert db.get_latest_run_id() == run_uuid
        db.close()

    def test_fail_run(self, tmp_path):
        from batho.modules.storage.sqlite_registry.engine import BathoDatabase

        db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
        run_uuid = "build_fail_001"
        db.create_run(run_uuid, root_path=str(tmp_path))
        db.fail_run(run_uuid, error_message="Indexer crashed")
        run = db.get_run(run_uuid)
        assert run["status"] == "failed"
        assert "Indexer crashed" in run["error_message"]
        db.close()

    def test_get_run_internal_id(self, tmp_path):
        from batho.modules.storage.sqlite_registry.engine import BathoDatabase

        db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
        run_uuid = "build_internal_001"
        internal_id = db.create_run(run_uuid, root_path=str(tmp_path))
        assert db.get_run_internal_id(run_uuid) == internal_id
        db.close()


class TestFileArtifacts:
    """Verify compressed blob insertion and retrieval with delta splitting and O(N) merging."""

    def test_insert_and_retrieve(self, tmp_path):
        from batho.modules.storage.sqlite_registry.engine import BathoDatabase

        db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
        run_uuid = "build_blob_001"
        run_id = db.create_run(run_uuid, root_path=str(tmp_path))

        agent_view = {
            "entities": [
                {
                    "id": "e1",
                    "type": "FUNCTION",
                    "name": "main",
                    "start_line": 1,
                    "end_line": 10,
                    "signature": "def main(): pass"
                }
            ]
        }
        storage_delta = {
            "entities": [
                {
                    "id": "e1",
                    "raw_content": "def main():\n    pass",
                    "syntax_glue": {"leading_whitespace": "  ", "trailing_whitespace": "\n"}
                }
            ],
        }
        relationships = [
            {
                "id": "r1",
                "type": "CALLS",
                "source_id": "e1",
                "target_id": "e2"
            }
        ]
        db.insert_file_artifact(run_id, "src/main.py", "abc123", agent_view, storage_delta, relationships)

        # Retrieve with include_storage=True to test O(N) merging
        artifacts = db.get_file_artifacts(run_id, include_storage=True)
        assert len(artifacts) == 1
        art = artifacts[0]
        assert art["file_path"] == "src/main.py"
        assert art["content_hash"] == "abc123"
        
        # Verify merged result
        graph = art["graph"]
        assert len(graph["entities"]) == 1
        ent = graph["entities"][0]
        assert ent["name"] == "main"
        assert ent["entity_type"] == "FUNCTION"
        assert ent["raw_content"] == "def main():\n    pass"
        assert ent["leading_whitespace"] == "  "
        assert ent["trailing_whitespace"] == "\n"
        
        assert len(graph["relationships"]) == 1
        assert graph["relationships"][0]["type"] == "CALLS"

        # Retrieve with include_storage=False to verify lightweight load
        artifacts_light = db.get_file_artifacts(run_id, include_storage=False)
        art_light = artifacts_light[0]
        ent_light = art_light["graph"]["entities"][0]
        assert ent_light["name"] == "main"
        assert "raw_content" not in ent_light
        assert "leading_whitespace" not in ent_light

        db.close()

    def test_blob_is_actually_compressed(self, tmp_path):
        import sqlite3
        import zstandard as zstd
        from batho.modules.storage.sqlite_registry.engine import BathoDatabase

        db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
        run_uuid = "build_compress_001"
        run_id = db.create_run(run_uuid, root_path=str(tmp_path))
        agent_view = {
            "entities": [
                {
                    "id": "e1",
                    "type": "FUNCTION",
                    "name": "main",
                    "start_line": 1,
                    "end_line": 10,
                }
            ]
        }
        storage_delta = {"entities": []}
        db.insert_file_artifact(run_id, "main.py", "hash1", agent_view, storage_delta, [])
        db.close()

        conn = sqlite3.connect(str(tmp_path / "test.batho"))
        row = conn.execute("SELECT bsg_agent_view FROM file_artifacts LIMIT 1").fetchone()
        conn.close()
        blob = row[0]
        assert isinstance(blob, bytes)
        
        dctx = zstd.ZstdDecompressor()
        decompressed = dctx.decompress(blob)
        payload = json.loads(decompressed.decode("utf-8"))
        assert "e" in payload

    def test_replace_on_upsert(self, tmp_path):
        from batho.modules.storage.sqlite_registry.engine import BathoDatabase

        db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
        run_uuid = "build_upsert_001"
        run_id = db.create_run(run_uuid, root_path=str(tmp_path))

        agent1 = {"entities": [{"id": "e1", "name": "old"}]}
        agent2 = {"entities": [{"id": "e1", "name": "new"}]}
        storage_delta = {"entities": []}
        
        db.insert_file_artifact(run_id, "foo.py", "hash1", agent1, storage_delta, [])
        db.insert_file_artifact(run_id, "foo.py", "hash2", agent2, storage_delta, [])

        arts = db.get_file_artifacts(run_id)
        assert len(arts) == 1
        assert arts[0]["content_hash"] == "hash2"
        db.close()


class TestMinification:
    """Verify JSON key minification and expansion round-trip."""

    def test_entity_round_trip(self):
        from batho.modules.storage.sqlite_registry.engine import _minify_entity, _expand_entity

        entity = {
            "entity_type": "FUNCTION",
            "name": "parse",
            "file": "src/parser.py",
            "start_line": 10,
            "end_line": 20,
        }
        mini = _minify_entity(entity)
        assert "ty" in mini
        assert "n" in mini
        assert "entity_type" not in mini

        expanded = _expand_entity(mini)
        assert expanded["entity_type"] == "FUNCTION"
        assert expanded["name"] == "parse"

    def test_relationship_round_trip(self):
        from batho.modules.storage.sqlite_registry.engine import _minify_relationship, _expand_relationship

        rel = {"type": "CALLS", "source_id": "e1", "target_id": "e2"}
        mini = _minify_relationship(rel)
        assert "rt" in mini
        expanded = _expand_relationship(mini)
        assert expanded["type"] == "CALLS"

    def test_graph_payload_round_trip(self):
        from batho.modules.storage.sqlite_registry.engine import _minify_graph_payload, _expand_graph_payload

        original = {
            "entities": [{"id": "e1", "entity_type": "CLASS", "name": "Foo"}],
            "relationships": [{"id": "r1", "type": "USES", "source_id": "e1", "target_id": "e2"}],
        }
        mini = _minify_graph_payload(original)
        assert "e" in mini
        assert "r" in mini

        expanded = _expand_graph_payload(mini)
        assert "entities" in expanded
        assert "relationships" in expanded
        assert expanded["entities"][0]["name"] == "Foo"


class TestFileTracking:
    """Verify file tracking with string_dict indirection."""

    def test_upsert_and_retrieve(self, tmp_path):
        from batho.modules.storage.sqlite_registry.engine import BathoDatabase

        db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
        records = [
            {
                "file_path": "src/app.py",
                "content_hash": "deadbeef",
                "mtime": 1234567890.0,
                "size": 1024,
                "is_indexed": 1,
                "last_run_id": None,
            }
        ]
        db.upsert_file_tracking(records)
        row = db.get_file_tracking("src/app.py")
        assert row is not None
        assert row["content_hash"] == "deadbeef"
        db.close()

    def test_get_all_file_hashes(self, tmp_path):
        from batho.modules.storage.sqlite_registry.engine import BathoDatabase

        db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
        db.upsert_file_tracking([
            {"file_path": "a.py", "content_hash": "h1", "mtime": 1.0, "size": 10, "is_indexed": 1},
            {"file_path": "b.py", "content_hash": "h2", "mtime": 2.0, "size": 20, "is_indexed": 0},
        ])
        hashes = db.get_all_file_hashes()
        assert hashes == {"a.py": "h1", "b.py": "h2"}

        unindexed = db.get_unindexed_files()
        assert "b.py" in unindexed
        assert "a.py" not in unindexed
        db.close()

    def test_delete_tracking(self, tmp_path):
        from batho.modules.storage.sqlite_registry.engine import BathoDatabase

        db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
        db.upsert_file_tracking([
            {"file_path": "del.py", "content_hash": "xx", "mtime": 1.0, "size": 5, "is_indexed": 0}
        ])
        db.delete_file_tracking("del.py")
        assert db.get_file_tracking("del.py") is None
        db.close()





class TestInMemoryCache:
    """Verify BathoCache in-memory AST and snapshot behavior."""

    def test_ast_set_and_get(self, tmp_path):
        from batho.modules.storage.cache.unified_cache import BathoCache

        cache = BathoCache(str(tmp_path))
        cache.set_ast("/test/file.py", "hash1", ["entity_mock"], ["rel_mock"], 0.0, 100)
        result = cache.get_ast("/test/file.py", "hash1")
        assert result is not None
        assert result[0] == ["entity_mock"]

    def test_ast_missing_returns_none(self, tmp_path):
        from batho.modules.storage.cache.unified_cache import BathoCache

        cache = BathoCache(str(tmp_path))
        assert cache.get_ast("/test/nonexistent.py", "nonexistent") is None

    def test_clear_ast_cache(self, tmp_path):
        from batho.modules.storage.cache.unified_cache import BathoCache

        cache = BathoCache(str(tmp_path))
        cache.set_ast("/test/file1.py", "h1", [], [], 0.0, 100)
        cache.set_ast("/test/file2.py", "h2", [], [], 0.0, 100)
        count = cache.clear_ast_cache()
        assert count == 2
        assert cache.get_ast("/test/file1.py", "h1") is None

    def test_snapshot_round_trip(self, tmp_path):
        from batho.modules.storage.cache.unified_cache import BathoCache
        from batho.core.schemas import FileSnapshot

        cache = BathoCache(str(tmp_path))
        snap = FileSnapshot(
            file_path="src/foo.py",
            file_hash="abc",
            file_size=100,
        )
        cache.set_file_snapshot(snap)
        retrieved = cache.get_file_snapshot("src/foo.py")
        assert retrieved is not None
        assert retrieved.file_hash == "abc"

        cache.delete_file_snapshot("src/foo.py")
        assert cache.get_file_snapshot("src/foo.py") is None


class TestGetDatabase:
    """Verify get_database creates and caches correctly."""

    def test_creates_database(self, tmp_path):
        from batho.modules.storage.sqlite_registry.engine import get_database

        db = get_database(tmp_path)
        assert db is not None
        assert db.path.exists()
        close_all_databases()

    def test_returns_same_instance(self, tmp_path):
        from batho.modules.storage.sqlite_registry.engine import get_database

        db1 = get_database(tmp_path)
        db2 = get_database(tmp_path)
        assert db1 is db2
        close_all_databases()

    def test_stats(self, tmp_path):
        from batho.modules.storage.sqlite_registry.engine import get_database

        db = get_database(tmp_path)
        stats = db.get_stats()
        assert "schema_version" in stats
        assert "file_size_bytes" in stats
        close_all_databases()
