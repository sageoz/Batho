"""T03: PROPERTY extraction implementation.

Tests verify:
  - Python @property decorated methods are extracted as PROPERTY, not METHOD
  - Python @x.setter decorated methods are extracted as PROPERTY with access_type="write"
  - TypeScript get/set accessors are extracted as PROPERTY
  - C# auto-properties are extracted as PROPERTY
  - PROPERTY entities have parent_id pointing to the enclosing class
"""

from __future__ import annotations

from batho.core.schemas import EntityType
from batho.modules.extraction.submodules.parser_factory._queries import (
    CSHARP_QUERY,
    PYTHON_QUERY,
    TYPESCRIPT_QUERY,
)
from batho.modules.extraction.submodules.parser_factory.factory import create_extractor


class TestPythonPropertyExtraction:
    """Python @property and @x.setter extraction."""

    def test_property_decorator_creates_property_entity(self):
        """Python @property method is extracted as PROPERTY, not METHOD."""
        extractor = create_extractor("python", PYTHON_QUERY)
        content = b"""
class Foo:
    def __init__(self):
        self._x = 0

    @property
    def x(self):
        return self._x
"""
        entities, _ = extractor.parse_file("test.py", content)

        properties = [e for e in entities if e.type == EntityType.PROPERTY]
        assert len(properties) == 1
        assert "x" in properties[0].name

        # x should NOT appear as METHOD
        methods = [e for e in entities if e.type == EntityType.METHOD]
        method_names = [m.name for m in methods]
        assert not any(n == "x" for n in method_names)

    def test_property_setter_creates_property_with_write_access(self):
        """Python @x.setter method is extracted as PROPERTY with access_type='write'."""
        extractor = create_extractor("python", PYTHON_QUERY)
        content = b"""
class Foo:
    def __init__(self):
        self._x = 0

    @property
    def x(self):
        return self._x

    @x.setter
    def x(self, value):
        self._x = value
"""
        entities, _ = extractor.parse_file("test.py", content)

        properties = [e for e in entities if e.type == EntityType.PROPERTY]
        assert len(properties) == 2

        # One should have access_type="write" (the setter)
        write_props = [e for e in properties if e.metadata.get("access_type") == "write"]
        assert len(write_props) == 1

        # One should have access_type="read" (the getter)
        read_props = [e for e in properties if e.metadata.get("access_type") == "read"]
        assert len(read_props) == 1

    def test_property_has_parent_id_pointing_to_class(self):
        """PROPERTY entity has parent_id pointing to the enclosing class."""
        extractor = create_extractor("python", PYTHON_QUERY)
        content = b"""
class Foo:
    @property
    def x(self):
        return 42
"""
        entities, _ = extractor.parse_file("test.py", content)

        classes = [e for e in entities if e.type == EntityType.CLASS]
        properties = [e for e in entities if e.type == EntityType.PROPERTY]
        assert len(classes) == 1
        assert len(properties) == 1

        # The property's parent_id should point to the class
        assert properties[0].parent_id == classes[0].id

    def test_regular_method_not_affected_by_property_capture(self):
        """Methods without @property decorator are still extracted as METHOD."""
        extractor = create_extractor("python", PYTHON_QUERY)
        content = b"""
class Foo:
    @property
    def x(self):
        return 42

    def regular(self):
        return x
"""
        entities, _ = extractor.parse_file("test.py", content)

        methods = [e for e in entities if e.type == EntityType.METHOD]
        method_names = [m.name for m in methods]
        assert any("regular" in n for n in method_names)


class TestTypeScriptPropertyExtraction:
    """TypeScript get/set accessor extraction."""

    def test_get_accessor_creates_property_entity(self):
        """TypeScript get accessor is extracted as PROPERTY."""
        extractor = create_extractor("typescript", TYPESCRIPT_QUERY)
        content = b"""
class Foo {
    get name(): string { return this._name; }
}
"""
        entities, _ = extractor.parse_file("test.ts", content)

        properties = [e for e in entities if e.type == EntityType.PROPERTY]
        assert len(properties) >= 1
        assert any("name" in p.name for p in properties)

    def test_set_accessor_creates_property_entity(self):
        """TypeScript set accessor is extracted as PROPERTY."""
        extractor = create_extractor("typescript", TYPESCRIPT_QUERY)
        content = b"""
class Foo {
    set name(value: string) { this._name = value; }
}
"""
        entities, _ = extractor.parse_file("test.ts", content)

        properties = [e for e in entities if e.type == EntityType.PROPERTY]
        assert len(properties) >= 1
        assert any("name" in p.name for p in properties)


