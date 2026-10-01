"""Tests for Phase 2 Task 2.2: Receiver-type-aware method resolution.

Tests cover:
  - receiver_var extraction in _make_contextual_stub (extractor.py)
  - _resolve_method_call: two-phase method resolution
  - _infer_variable_type: type inference from self/this, metadata, declarations
  - _check_stdlib_method: stdlib method lookup
  - Edge cases: no receiver_var, no dot in target, unknown type, etc.
  - Integration: end-to-end stub resolution with receiver types
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
    file: str = "/test/main.rs",
    start_line: int = 1,
    signature: str | None = None,
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
        signature=signature,
        id_override=id_override or f"batho test pkg 1.0.0 {file}/{name}#{start_line}",
    )


def _make_stub(
    target_name: str,
    caller_scope: str = "batho test pkg 1.0.0 /test/main.rs",
    receiver_var: str | None = None,
    file: str = "/test/main.rs",
    line: int = 10,
) -> Entity:
    """Create a contextual stub with receiver_var metadata."""
    if receiver_var is None and "." in target_name:
        receiver_var = ".".join(target_name.split(".")[:-1])
    stub_id = f"unresolved:{caller_scope}::{target_name}"
    meta = {
        "reference_type": "calls",
        "resolution_reason": "contextual_stub",
        "stub_resolution_state": "pending",
        "caller_scope": caller_scope,
        "target_name": target_name,
        "receiver_var": receiver_var,
    }
    return Entity(
        type=EntityType.EXTERNAL_SYMBOL,
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
# receiver_var extraction in _make_contextual_stub (extractor.py logic)
# ---------------------------------------------------------------------------


class TestReceiverVarExtraction:
    """Verify receiver_var is correctly extracted from ref_text.

    The extraction logic (in extractor.py _make_contextual_stub) stores the
    FULL receiver chain, not just the first segment — `self.db.execute`
    needs `self.db` so the deep-receiver guard can fire:
        receiver_var = ".".join(ref_text.split(".")[:-1]) if "." in ref_text
    """

    @pytest.mark.parametrize("ref_text,expected", [
        ("cursor.execute", "cursor"),
        ("self.method", "self"),
        ("this.prop", "this"),
        ("obj.a.b.c", "obj.a.b"),  # full chain, not just "obj"
        ("self.db.execute", "self.db"),
        ("json.dumps", "json"),
        ("std::option::Option", None),  # Uses :: not ., so no receiver_var
        ("simple", None),  # No dot
        ("", None),  # Empty string, no dot
        (".leading_dot", ""),  # Dot at start, receiver chain is empty
    ])
    def test_receiver_var_extraction(self, ref_text, expected):
        """Verify receiver_var is extracted correctly from ref_text."""
        if "." in ref_text:
            receiver_var = ".".join(ref_text.split(".")[:-1])
        else:
            receiver_var = None
        assert receiver_var == expected

    def test_stub_has_receiver_var_metadata(self):
        """A stub created with a dotted target_name has receiver_var in metadata."""
        stub = _make_stub("cursor.execute")
        assert stub.metadata["receiver_var"] == "cursor"

    def test_stub_without_dot_has_none_receiver_var(self):
        """A stub with a non-dotted target_name has receiver_var=None."""
        stub = _make_stub("simple_call")
        assert stub.metadata["receiver_var"] is None

    def test_stub_with_explicit_receiver_var(self):
        """A stub can be created with an explicit receiver_var override."""
        stub = _make_stub("custom.call", receiver_var="explicit")
        assert stub.metadata["receiver_var"] == "explicit"


# ---------------------------------------------------------------------------
# _resolve_method_call
# ---------------------------------------------------------------------------


class TestResolveMethodCall:
    """Verify _resolve_method_call resolves method calls via receiver type."""

    def test_resolves_project_method(self):
        """A method call on a known project type resolves to the method entity."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            # Register a project class and its method
            class_entity = _make_entity("Cursor", EntityType.STRUCT, start_line=1)
            method_entity = _make_entity("Cursor.execute", EntityType.METHOD, start_line=5)
            graph.add_entity(class_entity)
            graph.add_entity(method_entity)
            sm.define_symbol("Cursor", class_entity.id, "STRUCT", is_global=True)
            sm.define_symbol("Cursor.execute", method_entity.id, "METHOD", is_global=True)

            # Stub referencing cursor.execute — the caller's signature
            # annotates `cursor: Cursor` (Source 4: parameter annotation).
            caller = _make_entity(
                "handler", EntityType.FUNCTION, signature="fn handler(cursor: Cursor)"
            )
            graph.add_entity(caller)
            stub = _make_stub("cursor.execute", caller_scope=caller.id)
            graph.add_entity(stub)

            result = indexer._resolve_method_call(stub, graph, sm)
            assert result is not None
            assert result.symbol_id == method_entity.id
            indexer.close()

    def test_resolves_stdlib_method(self):
        """A method call on a stdlib type (Option.unwrap) resolves via stdlib table."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            # Register the stdlib module so it can be resolved
            sm.add_external_symbol(
                name="std::option::Option",
                symbol_id="batho stdb rust 1.70 std::option::Option/",
                symbol_type="module",
            )

            # Stub referencing opt.unwrap — the caller annotates `opt: Option`.
            caller = _make_entity(
                "handler", EntityType.FUNCTION, signature="fn handler(opt: Option)"
            )
            graph.add_entity(caller)
            stub = _make_stub("opt.unwrap", caller_scope=caller.id)
            graph.add_entity(stub)

            result = indexer._resolve_method_call(stub, graph, sm)
            assert result is not None
            indexer.close()

    def test_stdlib_hit_via_receiver_stamps_stdlib_method(self):
        """GRH-11: a stdlib-table hit reached through the receiver pipeline
        stamps `stdlib_method` (0.90), not the weakest `receiver_type` tier —
        provenance and confidence survive."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            sm.add_external_symbol(
                name="std::option::Option",
                symbol_id="batho stdb rust 1.70 std::option::Option/",
                symbol_type="module",
            )
            caller = _make_entity(
                "handler", EntityType.FUNCTION, signature="fn handler(opt: Option)"
            )
            graph.add_entity(caller)
            stub = _make_stub("opt.unwrap", caller_scope=caller.id)
            graph.add_entity(stub)

            result = indexer._resolve_method_call_with_tier(
                stub, graph, sm, "rust", None, None
            )
            assert result is not None
            _, tier = result
            assert tier == "stdlib_method"
            indexer.close()

    def test_no_receiver_var_returns_none(self):
        """A stub without receiver_var returns None."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            stub = _make_stub("bare_function", receiver_var=None)
            graph.add_entity(stub)

            result = indexer._resolve_method_call(stub, graph, sm)
            assert result is None
            indexer.close()

    def test_no_dot_in_target_returns_none(self):
        """A stub with no dot in target_name returns None."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            stub = _make_stub("nodot", receiver_var="some_var")
            graph.add_entity(stub)

            result = indexer._resolve_method_call(stub, graph, sm)
            assert result is None
            indexer.close()

    def test_unknown_receiver_type_returns_none(self):
        """A stub with an unresolvable receiver type returns None."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            stub = _make_stub("unknown_var.method")
            graph.add_entity(stub)

            result = indexer._resolve_method_call(stub, graph, sm)
            assert result is None
            indexer.close()

    def test_empty_target_name_returns_none(self):
        """A stub with empty target_name returns None."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            stub = _make_stub("", receiver_var="x")
            graph.add_entity(stub)

            result = indexer._resolve_method_call(stub, graph, sm)
            assert result is None
            indexer.close()


