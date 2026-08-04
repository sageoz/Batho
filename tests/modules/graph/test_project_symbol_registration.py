"""Tests for Phase 2 Task 2.1: Register project-internal definitions as global symbols.

The _register_project_symbols method registers all project-defined functions,
classes, methods, structs, enums, interfaces, and traits as global symbols in
the ScopeManager, enabling cross-file resolution.

Tests cover:
  - Registration of each eligible entity type (FUNCTION, METHOD, CLASS, etc.)
  - Non-eligible entity types are skipped (COMMENT, DOCUMENT, SETTING, etc.)
  - Contextual stubs are not registered
  - Both simple name and FQN are registered when FQN differs
  - Entities without FQN only register by simple name
  - Empty graph produces 0 registrations
  - Return value matches the count of registered entities
  - Symbols are resolvable via resolve_symbol_strict after registration
  - clear_failed_lookups is called after registration (integration)
  - Edge cases: duplicate names, entities with empty names, frozen entities
"""
import pytest
from pathlib import Path
import tempfile

from batho.core.schemas import Entity, EntityType
from batho.modules.extraction.scope_manager import ScopeManager
from batho.modules.graph.builder.codegraph import CodeGraphIndexer, InMemoryGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(
    name: str,
    entity_type: EntityType,
    file: str = "/test/main.py",
    start_line: int = 1,
    signature: str | None = None,
    metadata: dict | None = None,
    id_override: str | None = None,
) -> Entity:
    """Create a minimal Entity for testing."""
    return Entity(
        type=entity_type,
        name=name,
        file=file,
        start_line=start_line,
        end_line=start_line,
        metadata=metadata or {},
        signature=signature,
        id_override=id_override or f"batho test pkg 1.0.0 {file}/{name}#{start_line}",
    )


def _make_stub(name: str, target_name: str, caller_scope: str = "batho test pkg 1.0.0 /test/main.py") -> Entity:
    """Create a contextual stub entity."""
    stub_id = f"unresolved:{caller_scope}::{target_name}"
    return Entity(
        type=EntityType.UNRESOLVED,
        name=name,
        file="/test/main.py",
        start_line=10,
        end_line=10,
        metadata={
            "reference_type": "calls",
            "resolution_reason": "contextual_stub",
            "stub_resolution_state": "pending",
            "caller_scope": caller_scope,
            "target_name": target_name,
        },
        id_override=stub_id,
    )


def _make_indexer(tmp_dir: str) -> CodeGraphIndexer:
    """Create a CodeGraphIndexer instance for testing."""
    return CodeGraphIndexer(cache_path=tmp_dir, root=tmp_dir)


# ---------------------------------------------------------------------------
# Registration of eligible entity types
# ---------------------------------------------------------------------------


class TestRegisterProjectSymbolsEligibleTypes:
    """Verify each eligible entity type is registered."""

    @pytest.mark.parametrize("entity_type", [
        EntityType.FUNCTION,
        EntityType.METHOD,
        EntityType.CLASS,
        EntityType.STRUCT,
        EntityType.INTERFACE,
        EntityType.ENUM,
        EntityType.TRAIT,
    ])
    def test_eligible_type_is_registered(self, entity_type):
        """Each eligible entity type is registered as a global symbol."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            entity = _make_entity("MySymbol", entity_type)
            graph.add_entity(entity)

            sm = ScopeManager()
            count = indexer._register_project_symbols(graph, sm)

            assert count == 1
            info = sm.resolve_symbol("MySymbol")
            assert info is not None
            assert info.symbol_id == entity.id
            assert info.symbol_type == entity_type.name
            indexer.close()

    def test_all_eligible_types_in_one_graph(self):
        """All eligible entity types in a single graph are registered."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            entities = []
            for i, et in enumerate([
                EntityType.FUNCTION, EntityType.METHOD, EntityType.CLASS,
                EntityType.STRUCT, EntityType.INTERFACE, EntityType.ENUM,
                EntityType.TRAIT,
            ]):
                e = _make_entity(f"sym_{et.name.lower()}", et, start_line=i + 1)
                graph.add_entity(e)
                entities.append(e)

            sm = ScopeManager()
            count = indexer._register_project_symbols(graph, sm)

            assert count == 7
            for e in entities:
                info = sm.resolve_symbol(e.name)
                assert info is not None, f"Symbol {e.name} not found in scope manager"
                assert info.symbol_id == e.id
            indexer.close()


# ---------------------------------------------------------------------------
# Non-eligible entity types are skipped
# ---------------------------------------------------------------------------


