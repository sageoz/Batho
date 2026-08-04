"""Tests for CONTAINS relationship synthesis between Rust/Go types and their methods.

Verifies that ref.impl_type (Rust) and ref.receiver_type (Go) captures correctly
link struct/enum/trait entities to their impl-block / receiver methods via
CONTAINS relationships, reducing false orphan pruning.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from batho.core.schemas import EntityType, RelationshipType
from batho.modules.extraction.submodules.parser_factory.factory import get_extractor


RUST_STRUCT_WITH_IMPL = b"""\
struct Foo {
    x: i32,
}

impl Foo {
    fn bar(&self) -> i32 {
        self.x
    }

    fn baz(&self) -> bool {
        self.x > 0
    }
}
"""

RUST_ENUM_WITH_IMPL = b"""\
enum Color {
    Red,
    Blue,
}

impl Color {
    fn from_str(s: &str) -> Color {
        Color::Red
    }
}
"""

RUST_TRAIT_IMPL = b"""\
trait Greet {
    fn hello(&self);
}

struct Person {
    name: String,
}

impl Greet for Person {
    fn hello(&self) {
        println!("hi");
    }
}
"""

RUST_FREE_FUNCTIONS = b"""\
fn main() {
    println!("hello");
}

fn helper() -> i32 {
    42
}
"""

GO_STRUCT_WITH_METHODS = b"""\
package main

type Foo struct {
    x int
}

func (f *Foo) Bar() int {
    return f.x
}

func (f Foo) Baz() bool {
    return f.x > 0
}
"""

GO_INTERFACE_NO_METHODS = b"""\
package main

type Reader interface {
    Read(p []byte) (n int, err error)
}
"""

GO_STRUCT_POINTER_RECEIVER = b"""\
package main

type Buffer struct {
    data []byte
}

