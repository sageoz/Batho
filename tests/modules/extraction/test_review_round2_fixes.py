"""Tests for review round 2 fixes:

- a1f3c9e2: T10 indirect_call guard — bare identifiers resolve via raw-name lookup
- b2e4d8f1: ENUM pushed to scope_stack — enum member FQN/ID uniqueness
- c3f5a7b9: Property setter access_type for TS/C# + accessor in _META_SUFFIXES
- d4a6b8c0: Python parameter query — defaults, typed, *args, **kwargs; no self/cls
- e5b7c9d1: C# base_list — INHERITS vs IMPLEMENTS via symbol lookup
- f6c8d0e2: from_dict reclassification consistent across construction paths
- a7b9c1d3: factory.get_extractor honors parsing config
- b8c0d2e4: Minor bundle — applied_filters reports merged types
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from batho.core.schemas import (
    EntityCategory,
    EntityType,
    Relationship,
    RelationshipType,
    SymbolRole,
)
from batho.modules.extraction.submodules.parser_factory.factory import create_extractor
from batho.modules.extraction.submodules.parser_factory._queries import (
    CSHARP_QUERY,
    PYTHON_QUERY,
    TYPESCRIPT_QUERY,
)


# ---------------------------------------------------------------------------
# a1f3c9e2: T10 indirect_call with parameterized functions
# ---------------------------------------------------------------------------


class TestIndirectCallRawNameLookup:
    """a1f3c9e2: indirect_call must fire for functions with parameters."""

    def test_indirect_call_function_with_params(self):
        """map(func, xs) emits indirect CALLS edge even when func has parameters."""
        extractor = create_extractor("python", PYTHON_QUERY)
        content = (
            b"def func(x):\n"
            b"    return x\n"
            b"\n"
            b"def caller(xs):\n"
            b"    return map(func, xs)\n"
        )
        entities, rels = extractor.parse_file("test.py", content)

        indirect = [
            r for r in rels
            if r.type == RelationshipType.CALLS and r.metadata.get("indirect")
        ]
        assert len(indirect) > 0, (
            "Expected indirect CALLS edge for map(func, xs) where func has params"
        )
        func_ent = next(e for e in entities if e.name.startswith("func"))
        target_ids = {r.target_id for r in indirect}
        assert func_ent.id in target_ids

    def test_indirect_call_confidence_and_role(self):
        """Indirect call edge has confidence=0.7 and Dynamic role bit."""
        extractor = create_extractor("python", PYTHON_QUERY)
        content = (
            b"def func(x):\n"
            b"    return x\n"
            b"\n"
            b"def caller(xs):\n"
            b"    return map(func, xs)\n"
        )
        entities, rels = extractor.parse_file("test.py", content)

        indirect = [
            r for r in rels
            if r.type == RelationshipType.CALLS and r.metadata.get("indirect")
        ]
        assert len(indirect) > 0
        for r in indirect:
            assert abs(r.confidence - 0.7) < 0.01, f"Expected 0.7, got {r.confidence}"
            assert r.roles & SymbolRole.Dynamic

    def test_indirect_call_local_var_still_skipped(self):
        """Soundness guard still skips local variables (not functions)."""
        extractor = create_extractor("python", PYTHON_QUERY)
        content = (
            b"def caller(xs):\n"
            b"    cb = 42\n"
            b"    return map(cb, xs)\n"
        )
        entities, rels = extractor.parse_file("test.py", content)

        indirect = [
            r for r in rels
            if r.type == RelationshipType.CALLS and r.metadata.get("indirect")
        ]
        assert len(indirect) == 0, "Local variable must not produce indirect edge"


# ---------------------------------------------------------------------------
# b2e4d8f1: ENUM scope stack
# ---------------------------------------------------------------------------


class TestEnumScopeStack:
    """b2e4d8f1: ENUM members get qualified FQNs and unique IDs."""

    def test_csharp_same_named_variants_distinct(self):
        """C# enum members in different enums get distinct IDs and FQNs."""
        extractor = create_extractor("csharp", CSHARP_QUERY)
        content = (
            b"enum Color {\n"
            b"    Red,\n"
            b"}\n"
            b"enum Status {\n"
            b"    Red,\n"
            b"}\n"
        )
        entities, _ = extractor.parse_file("test.cs", content)

        members = [e for e in entities if e.type == EntityType.ENUM_MEMBER]
        assert len(members) == 2, f"Expected 2 enum members, got {len(members)}"
        ids = {e.id for e in members}
        assert len(ids) == 2, f"Expected 2 distinct IDs, got {ids}"
        names = {e.name for e in members}
        assert names == {"Color.Red", "Status.Red"}, f"Got {names}"