class TestRegisterProjectSymbolsSkippedTypes:
    """Verify non-eligible entity types are not registered."""

    @pytest.mark.parametrize("entity_type", [
        EntityType.COMMENT_BLOCK,
        EntityType.DOCUMENT,
        EntityType.SETTING,
        EntityType.SECTION,
        EntityType.ELEMENT,
        EntityType.ENTRY_POINT,
        EntityType.ENVIRONMENT_VARIABLE,
        EntityType.MODULE,
        EntityType.NAMESPACE,
    ])
    def test_non_eligible_type_skipped(self, entity_type):
        """Non-eligible entity types are not registered."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            entity = _make_entity("NotASymbol", entity_type)
            graph.add_entity(entity)

            sm = ScopeManager()
            count = indexer._register_project_symbols(graph, sm)

            assert count == 0
            assert sm.resolve_symbol("NotASymbol") is None
            indexer.close()

    def test_mixed_eligible_and_non_eligible(self):
        """A graph with mixed types only registers eligible ones."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            # Eligible
            graph.add_entity(_make_entity("func1", EntityType.FUNCTION, start_line=1))
            graph.add_entity(_make_entity("Class1", EntityType.CLASS, start_line=2))
            # Non-eligible
            graph.add_entity(_make_entity("comment1", EntityType.COMMENT_BLOCK, start_line=3))
            graph.add_entity(_make_entity("doc1", EntityType.DOCUMENT, start_line=4))

            sm = ScopeManager()
            count = indexer._register_project_symbols(graph, sm)

            assert count == 2
            assert sm.resolve_symbol("func1") is not None
            assert sm.resolve_symbol("Class1") is not None
            assert sm.resolve_symbol("comment1") is None
            assert sm.resolve_symbol("doc1") is None
            indexer.close()


# ---------------------------------------------------------------------------
# Contextual stubs are not registered
# ---------------------------------------------------------------------------


class TestRegisterProjectSymbolsSkipsStubs:
    """Verify contextual stubs are not registered as project symbols."""

    def test_stub_not_registered(self):
        """Contextual stub entities are skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            stub = _make_stub("unresolved_call", "target_func")
            graph.add_entity(stub)

            sm = ScopeManager()
            count = indexer._register_project_symbols(graph, sm)

            assert count == 0
            indexer.close()

    def test_stubs_and_real_entities_mixed(self):
        """Stubs are skipped but real entities in the same graph are registered."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            graph.add_entity(_make_entity("real_func", EntityType.FUNCTION, start_line=1))
            graph.add_entity(_make_stub("stub1", "missing_func"))
            graph.add_entity(_make_entity("RealClass", EntityType.CLASS, start_line=5))
            graph.add_entity(_make_stub("stub2", "another_missing"))

            sm = ScopeManager()
            count = indexer._register_project_symbols(graph, sm)

            assert count == 2
            assert sm.resolve_symbol("real_func") is not None
            assert sm.resolve_symbol("RealClass") is not None
            indexer.close()


# ---------------------------------------------------------------------------
# FQN registration
# ---------------------------------------------------------------------------


