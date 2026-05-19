"""Tests for unresolved entity node lifecycle (Phase 9 of UNRESOLVED entity migration).

Covers:
- Creation: extractors emit UNRESOLVED entities instead of unresolved: strings
- Re-resolution: rebuilds attempt to re-resolve existing unresolved nodes
- Pruning: after max_attempts, unresolved nodes are auto-pruned
- File deletion: removing a file also removes its unresolved entities
- Validation: validate_graph_consistency accepts UNRESOLVED entity targets
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from batho.context.codegraph import CodeGraphIndexer, InMemoryGraph
from batho.context.schema import Entity, EntityType, Relationship, RelationshipType
from batho.context.symbol_index import SymbolIndex


def _unresolved_entity(
    name: str,
    file: str,
    line: int = 5,
    rel_type: str = "imports",
    attempts: int = 1,
) -> Entity:
    now = datetime.now(timezone.utc).isoformat()
    return Entity(
        type=EntityType.UNRESOLVED,
        name=name,
        file=file,
        start_line=line,
        end_line=line,
        metadata={
            "reference_type": rel_type,
            "resolution_reason": "not_found",
            "attempts": attempts,
            "created_at": now,
            "last_attempt": now,
            "is_visible": False,
        },
    )


def _real_entity(
    name: str,
    file: str,
    etype: EntityType = EntityType.FUNCTION,
    line: int = 1,
) -> Entity:
    return Entity(
        type=etype,
        name=name,
        file=file,
        start_line=line,
        end_line=line + 5,
    )


class TestUnresolvedEntityCreation:
    """Verify extractors create UNRESOLVED entities, not unresolved: strings."""

    def test_python_import_creates_unresolved_entity(self):
        from batho.context.languages.python import PythonExtractor

        extractor = PythonExtractor()
        # Python extractor's tree-sitter query doesn't match import_statement
        # (grammar uses child nodes, not named fields), so import UNRESOLVED
        # entities come from language extractors like R. Use call capture instead.
        source = b"def caller():\n    unknown_func()\n"
        entities, relationships = extractor.parse_file("test.py", source)

        unresolved = [e for e in entities if e.type == EntityType.UNRESOLVED]
        assert len(unresolved) >= 1
        assert any(e.name == "unknown_func" for e in unresolved)

        # Check UNRESOLVED entity metadata
        for e in unresolved:
            assert "reference_type" in e.metadata
            assert "resolution_reason" in e.metadata
            assert "attempts" in e.metadata
            assert "created_at" in e.metadata
            assert "last_attempt" in e.metadata
            assert "is_visible" in e.metadata
            assert e.metadata["is_visible"] is False

        # No relationships should use unresolved: string prefix
        for rel in relationships:
            assert not rel.target_id.startswith("unresolved:"), (
                f"Relationship should not have unresolved: prefix: {rel.target_id}"
            )

    def test_r_import_creates_unresolved_entity(self):
        from batho.context.languages.r import RExtractor

        extractor = RExtractor()
        # library() calls inside a function body produce import relationships
        source = b"foo <- function(x) x\nrun <- function() {\n    library(nonexistent_pkg)\n}\n"
        entities, relationships = extractor.parse_file("test.R", source)

        unresolved = [e for e in entities if e.type == EntityType.UNRESOLVED]
        assert len(unresolved) >= 1
        assert any(e.name == "nonexistent_pkg" for e in unresolved)

        for e in unresolved:
            if e.name == "nonexistent_pkg":
                assert "reference_type" in e.metadata
                assert e.metadata["reference_type"] == "imports"

        # No relationships should use unresolved: string prefix
        for rel in relationships:
            assert not rel.target_id.startswith("unresolved:")

    def test_python_call_creates_unresolved_entity(self):
        from batho.context.languages.python import PythonExtractor

        extractor = PythonExtractor()
        source = b"def main():\n    unknown_func()\n"
        entities, relationships = extractor.parse_file("test.py", source)

        unresolved = [e for e in entities if e.type == EntityType.UNRESOLVED]
        assert len(unresolved) >= 1
        assert any(e.name == "unknown_func" for e in unresolved)

        for rel in relationships:
            assert not rel.target_id.startswith("unresolved:")


class TestUnresolvedReResolution:
    """Verify rebuilds attempt to re-resolve existing unresolved nodes."""

    def test_re_resolve_on_rebuild(self, tmp_path: Path):
        cache_path = str(tmp_path / "cache.db")
        indexer = CodeGraphIndexer(cache_path=cache_path, root=str(tmp_path))

        source = _real_entity("caller", "src/main.py")
        target = _real_entity(
            "pkg.utils.helpers",
            "pkg/utils/helpers.py",
            etype=EntityType.MODULE,
        )
        unresolved = _unresolved_entity("pkg.utils.helpers", "src/main.py")

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
        resolved, resolved_count, _ = indexer._resolve_imports(
            graph, symbol_index=symbol_index,
        )

        # Should have resolved the unresolved entity
        assert resolved_count == 1
        # The unresolved entity should be removed
        assert unresolved.id not in resolved.entities
        # The relationship should now point to the real target
        import_rels = [
            r for r in resolved.relationships
            if r.source_id == source.id and r.type == RelationshipType.IMPORTS
        ]
        assert len(import_rels) >= 1
        assert any(r.target_id == target.id for r in import_rels)

    def test_unresolved_remains_when_no_match(self, tmp_path: Path):
        cache_path = str(tmp_path / "cache.db")
        indexer = CodeGraphIndexer(cache_path=cache_path, root=str(tmp_path))

        source = _real_entity("caller", "src/main.py")
        # No matching entity for "nonexistent.lib"
        unresolved = _unresolved_entity("nonexistent.lib", "src/main.py")

        graph = InMemoryGraph()
        graph.add_entity(source)
        graph.add_entity(unresolved)
        graph.add_relationship(
            Relationship(
                source_id=source.id,
                target_id=unresolved.id,
                type=RelationshipType.IMPORTS,
            )
        )

        symbol_index = SymbolIndex.build(graph)
        resolved, resolved_count, _ = indexer._resolve_imports(
            graph, symbol_index=symbol_index,
        )

        # Should NOT have resolved
        assert resolved_count == 0
        # The unresolved entity should still exist
        assert unresolved.id in resolved.entities


class TestUnresolvedPruning:
    """Verify unresolved nodes are pruned after max_attempts."""

    def test_pruned_after_max_attempts(self, tmp_path: Path):
        cache_path = str(tmp_path / "cache.db")
        indexer = CodeGraphIndexer(cache_path=cache_path, root=str(tmp_path))

        source = _real_entity("caller", "src/main.py")
        # Entity that has already been attempted many times
        unresolved = _unresolved_entity(
            "nonexistent.lib", "src/main.py", attempts=10,
        )

        graph = InMemoryGraph()
        graph.add_entity(source)
        graph.add_entity(unresolved)
        graph.add_relationship(
            Relationship(
                source_id=source.id,
                target_id=unresolved.id,
                type=RelationshipType.IMPORTS,
            )
        )

        symbol_index = SymbolIndex.build(graph)
        resolved, _, pruned_count = indexer._resolve_imports(
            graph,
            symbol_index=symbol_index,
            max_unresolved_attempts=10,
            prune_unresolved=True,
        )

        # Should be pruned (attempts=10 + 1 >= max_attempts=10)
        assert pruned_count == 1
        assert unresolved.id not in resolved.entities

    def test_not_pruned_when_below_threshold(self, tmp_path: Path):
        cache_path = str(tmp_path / "cache.db")
        indexer = CodeGraphIndexer(cache_path=cache_path, root=str(tmp_path))

        source = _real_entity("caller", "src/main.py")
        unresolved = _unresolved_entity(
            "nonexistent.lib", "src/main.py", attempts=1,
        )

        graph = InMemoryGraph()
        graph.add_entity(source)
        graph.add_entity(unresolved)
        graph.add_relationship(
            Relationship(
                source_id=source.id,
                target_id=unresolved.id,
                type=RelationshipType.IMPORTS,
            )
        )

        symbol_index = SymbolIndex.build(graph)
        resolved, _, pruned_count = indexer._resolve_imports(
            graph,
            symbol_index=symbol_index,
            max_unresolved_attempts=10,
            prune_unresolved=True,
        )

        # Should NOT be pruned (attempts=2 < 10)
        assert pruned_count == 0
        assert unresolved.id in resolved.entities

    def test_pruning_disabled(self, tmp_path: Path):
        cache_path = str(tmp_path / "cache.db")
        indexer = CodeGraphIndexer(cache_path=cache_path, root=str(tmp_path))

        source = _real_entity("caller", "src/main.py")
        unresolved = _unresolved_entity(
            "nonexistent.lib", "src/main.py", attempts=20,
        )

        graph = InMemoryGraph()
        graph.add_entity(source)
        graph.add_entity(unresolved)
        graph.add_relationship(
            Relationship(
                source_id=source.id,
                target_id=unresolved.id,
                type=RelationshipType.IMPORTS,
            )
        )

        symbol_index = SymbolIndex.build(graph)
        resolved, _, pruned_count = indexer._resolve_imports(
            graph,
            symbol_index=symbol_index,
            max_unresolved_attempts=10,
            prune_unresolved=False,
        )

        # Should NOT be pruned even though attempts > max
        assert pruned_count == 0
        assert unresolved.id in resolved.entities


class TestUnresolvedFileDeletion:
    """Verify file deletion removes associated unresolved nodes."""

    def test_remove_unresolved_on_file_deletion(self):
        from batho.context.codegraph import IncrementalGraphUpdater

        updater = IncrementalGraphUpdater()
        target_file = "src/deleted.py"

        real = _real_entity("real_func", target_file)
        unresolved = _unresolved_entity("missing_ref", target_file)

        graph = InMemoryGraph()
        graph.add_entity(real)
        graph.add_entity(unresolved)
        graph.add_relationship(
            Relationship(
                source_id=real.id,
                target_id=unresolved.id,
                type=RelationshipType.CALLS,
            )
        )

        # Simulate file deletion
        updater.remove_entities_for_file(graph, target_file)

        # Both the real entity and the unresolved entity should be removed
        assert real.id not in graph.entities
        assert unresolved.id not in graph.entities
        # The relationship should also be removed
        assert len(graph.relationships) == 0

    def test_other_file_unresolved_preserved(self):
        from batho.context.codegraph import IncrementalGraphUpdater

        updater = IncrementalGraphUpdater()
        deleted_file = "src/deleted.py"
        kept_file = "src/kept.py"

        real_deleted = _real_entity("real_deleted", deleted_file)
        unresolved_deleted = _unresolved_entity("missing_deleted", deleted_file)
        real_kept = _real_entity("real_kept", kept_file)
        unresolved_kept = _unresolved_entity("missing_kept", kept_file)

        graph = InMemoryGraph()
        for e in [real_deleted, unresolved_deleted, real_kept, unresolved_kept]:
            graph.add_entity(e)

        # Delete only the deleted_file
        updater.remove_entities_for_file(graph, deleted_file)

        # Deleted file entities should be gone
        assert real_deleted.id not in graph.entities
        assert unresolved_deleted.id not in graph.entities
        # Kept file entities should be preserved
        assert real_kept.id in graph.entities
        assert unresolved_kept.id in graph.entities


class TestUnresolvedValidation:
    """Verify validate_graph_consistency handles UNRESOLVED entities."""

    def test_unresolved_entity_target_is_valid(self):
        from batho.context.codegraph import IncrementalGraphUpdater

        updater = IncrementalGraphUpdater()

        source = _real_entity("caller", "src/main.py")
        unresolved = _unresolved_entity("missing_ref", "src/main.py")

        graph = InMemoryGraph()
        graph.add_entity(source)
        graph.add_entity(unresolved)
        graph.add_relationship(
            Relationship(
                source_id=source.id,
                target_id=unresolved.id,
                type=RelationshipType.CALLS,
            )
        )

        assert updater.validate_graph_consistency(graph) is True

    def test_dotted_identifier_not_valid_target(self):
        """Dotted identifiers like 'batho.context.codegraph' are no longer valid targets."""
        from batho.context.codegraph import IncrementalGraphUpdater

        updater = IncrementalGraphUpdater()

        source = _real_entity("caller", "src/main.py")
        graph = InMemoryGraph()
        graph.add_entity(source)
        graph.add_relationship(
            Relationship(
                source_id=source.id,
                target_id="batho.context.codegraph",
                type=RelationshipType.IMPORTS,
            )
        )

        # This should fail because batho.context.codegraph is not a real entity
        assert updater.validate_graph_consistency(graph) is False


class TestUnresolvedAttemptTracking:
    """Verify attempt counter increments on failed resolution."""

    def test_attempt_counter_increments(self, tmp_path: Path):
        cache_path = str(tmp_path / "cache.db")
        indexer = CodeGraphIndexer(cache_path=cache_path, root=str(tmp_path))

        source = _real_entity("caller", "src/main.py")
        unresolved = _unresolved_entity(
            "nonexistent.lib", "src/main.py", attempts=1,
        )

        graph = InMemoryGraph()
        graph.add_entity(source)
        graph.add_entity(unresolved)
        graph.add_relationship(
            Relationship(
                source_id=source.id,
                target_id=unresolved.id,
                type=RelationshipType.IMPORTS,
            )
        )

        symbol_index = SymbolIndex.build(graph)
        resolved, _, _ = indexer._resolve_imports(
            graph,
            symbol_index=symbol_index,
            max_unresolved_attempts=100,  # high threshold to avoid pruning
            prune_unresolved=True,
        )

        # Entity should still exist with incremented attempts
        updated = resolved.entities.get(unresolved.id)
        assert updated is not None
        assert updated.metadata.get("attempts") == 2
        assert "last_attempt" in updated.metadata


class TestSymbolIndexExcludesUnresolved:
    """Verify SymbolIndex does not include UNRESOLVED entities."""

    def test_unresolved_not_in_symbol_index(self):
        source = _real_entity("caller", "src/main.py")
        unresolved = _unresolved_entity("test_ref", "src/main.py")

        graph = InMemoryGraph()
        graph.add_entity(source)
        graph.add_entity(unresolved)

        symbol_index = SymbolIndex.build(graph)

        # "test_ref" should NOT be in the symbol index because
        # the UNRESOLVED entity is excluded
        assert symbol_index.names.get("test_ref") is None
        assert symbol_index.names.get("caller") is not None
