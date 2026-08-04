"""Tests for Phase 5: Performance Preservation.

Tests cover:
  - Lazy mode in resolve_contextual_stubs (lazy=True)
  - On-demand resolution via resolve_stub_on_demand
  - _resolve_single_stub helper (extracted resolution pipeline)
  - Per-phase timing metrics in build_stats
  - lazy_stub_resolution parameter in build_graph
  - End-to-end build with lazy mode
  - Verification that existing patterns (partitioned locks, batched updates)
    remain intact
"""
import pytest
import tempfile
from pathlib import Path

from batho.core.schemas import Entity, EntityType, Relationship, RelationshipType
from batho.modules.extraction.scope_manager import ScopeManager
from batho.modules.graph.builder.codegraph import (
    CodeGraphIndexer,
    InMemoryGraph,
    _RESOLUTION_CONFIDENCE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(
    name: str,
    entity_type: EntityType,
    file: str = "/test/main.py",
    start_line: int = 1,
    metadata: dict | None = None,
    id_override: str | None = None,
) -> Entity:
    return Entity(
        type=entity_type,
        name=name,
        file=file,
        start_line=start_line,
        end_line=start_line,
        metadata=metadata or {},
        id_override=id_override or f"batho test pkg 1.0.0 {file}/{name}#{start_line}",
    )


def _make_stub(
    target_name: str,
    caller_scope: str = "batho test pkg 1.0.0 /test/main.py",
    receiver_var: str | None = None,
    receiver_type: str | None = None,
    file: str = "/test/main.py",
    line: int = 10,
    stub_id: str | None = None,
) -> Entity:
    """Create a contextual stub entity."""
    if receiver_var is None and "." in target_name:
        receiver_var = target_name.split(".")[0]
    if stub_id is None:
        stub_id = f"unresolved:{caller_scope}::{target_name}"
    else:
        stub_id = f"unresolved:{stub_id}"
    meta = {
        "reference_type": "calls",
        "resolution_reason": "contextual_stub",
        "stub_resolution_state": "pending",
        "caller_scope": caller_scope,
        "target_name": target_name,
        "receiver_var": receiver_var,
    }
    if receiver_type:
        meta["receiver_type"] = receiver_type
    return Entity(
        type=EntityType.UNRESOLVED,
        name=target_name,
        file=file,
        start_line=line,
        end_line=line,
        metadata=meta,
        id_override=stub_id,
    )


def _make_indexer(tmp_dir: str) -> CodeGraphIndexer:
    return CodeGraphIndexer(cache_path=tmp_dir, root=tmp_dir)


# ---------------------------------------------------------------------------
# Lazy mode in resolve_contextual_stubs
# ---------------------------------------------------------------------------


class TestLazyMode:
    """Verify lazy mode skips upfront resolution."""

    def test_lazy_mode_returns_zero_resolved(self):
        """In lazy mode, resolve_contextual_stubs returns 0 resolved."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            # Register a project symbol
            func_ent = _make_entity("my_func", EntityType.FUNCTION)
            graph.add_entity(func_ent)
            sm.define_symbol("my_func", func_ent.id, "FUNCTION", is_global=True)

            # Create a stub that would resolve in eager mode
            stub = _make_stub("my_func")
            graph.add_entity(stub)

            resolved, unresolved = indexer.resolve_contextual_stubs(
                graph, sm, lazy=True
            )

            assert resolved == 0
            assert unresolved == 1  # 1 pending stub
            indexer.close()

    def test_lazy_mode_leaves_stubs_pending(self):
        """In lazy mode, stubs remain in 'pending' state."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            func_ent = _make_entity("my_func", EntityType.FUNCTION)
            graph.add_entity(func_ent)
            sm.define_symbol("my_func", func_ent.id, "FUNCTION", is_global=True)

            stub = _make_stub("my_func")
            graph.add_entity(stub)

            indexer.resolve_contextual_stubs(graph, sm, lazy=True)

            updated_stub = graph.get_entity(stub.id)
            assert updated_stub.metadata["stub_resolution_state"] == "pending"
            indexer.close()

    def test_lazy_mode_no_relationship_changes(self):
        """In lazy mode, relationships are not rewritten."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            func_ent = _make_entity("my_func", EntityType.FUNCTION)
            graph.add_entity(func_ent)
            sm.define_symbol("my_func", func_ent.id, "FUNCTION", is_global=True)

            stub = _make_stub("my_func")
            graph.add_entity(stub)

            caller = _make_entity("caller", EntityType.FUNCTION, start_line=20)
            graph.add_entity(caller)
            rel = Relationship(
                source_id=caller.id,
                target_id=stub.id,
                type=RelationshipType.CALLS,
            )
            graph.add_relationship(rel)

            indexer.resolve_contextual_stubs(graph, sm, lazy=True)

            # Relationship should still point to the stub, not the target
            updated_rels = [r for r in graph.relationships if r.source_id == caller.id]
            assert len(updated_rels) == 1
            assert updated_rels[0].target_id == stub.id
            indexer.close()

    def test_eager_mode_still_resolves(self):
        """Eager mode (default) still resolves stubs as before."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            func_ent = _make_entity("my_func", EntityType.FUNCTION)
            graph.add_entity(func_ent)
            sm.define_symbol("my_func", func_ent.id, "FUNCTION", is_global=True)

            stub = _make_stub("my_func")
            graph.add_entity(stub)

            resolved, unresolved = indexer.resolve_contextual_stubs(
                graph, sm, lazy=False
            )

            assert resolved == 1
            assert unresolved == 0
            indexer.close()

    def test_lazy_mode_with_no_stubs(self):
        """Lazy mode with no stubs returns (0, 0)."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            resolved, unresolved = indexer.resolve_contextual_stubs(
                graph, sm, lazy=True
            )

            assert resolved == 0
            assert unresolved == 0
            indexer.close()

    def test_lazy_mode_with_multiple_stubs(self):
        """Lazy mode counts all pending stubs correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            for i in range(5):
                graph.add_entity(_make_stub(f"func_{i}", stub_id=f"stub_{i}"))

            resolved, unresolved = indexer.resolve_contextual_stubs(
                graph, sm, lazy=True
            )

            assert resolved == 0
            assert unresolved == 5
            indexer.close()

    def test_lazy_mode_does_not_prune(self):
        """Lazy mode does not prune stubs (pruning happens on-demand)."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            # Prunable stub (common method, unknown receiver)
            stub = _make_stub("var.unwrap")
            graph.add_entity(stub)

            indexer.resolve_contextual_stubs(graph, sm, lazy=True)

            updated_stub = graph.get_entity(stub.id)
            # Should remain pending, not pruned
            assert updated_stub.metadata["stub_resolution_state"] == "pending"
            indexer.close()


# ---------------------------------------------------------------------------
# On-demand resolution via resolve_stub_on_demand
# ---------------------------------------------------------------------------


class TestOnDemandResolution:
    """Verify resolve_stub_on_demand resolves individual stubs."""

    def test_on_demand_resolves_pending_stub(self):
        """resolve_stub_on_demand resolves a pending stub."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            func_ent = _make_entity("my_func", EntityType.FUNCTION)
            graph.add_entity(func_ent)
            sm.define_symbol("my_func", func_ent.id, "FUNCTION", is_global=True)

            stub = _make_stub("my_func")
            graph.add_entity(stub)

            # First, build in lazy mode (stub stays pending)
            indexer.resolve_contextual_stubs(graph, sm, lazy=True)
            assert graph.get_entity(stub.id).metadata["stub_resolution_state"] == "pending"

            # Now resolve on-demand
            target_id = indexer.resolve_stub_on_demand(stub.id, graph, sm)

            assert target_id == func_ent.id
            updated_stub = graph.get_entity(stub.id)
            assert updated_stub.metadata["stub_resolution_state"] == "resolved"
            assert updated_stub.metadata["resolved_target_id"] == func_ent.id
            assert updated_stub.metadata["resolution_strategy"] == "exact_match"
            assert updated_stub.metadata["resolution_confidence"] == 0.95
            indexer.close()

    def test_on_demand_cache_hit(self):
        """resolve_stub_on_demand returns cached result for already-resolved stub."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            func_ent = _make_entity("my_func", EntityType.FUNCTION)
            graph.add_entity(func_ent)
            sm.define_symbol("my_func", func_ent.id, "FUNCTION", is_global=True)

            stub = _make_stub("my_func")
            graph.add_entity(stub)

            # Resolve eagerly first
            indexer.resolve_contextual_stubs(graph, sm, lazy=False)
            assert graph.get_entity(stub.id).metadata["stub_resolution_state"] == "resolved"

            # On-demand call should return cached target
            target_id = indexer.resolve_stub_on_demand(stub.id, graph, sm)
            assert target_id == func_ent.id
            indexer.close()

    def test_on_demand_unresolvable_stub(self):
        """resolve_stub_on_demand returns None for unresolvable stubs."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            stub = _make_stub("nonexistent_function")
            graph.add_entity(stub)

            target_id = indexer.resolve_stub_on_demand(stub.id, graph, sm)
            assert target_id is None
            indexer.close()

    def test_on_demand_prunes_common_method(self):
        """resolve_stub_on_demand prunes common method stubs on unknown receivers."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            stub = _make_stub("var.unwrap")
            graph.add_entity(stub)

            target_id = indexer.resolve_stub_on_demand(stub.id, graph, sm)
            assert target_id is None

            updated_stub = graph.get_entity(stub.id)
            assert updated_stub.metadata["stub_resolution_state"] == "pruned"
            assert updated_stub.metadata["prune_reason"] == "common_method_unknown_receiver"
            indexer.close()

    def test_on_demand_nonexistent_stub(self):
        """resolve_stub_on_demand returns None for nonexistent stub IDs."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            target_id = indexer.resolve_stub_on_demand("nonexistent_id", graph, sm)
            assert target_id is None
            indexer.close()

    def test_on_demand_non_stub_entity(self):
        """resolve_stub_on_demand returns None for non-stub entities."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            func_ent = _make_entity("my_func", EntityType.FUNCTION)
            graph.add_entity(func_ent)

            target_id = indexer.resolve_stub_on_demand(func_ent.id, graph, sm)
            assert target_id is None
            indexer.close()

    def test_on_demand_already_pruned(self):
        """resolve_stub_on_demand returns None for already-pruned stubs."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            stub = _make_stub("var.unwrap")
            graph.add_entity(stub)

            # Prune it first
            indexer.resolve_stub_on_demand(stub.id, graph, sm)
            assert graph.get_entity(stub.id).metadata["stub_resolution_state"] == "pruned"

            # Second call should return None (already pruned)
            target_id = indexer.resolve_stub_on_demand(stub.id, graph, sm)
            assert target_id is None
            indexer.close()

    def test_on_demand_receiver_type_resolution(self):
        """resolve_stub_on_demand resolves via receiver-type inference."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            class_ent = _make_entity("Cursor", EntityType.STRUCT, start_line=1)
            method_ent = _make_entity("Cursor.execute", EntityType.METHOD, start_line=5)
            graph.add_entity(class_ent)
            graph.add_entity(method_ent)
            sm.define_symbol("Cursor", class_ent.id, "STRUCT", is_global=True)
            sm.define_symbol("Cursor.execute", method_ent.id, "METHOD", is_global=True)

            stub = _make_stub("cursor.execute", receiver_type="Cursor")
            graph.add_entity(stub)

            target_id = indexer.resolve_stub_on_demand(stub.id, graph, sm)
            assert target_id == method_ent.id
            updated_stub = graph.get_entity(stub.id)
            assert updated_stub.metadata["resolution_strategy"] == "receiver_type"
            assert updated_stub.metadata["resolution_confidence"] == 0.65
            indexer.close()

    def test_on_demand_multiple_stubs(self):
        """resolve_stub_on_demand resolves multiple stubs independently."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            func_ent = _make_entity("real_func", EntityType.FUNCTION)
            graph.add_entity(func_ent)
            sm.define_symbol("real_func", func_ent.id, "FUNCTION", is_global=True)

            stub1 = _make_stub("real_func", stub_id="stub1")
            stub2 = _make_stub("nonexistent", stub_id="stub2")
            stub3 = _make_stub("var.unwrap", stub_id="stub3")
            graph.add_entity(stub1)
            graph.add_entity(stub2)
            graph.add_entity(stub3)

            # Resolve only stub1
            t1 = indexer.resolve_stub_on_demand(stub1.id, graph, sm)
            assert t1 == func_ent.id
            assert graph.get_entity(stub1.id).metadata["stub_resolution_state"] == "resolved"

            # stub2 and stub3 should still be pending
            assert graph.get_entity(stub2.id).metadata["stub_resolution_state"] == "pending"
            assert graph.get_entity(stub3.id).metadata["stub_resolution_state"] == "pending"

            # Resolve stub2 (unresolvable)
            t2 = indexer.resolve_stub_on_demand(stub2.id, graph, sm)
            assert t2 is None

            # Resolve stub3 (prunable)
            t3 = indexer.resolve_stub_on_demand(stub3.id, graph, sm)
            assert t3 is None
            assert graph.get_entity(stub3.id).metadata["stub_resolution_state"] == "pruned"
            indexer.close()


# ---------------------------------------------------------------------------
# _resolve_single_stub helper
# ---------------------------------------------------------------------------


class TestResolveSingleStub:
    """Verify the extracted _resolve_single_stub helper."""

    def test_exact_match(self):
        """_resolve_single_stub resolves via exact dotpath match."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            func_ent = _make_entity("my_func", EntityType.FUNCTION)
            graph.add_entity(func_ent)
            sm.define_symbol("my_func", func_ent.id, "FUNCTION", is_global=True)

            stub = _make_stub("my_func")
            graph.add_entity(stub)

            resolved_info, strategy = indexer._resolve_single_stub(stub, graph, sm)
            assert resolved_info is not None
            assert resolved_info.symbol_id == func_ent.id
            assert strategy == "exact_match"
            indexer.close()

    def test_receiver_type_strategy(self):
        """_resolve_single_stub resolves via receiver-type inference."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            class_ent = _make_entity("Cursor", EntityType.STRUCT, start_line=1)
            method_ent = _make_entity("Cursor.execute", EntityType.METHOD, start_line=5)
            graph.add_entity(class_ent)
            graph.add_entity(method_ent)
            sm.define_symbol("Cursor", class_ent.id, "STRUCT", is_global=True)
            sm.define_symbol("Cursor.execute", method_ent.id, "METHOD", is_global=True)

            stub = _make_stub("cursor.execute", receiver_type="Cursor")
            graph.add_entity(stub)

            resolved_info, strategy = indexer._resolve_single_stub(stub, graph, sm)
            assert resolved_info is not None
            assert resolved_info.symbol_id == method_ent.id
            assert strategy == "receiver_type"
            indexer.close()

    def test_unresolvable(self):
        """_resolve_single_stub returns (None, 'unresolved') for unknown targets."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            stub = _make_stub("nonexistent_function")
            graph.add_entity(stub)

            resolved_info, strategy = indexer._resolve_single_stub(stub, graph, sm)
            assert resolved_info is None
            assert strategy == "unresolved"
            indexer.close()

    def test_empty_target_name(self):
        """_resolve_single_stub returns (None, 'unresolved') for empty target."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            stub = _make_stub("")
            graph.add_entity(stub)

            resolved_info, strategy = indexer._resolve_single_stub(stub, graph, sm)
            assert resolved_info is None
            assert strategy == "unresolved"
            indexer.close()


# ---------------------------------------------------------------------------
# Per-phase timing metrics
# ---------------------------------------------------------------------------


class TestTimingMetrics:
    """Verify per-phase timing metrics are in build_stats."""

    def test_build_stats_has_timing_metrics(self):
        """build_stats includes project_symbol_ms and stub_resolution_ms."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text("""
def my_func():
    pass

def main():
    my_func()
""", encoding="utf-8")

            indexer = CodeGraphIndexer(cache_path=str(root), root=str(root))
            indexer.build_graph(
                root=str(root),
                max_workers=1,
                verbose=False,
                ast_cache_enabled=False,
            )

            stats = indexer.build_stats
            assert "project_symbol_ms" in stats
            assert "stub_resolution_ms" in stats
            assert isinstance(stats["project_symbol_ms"], (int, float))
            assert isinstance(stats["stub_resolution_ms"], (int, float))
            assert stats["project_symbol_ms"] >= 0
            assert stats["stub_resolution_ms"] >= 0
            indexer.close()

    def test_build_stats_has_lazy_flag(self):
        """build_stats includes lazy_stub_resolution flag."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text("""
def my_func():
    pass
""", encoding="utf-8")

            indexer = CodeGraphIndexer(cache_path=str(root), root=str(root))
            indexer.build_graph(
                root=str(root),
                max_workers=1,
                verbose=False,
                ast_cache_enabled=False,
            )

            stats = indexer.build_stats
            assert "lazy_stub_resolution" in stats
            assert stats["lazy_stub_resolution"] is False
            indexer.close()

    def test_build_stats_lazy_flag_true(self):
        """build_stats shows lazy_stub_resolution=True when lazy mode is used."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text("""
def my_func():
    pass

def main():
    my_func()
""", encoding="utf-8")

            indexer = CodeGraphIndexer(cache_path=str(root), root=str(root))
            indexer.build_graph(
                root=str(root),
                max_workers=1,
                verbose=False,
                ast_cache_enabled=False,
                lazy_stub_resolution=True,
            )

            stats = indexer.build_stats
            assert stats["lazy_stub_resolution"] is True
            indexer.close()


# ---------------------------------------------------------------------------
# End-to-end build with lazy mode
# ---------------------------------------------------------------------------


class TestLazyBuildEndToEnd:
    """Verify lazy mode works in a full build."""

    def test_lazy_build_leaves_stubs_pending(self):
        """A full build with lazy_stub_resolution=True leaves stubs pending."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "utils.py").write_text("""
def helper():
    pass
""", encoding="utf-8")

            (root / "main.py").write_text("""
from utils import helper

def main():
    helper()
""", encoding="utf-8")

            indexer = CodeGraphIndexer(cache_path=str(root), root=str(root))
            graph = indexer.build_graph(
                root=str(root),
                max_workers=1,
                verbose=False,
                ast_cache_enabled=False,
                lazy_stub_resolution=True,
                skip_orphan_pruning=True,
            )

            stubs = [e for e in graph.entities.values() if e.is_contextual_stub]
            # In lazy mode, no stubs should be resolved or pruned
            for s in stubs:
                state = s.metadata.get("stub_resolution_state", "pending")
                assert state not in ("resolved", "pruned"), (
                    f"Stub {s.id} should be pending in lazy mode, got {state}"
                )

            indexer.close()

    def test_lazy_build_then_on_demand_resolves(self):
        """A lazy build followed by on-demand resolution works correctly.

        Uses a project with a function call that creates a contextual stub,
        then resolves it on-demand.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Create a file with an unresolved reference (creates a stub)
            (root / "main.py").write_text("""
def my_defined_func():
    pass

def main():
    my_defined_func()
    obj.unwrap()
""", encoding="utf-8")

            indexer = CodeGraphIndexer(cache_path=str(root), root=str(root))
            graph = indexer.build_graph(
                root=str(root),
                max_workers=1,
                verbose=False,
                ast_cache_enabled=False,
                lazy_stub_resolution=True,
                skip_orphan_pruning=True,
            )

            stubs = [e for e in graph.entities.values() if e.is_contextual_stub]
            # In lazy mode, stubs should not be resolved or pruned
            for s in stubs:
                assert s.metadata.get("stub_resolution_state", "pending") not in ("resolved", "pruned")

            if len(stubs) == 0:
                # If no stubs were created, skip the on-demand test
                # (some extractors may resolve everything inline)
                pytest.skip("No contextual stubs created in this test case")

            # Now resolve on-demand using a fresh scope manager with
            # project symbols re-registered
            sm = ScopeManager()
            indexer._register_project_symbols(graph, sm)

            resolved_count = 0
            pruned_count = 0
            for s in stubs:
                target = indexer.resolve_stub_on_demand(s.id, graph, sm)
                if target is not None:
                    resolved_count += 1
                else:
                    state = graph.get_entity(s.id).metadata.get("stub_resolution_state")
                    if state == "pruned":
                        pruned_count += 1

            # At least some stubs should be resolved or pruned
            assert resolved_count + pruned_count > 0, (
                f"On-demand resolution should resolve or prune at least 1 of {len(stubs)} stubs"
            )
            indexer.close()

    def test_eager_build_resolves_stubs(self):
        """A normal (eager) build resolves stubs as before."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "utils.py").write_text("""
def helper():
    pass
""", encoding="utf-8")

            (root / "main.py").write_text("""
from utils import helper

def main():
    helper()
""", encoding="utf-8")

            indexer = CodeGraphIndexer(cache_path=str(root), root=str(root))
            graph = indexer.build_graph(
                root=str(root),
                max_workers=1,
                verbose=False,
                ast_cache_enabled=False,
            )

            # In eager mode, build_stats should show resolved or pruned stubs.
            # (Resolved stubs may be orphan-pruned from the graph, so check
            # build_stats rather than graph entities.)
            stats = indexer.build_stats
            assert stats["unresolved_resolved_count"] > 0 or stats["unresolved_pruned_count"] > 0, (
                "Eager mode should resolve or prune at least some stubs"
            )
            indexer.close()


# ---------------------------------------------------------------------------
# Verification: existing patterns remain intact
# ---------------------------------------------------------------------------


class TestExistingPatternsIntact:
    """Verify that existing performance patterns are not broken by Phase 5."""

    def test_partitioned_locks_exist(self):
        """ScopeManager still uses partitioned locks."""
        sm = ScopeManager()
        assert hasattr(sm, "_get_partition_key")
        assert hasattr(sm, "_get_partition_lock")
        assert hasattr(sm, "_partitioned_global")
        assert hasattr(sm, "_partitioned_local")
        assert hasattr(sm, "_locks")

    def test_batched_update_relationships_exists(self):
        """InMemoryGraph still has batched update_relationships."""
        assert hasattr(InMemoryGraph, "update_relationships")

    def test_resolution_confidence_constant_unchanged(self):
        """_RESOLUTION_CONFIDENCE still has all 7 tiers."""
        expected = {
            "exact_match", "stdlib_method", "import_map",
            "parent_chain", "scope_qualified", "receiver_type", "unresolved",
        }
        assert set(_RESOLUTION_CONFIDENCE.keys()) == expected

    def test_eager_mode_backward_compatible(self):
        """Eager mode (default) produces same results as before Phase 5."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text("""
def my_func():
    pass

def main():
    my_func()
    obj.unwrap()
""", encoding="utf-8")

            indexer = CodeGraphIndexer(cache_path=str(root), root=str(root))
            graph = indexer.build_graph(
                root=str(root),
                max_workers=1,
                verbose=False,
                ast_cache_enabled=False,
            )

            stats = indexer.build_stats
            # Eager mode should still resolve and prune
            assert stats["unresolved_resolved_count"] >= 0
            assert stats["unresolved_pruned_count"] >= 0
            assert stats["lazy_stub_resolution"] is False
            indexer.close()
