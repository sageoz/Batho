"""Tests for batho_core.context.codegraph module."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from batho_core.context.codegraph import (
    CodeGraphIndexer,
    InMemoryGraph,
    _FileStateCache,
)
from batho_core.utils.file_io import _calculate_shannon_entropy, _is_binary, _read_file_content
from batho_core.context.schema import Entity, EntityType, Relationship, RelationshipType


# ---------------------------------------------------------------------------
# _calculate_shannon_entropy
# ---------------------------------------------------------------------------

class TestShannonEntropy:

    def test_empty_data(self):
        assert _calculate_shannon_entropy(b"") == 0.0

    def test_uniform_bytes(self):
        """All same bytes → 0 entropy."""
        assert _calculate_shannon_entropy(b"\x00" * 100) == 0.0

    def test_two_values(self):
        """50/50 split → 1.0 bit."""
        data = b"\x00" * 50 + b"\x01" * 50
        assert abs(_calculate_shannon_entropy(data) - 1.0) < 0.01

    def test_high_entropy(self):
        """Random-looking data → high entropy."""
        data = bytes(range(256)) * 4
        entropy = _calculate_shannon_entropy(data)
        assert entropy > 7.5


# ---------------------------------------------------------------------------
# _is_binary
# ---------------------------------------------------------------------------

class TestIsBinary:

    def test_empty_not_binary(self):
        assert not _is_binary(b"")

    def test_png_header(self):
        assert _is_binary(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    def test_pdf_header(self):
        assert _is_binary(b"%PDF-1.4 " + b"\x00" * 100)

    def test_elf_header(self):
        assert _is_binary(b"\x7fELF" + b"\x00" * 100)

    def test_jpeg_header(self):
        assert _is_binary(b"\xff\xd8\xff" + b"\x00" * 100)

    def test_python_source(self):
        assert not _is_binary(b"def hello():\n    print('hi')\n")

    def test_null_bytes_ratio(self):
        """High null byte ratio → binary."""
        data = b"\x00" * 50 + b"text"
        assert _is_binary(data)


# ---------------------------------------------------------------------------
# _read_file_content
# ---------------------------------------------------------------------------

class TestReadFileContent:

    def test_reads_text_file(self, tmp_path: Path):
        f = tmp_path / "code.py"
        f.write_text("print('hello')\n")
        result = _read_file_content(str(f))
        assert result is not None

    def test_returns_none_for_binary(self, tmp_path: Path):
        f = tmp_path / "image.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)
        assert _read_file_content(str(f)) is None

    def test_returns_none_for_oversized(self, tmp_path: Path):
        f = tmp_path / "huge.py"
        f.write_bytes(b"x" * 600_000)
        assert _read_file_content(str(f), max_size_kb=500) is None

    def test_returns_none_for_missing(self):
        assert _read_file_content("/no/file.py") is None


# ---------------------------------------------------------------------------
# InMemoryGraph
# ---------------------------------------------------------------------------

class TestInMemoryGraph:

    def test_add_and_get_entity(self):
        graph = InMemoryGraph()
        e = Entity(type=EntityType.FUNCTION, name="f", file="a.py", start_line=1, end_line=2)
        graph.add_entity(e)
        assert graph.get_entity(e.id) is e

    def test_add_relationship(self):
        graph = InMemoryGraph()
        r = Relationship(source_id="a", target_id="b", type=RelationshipType.CALLS)
        graph.add_relationship(r)
        assert len(graph.relationships) == 1

    def test_neighbors_out(self):
        graph = InMemoryGraph()
        r = Relationship(source_id="a", target_id="b", type=RelationshipType.CALLS)
        graph.add_relationship(r)
        assert "b" in graph.neighbors("a", "out")

    def test_neighbors_in(self):
        graph = InMemoryGraph()
        r = Relationship(source_id="a", target_id="b", type=RelationshipType.CALLS)
        graph.add_relationship(r)
        assert "a" in graph.neighbors("b", "in")

    def test_neighbors_both(self):
        graph = InMemoryGraph()
        graph.add_relationship(Relationship(source_id="a", target_id="b", type=RelationshipType.CALLS))
        result = graph.neighbors("a", "both")
        assert "b" in result

    def test_entities_by_file(self):
        graph = InMemoryGraph()
        e1 = Entity(type=EntityType.FUNCTION, name="f", file="a.py", start_line=1, end_line=2)
        e2 = Entity(type=EntityType.FUNCTION, name="g", file="b.py", start_line=1, end_line=2)
        graph.add_entity(e1)
        graph.add_entity(e2)
        assert len(graph.entities_by_file("a.py")) == 1

    def test_entities_by_type(self):
        graph = InMemoryGraph()
        graph.add_entity(Entity(type=EntityType.FUNCTION, name="f", file="a.py", start_line=1, end_line=2))
        graph.add_entity(Entity(type=EntityType.CLASS, name="C", file="a.py", start_line=5, end_line=10))
        assert len(graph.entities_by_type(EntityType.FUNCTION)) == 1

    def test_root_entities(self):
        graph = InMemoryGraph()
        e1 = Entity(type=EntityType.FUNCTION, name="f", file="a.py", start_line=1, end_line=2)
        e2 = Entity(type=EntityType.METHOD, name="m", file="a.py", start_line=3, end_line=4, parent_id="some_id")
        graph.add_entity(e1)
        graph.add_entity(e2)
        roots = graph.root_entities()
        assert len(roots) == 1
        assert roots[0].name == "f"

    def test_stats(self):
        graph = InMemoryGraph()
        graph.add_entity(Entity(type=EntityType.FUNCTION, name="f", file="a.py", start_line=1, end_line=2))
        s = graph.stats()
        assert s["entity_count"] == 1
        assert s["file_count"] == 1

    def test_len_and_contains(self):
        graph = InMemoryGraph()
        e = Entity(type=EntityType.FUNCTION, name="f", file="a.py", start_line=1, end_line=2)
        graph.add_entity(e)
        assert len(graph) == 1
        assert e.id in graph

    def test_repr(self):
        graph = InMemoryGraph()
        assert "InMemoryGraph" in repr(graph)

    def test_to_dict_from_dict_roundtrip(self, mock_graph):
        d = mock_graph.to_dict()
        restored = InMemoryGraph.from_dict(d)
        assert len(restored.entities) == len(mock_graph.entities)
        assert len(restored.relationships) == len(mock_graph.relationships)


# ---------------------------------------------------------------------------
# _FileStateCache
# ---------------------------------------------------------------------------

class TestFileStateCache:

    def test_save_and_load(self, tmp_path: Path):
        cache_path = tmp_path / "cache.json"
        cache = _FileStateCache(cache_path)
        cache.update("src/main.py", 1234.0, "abc123")
        cache.save()

        cache2 = _FileStateCache(cache_path)
        assert cache2.is_cached("src/main.py", "abc123")

    def test_is_cached_miss(self, tmp_path: Path):
        cache = _FileStateCache(tmp_path / "cache.json")
        assert not cache.is_cached("missing.py", "hash")

    def test_invalidate(self, tmp_path: Path):
        cache = _FileStateCache(tmp_path / "cache.json")
        cache.update("a.py", 1.0, "h1")
        assert cache.is_cached("a.py", "h1")
        cache.invalidate("a.py")
        assert not cache.is_cached("a.py", "h1")

    def test_path_normalization(self, tmp_path: Path):
        root = tmp_path / "repo"
        root.mkdir()
        cache = _FileStateCache(tmp_path / "cache.json", root=root)
        abs_path = str(root / "src" / "main.py")
        cache.update(abs_path, 1.0, "hash1")
        assert cache.is_cached(abs_path, "hash1")

    def test_corrupted_checksum(self, tmp_path: Path):
        cache_path = tmp_path / "cache.json"
        cache_path.write_text(json.dumps({
            "schema_version": "file-cache.v1",
            "files": {"a.py": {"mtime": 1.0, "sha256": "h1"}},
            "_checksum": "invalid_checksum",
        }))
        cache = _FileStateCache(cache_path)
        # Should not load corrupted data
        assert not cache.is_cached("a.py", "h1")
        backups = list(tmp_path.glob("cache.json.corrupt.*"))
        assert backups
        assert not cache_path.exists()


# ---------------------------------------------------------------------------
# CodeGraphIndexer
# ---------------------------------------------------------------------------

class TestCodeGraphIndexer:

    def test_build_graph_simple_python(self, simple_python_repo: Path, tmp_path: Path):
        cache_path = tmp_path / "cache.json"
        indexer = CodeGraphIndexer(cache_path=str(cache_path), root=str(simple_python_repo))
        graph = indexer.build_graph(root=str(simple_python_repo))
        assert len(graph.entities) > 0
        assert len(graph.relationships) >= 0

    def test_build_graph_caches(self, simple_python_repo: Path, tmp_path: Path):
        """Second run should hit cache entries."""
        cache_path = tmp_path / "cache.json"
        indexer = CodeGraphIndexer(cache_path=str(cache_path), root=str(simple_python_repo))
        graph1 = indexer.build_graph(root=str(simple_python_repo))
        stats1 = indexer.stats

        indexer2 = CodeGraphIndexer(cache_path=str(cache_path), root=str(simple_python_repo))
        graph2 = indexer2.build_graph(root=str(simple_python_repo))
        stats2 = indexer2.stats

        assert stats2["files_cached"] >= stats1.get("files_cached", 0)

    def test_build_graph_empty_dir(self, tmp_path: Path):
        root = tmp_path / "empty"
        root.mkdir()
        cache_path = tmp_path / "cache.json"
        indexer = CodeGraphIndexer(cache_path=str(cache_path), root=str(root))
        graph = indexer.build_graph(root=str(root))
        assert len(graph.entities) == 0

    def test_build_graph_with_extensions_filter(self, simple_python_repo: Path, tmp_path: Path):
        cache_path = tmp_path / "cache.json"
        indexer = CodeGraphIndexer(cache_path=str(cache_path), root=str(simple_python_repo))
        graph = indexer.build_graph(root=str(simple_python_repo), extensions=[".py"])
        # Should only index .py files
        for e in graph.entities.values():
            assert e.file.endswith(".py") or not Path(e.file).suffix

    def test_invalidate(self, tmp_path: Path):
        cache_path = tmp_path / "cache.json"
        indexer = CodeGraphIndexer(cache_path=str(cache_path))
        indexer._cache.update("test.py", 1.0, "hash1")
        indexer._cache.save()
        indexer.invalidate("test.py")
        assert not indexer._cache.is_cached("test.py", "hash1")
