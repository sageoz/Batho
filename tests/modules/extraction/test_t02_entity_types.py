"""T02: Missing entity types — CONSTRUCTOR, ENUM_MEMBER, PARAMETER, TYPE_PARAMETER.

Tests verify:
  - Python __init__ is extracted as CONSTRUCTOR, not METHOD
  - Rust enum variants are extracted as ENUM_MEMBER
  - PARAMETER extraction is opt-in (off by default)
  - TYPE_PARAMETER extraction is opt-in (off by default)
  - New types map to EntityCategory.CODE (T01 integration)
  - No entity count regression with default config
"""

from __future__ import annotations

from batho.core.schemas import EntityCategory, EntityType
from batho.modules.extraction.submodules.parser_factory._queries import (
    PYTHON_QUERY,
    RUST_QUERY,
)
from batho.modules.extraction.submodules.parser_factory.factory import create_extractor


class TestConstructorExtraction:
    """CONSTRUCTOR entity type tests."""

    def test_python_init_is_constructor(self):
        """Python __init__ method is extracted as CONSTRUCTOR, not METHOD."""
        extractor = create_extractor("python", PYTHON_QUERY)
        content = b"""
class MyClass:
    def __init__(self, x):
        self.x = x

    def regular_method(self):
        return self.x
"""
        entities, _ = extractor.parse_file("test.py", content)

        constructors = [e for e in entities if e.type == EntityType.CONSTRUCTOR]
        assert len(constructors) == 1
        # Name has FQN prefix and param hash (e.g. "MyClass.__init___[bff627]")
        assert "__init__" in constructors[0].name

        # __init__ should NOT appear as METHOD
        methods = [e for e in entities if e.type == EntityType.METHOD]
        method_names = [m.name for m in methods]
        assert not any("__init__" in n for n in method_names)
        # regular_method should still be METHOD
        assert any("regular_method" in n for n in method_names)

    def test_constructor_category_is_code(self):
        """EntityType.CONSTRUCTOR.category == EntityCategory.CODE."""
        assert EntityType.CONSTRUCTOR.category == EntityCategory.CODE

    def test_java_constructor_capture(self):
        """Java constructor_declaration is captured as CONSTRUCTOR."""
        from batho.modules.extraction.submodules.parser_factory._queries import JAVA_QUERY

        extractor = create_extractor("java", JAVA_QUERY)
        content = b"""
public class Foo {
    public Foo(int x) {
        this.x = x;
    }
}
"""
        entities, _ = extractor.parse_file("Foo.java", content)
        constructors = [e for e in entities if e.type == EntityType.CONSTRUCTOR]
        assert len(constructors) == 1
        # Name may have FQN prefix or param hash; just check it contains "Foo"
        assert "Foo" in constructors[0].name


class TestEnumMemberExtraction:
    """ENUM_MEMBER entity type tests."""

    def test_rust_enum_variants_are_enum_members(self):
        """Rust enum variants are extracted as ENUM_MEMBER.

        b2e4d8f1 fix: ENUM is pushed to the scope stack, so members get
        qualified FQNs (Color.Red) — this disambiguates same-named variants
        across enums in one file.
        """
        extractor = create_extractor("rust", RUST_QUERY)
        content = b"""
enum Color {
    Red,
    Green,
    Blue,
}
"""
        entities, _ = extractor.parse_file("test.rs", content)

        enum_members = [e for e in entities if e.type == EntityType.ENUM_MEMBER]
        member_names = {e.name for e in enum_members}
        assert "Color.Red" in member_names
        assert "Color.Green" in member_names
        assert "Color.Blue" in member_names

    def test_same_named_variants_in_different_enums_get_distinct_ids(self):
        """Two same-named variants in different enums produce distinct entity IDs."""
        extractor = create_extractor("rust", RUST_QUERY)
        content = b"""
enum Color {
    Red,
}
enum Status {
    Red,
}
"""
        entities, _ = extractor.parse_file("test.rs", content)

        enum_members = [e for e in entities if e.type == EntityType.ENUM_MEMBER]
        assert len(enum_members) == 2
        ids = {e.id for e in enum_members}
        assert len(ids) == 2, f"Expected 2 distinct IDs, got {ids}"
        names = {e.name for e in enum_members}
        assert names == {"Color.Red", "Status.Red"}

    def test_enum_member_category_is_code(self):
        """EntityType.ENUM_MEMBER.category == EntityCategory.CODE."""
        assert EntityType.ENUM_MEMBER.category == EntityCategory.CODE


class TestParameterExtraction:
    """PARAMETER entity type tests (opt-in)."""

    def test_parameters_off_by_default(self):
        """With default config, no PARAMETER entities are created."""
        extractor = create_extractor("python", PYTHON_QUERY)
        content = b"""
def foo(a, b):
    return a + b
"""
        entities, _ = extractor.parse_file("test.py", content)
        parameters = [e for e in entities if e.type == EntityType.PARAMETER]
        assert len(parameters) == 0

    def test_parameters_on_when_enabled(self):
        """With extract_parameters=True, PARAMETER entities are created."""
        extractor = create_extractor(
            "python", PYTHON_QUERY, {"extract_parameters": True}
        )
        content = b"""
def foo(a, b):
    return a + b
"""
        entities, _ = extractor.parse_file("test.py", content)
        parameters = [e for e in entities if e.type == EntityType.PARAMETER]
        param_names = {e.name for e in parameters}
        assert "a" in param_names
        assert "b" in param_names

    def test_parameter_category_is_code(self):
        """EntityType.PARAMETER.category == EntityCategory.CODE."""
        assert EntityType.PARAMETER.category == EntityCategory.CODE


class TestTypeParameterExtraction:
    """TYPE_PARAMETER entity type tests (opt-in)."""

    def test_type_parameters_off_by_default(self):
        """With default config, no TYPE_PARAMETER entities are created."""
        extractor = create_extractor("python", PYTHON_QUERY)
        content = b"""
def identity(x):
    return x
"""
        entities, _ = extractor.parse_file("test.py", content)
        type_params = [e for e in entities if e.type == EntityType.TYPE_PARAMETER]
        assert len(type_params) == 0

    def test_type_parameter_category_is_code(self):
        """EntityType.TYPE_PARAMETER.category == EntityCategory.CODE."""
        assert EntityType.TYPE_PARAMETER.category == EntityCategory.CODE


class TestNoEntityCountRegression:
    """Default config should not inflate entity counts."""

    def test_default_config_no_extra_entities(self):
        """With default config, a simple Python file produces no PARAMETER or TYPE_PARAMETER entities."""
        extractor = create_extractor("python", PYTHON_QUERY)
        content = b"""
class MyClass:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def compute(self):
        return self.x + self.y

def helper(a, b):
    return a * b
"""
        entities, _ = extractor.parse_file("test.py", content)

        # Should have: 1 CLASS, 1 CONSTRUCTOR, 1 METHOD, 1 FUNCTION
        # Should NOT have: PARAMETER, TYPE_PARAMETER
        type_counts: dict[EntityType, int] = {}
        for e in entities:
            type_counts[e.type] = type_counts.get(e.type, 0) + 1

        assert type_counts.get(EntityType.PARAMETER, 0) == 0
        assert type_counts.get(EntityType.TYPE_PARAMETER, 0) == 0
        assert type_counts.get(EntityType.CONSTRUCTOR, 0) == 1
        assert type_counts.get(EntityType.CLASS, 0) == 1
        assert type_counts.get(EntityType.METHOD, 0) == 1
        assert type_counts.get(EntityType.FUNCTION, 0) == 1