class TestCSharpPropertyExtraction:
    """C# auto-property extraction."""

    def test_auto_property_creates_property_entity(self):
        """C# auto-property is extracted as PROPERTY."""
        extractor = create_extractor("csharp", CSHARP_QUERY)
        content = b"""
public class Foo {
    public string Name { get; set; }
}
"""
        entities, _ = extractor.parse_file("Foo.cs", content)

        properties = [e for e in entities if e.type == EntityType.PROPERTY]
        assert len(properties) >= 1
        assert any("Name" in p.name for p in properties)

    def test_property_has_parent_id_pointing_to_class(self):
        """C# PROPERTY entity has parent_id pointing to the enclosing class."""
        extractor = create_extractor("csharp", CSHARP_QUERY)
        content = b"""
public class Foo {
    public string Name { get; set; }
}
"""
        entities, _ = extractor.parse_file("Foo.cs", content)

        classes = [e for e in entities if e.type == EntityType.CLASS]
        properties = [e for e in entities if e.type == EntityType.PROPERTY]
        assert len(classes) == 1
        assert len(properties) >= 1

        # At least one property should have parent_id pointing to the class
        assert any(p.parent_id == classes[0].id for p in properties)


class TestPropertyCategory:
    """PROPERTY entity type category integration (T01)."""

    def test_property_category_is_code(self):
        """EntityType.PROPERTY.category == EntityCategory.CODE."""
        from batho.core.schemas import EntityCategory
        assert EntityType.PROPERTY.category == EntityCategory.CODE


class TestKotlinPropertyExtraction:
    """T03: Kotlin class-scoped val/var properties."""

    def _extract(self, content: bytes):
        from batho.modules.extraction.submodules.parser_factory._queries import KOTLIN_QUERY
        extractor = create_extractor("kotlin", KOTLIN_QUERY)
        entities, _ = extractor.parse_file("Foo.kt", content)
        return entities

    def test_kotlin_val_creates_property(self):
        """Kotlin class-scoped `val` is extracted as PROPERTY with access_type=read."""
        entities = self._extract(
            b"class Foo {\n    val name: String = \"x\"\n}\n"
        )
        props = [e for e in entities if e.type == EntityType.PROPERTY]
        assert len(props) == 1, f"Expected 1 PROPERTY, got {[(e.type.name, e.name) for e in entities]}"
        assert props[0].name.endswith("name")
        assert props[0].metadata.get("access_type") == "read"

    def test_kotlin_var_is_write(self):
        """Kotlin `var` property gets access_type=write."""
        entities = self._extract(
            b"class Foo {\n    var count: Int = 0\n}\n"
        )
        props = [e for e in entities if e.type == EntityType.PROPERTY]
        assert len(props) == 1
        assert props[0].metadata.get("access_type") == "write"

    def test_kotlin_property_parent_is_class(self):
        """PROPERTY entity has parent_id pointing to the enclosing class."""
        entities = self._extract(
            b"class Foo {\n    val name: String = \"x\"\n}\n"
        )
        prop = next(e for e in entities if e.type == EntityType.PROPERTY)
        parent = next((e for e in entities if e.id == prop.parent_id), None)
        assert parent is not None, "PROPERTY should have a parent_id"
        assert parent.type == EntityType.CLASS

    def test_kotlin_modifiers_do_not_block_capture(self):
        """`private val x` (modifiers before binding) is still captured."""
        entities = self._extract(
            b"class Foo {\n    private val secret = 1\n}\n"
        )
        props = [e for e in entities if e.type == EntityType.PROPERTY]
        assert len(props) == 1
        assert props[0].name.endswith("secret")

    def test_kotlin_object_property(self):
        """Properties inside `object` declarations are captured; the object
        itself becomes a CLASS entity (singleton) and acts as parent."""
        entities = self._extract(
            b"object Singleton {\n    const val TAG = \"x\"\n}\n"
        )
        props = [e for e in entities if e.type == EntityType.PROPERTY]
        assert len(props) == 1
        assert props[0].name.endswith("TAG")
        assert props[0].parent_id is not None

    def test_kotlin_methods_not_properties(self):
        """`fun` members are METHOD, not PROPERTY (no overlap)."""
        entities = self._extract(
            b"class Foo {\n    fun compute(): Int = 1\n}\n"
        )
        assert not [e for e in entities if e.type == EntityType.PROPERTY]
        assert any(e.type == EntityType.METHOD for e in entities)
