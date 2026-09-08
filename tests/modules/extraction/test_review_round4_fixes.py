"""Tests for review round 4 fixes (Extraction):

- 3f8a1d62: Kotlin methods inside object declarations are captured
- 5c2e9b74: Kotlin interfaces emit INTERFACE entities, not CLASS
"""

from __future__ import annotations

from batho.core.schemas import EntityType
from batho.modules.extraction.submodules.parser_factory.factory import create_extractor
from batho.modules.extraction.submodules.parser_factory._queries import KOTLIN_QUERY


class TestKotlinObjectMethods:
    """3f8a1d62: methods inside object_declaration bodies must be captured."""

    def test_method_inside_object_declaration(self):
        """object_declaration class_body functions are captured as METHOD.

        Uses a modifier so the declaration parses as object_declaration in
        the tree-sitter-language-pack Kotlin grammar (a bare top-level
        `object Name { ... }` with members is misparsed as an expression by
        the grammar itself — a separate pre-existing limitation).
        """
        extractor = create_extractor("kotlin", KOTLIN_QUERY)
        content = (
            b"public object Singleton {\n"
            b"    val cached: String = \"c\"\n"
            b"    fun run(x: Int) {}\n"
            b"}\n"
        )
        entities, _rels = extractor.parse_file("test.kt", content)

        methods = [e for e in entities if e.type == EntityType.METHOD]
        assert len(methods) == 1, (
            f"Expected METHOD inside object_declaration, got: "
            f"{[(e.type.name, e.name) for e in entities]}"
        )
        assert methods[0].name.startswith("Singleton.run")

        properties = [e for e in entities if e.type == EntityType.PROPERTY]
        assert len(properties) == 1
        assert properties[0].name.startswith("Singleton.cached")

    def test_method_inside_object_with_supertype(self):
        """object X : Super { fun go() {} } also captures the method."""
        extractor = create_extractor("kotlin", KOTLIN_QUERY)
        content = b"object Solo : Runnable { fun go() {} }\n"
        entities, _rels = extractor.parse_file("test.kt", content)

        methods = [e for e in entities if e.type == EntityType.METHOD]
        assert len(methods) == 1
        assert methods[0].name.startswith("Solo.go")


class TestKotlinInterfaceEntityType:
    """5c2e9b74: Kotlin interfaces are INTERFACE, not CLASS."""

    def test_interface_entity_type(self):
        extractor = create_extractor("kotlin", KOTLIN_QUERY)
        content = b"interface Iface { fun baz() }\n"
        entities, _rels = extractor.parse_file("test.kt", content)

        ifaces = [e for e in entities if e.name == "Iface"]
        assert len(ifaces) == 1
        assert ifaces[0].type == EntityType.INTERFACE, (
            f"interface must be INTERFACE, got {ifaces[0].type}"
        )

    def test_class_still_class_and_enum_class_unaffected(self):
        """`class C : I` and `enum class Color` must remain CLASS."""
        extractor = create_extractor("kotlin", KOTLIN_QUERY)
        content = (
            b"interface Iface { fun baz() }\n"
            b"class Impl : Iface { override fun baz() {} }\n"
            b"enum class Color { RED }\n"
        )
        entities, _rels = extractor.parse_file("test.kt", content)

        by_name = {e.name: e for e in entities}
        assert by_name["Impl"].type == EntityType.CLASS
        assert by_name["Color"].type == EntityType.CLASS
        assert by_name["Iface"].type == EntityType.INTERFACE
        # Members still captured with qualified FQNs
        assert any(
            e.name.startswith("Impl.baz") and e.type == EntityType.METHOD
            for e in entities
        )
        assert any(e.name == "Color.RED" for e in entities)

    def test_interface_scope_qualifies_members(self):
        """INTERFACE is pushed to the scope stack — members get qualified FQNs.

        The method needs a body: the grammar wraps bodyless interface
        functions in an ERROR node (pre-existing grammar limitation).
        """
        extractor = create_extractor("kotlin", KOTLIN_QUERY)
        content = b"interface Iface { fun baz() { return 1 } }\n"
        entities, _rels = extractor.parse_file("test.kt", content)

        methods = [e for e in entities if e.type == EntityType.METHOD]
        assert len(methods) == 1
        assert methods[0].name.startswith("Iface.baz")
