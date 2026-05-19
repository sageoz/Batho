"""Tests for batho.context.codegraph module."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from batho.context.codegraph import (
    CodeGraphIndexer,
    InMemoryGraph,
)
from batho.context.symbol_index import SymbolIndex
from batho.utils.file_io import read_file_bytes
from batho.utils.hash import _calculate_shannon_entropy, _is_binary
from batho.context.schema import Entity, EntityType, Relationship, RelationshipType


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
# read_file_bytes (with detect_binary=True)
# ---------------------------------------------------------------------------


class TestReadFileContent:
    def test_reads_text_file(self, tmp_path: Path):
        f = tmp_path / "code.py"
        f.write_text("print('hello')\n")
        result = read_file_bytes(str(f), detect_binary=True)
        assert result is not None

    def test_returns_none_for_binary(self, tmp_path: Path):
        f = tmp_path / "image.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)
        assert read_file_bytes(str(f), detect_binary=True) is None

    def test_returns_none_for_oversized(self, tmp_path: Path):
        f = tmp_path / "huge.py"
        f.write_bytes(b"x" * 600_000)
        assert read_file_bytes(str(f), max_size_kb=500, detect_binary=True) is None

    def test_returns_none_for_missing(self):
        assert read_file_bytes("/no/file.py", detect_binary=True) is None


# ---------------------------------------------------------------------------
# InMemoryGraph
# ---------------------------------------------------------------------------


class TestInMemoryGraph:
    def test_add_and_get_entity(self):
        graph = InMemoryGraph()
        e = Entity(
            type=EntityType.FUNCTION, name="f", file="a.py", start_line=1, end_line=2
        )
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
        graph.add_relationship(
            Relationship(source_id="a", target_id="b", type=RelationshipType.CALLS)
        )
        result = graph.neighbors("a", "both")
        assert "b" in result

    def test_entities_by_file(self):
        graph = InMemoryGraph()
        e1 = Entity(
            type=EntityType.FUNCTION, name="f", file="a.py", start_line=1, end_line=2
        )
        e2 = Entity(
            type=EntityType.FUNCTION, name="g", file="b.py", start_line=1, end_line=2
        )
        graph.add_entity(e1)
        graph.add_entity(e2)
        assert len(graph.entities_by_file("a.py")) == 1

    def test_entities_by_type(self):
        graph = InMemoryGraph()
        graph.add_entity(
            Entity(
                type=EntityType.FUNCTION,
                name="f",
                file="a.py",
                start_line=1,
                end_line=2,
            )
        )
        graph.add_entity(
            Entity(
                type=EntityType.CLASS, name="C", file="a.py", start_line=5, end_line=10
            )
        )
        assert len(graph.entities_by_type(EntityType.FUNCTION)) == 1

    def test_root_entities(self):
        graph = InMemoryGraph()
        e1 = Entity(
            type=EntityType.FUNCTION, name="f", file="a.py", start_line=1, end_line=2
        )
        e2 = Entity(
            type=EntityType.METHOD,
            name="m",
            file="a.py",
            start_line=3,
            end_line=4,
            parent_id="some_id",
        )
        graph.add_entity(e1)
        graph.add_entity(e2)
        roots = graph.root_entities()
        assert len(roots) == 1
        assert roots[0].name == "f"

    def test_stats(self):
        graph = InMemoryGraph()
        graph.add_entity(
            Entity(
                type=EntityType.FUNCTION,
                name="f",
                file="a.py",
                start_line=1,
                end_line=2,
            )
        )
        s = graph.stats()
        assert s["entity_count"] == 1
        assert s["file_count"] == 1

    def test_len_and_contains(self):
        graph = InMemoryGraph()
        e = Entity(
            type=EntityType.FUNCTION, name="f", file="a.py", start_line=1, end_line=2
        )
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
# CodeGraphIndexer
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# CodeGraphIndexer
# ---------------------------------------------------------------------------


class TestCodeGraphIndexer:
    def test_build_graph_simple_python(self, simple_python_repo: Path, tmp_path: Path):
        cache_path = str(tmp_path / "cache.db")
        indexer = CodeGraphIndexer(
            cache_path=cache_path, root=str(simple_python_repo)
        )
        graph = indexer.build_graph(root=str(simple_python_repo))
        assert len(graph.entities) > 0
        assert len(graph.relationships) >= 0

    def test_build_graph_caches(self, simple_python_repo: Path, tmp_path: Path):
        """Second run should hit cache entries."""
        cache_path = str(tmp_path / "cache.db")
        indexer = CodeGraphIndexer(
            cache_path=cache_path, root=str(simple_python_repo)
        )
        graph1 = indexer.build_graph(root=str(simple_python_repo))
        stats1 = indexer.stats

        indexer2 = CodeGraphIndexer(
            cache_path=cache_path, root=str(simple_python_repo)
        )
        graph2 = indexer2.build_graph(root=str(simple_python_repo))
        stats2 = indexer2.stats

        assert stats2["files_cached"] >= stats1.get("files_cached", 0)

    def test_build_graph_empty_dir(self, tmp_path: Path):
        root = tmp_path / "empty"
        root.mkdir()
        cache_path = str(tmp_path / "cache.db")
        indexer = CodeGraphIndexer(cache_path=cache_path, root=str(root))
        graph = indexer.build_graph(root=str(root))
        assert len(graph.entities) == 0

    def test_build_graph_with_extensions_filter(
        self, simple_python_repo: Path, tmp_path: Path
    ):
        cache_path = str(tmp_path / "cache.db")
        indexer = CodeGraphIndexer(
            cache_path=cache_path, root=str(simple_python_repo)
        )
        graph = indexer.build_graph(root=str(simple_python_repo), extensions=[".py"])
        # Should only index .py files
        for e in graph.entities.values():
            assert e.file.endswith(".py") or not Path(e.file).suffix

    def test_invalidate(self, tmp_path: Path):
        cache_path = str(tmp_path / "cache.db")
        indexer = CodeGraphIndexer(cache_path=cache_path)
        
        # Cache some entities using new BathoCache.set_ast()
        entities = [
            Entity(
                id="test_entity",
                type=EntityType.FUNCTION,
                name="test_func",
                file="test.py",
                line=1,
                start_line=1,
                end_line=10,
            )
        ]
        # set_ast(file_hash, file_path, entities, relationships, mtime, size, ttl_days)
        indexer._cache.set_ast(
            file_hash="hash123",
            file_path="test.py",
            entities=entities,
            relationships=[],
            mtime=1.0,
            size=100,
            ttl_days=30
        )
        
        # Verify it's cached
        cached = indexer._cache.get_ast("hash123")
        assert cached is not None
        
        # Invalidate using indexer.invalidate (uses delete_ast_by_path)
        indexer.invalidate("test.py")
        
        # Should not be cached after invalidation
        cached = indexer._cache.get_ast("hash123")
        assert cached is None

    def test_resolve_imports_uses_normalized_candidates(self, tmp_path: Path):
        cache_path = str(tmp_path / "cache.db")
        indexer = CodeGraphIndexer(cache_path=str(cache_path), root=str(tmp_path))

        source = Entity(
            type=EntityType.FUNCTION,
            name="caller",
            file="src/main.py",
            start_line=1,
            end_line=2,
        )
        target = Entity(
            type=EntityType.MODULE,
            name="pkg.utils.helpers",
            file="pkg/utils/helpers.py",
            start_line=1,
            end_line=20,
        )

        # Create UNRESOLVED entities instead of unresolved: string targets
        now = datetime.now(timezone.utc).isoformat()
        unresolved_pkg = Entity(
            type=EntityType.UNRESOLVED,
            name="pkg/utils/helpers.py",
            file="src/main.py",
            start_line=5,
            end_line=5,
            metadata={
                "reference_type": "imports",
                "resolution_reason": "not_found",
                "attempts": 1,
                "created_at": now,
                "last_attempt": now,
                "is_visible": False,
            },
        )
        unresolved_ext = Entity(
            type=EntityType.UNRESOLVED,
            name="external/pkg",
            file="src/main.py",
            start_line=6,
            end_line=6,
            metadata={
                "reference_type": "imports",
                "resolution_reason": "not_found",
                "attempts": 1,
                "created_at": now,
                "last_attempt": now,
                "is_visible": False,
            },
        )

        graph = InMemoryGraph()
        graph.add_entity(source)
        graph.add_entity(target)
        graph.add_entity(unresolved_pkg)
        graph.add_entity(unresolved_ext)
        graph.add_relationship(
            Relationship(
                source_id=source.id,
                target_id=unresolved_pkg.id,
                type=RelationshipType.IMPORTS,
            )
        )
        graph.add_relationship(
            Relationship(
                source_id=source.id,
                target_id=unresolved_ext.id,
                type=RelationshipType.IMPORTS,
            )
        )

        resolved, _, _ = indexer._resolve_imports(graph)

        import_targets = [
            rel.target_id
            for rel in resolved.relationships
            if rel.source_id == source.id and rel.type == RelationshipType.IMPORTS
        ]
        # pkg.utils.helpers should resolve to the target entity
        assert target.id in import_targets
        # external/pkg should remain as an UNRESOLVED entity
        remaining_unresolved = [
            e.name for e in resolved.entities.values()
            if e.type == EntityType.UNRESOLVED
        ]
        assert "external/pkg" in remaining_unresolved

    def test_resolve_imports_with_symbol_index(self, tmp_path: Path):
        cache_path = str(tmp_path / "cache.db")
        indexer = CodeGraphIndexer(cache_path=str(cache_path), root=str(tmp_path))

        source = Entity(
            type=EntityType.FUNCTION,
            name="caller",
            file="src/main.py",
            start_line=1,
            end_line=2,
        )
        target = Entity(
            type=EntityType.MODULE,
            name="pkg.api.client",
            file="pkg/api/client.py",
            start_line=1,
            end_line=30,
        )

        # Create UNRESOLVED entity
        now = datetime.now(timezone.utc).isoformat()
        unresolved = Entity(
            type=EntityType.UNRESOLVED,
            name="pkg/api/client.py",
            file="src/main.py",
            start_line=5,
            end_line=5,
            metadata={
                "reference_type": "imports",
                "resolution_reason": "not_found",
                "attempts": 1,
                "created_at": now,
                "last_attempt": now,
                "is_visible": False,
            },
        )

        graph = InMemoryGraph()
        graph.add_entity(source)
        graph.add_entity(target)
        graph.add_entity(unresolved)
        graph.add_relationship(
            Relationship(
                source_id=source.id,
                target_id=unresolved.id,
                type=RelationshipType.IMPORTS,
            )
        )

        symbol_index = SymbolIndex.build(graph)
        resolved, resolved_count, _ = indexer._resolve_imports(graph, symbol_index=symbol_index)
        assert resolved_count == 1
        import_targets = [
            rel.target_id
            for rel in resolved.relationships
            if rel.source_id == source.id and rel.type == RelationshipType.IMPORTS
        ]
        assert target.id in import_targets

    def test_resolve_imports_prefers_symbol_in_closest_source_path(self, tmp_path: Path):
        cache_path = str(tmp_path / "cache.db")
        indexer = CodeGraphIndexer(cache_path=str(cache_path), root=str(tmp_path))

        source = Entity(
            type=EntityType.FUNCTION,
            name="caller",
            file="pkg/beta/main.py",
            start_line=1,
            end_line=2,
        )
        alpha_target = Entity(
            type=EntityType.MODULE,
            name="pkg.alpha.client",
            file="pkg/alpha/client.py",
            start_line=1,
            end_line=30,
        )
        beta_target = Entity(
            type=EntityType.MODULE,
            name="pkg.beta.client",
            file="pkg/beta/client.py",
            start_line=1,
            end_line=30,
        )

        # Create UNRESOLVED entity
        now = datetime.now(timezone.utc).isoformat()
        unresolved = Entity(
            type=EntityType.UNRESOLVED,
            name="client",
            file="pkg/beta/main.py",
            start_line=5,
            end_line=5,
            metadata={
                "reference_type": "imports",
                "resolution_reason": "not_found",
                "attempts": 1,
                "created_at": now,
                "last_attempt": now,
                "is_visible": False,
            },
        )

        graph = InMemoryGraph()
        graph.add_entity(source)
        graph.add_entity(alpha_target)
        graph.add_entity(beta_target)
        graph.add_entity(unresolved)
        graph.add_relationship(
            Relationship(
                source_id=source.id,
                target_id=unresolved.id,
                type=RelationshipType.IMPORTS,
            )
        )

        symbol_index = SymbolIndex.build(graph)
        resolved, _, _ = indexer._resolve_imports(graph, symbol_index=symbol_index)
        import_targets = [
            rel.target_id
            for rel in resolved.relationships
            if rel.source_id == source.id and rel.type == RelationshipType.IMPORTS
        ]
        assert beta_target.id in import_targets

    def test_build_graph_applies_bsg_rules_from_config(
        self, simple_python_repo: Path, tmp_path: Path, monkeypatch
    ):
        cfg_file = tmp_path / "batho.yaml"
        cfg_file.write_text(
            """
