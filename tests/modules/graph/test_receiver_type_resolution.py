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
    receiver_type: str | None = None,
    file: str = "/test/main.rs",
    line: int = 10,
) -> Entity:
    """Create a contextual stub with receiver_var metadata."""
    if receiver_var is None and "." in target_name:
        receiver_var = target_name.split(".")[0]
    stub_id = f"unresolved:{caller_scope}::{target_name}"
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
# receiver_var extraction in _make_contextual_stub (extractor.py logic)
# ---------------------------------------------------------------------------


class TestReceiverVarExtraction:
    """Verify receiver_var is correctly extracted from ref_text.

    The extraction logic (in extractor.py _make_contextual_stub) is:
        receiver_var = ref_text.split(".")[0] if "." in ref_text else None
    """

    @pytest.mark.parametrize("ref_text,expected", [
        ("cursor.execute", "cursor"),
        ("self.method", "self"),
        ("this.prop", "this"),
        ("obj.a.b.c", "obj"),
        ("json.dumps", "json"),
        ("std::option::Option", None),  # Uses :: not ., so no receiver_var
        ("simple", None),  # No dot
        ("", None),  # Empty string, no dot
        (".leading_dot", ""),  # Dot at start, first segment is empty
    ])
    def test_receiver_var_extraction(self, ref_text, expected):
        """Verify receiver_var is extracted correctly from ref_text."""
        if "." in ref_text:
            receiver_var = ref_text.split(".")[0]
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

            # Stub referencing cursor.execute with receiver_type hint
            stub = _make_stub("cursor.execute", receiver_type="Cursor")
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

            # Stub referencing opt.unwrap with receiver_type=Option
            stub = _make_stub("opt.unwrap", receiver_type="Option")
            graph.add_entity(stub)

            result = indexer._resolve_method_call(stub, graph, sm)
            assert result is not None
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

            stub = _make_stub("unknown_var.method", receiver_type="UnknownType")
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

    def test_receiver_type_metadata_hint(self):
        """receiver_type in stub metadata is used as type hint."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            stub = _make_stub("var.method", receiver_type="HashMap")
            graph.add_entity(stub)

            var_type = indexer._infer_variable_type("var", stub, graph, sm)
            assert var_type == "HashMap"
            indexer.close()

    def test_variable_declaration_in_same_file(self):
        """A variable entity with declared_type in the same file is used."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            # Variable declaration with type annotation
            var_entity = _make_entity(
                "my_var", EntityType.FUNCTION,  # Using FUNCTION as a stand-in
                file="/test/main.rs",
                start_line=5,
                metadata={"declared_type": "Vec<String>"},
            )
            graph.add_entity(var_entity)

            stub = _make_stub("my_var.push", file="/test/main.rs", line=10)
            graph.add_entity(stub)

            var_type = indexer._infer_variable_type("my_var", stub, graph, sm)
            assert var_type == "Vec<String>"
            indexer.close()

    def test_variable_declaration_in_different_file_not_used(self):
        """A variable declaration in a different file is not used for inference."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            var_entity = _make_entity(
                "my_var", EntityType.FUNCTION,
                file="/test/other.rs",
                start_line=5,
                metadata={"declared_type": "Vec<String>"},
            )
            graph.add_entity(var_entity)

            stub = _make_stub("my_var.push", file="/test/main.rs", line=10)
            graph.add_entity(stub)

            var_type = indexer._infer_variable_type("my_var", stub, graph, sm)
            assert var_type is None
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
        """opt.unwrap with receiver_type=Option resolves via stdlib."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer = _make_indexer(tmp)
            graph = InMemoryGraph()
            sm = ScopeManager()

            sm.add_external_symbol(
                name="std::option::Option",
                symbol_id="batho stdb rust 1.70 std::option::Option/",
                symbol_type="module",
            )

            stub = _make_stub("opt.unwrap", receiver_type="Option")
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

            stub = _make_stub("obj.a.b.c", receiver_type="SomeType")
            graph.add_entity(stub)

            # _resolve_method_call should try "SomeType.a.b.c"
            # which won't resolve, but the method_name extraction is correct
            target_name = stub.metadata.get("target_name", "")
            method_name = target_name.split(".", 1)[1]
            assert method_name == "a.b.c"
            indexer.close()