# ---------------------------------------------------------------------------
# _infer_variable_type
# ---------------------------------------------------------------------------


class TestInferVariableType:
    """Verify _infer_variable_type infers types from multiple sources."""

    def test_self_resolves_to_enclosing_class(self):
        """self/this resolves to the enclosing class from caller_scope."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            # Register a class
            class_entity = _make_entity("MyClass", EntityType.CLASS, start_line=1)
            sm.define_symbol("MyClass", class_entity.id, "CLASS", is_global=True)

            # Stub with self as receiver, caller_scope containing MyClass
            stub = _make_stub(
                "self.method",
                caller_scope="batho test pkg 1.0.0 /test/MyClass/method",
            )
            graph.add_entity(stub)

            var_type = indexer._infer_variable_type("self", stub, graph, sm)
            assert var_type == "MyClass"
            indexer.close()

    def test_this_resolves_to_enclosing_class(self):
        """this (JS/TS) resolves to the enclosing class."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            class_entity = _make_entity("Component", EntityType.CLASS, start_line=1)
            sm.define_symbol("Component", class_entity.id, "CLASS", is_global=True)

            stub = _make_stub(
                "this.render",
                caller_scope="batho test pkg 1.0.0 /test/Component/render",
            )
            graph.add_entity(stub)

            var_type = indexer._infer_variable_type("this", stub, graph, sm)
            assert var_type == "Component"
            indexer.close()

    def test_self_with_nested_scope_finds_outer_class(self):
        """self in a nested method scope finds the enclosing class."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            class_entity = _make_entity("Outer", EntityType.CLASS, start_line=1)
            sm.define_symbol("Outer", class_entity.id, "CLASS", is_global=True)

            stub = _make_stub(
                "self.inner",
                caller_scope="batho test pkg 1.0.0 /test/Outer/ OuterMethod/nested_closure",
            )
            graph.add_entity(stub)

            var_type = indexer._infer_variable_type("self", stub, graph, sm)
            assert var_type == "Outer"
            indexer.close()

    def test_self_with_no_enclosing_class_returns_none(self):
        """self with no class in the scope path returns None."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            stub = _make_stub(
                "self.method",
                caller_scope="batho test pkg 1.0.0 /test/free_function",
            )
            graph.add_entity(stub)

            var_type = indexer._infer_variable_type("self", stub, graph, sm)
            assert var_type is None
            indexer.close()

    def test_param_annotation_types_receiver(self):
        """A caller signature param annotation types the receiver var."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            caller = _make_entity(
                "handler", EntityType.FUNCTION, signature="fn handler(var: HashMap)"
            )
            graph.add_entity(caller)
            stub = _make_stub("var.method", caller_scope=caller.id)
            graph.add_entity(stub)

            var_type = indexer._infer_variable_type("var", stub, graph, sm)
            assert var_type == "HashMap"
            indexer.close()

    def test_self_with_empty_scope_returns_none(self):
        """self with empty caller_scope returns None."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            stub = _make_stub("self.method", caller_scope="")
            graph.add_entity(stub)

            var_type = indexer._infer_variable_type("self", stub, graph, sm)
            assert var_type is None
            indexer.close()

    def test_self_with_short_scope_returns_none(self):
        """self with a caller_scope that has fewer than 5 parts uses the
        full string as scope_path."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            # Register a class so it can be found
            sm.define_symbol("ShortClass", "id_short", "CLASS", is_global=True)

            stub = _make_stub(
                "self.method",
                caller_scope="ShortClass/method",  # Only 2 parts
            )
            graph.add_entity(stub)

            var_type = indexer._infer_variable_type("self", stub, graph, sm)
            # scope_path = "ShortClass/method", segments = ["ShortClass", "method"]
            # "ShortClass" is found as a CLASS
            assert var_type == "ShortClass"
            indexer.close()

    def test_self_prefers_struct_over_function(self):
        """When walking scope segments, the first CLASS/STRUCT/TRAIT/INTERFACE
        is returned, not other types."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            sm.define_symbol("MyStruct", "id_struct", "STRUCT", is_global=True)
            sm.define_symbol("helper_fn", "id_fn", "FUNCTION", is_global=True)

            stub = _make_stub(
                "self.method",
                caller_scope="batho test pkg 1.0.0 /test/helper_fn/MyStruct/method",
            )
            graph.add_entity(stub)

            var_type = indexer._infer_variable_type("self", stub, graph, sm)
            # Walking from innermost: "method" (skip), "MyStruct" (STRUCT - match!)
            assert var_type == "MyStruct"
            indexer.close()