func (b *Buffer) Write(p []byte) {
    b.data = append(b.data, p...)
}
"""


class TestRustContainsSynthesis:
    """Verify Rust impl blocks generate CONTAINS from struct/enum to methods."""

    @pytest.fixture(scope="class")
    def extractor(self):
        return get_extractor("rust")

    def test_struct_impl_methods_get_contains(
        self, tmp_path: Path, extractor
    ) -> None:
        file_path = tmp_path / "foo.rs"
        file_path.write_bytes(RUST_STRUCT_WITH_IMPL)

        entities, relationships = extractor.parse_file(str(file_path), RUST_STRUCT_WITH_IMPL)

        struct_ents = [e for e in entities if e.type == EntityType.STRUCT and e.name == "Foo"]
        method_ents = [e for e in entities if e.type == EntityType.METHOD]
        assert len(struct_ents) == 1, f"Expected 1 Foo struct, got {len(struct_ents)}"
        assert len(method_ents) == 2, f"Expected 2 methods, got {len(method_ents)}"

        contains_rels = [
            r for r in relationships
            if r.type == RelationshipType.CONTAINS and r.source_id == struct_ents[0].id
        ]
        method_ids = {m.id for m in method_ents}
        contains_targets = {r.target_id for r in contains_rels}
        assert contains_targets == method_ids, (
            f"Expected CONTAINS from Foo to both methods, got targets: {contains_targets}"
        )

    def test_enum_impl_method_gets_contains(
        self, tmp_path: Path, extractor
    ) -> None:
        file_path = tmp_path / "color.rs"
        file_path.write_bytes(RUST_ENUM_WITH_IMPL)

        entities, relationships = extractor.parse_file(str(file_path), RUST_ENUM_WITH_IMPL)

        enum_ents = [e for e in entities if e.type == EntityType.ENUM and e.name == "Color"]
        method_ents = [e for e in entities if e.type == EntityType.METHOD]
        assert len(enum_ents) == 1, f"Expected 1 Color enum, got {len(enum_ents)}"
        assert len(method_ents) == 1, f"Expected 1 method, got {len(method_ents)}"

        contains_rels = [
            r for r in relationships
            if r.type == RelationshipType.CONTAINS and r.source_id == enum_ents[0].id
        ]
        assert len(contains_rels) == 1, (
            f"Expected 1 CONTAINS from Color to from_str, got {len(contains_rels)}"
        )
        assert contains_rels[0].target_id == method_ents[0].id

    def test_trait_impl_links_to_struct_not_trait(
        self, tmp_path: Path, extractor
    ) -> None:
        file_path = tmp_path / "person.rs"
        file_path.write_bytes(RUST_TRAIT_IMPL)

        entities, relationships = extractor.parse_file(str(file_path), RUST_TRAIT_IMPL)

        struct_ents = [e for e in entities if e.type == EntityType.STRUCT and e.name == "Person"]
        trait_ents = [e for e in entities if e.type == EntityType.TRAIT and e.name == "Greet"]
        method_ents = [e for e in entities if e.type == EntityType.METHOD]
        assert len(struct_ents) == 1
        assert len(trait_ents) == 1
        assert len(method_ents) == 1

        # CONTAINS should go from Person (the impl target), not Greet (the trait)
        contains_from_struct = [
            r for r in relationships
            if r.type == RelationshipType.CONTAINS and r.source_id == struct_ents[0].id
        ]
        assert len(contains_from_struct) == 1
        assert contains_from_struct[0].target_id == method_ents[0].id

        contains_from_trait = [
            r for r in relationships
            if r.type == RelationshipType.CONTAINS and r.source_id == trait_ents[0].id
        ]
        assert len(contains_from_trait) == 0, "Trait should not CONTAIN the impl method"

    def test_free_functions_no_false_contains(
        self, tmp_path: Path, extractor
    ) -> None:
        file_path = tmp_path / "main.rs"
        file_path.write_bytes(RUST_FREE_FUNCTIONS)

        entities, relationships = extractor.parse_file(str(file_path), RUST_FREE_FUNCTIONS)

        contains_rels = [r for r in relationships if r.type == RelationshipType.CONTAINS]
        assert len(contains_rels) == 0, (
            f"Free functions should not have CONTAINS relationships, got {len(contains_rels)}"
        )


class TestGoContainsSynthesis:
    """Verify Go receiver methods generate CONTAINS from struct to methods."""

    @pytest.fixture(scope="class")
    def extractor(self):
        return get_extractor("go")

    def test_struct_methods_get_contains(
        self, tmp_path: Path, extractor
    ) -> None:
        file_path = tmp_path / "foo.go"
        file_path.write_bytes(GO_STRUCT_WITH_METHODS)

        entities, relationships = extractor.parse_file(str(file_path), GO_STRUCT_WITH_METHODS)

        struct_ents = [e for e in entities if e.type == EntityType.STRUCT and e.name == "Foo"]
        method_ents = [e for e in entities if e.type == EntityType.METHOD]
        assert len(struct_ents) == 1, f"Expected 1 Foo struct, got {len(struct_ents)}"
        assert len(method_ents) == 2, f"Expected 2 methods, got {len(method_ents)}"

        contains_rels = [
            r for r in relationships
            if r.type == RelationshipType.CONTAINS and r.source_id == struct_ents[0].id
        ]
        method_ids = {m.id for m in method_ents}
        contains_targets = {r.target_id for r in contains_rels}
        assert contains_targets == method_ids, (
            f"Expected CONTAINS from Foo to both methods, got targets: {contains_targets}"
        )

    def test_pointer_receiver_gets_contains(
        self, tmp_path: Path, extractor
    ) -> None:
        file_path = tmp_path / "buffer.go"
        file_path.write_bytes(GO_STRUCT_POINTER_RECEIVER)

        entities, relationships = extractor.parse_file(str(file_path), GO_STRUCT_POINTER_RECEIVER)

        struct_ents = [e for e in entities if e.type == EntityType.STRUCT and e.name == "Buffer"]
        method_ents = [e for e in entities if e.type == EntityType.METHOD]
        assert len(struct_ents) == 1
        assert len(method_ents) == 1

        contains_rels = [
            r for r in relationships
            if r.type == RelationshipType.CONTAINS and r.source_id == struct_ents[0].id
        ]
        assert len(contains_rels) == 1, (
            f"Expected 1 CONTAINS from Buffer to Write, got {len(contains_rels)}"
        )
        assert contains_rels[0].target_id == method_ents[0].id

    def test_interface_no_false_contains(
        self, tmp_path: Path, extractor
    ) -> None:
        file_path = tmp_path / "reader.go"
        file_path.write_bytes(GO_INTERFACE_NO_METHODS)

        entities, relationships = extractor.parse_file(str(file_path), GO_INTERFACE_NO_METHODS)

        interface_ents = [e for e in entities if e.type == EntityType.INTERFACE]
        contains_rels = [r for r in relationships if r.type == RelationshipType.CONTAINS]
        # Interface declaration has no receiver methods — no CONTAINS should be synthesized
        interface_contains = [
            r for r in contains_rels
            if interface_ents and r.source_id == interface_ents[0].id
        ]
        assert len(interface_contains) == 0, (
            "Interface should not have synthesized CONTAINS to non-receiver methods"
        )