# ---------------------------------------------------------------------------
# c3f5a7b9: Property setter access_type for TS/C#
# ---------------------------------------------------------------------------


class TestPropertyAccessType:
    """c3f5a7b9: TS set accessors get access_type='write'."""

    def test_ts_set_accessor_is_write(self):
        """TypeScript set accessor has access_type='write'."""
        extractor = create_extractor("typescript", TYPESCRIPT_QUERY)
        content = (
            b"class Foo {\n"
            b"  get bar(): number { return 1; }\n"
            b"  set bar(v: number) { this._v = v; }\n"
            b"}\n"
        )
        entities, _ = extractor.parse_file("test.ts", content)

        props = [e for e in entities if e.type == EntityType.PROPERTY]
        setters = [e for e in props if e.metadata.get("access_type") == "write"]
        getters = [e for e in props if e.metadata.get("access_type") == "read"]
        assert len(setters) >= 1, f"Expected at least one write accessor, got {props}"
        assert len(getters) >= 1, f"Expected at least one read accessor, got {props}"

    def test_accessor_suffix_in_meta_suffixes(self):
        """'accessor' is in _META_SUFFIXES so TS get/set captures are not dropped."""
        from batho.modules.extraction.extractor import _META_SUFFIXES
        assert "accessor" in _META_SUFFIXES


# ---------------------------------------------------------------------------
# d4a6b8c0: Python parameter query completeness
# ---------------------------------------------------------------------------


class TestPythonParameterQuery:
    """d4a6b8c0: Python params — defaults, typed, splats; no self/cls."""

    def _extract_params(self, content: bytes) -> list[str]:
        extractor = create_extractor("python", PYTHON_QUERY)
        extractor.set_parsing_config({"extract_parameters": True})
        entities, _ = extractor.parse_file("test.py", content)
        return [e.name for e in entities if e.type == EntityType.PARAMETER]

    def test_all_parameter_forms_captured(self):
        """def f(a, b=1, *args, **kwargs) yields PARAMETER entities for all four."""
        names = self._extract_params(
            b"def f(a, b=1, *args, **kwargs):\n    pass\n"
        )
        assert "a" in names
        assert "b" in names
        assert "args" in names
        assert "kwargs" in names

    def test_typed_parameter_captured(self):
        """Typed parameters (b: int) are captured."""
        names = self._extract_params(b"def f(a, b: int):\n    pass\n")
        assert "b" in names

    def test_self_cls_excluded(self):
        """self/cls receiver params are not extracted as PARAMETER entities."""
        extractor = create_extractor("python", PYTHON_QUERY)
        extractor.set_parsing_config({"extract_parameters": True})
        content = (
            b"class C:\n"
            b"    def m(self, cls, x):\n"
            b"        pass\n"
        )
        entities, _ = extractor.parse_file("test.py", content)
        param_names = [e.name for e in entities if e.type == EntityType.PARAMETER]
        # self/cls must not appear (even FQN-qualified); x must appear
        assert not any(n.split(".")[-1] in ("self", "cls") for n in param_names), \
            f"self/cls should be excluded, got {param_names}"
        assert any(n.split(".")[-1] == "x" for n in param_names), \
            f"Parameter x should be extracted, got {param_names}"


# ---------------------------------------------------------------------------
# e5b7c9d1: C# base_list classification
# ---------------------------------------------------------------------------