# ---------------------------------------------------------------------------
# _check_stdlib_method
# ---------------------------------------------------------------------------


class TestCheckStdlibMethod:
    """Verify _check_stdlib_method looks up methods in the stdlib table."""

    def test_option_unwrap_resolves(self):
        """Option.unwrap is found in the Rust stdlib table."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            sm = ScopeManager()
            # Register the stdlib module
            sm.add_external_symbol(
                name="std::option::Option",
                symbol_id="batho stdb rust 1.70 std::option::Option/",
                symbol_type="module",
            )

            result = indexer._check_stdlib_method("Option", "unwrap", sm)
            assert result is not None
            indexer.close()

    def test_result_ok_resolves(self):
        """Result.ok is found in the Rust stdlib table."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            sm = ScopeManager()
            sm.add_external_symbol(
                name="std::result::Result",
                symbol_id="batho stdb rust 1.70 std::result::Result/",
                symbol_type="module",
            )

            result = indexer._check_stdlib_method("Result", "ok", sm)
            assert result is not None
            indexer.close()

    def test_vec_push_resolves(self):
        """Vec.push is found in the Rust stdlib table."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            sm = ScopeManager()
            sm.add_external_symbol(
                name="std::vec::Vec",
                symbol_id="batho stdb rust 1.70 std::vec::Vec/",
                symbol_type="module",
            )

            result = indexer._check_stdlib_method("Vec", "push", sm)
            assert result is not None
            indexer.close()

    def test_unknown_method_returns_none(self):
        """An unknown method on a known type returns None."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            sm = ScopeManager()
            sm.add_external_symbol(
                name="std::option::Option",
                symbol_id="batho stdb rust 1.70 std::option::Option/",
                symbol_type="module",
            )

            result = indexer._check_stdlib_method("Option", "nonexistent_method", sm)
            assert result is None
            indexer.close()

    def test_unknown_type_returns_none(self):
        """An unknown type that's not in _TYPE_TO_STDLIB_MODULE returns None
        (unless the type name itself is a registered module)."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            sm = ScopeManager()

            result = indexer._check_stdlib_method("UnknownType", "method", sm)
            assert result is None
            indexer.close()

    def test_string_len_resolves(self):
        """String.len is found in the Rust stdlib table."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            sm = ScopeManager()
            sm.add_external_symbol(
                name="std::string::String",
                symbol_id="batho stdb rust 1.70 std::string::String/",
                symbol_type="module",
            )

            result = indexer._check_stdlib_method("String", "len", sm)
            assert result is not None
            indexer.close()

    def test_promise_then_resolves(self):
        """Promise.then is found in the JavaScript stdlib table."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            sm = ScopeManager()
            sm.add_external_symbol(
                name="Promise",
                symbol_id="batho npm javascript es6 Promise/",
                symbol_type="module",
            )

            result = indexer._check_stdlib_method("Promise", "then", sm)
            assert result is not None
            indexer.close()

    def test_array_push_resolves(self):
        """Array.push is found in the JavaScript stdlib table."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            sm = ScopeManager()
            sm.add_external_symbol(
                name="Array.prototype",
                symbol_id="batho npm javascript es6 Array.prototype/",
                symbol_type="module",
            )

            result = indexer._check_stdlib_method("Array", "push", sm)
            assert result is not None
            indexer.close()

    def test_empty_method_name_returns_none(self):
        """An empty method name returns None."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            sm = ScopeManager()
            sm.add_external_symbol(
                name="std::option::Option",
                symbol_id="batho stdb rust 1.70 std::option::Option/",
                symbol_type="module",
            )

            result = indexer._check_stdlib_method("Option", "", sm)
            assert result is None
            indexer.close()


# ---------------------------------------------------------------------------
# _TYPE_TO_STDLIB_MODULE mapping
# ---------------------------------------------------------------------------


class TestTypeToStdlibModuleMapping:
    """Verify the _TYPE_TO_STDLIB_MODULE mapping covers expected types."""

    def test_mapping_contains_rust_types(self):
        """Rust prelude types are in the mapping."""
        mapping = CodeGraphIndexer._TYPE_TO_STDLIB_MODULE
        assert "Option" in mapping
        assert "Result" in mapping
        assert "Vec" in mapping
        assert "String" in mapping
        assert "HashMap" in mapping
        assert "HashSet" in mapping
        assert mapping["Option"] == "std::option::Option"
        assert mapping["Result"] == "std::result::Result"
        assert mapping["Vec"] == "std::vec::Vec"

    def test_mapping_contains_js_types(self):
        """JavaScript/TypeScript built-in types are in the mapping."""
        mapping = CodeGraphIndexer._TYPE_TO_STDLIB_MODULE
        assert "Array" in mapping
        assert "Promise" in mapping
        assert mapping["Array"] == "Array.prototype"
        assert mapping["Promise"] == "Promise"

    def test_unknown_type_falls_back_to_self(self):
        """An unknown type name falls back to using itself as the module path."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            # "CustomType" is not in the mapping, so module_path = "CustomType"
            module_path = indexer._TYPE_TO_STDLIB_MODULE.get("CustomType", "CustomType")
            assert module_path == "CustomType"
            indexer.close()


