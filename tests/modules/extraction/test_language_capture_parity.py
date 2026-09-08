"""Tests for cross-language PARAMETER / TYPE_PARAMETER / Rust CONSTRUCTOR captures.

Closes the capture-parity gap where def.parameter / def.type_parameter
captures existed only for Python:

- def.parameter: TypeScript, Java, C#, Rust (opt-in via extract_parameters)
- def.type_parameter: TypeScript, Java, C#, Rust (opt-in via
  extract_type_parameters)
- def.constructor: Rust `new` associated functions in impl blocks (TS, Java
  and C# already had constructor captures)
"""

from __future__ import annotations

from batho.core.schemas import EntityType
from batho.modules.extraction.submodules.parser_factory._queries import (
    C_QUERY,
    CPP_QUERY,
    CSHARP_QUERY,
    JAVA_QUERY,
    PYTHON_QUERY,
    RUST_QUERY,
    TYPESCRIPT_QUERY,
)
from batho.modules.extraction.submodules.parser_factory.factory import create_extractor

OPT_IN = {"extract_parameters": True, "extract_type_parameters": True}


def _extract(lang: str, query: str, content: bytes, filename: str):
    extractor = create_extractor(lang, query)
    extractor.set_parsing_config(OPT_IN)
    entities, _ = extractor.parse_file(filename, content)
    return entities


def _names_of_type(entities, entity_type):
    return [e.name for e in entities if e.type == entity_type]


# ---------------------------------------------------------------------------
# Rust CONSTRUCTOR (impl + new)
# ---------------------------------------------------------------------------


class TestRustConstructorCapture:
    """Rust `new` associated functions are captured as CONSTRUCTOR."""

    def test_new_in_impl_is_constructor(self):
        entities = _extract(
            "rust", RUST_QUERY,
            b"struct S { x: i32 }\nimpl S {\n    pub fn new(x: i32) -> Self { S { x } }\n}\n",
            "test.rs",
        )
        ctors = [e for e in entities if e.type == EntityType.CONSTRUCTOR]
        assert len(ctors) == 1, f"Expected 1 CONSTRUCTOR, got {ctors}"
        assert ctors[0].name.startswith("new")
        assert ctors[0].signature == "new(x: i32) -> Self"

    def test_new_not_duplicated_as_method(self):
        entities = _extract(
            "rust", RUST_QUERY,
            b"struct S;\nimpl S {\n    fn new() -> Self { S }\n    fn other(&self) {}\n}\n",
            "test.rs",
        )
        assert len([e for e in entities if e.type == EntityType.CONSTRUCTOR]) == 1
        method_names = [e.name for e in entities if e.type == EntityType.METHOD]
        assert not any(n.startswith("new") for n in method_names), method_names
        assert any(n.startswith("other") for n in method_names), method_names

    def test_free_new_function_not_constructor(self):
        entities = _extract(
            "rust", RUST_QUERY,
            b"fn new() -> i32 { 0 }\n",
            "test.rs",
        )
        assert not [e for e in entities if e.type == EntityType.CONSTRUCTOR]
        assert any(e.type == EntityType.FUNCTION for e in entities)

    def test_default_impl_not_constructor(self):
        entities = _extract(
            "rust", RUST_QUERY,
            b"struct S;\nimpl Default for S {\n    fn default() -> Self { S }\n}\n",
            "test.rs",
        )
        assert not [e for e in entities if e.type == EntityType.CONSTRUCTOR]
        assert any(e.type == EntityType.METHOD for e in entities)


# ---------------------------------------------------------------------------
# PARAMETER captures (TS / Java / C# / Rust)
# ---------------------------------------------------------------------------


class TestTypeScriptParameterCapture:
    def test_plain_optional_rest_captured(self):
        entities = _extract(
            "typescript", TYPESCRIPT_QUERY,
            (b"class C {\n"
             b"  m(a: number, b?: string, ...rest: boolean[]) {}\n"
             b"}\n"),
            "test.ts",
        )
        params = [e for e in entities if e.type == EntityType.PARAMETER]
        names = {p.name.split(".")[-1] for p in params}
        assert names == {"a", "b", "rest"}, f"Got {names}"

    def test_disabled_by_default(self):
        extractor = create_extractor("typescript", TYPESCRIPT_QUERY)
        entities, _ = extractor.parse_file(
            "test.ts", b"class C {\n  m(a: number) {}\n}\n"
        )
        assert not [e for e in entities if e.type == EntityType.PARAMETER]


class TestJavaParameterCapture:
    def test_plain_and_varargs_captured(self):
        entities = _extract(
            "java", JAVA_QUERY,
            b"class C {\n    void m(int a, final String b, String... rest) {}\n}\n",
            "Test.java",
        )
        names = {p.name.split(".")[-1] for p in entities if p.type == EntityType.PARAMETER}
        assert names == {"a", "b", "rest"}, f"Got {names}"


class TestCSharpParameterCapture:
    def test_plain_optional_params_modifiers_captured(self):
        entities = _extract(
            "csharp", CSHARP_QUERY,
            (b"class C {\n"
             b"    public void M(int a, string b = \"x\", ref int c, out int d, params string[] rest) { d = 0; }\n"
             b"}\n"),
            "Test.cs",
        )
        names = {p.name.split(".")[-1] for p in entities if p.type == EntityType.PARAMETER}
        assert names == {"a", "b", "c", "d", "rest"}, f"Got {names}"