class TestCSharpBaseList:
    """e5b7c9d1: C# base class → INHERITS, interface → IMPLEMENTS."""

    def test_base_class_produces_inherits(self, tmp_path: Path):
        """class Foo : Bar produces an INHERITS edge to Bar."""
        from batho.orchestrator.build import run_build, BuildOptions

        root = tmp_path / "cs_repo"
        root.mkdir()
        (root / "types.cs").write_text(
            "public class Bar { }\n"
            "public class Foo : Bar { }\n",
            encoding="utf-8",
        )
        result = run_build(BuildOptions(root=root, force_full=True))
        assert result.success

        from batho.mcp.tools import _get_reader
        reader = _get_reader(str(root))
        rels = reader._get_table("rels_views").to_pylist()
        inherits = [r for r in rels if r.get("relation_type") == "INHERITS"]
        assert len(inherits) >= 1, f"Expected INHERITS edge for class Foo : Bar, got {rels}"

    def test_interface_produces_implements(self, tmp_path: Path):
        """class Foo : IFoo produces IMPLEMENTS (IFoo is an interface)."""
        from batho.orchestrator.build import run_build, BuildOptions

        root = tmp_path / "cs_repo"
        root.mkdir()
        (root / "types.cs").write_text(
            "public interface IFoo { }\n"
            "public class Foo : IFoo { }\n",
            encoding="utf-8",
        )
        result = run_build(BuildOptions(root=root, force_full=True))
        assert result.success

        from batho.mcp.tools import _get_reader
        reader = _get_reader(str(root))
        rels = reader._get_table("rels_views").to_pylist()
        implements = [r for r in rels if r.get("relation_type") == "IMPLEMENTS"]
        assert len(implements) >= 1, f"Expected IMPLEMENTS edge for IFoo, got {rels}"
        # The key assertion: IFoo should be IMPLEMENTS, not INHERITS
        assert not any(r.get("relation_type") == "INHERITS" for r in rels), \
            f"Interface base must not produce INHERITS, got {rels}"


# ---------------------------------------------------------------------------
# f6c8d0e2: from_dict reclassification consistency
# ---------------------------------------------------------------------------


class TestReclassificationConsistency:
    """f6c8d0e2: reclassification behaves identically on all construction paths."""

    def test_direct_construction_reclassified(self):
        """Direct Relationship(type=REFERENCES, roles=WriteAccess) → WRITES."""
        rel = Relationship(
            source_id="a",
            target_id="b",
            type=RelationshipType.REFERENCES,
            roles=SymbolRole.WriteAccess,
        )
        assert rel.type == RelationshipType.WRITES

    def test_direct_construction_read_reclassified(self):
        """Direct construction with ReadAccess → READS."""
        rel = Relationship(
            source_id="a",
            target_id="b",
            type=RelationshipType.REFERENCES,
            roles=SymbolRole.ReadAccess,
        )
        assert rel.type == RelationshipType.READS

    def test_direct_construction_no_role_kept(self):
        """Direct construction with no roles stays REFERENCES."""
        rel = Relationship(
            source_id="a",
            target_id="b",
            type=RelationshipType.REFERENCES,
            roles=SymbolRole(0),
        )
        assert rel.type == RelationshipType.REFERENCES

    def test_from_dict_and_direct_produce_same_id(self):
        """from_dict and direct construction produce identical ids."""
        d = {
            "source_id": "a",
            "target_id": "b",
            "type": "references",
            "roles": int(SymbolRole.WriteAccess),
            "metadata": {"line_number": 3},
        }
        from_dict_rel = Relationship.from_dict(d)
        direct_rel = Relationship(
            source_id="a",
            target_id="b",
            type=RelationshipType.REFERENCES,
            roles=SymbolRole.WriteAccess,
            metadata={"line_number": 3},
        )
        assert from_dict_rel.type == direct_rel.type == RelationshipType.WRITES
        assert from_dict_rel.id == direct_rel.id

    def test_roundtrip_legacy_references(self):
        """Round-trip: serialize REFERENCES+WriteAccess dict, from_dict → WRITES."""
        d = {
            "source_id": "a",
            "target_id": "b",
            "type": "references",
            "roles": 4,  # WriteAccess
            "metadata": {"line_number": 10},
        }
        rel = Relationship.from_dict(d)
        assert rel.type == RelationshipType.WRITES
        # Documented id change: recomputed id differs from a REFERENCES-typed edge
        legacy = Relationship(
            source_id="a", target_id="b", type=RelationshipType.REFERENCES,
            roles=SymbolRole.WriteAccess, metadata={"line_number": 10},
        )
        # legacy construction is also reclassified, so ids match
        assert rel.id == legacy.id


# ---------------------------------------------------------------------------
# a7b9c1d3: factory.get_extractor honors parsing config
# ---------------------------------------------------------------------------