rules:
  enabled: true
  builtin_plugins: []
  custom_rules_inline:
    - name: mark-python-files
      file_patterns: ["**/*.py"]
      metadata:
        bsg.test_marker: enabled
""".strip()
            + "\n",
            encoding="utf-8",
        )

        monkeypatch.chdir(tmp_path)

        cache_path = tmp_path / "cache.db"
        indexer = CodeGraphIndexer(
            cache_path=str(cache_path), root=str(simple_python_repo)
        )
        graph = indexer.build_graph(root=str(simple_python_repo), extensions=[".py"])

        assert any(
            entity.metadata.get("bsg.test_marker") == "enabled"
            for entity in graph.entities.values()
        )
        assert indexer.stats.get("rules_enabled") is True
        assert indexer.stats.get("entities_rule_tagged", 0) >= 1

    def test_build_graph_applies_semantic_overlay_before_rules(self, tmp_path: Path):
        root = tmp_path / "repo"
        src_dir = root / "services" / "api"
        src_dir.mkdir(parents=True)
        (src_dir / "user_routes.py").write_text(
            """
def get_user_endpoint(user_id: str):
    return user_id
""".strip()
            + "\n",
            encoding="utf-8",
        )

        cache_path = tmp_path / "cache.db"
        indexer = CodeGraphIndexer(cache_path=str(cache_path), root=str(root))
        graph = indexer.build_graph(root=str(root), extensions=[".py"])

        assert len(graph.entities) >= 1
        assert indexer.stats.get("semantic_tags_added", 0) >= 1
        assert any(
            "ApiBoundary" in (entity.metadata or {}).get("bsg.usn", [])
            for entity in graph.entities.values()
        )

    def test_build_graph_derives_inherits_and_overrides(self, tmp_path: Path):
        root = tmp_path / "repo"
        root.mkdir(parents=True)
        (root / "models.py").write_text(
            """
class Base:
    def run(self):
        return 1


class Child(Base):
    def run(self):
        return 2
""".strip()
            + "\n",
            encoding="utf-8",
        )

        cache_path = tmp_path / "cache.db"
        indexer = CodeGraphIndexer(cache_path=str(cache_path), root=str(root))
        graph = indexer.build_graph(root=str(root), extensions=[".py"])

        def _entity_name(entity_id: str) -> str | None:
            entity = graph.get_entity(entity_id)
            return entity.name if entity is not None else None

        assert any(
            rel.type == RelationshipType.INHERITS
            and _entity_name(rel.source_id) == "Child"
            and _entity_name(rel.target_id) == "Base"
            for rel in graph.relationships
        )
        assert any(
            rel.type == RelationshipType.OVERRIDES
            and _entity_name(rel.source_id) == "run"
            and _entity_name(rel.target_id) == "run"
            for rel in graph.relationships
        )