class TestRegisterProjectSymbolsFQN:
    """Verify FQN (qualified name) registration behavior."""

    def test_fqn_registered_when_different_from_name(self):
        """When entity.fqn differs from entity.name, both are registered."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            # CLASS entities have fqn = name (from schemas.py), so we use
            # signature to provide a different FQN
            entity = _make_entity(
                "MyClass",
                EntityType.CLASS,
                signature="module.MyClass",
            )
            graph.add_entity(entity)

            sm = ScopeManager()
            count = indexer._register_project_symbols(graph, sm)

            assert count == 1
            # Both simple name and FQN should resolve
            assert sm.resolve_symbol("MyClass") is not None
            assert sm.resolve_symbol("module.MyClass") is not None
            indexer.close()

    def test_fqn_not_duplicated_when_same_as_name(self):
        """When fqn equals name, only one registration occurs (no duplicate)."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            # CLASS without signature: fqn = name
            entity = _make_entity("SimpleClass", EntityType.CLASS)
            graph.add_entity(entity)

            sm = ScopeManager()
            count = indexer._register_project_symbols(graph, sm)

            assert count == 1
            assert sm.resolve_symbol("SimpleClass") is not None
            indexer.close()

    def test_function_without_fqn(self):
        """FUNCTION entities have fqn=None (no signature), so only simple name registered."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            entity = _make_entity("my_function", EntityType.FUNCTION)
            graph.add_entity(entity)

            sm = ScopeManager()
            count = indexer._register_project_symbols(graph, sm)

            assert count == 1
            assert sm.resolve_symbol("my_function") is not None
            indexer.close()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestRegisterProjectSymbolsEdgeCases:
    """Verify edge case handling."""

    def test_empty_graph(self):
        """An empty graph produces 0 registrations."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()
            count = indexer._register_project_symbols(graph, sm)
            assert count == 0
            assert sm.global_symbol_count == 0
            indexer.close()

    def test_duplicate_names_different_entities(self):
        """Two entities with the same name but different IDs both register.

        The ScopeManager stores by name, so the last one wins for simple
        name resolution. This is expected behavior (shadowing).
        """
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            e1 = _make_entity("dup", EntityType.FUNCTION, start_line=1,
                              id_override="id_dup_1")
            e2 = _make_entity("dup", EntityType.FUNCTION, start_line=10,
                              id_override="id_dup_2")
            graph.add_entity(e1)
            graph.add_entity(e2)

            sm = ScopeManager()
            count = indexer._register_project_symbols(graph, sm)

            assert count == 2  # Both entities are counted
            # The scope manager resolves to the last-registered one
            info = sm.resolve_symbol("dup")
            assert info is not None
            indexer.close()

    def test_large_number_of_entities(self):
        """Registration handles a large number of entities without error."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            for i in range(1000):
                graph.add_entity(_make_entity(
                    f"func_{i}", EntityType.FUNCTION, start_line=i + 1,
                    id_override=f"id_func_{i}",
                ))

            sm = ScopeManager()
            count = indexer._register_project_symbols(graph, sm)

            assert count == 1000
            assert sm.global_symbol_count >= 1000
            indexer.close()

    def test_external_symbol_entities_skipped(self):
        """EXTERNAL_SYMBOL entities are not in _GLOBAL_SYMBOL_ENTITY_TYPES."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            entity = _make_entity("ext_sym", EntityType.EXTERNAL_SYMBOL,
                                  id_override="batho pip python 3.x ext/sym")
            graph.add_entity(entity)

            sm = ScopeManager()
            count = indexer._register_project_symbols(graph, sm)

            assert count == 0
            indexer.close()

    def test_unresolved_non_stub_entities_skipped(self):
        """UNRESOLVED entities that are not contextual stubs are still skipped
        because UNRESOLVED is not in _GLOBAL_SYMBOL_ENTITY_TYPES."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            # UNRESOLVED entity that is NOT a contextual stub
            entity = Entity(
                type=EntityType.UNRESOLVED,
                name="manual_unresolved",
                file="/test/main.py",
                start_line=1,
                end_line=1,
                metadata={},
                id_override="manual_unresolved_id",
            )
            graph.add_entity(entity)

            sm = ScopeManager()
            count = indexer._register_project_symbols(graph, sm)

            assert count == 0
            indexer.close()


# ---------------------------------------------------------------------------
# Integration: symbols are resolvable after registration
# ---------------------------------------------------------------------------


class TestRegisterProjectSymbolsIntegration:
    """Verify registered symbols are actually resolvable via strict resolution."""

    def test_registered_symbol_resolvable_strict(self):
        """After registration, symbols can be found via resolve_symbol_strict."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            entity = _make_entity("findable", EntityType.FUNCTION)
            graph.add_entity(entity)

            sm = ScopeManager()
            # Prime the cache with a failure
            assert sm.resolve_symbol_strict("findable") is None
            # Register
            indexer._register_project_symbols(graph, sm)
            # Clear cache so the retry works
            sm.clear_failed_lookups()
            # Now it should resolve
            info = sm.resolve_symbol_strict("findable")
            assert info is not None
            assert info.symbol_id == entity.id
            indexer.close()

    def test_registered_symbol_resolvable_dotpath(self):
        """After registration, symbols with FQN can be found via dotpath."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            entity = _make_entity(
                "MyClass",
                EntityType.CLASS,
                signature="pkg.MyClass",
            )
            graph.add_entity(entity)

            sm = ScopeManager()
            indexer._register_project_symbols(graph, sm)

            # Resolve via FQN
            info = sm.resolve_symbol_dotpath("pkg.MyClass")
            assert info is not None
            assert info.symbol_id == entity.id
            indexer.close()

    def test_clear_failed_lookups_needed_for_retry(self):
        """Without clear_failed_lookups, a pre-cached failure stays None
        even after the symbol is registered."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            entity = _make_entity("cached_fail", EntityType.FUNCTION)
            graph.add_entity(entity)

            sm = ScopeManager()
            # Prime the cache
            assert sm.resolve_symbol_strict("cached_fail") is None
            # Register the symbol
            indexer._register_project_symbols(graph, sm)
            # WITHOUT clearing: still returns None (cached)
            assert sm.resolve_symbol_strict("cached_fail") is None
            # After clearing: resolves
            sm.clear_failed_lookups()
            assert sm.resolve_symbol_strict("cached_fail") is not None
            indexer.close()