class TestFactoryGetExtractorConfig:
    """a7b9c1d3: factory.get_extractor applies registry parsing config."""

    def test_factory_get_extractor_honors_config(self):
        from batho.modules.extraction.submodules.parser_factory import factory
        from batho.modules.extraction.submodules.parser_factory.registry import set_parsing_config

        factory._extractor_cache.clear()
        set_parsing_config({"extract_parameters": True})
        ext = factory.get_extractor("python")
        assert ext is not None
        assert ext._parsing_config.get("extract_parameters") is True
        # Reset
        set_parsing_config({})
        factory._extractor_cache.clear()


# ---------------------------------------------------------------------------
# b8c0d2e4: Minor bundle
# ---------------------------------------------------------------------------


class TestMinorFixes:
    """b8c0d2e4: EntityType.category returns None for dead types; applied_filters merged."""

    def test_category_none_for_dead_types(self):
        """Dead types (UNRESOLVED etc.) return None instead of raising KeyError."""
        assert EntityType.UNRESOLVED.category is None
        assert EntityType.ATTRIBUTE.category is None
        assert EntityType.GLOBAL_STATEMENT.category is None
        assert EntityType.IMPORT_BLOCK.category is None

    def test_category_works_for_live_types(self):
        """Live types still return their category."""
        assert EntityType.FUNCTION.category == EntityCategory.CODE
        assert EntityType.MODULE.category == EntityCategory.CODE

    def test_applied_filters_reports_merged_types(self, tmp_path: Path):
        """graph_query with entity_categories reports merged entity_types."""
        from batho.orchestrator.build import run_build, BuildOptions
        from batho.mcp.server import create_app

        root = tmp_path / "sample_repo"
        root.mkdir()
        (root / "main.py").write_text(
            "def main():\n    return 42\n",
            encoding="utf-8",
        )
        run_build(BuildOptions(root=root, force_full=True))

        app = create_app(root=str(root), registry_path=tmp_path / "mcp-repos.json")
        result = asyncio.run(app.call_tool("graph_query", {"entity_categories": ["code"]}))
        structured = result.structured_content or {}
        applied = structured.get("meta", {}).get("applied_filters", {})
        # entity_types should be the merged (expanded) set, not None/empty
        assert "entity_types" in applied, f"Expected merged entity_types in {applied}"
        assert "function" in [t.lower() for t in applied["entity_types"]]


# ---------------------------------------------------------------------------
# T10 review fix: arrow-function params in the shadowing guard
# ---------------------------------------------------------------------------


class TestIndirectCallArrowFunctionParams:
    """T10: _enclosing_function_params must stop at arrow functions too.

    Without `arrow_function` in _FUNCTION_NODE_TYPES, the walk-up skipped the
    arrow and collected the *outer* function's parameters, so a shadowing
    arrow parameter produced a false-positive indirect CALLS edge.
    """

    def test_ts_arrow_param_shadow_suppressed(self):
        """submit(handler) inside an arrow whose parameter shadows a module
        function does NOT emit an indirect CALLS edge."""
        extractor = create_extractor("typescript", TYPESCRIPT_QUERY)
        content = (
            b"function handler() { return 1; }\n"
            b"function outer() {\n"
            b"  const run = (handler) => {\n"
            b"    submit(handler);\n"
            b"  };\n"
            b"  return run;\n"
            b"}\n"
        )
        entities, rels = extractor.parse_file("test.ts", content)

        indirect = [
            r for r in rels
            if r.type == RelationshipType.CALLS and r.metadata.get("indirect")
        ]
        assert len(indirect) == 0, (
            "Arrow-function parameter shadowing a module function must not "
            f"produce an indirect edge, got {indirect}"
        )

    def test_ts_arrow_non_shadow_still_emits(self):
        """Without shadowing, the indirect edge inside an arrow still fires."""
        extractor = create_extractor("typescript", TYPESCRIPT_QUERY)
        content = (
            b"function handler() { return 1; }\n"
            b"function outer() {\n"
            b"  const run = () => {\n"
            b"    submit(handler);\n"
            b"  };\n"
            b"  return run;\n"
            b"}\n"
        )
        entities, rels = extractor.parse_file("test.ts", content)

        indirect = [
            r for r in rels
            if r.type == RelationshipType.CALLS and r.metadata.get("indirect")
        ]
        assert len(indirect) > 0, (
            "Non-shadowed indirect call inside an arrow function must still "
            "be emitted"
        )
        handler_ent = next(
            e for e in entities if e.name.startswith("handler")
        )
        assert handler_ent.id in {r.target_id for r in indirect}