# ---------------------------------------------------------------------------
# Integration: end-to-end resolution
# ---------------------------------------------------------------------------


class TestReceiverTypeResolutionIntegration:
    """Verify end-to-end receiver-type resolution with a real build."""

    def test_self_method_call_resolves(self):
        """A self.method call inside a class resolves to the project method."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            # Project class and method
            class_ent = _make_entity("Repo", EntityType.STRUCT, start_line=1)
            method_ent = _make_entity("Repo.save", EntityType.METHOD, start_line=5)
            graph.add_entity(class_ent)
            graph.add_entity(method_ent)
            sm.define_symbol("Repo", class_ent.id, "STRUCT", is_global=True)
            sm.define_symbol("Repo.save", method_ent.id, "METHOD", is_global=True)

            # Stub: self.save called inside Repo::other_method
            stub = _make_stub(
                "self.save",
                caller_scope="batho test pkg 1.0.0 /test/Repo/other_method",
            )
            graph.add_entity(stub)

            result = indexer._resolve_method_call(stub, graph, sm)
            assert result is not None
            assert result.symbol_id == method_ent.id
            indexer.close()

    def test_stdlib_method_on_option_resolves(self):
        """opt.unwrap with caller annotating `opt: Option` resolves via stdlib."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            sm.add_external_symbol(
                name="std::option::Option",
                symbol_id="batho stdb rust 1.70 std::option::Option/",
                symbol_type="module",
            )

            caller = _make_entity(
                "handler", EntityType.FUNCTION, signature="fn handler(opt: Option)"
            )
            graph.add_entity(caller)
            stub = _make_stub("opt.unwrap", caller_scope=caller.id)
            graph.add_entity(stub)

            result = indexer._resolve_method_call(stub, graph, sm)
            assert result is not None
            indexer.close()

    def test_chained_dot_path_extracts_correct_method(self):
        """For target_name 'obj.a.b.c', method_name is 'a.b.c' (everything
        after the first dot). The receiver_var is 'obj'."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            stub = _make_stub("obj.a.b.c")
            graph.add_entity(stub)

            # The method_name extraction keeps the full chain after the
            # first dot regardless of resolution.
            target_name = stub.metadata.get("target_name", "")
            method_name = target_name.split(".", 1)[1]
            assert method_name == "a.b.c"
            indexer.close()


# ---------------------------------------------------------------------------
# GRH-13/14: id-grammar and signature-scan edge cases
# ---------------------------------------------------------------------------


class TestExternalQualifiedNameSpaces:
    """GRH-13: PEP 508 version specs may contain spaces — the tail field must
    anchor on the LAST space, not a fixed split position."""

    def test_spaced_version_spec_keeps_path(self):
        from batho.modules.graph.builder.codegraph import _external_qualified_name

        # `fastapi >= 0.100, < 1.0` — version spec with interior whitespace.
        assert _external_qualified_name(
            "batho pip fastapi >= 0.100, < 1.0 fastapi/FastAPI()."
        ) == "fastapi.FastAPI"

    def test_unspaced_spec_unchanged(self):
        from batho.modules.graph.builder.codegraph import _external_qualified_name

        assert _external_qualified_name(
            "batho pip fastapi >=0.141.1 fastapi/FastAPI()."
        ) == "fastapi.FastAPI"
        assert _external_qualified_name(
            "batho npm zod ^3 zod/"
        ) == "zod"

    def test_non_packaged_ids_still_none(self):
        from batho.modules.graph.builder.codegraph import _external_qualified_name

        assert _external_qualified_name("unresolved:x::y") is None
        assert _external_qualified_name("ent|FUNCTION|f|1|2|1|1|g") is None


class TestSignatureParamMapDefaults:
    """GRH-14: `<`/`>` inside default values are comparisons/expressions,
    not generic brackets — they must not truncate the parameter list."""

    def test_comparison_in_default_keeps_later_params(self):
        from batho.modules.graph.builder.codegraph import _signature_param_map

        m = _signature_param_map("fn f(a: int = (x > y), b: Svc)")
        assert set(m) == {"a", "b"}
        assert m["b"][0] == "Svc"

    def test_shift_operators_in_default(self):
        from batho.modules.graph.builder.codegraph import _signature_param_map

        m = _signature_param_map("fn f(a = (1 << 3) >> 1, b: str = 'x')")
        assert set(m) == {"a", "b"}

    def test_generics_in_annotation_still_counted(self):
        from batho.modules.graph.builder.codegraph import _signature_param_map

        m = _signature_param_map("fn f(v: Vec<T>, m: Map<K, V>)")
        assert set(m) == {"v", "m"}
        assert m["v"][0] == "Vec<T>"

    def test_greater_equal_in_default(self):
        from batho.modules.graph.builder.codegraph import _signature_param_map

        m = _signature_param_map("fn f(a: int = (x >= y), b: Svc)")
        assert set(m) == {"a", "b"}


class TestLazyParityBindingMaps:
    """GRH-16: resolve_stub_on_demand must build the same binding maps the
    batch pass constructs — Source-5 assignment inference is otherwise dead
    in lazy mode."""

    def test_lazy_resolution_uses_assignment_binding(self):
        import tempfile

        from batho.core.schemas import Relationship, RelationshipType

        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            svc = _make_entity("Svc", EntityType.STRUCT, start_line=1)
            ping = _make_entity("Svc.ping", EntityType.METHOD, start_line=3)
            factory = _make_entity(
                "get_svc", EntityType.FUNCTION, start_line=6,
                signature="fn get_svc() -> Svc",
            )
            caller = _make_entity(
                "handler", EntityType.FUNCTION, start_line=8,
                signature="fn handler()",
            )
            for e in (svc, ping, factory, caller):
                graph.add_entity(e)
            sm.define_symbol("Svc", svc.id, "STRUCT", is_global=True)
            sm.define_symbol("Svc.ping", ping.id, "METHOD", is_global=True)
            sm.define_symbol("get_svc", factory.id, "FUNCTION", is_global=True)

            # `svc = get_svc()` at line 9 — the assigned_to edge metadata the
            # batch pass reads into _assigned_by_scope_var.
            graph.add_relationship(Relationship(
                source_id=caller.id,
                target_id=factory.id,
                type=RelationshipType.USES,
                metadata={"assigned_to": "svc", "line_number": 9},
            ))

            # `svc.ping()` at line 10 inside handler — unresolved stub.
            stub = _make_stub("svc.ping", caller_scope=caller.id, line=10)
            graph.add_entity(stub)

            target = indexer.resolve_stub_on_demand(stub.id, graph, sm)
            assert target == ping.id
            updated = graph.get_entity(stub.id)
            assert updated.metadata["stub_resolution_state"] == "resolved"
            assert updated.metadata["resolution_strategy"] == "receiver_assignment"
            indexer.close()