class TestRustParameterCapture:
    def test_parameter_forms_captured(self):
        entities = _extract(
            "rust", RUST_QUERY,
            (b"impl S {\n"
             b"    fn m(&self, a: i32, mut b: u8, ref c: u8, (d, e): (i32, i32), f: &str) {}\n"
             b"}\n"),
            "test.rs",
        )
        names = {p.name.split(".")[-1] for p in entities if p.type == EntityType.PARAMETER}
        assert names == {"a", "b", "c", "d", "e", "f"}, f"Got {names}"

    def test_self_receiver_excluded(self):
        entities = _extract(
            "rust", RUST_QUERY,
            b"impl S {\n    fn m(&self, x: i32) {}\n}\n",
            "test.rs",
        )
        names = [p.name.split(".")[-1] for p in entities if p.type == EntityType.PARAMETER]
        assert "self" not in names, f"self must be excluded, got {names}"
        assert "x" in names, f"x must be captured, got {names}"


# ---------------------------------------------------------------------------
# TYPE_PARAMETER captures (TS / Java / C# / Rust)
# ---------------------------------------------------------------------------


class TestTypeParameterCapture:
    def test_typescript(self):
        entities = _extract(
            "typescript", TYPESCRIPT_QUERY,
            b"class C<T, K extends keyof T = string> {}\nfunction f<U>(x: U) {}\n",
            "test.ts",
        )
        names = {p.name.split(".")[-1] for p in entities if p.type == EntityType.TYPE_PARAMETER}
        assert names == {"T", "K", "U"}, f"Got {names}"

    def test_java_no_bound_false_positive(self):
        entities = _extract(
            "java", JAVA_QUERY,
            b"class C<T, K extends Comparable<K>> {}\n",
            "Test.java",
        )
        names = {p.name.split(".")[-1] for p in entities if p.type == EntityType.TYPE_PARAMETER}
        assert names == {"T", "K"}, f"Got {names}"

    def test_csharp(self):
        entities = _extract(
            "csharp", CSHARP_QUERY,
            b"class C<T, K> where K : class {}\n",
            "Test.cs",
        )
        names = {p.name.split(".")[-1] for p in entities if p.type == EntityType.TYPE_PARAMETER}
        assert names == {"T", "K"}, f"Got {names}"

    def test_rust_no_default_type_false_positive(self):
        entities = _extract(
            "rust", RUST_QUERY,
            b"struct S<T: Clone, K = String> {}\n",
            "test.rs",
        )
        names = {p.name.split(".")[-1] for p in entities if p.type == EntityType.TYPE_PARAMETER}
        assert names == {"T", "K"}, f"Got {names}"

    def test_python_still_works(self):
        entities = _extract(
            "python", PYTHON_QUERY,
            b"def f[T](x: T):\n    pass\n",
            "test.py",
        )
        names = {p.name.split(".")[-1] for p in entities if p.type == EntityType.TYPE_PARAMETER}
        assert "T" in names, f"Got {names}"


# ---------------------------------------------------------------------------
# ENUM_MEMBER parity (Java, Kotlin, C, C++)
# ---------------------------------------------------------------------------


class TestEnumMemberParity:
    """T02 residual: ENUM_MEMBER captures for Java, Kotlin, C, C++."""

    def test_java_enum_members(self):
        entities = _extract(
            "java", JAVA_QUERY,
            b"enum Color { RED, GREEN }\n",
            "Color.java",
        )
        members = _names_of_type(entities, EntityType.ENUM_MEMBER)
        assert sorted(m.replace("Color.", "") for m in members) == ["GREEN", "RED"]

    def test_kotlin_enum_entries(self):
        from batho.modules.extraction.submodules.parser_factory._queries import KOTLIN_QUERY
        entities = _extract(
            "kotlin", KOTLIN_QUERY,
            b"enum class Color { RED, GREEN }\n",
            "Color.kt",
        )
        members = _names_of_type(entities, EntityType.ENUM_MEMBER)
        assert sorted(m.replace("Color.", "") for m in members) == ["GREEN", "RED"]

    def test_c_enum_enumerators(self):
        entities = _extract(
            "c", C_QUERY,
            b"enum Color { RED, GREEN };\n",
            "color.c",
        )
        members = _names_of_type(entities, EntityType.ENUM_MEMBER)
        assert sorted(m.rsplit(".", 1)[-1] for m in members) == ["GREEN", "RED"]

    def test_cpp_enum_enumerators(self):
        entities = _extract(
            "cpp", CPP_QUERY,
            b"enum Color { RED, GREEN };\n",
            "color.cpp",
        )
        members = _names_of_type(entities, EntityType.ENUM_MEMBER)
        assert sorted(m.rsplit(".", 1)[-1] for m in members) == ["GREEN", "RED"]

    def test_java_enum_declaration(self):
        """Java enum_declaration also produces the ENUM container entity."""
        entities = _extract(
            "java", JAVA_QUERY,
            b"enum Color { RED }\n",
            "Color.java",
        )
        assert any(e.type == EntityType.ENUM and e.name == "Color" for e in entities)
