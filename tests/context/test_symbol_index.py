"""Tests for SymbolIndex lookup behavior."""

from __future__ import annotations

from batho_core.context.codegraph import InMemoryGraph
from batho_core.context.schema import Entity, EntityType
from batho_core.context.symbol_index import SymbolIndex


class TestSymbolIndex:
    def test_build_indexes_full_name_tail_and_module_stem(self):
        graph = InMemoryGraph()
        module = Entity(
            type=EntityType.MODULE,
            name="pkg.utils.helpers",
            file="pkg/utils/helpers.py",
            start_line=1,
            end_line=20,
        )
        graph.add_entity(module)

        index = SymbolIndex.build(graph)

        assert index.resolve_candidates(["pkg.utils.helpers"]) == module.id
        assert index.resolve_candidates(["helpers"]) == module.id

    def test_resolve_candidates_returns_first_matching_candidate(self):
        graph = InMemoryGraph()
        target = Entity(
            type=EntityType.FUNCTION,
            name="pkg.service.run",
            file="src/service.py",
            start_line=1,
            end_line=3,
        )
        graph.add_entity(target)

        index = SymbolIndex.build(graph)
        resolved = index.resolve_candidates(["missing", "run", "pkg.service.run"])
        assert resolved == target.id

    def test_resolve_candidates_returns_none_when_unresolved(self):
        graph = InMemoryGraph()
        index = SymbolIndex.build(graph)
        assert index.resolve_candidates(["unknown"]) is None

    def test_resolve_candidates_prefers_source_file_proximity(self):
        graph = InMemoryGraph()
        first = Entity(
            type=EntityType.MODULE,
            name="pkg.alpha.client",
            file="pkg/alpha/client.py",
            start_line=1,
            end_line=10,
        )
        second = Entity(
            type=EntityType.MODULE,
            name="pkg.beta.client",
            file="pkg/beta/client.py",
            start_line=1,
            end_line=10,
        )
        graph.add_entity(first)
        graph.add_entity(second)

        index = SymbolIndex.build(graph)
        resolved = index.resolve_candidates(
            ["client"],
            source_file="pkg/beta/main.py",
        )

        assert resolved == second.id

    def test_resolve_candidates_supports_case_insensitive_fuzzy(self):
        graph = InMemoryGraph()
        entity = Entity(
            type=EntityType.FUNCTION,
            name="pkg.service.FetchUser",
            file="src/service.py",
            start_line=1,
            end_line=3,
        )
        graph.add_entity(entity)

        index = SymbolIndex.build(graph)
        assert index.resolve_candidates(["fetchuser"], fuzzy_matching=False) is None
        assert (
            index.resolve_candidates(["fetchuser"], fuzzy_matching=True) == entity.id
        )
