"""Round-4 observation fix: stub ref-key normalization.

The stub ID format is ``unresolved:{caller_scope}::{ref_key}``. The ``::``
separator must be unambiguous, but ref text can itself contain ``::`` (Rust
paths like ``std::io::Write``, Ruby constant paths like ``Foo::Bar``). The
ref key is therefore dot-normalized at generation time (``_stub_ref_key``),
matching the convention ``_normalize_import_target`` already uses for import
targets. Display name and metadata keep the caller-written spelling.

Invariant pinned here: every emitted stub ID contains exactly one ``::``
(the scope/ref separator), for every language — including fixtures whose
source text uses ``::``-scoped references.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from batho.core.schemas import EntityType
from batho.modules.extraction.extractor import _stub_ref_key
from batho.modules.extraction.submodules.parser_factory.factory import get_extractor


class TestStubRefKey:
    """Unit tests for the _stub_ref_key helper."""

    def test_rust_scoped_path_normalized(self):
        assert _stub_ref_key("std::io::Write") == "std.io.Write"

    def test_ruby_constant_path_normalized(self):
        assert _stub_ref_key("Foo::Bar") == "Foo.Bar"

    def test_dotted_path_unchanged(self):
        assert _stub_ref_key("os.path.join") == "os.path.join"

    def test_bare_identifier_unchanged(self):
        assert _stub_ref_key("helper") == "helper"

    def test_idempotent(self):
        once = _stub_ref_key("a::b::c")
        assert _stub_ref_key(once) == once

    def test_empty(self):
        assert _stub_ref_key("") == ""


RUST_SCOPED_USE = b"""\
mod services {}

use crate::services::render;

fn main() {
    render();
}
"""

KOTLIN_METHOD_CALL = b"""\
class Widget {
    fun run() {
        Helper.assist()
    }
}
"""

RUBY_SCOPED_CALL = b"""\
module Outer
  def help; end
end

def run
  Outer::help
end
"""


class TestStubIdSingleSeparatorInvariant:
    """Stub IDs must contain exactly one '::' — the scope/ref separator.

    Ref text that itself contains '::' (Rust/Ruby scoped paths) must be
    dot-normalized in the ID; the display name keeps the original spelling.
    """

    @pytest.mark.parametrize(
        ("language", "filename", "source"),
        [
            ("rust", "main.rs", RUST_SCOPED_USE),
            ("kotlin", "widget.kt", KOTLIN_METHOD_CALL),
            ("ruby", "probe.rb", RUBY_SCOPED_CALL),
        ],
    )
    def test_stub_ids_have_single_scope_separator(
        self, tmp_path: Path, language: str, filename: str, source: bytes
    ) -> None:
        extractor = get_extractor(language)
        file_path = tmp_path / filename
        file_path.write_bytes(source)

        entities, relationships = extractor.parse_file(str(file_path), source)

        stubs = [e for e in entities if e.id.startswith("unresolved:")]
        assert stubs, f"expected at least one contextual stub for {language} fixture"
        for stub in stubs:
            assert stub.id.count("::") == 1, (
                f"stub ID must contain exactly one '::' separator: {stub.id!r}"
            )
            # Display name keeps the caller-written spelling (no rewriting).
            assert "::" not in stub.name or stub.name == stub.metadata.get("target_name")

    def test_rust_stub_name_preserves_source_spelling(
        self, tmp_path: Path
    ) -> None:
        extractor = get_extractor("rust")
        file_path = tmp_path / "main.rs"
        file_path.write_bytes(RUST_SCOPED_USE)

        entities, _ = extractor.parse_file(str(file_path), RUST_SCOPED_USE)

        stubs = [e for e in entities if e.id.startswith("unresolved:")]
        assert stubs, "expected a contextual stub for the unresolved call"
        for stub in stubs:
            assert stub.metadata.get("target_name") == stub.name
            assert stub.id.startswith("unresolved:")
            assert "::" in stub.id
