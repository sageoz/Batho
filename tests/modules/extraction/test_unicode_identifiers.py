"""Regression tests for non-Latin Python identifier extraction (H5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from batho.core.schemas import EntityType
from batho.modules.extraction.fallback_parser import FallbackParser
from batho.modules.extraction.submodules.parser_factory.factory import get_extractor


# Valid Python 3 identifiers covering CJK, RTL, Cyrillic, Greek, Korean,
# Latin-1 supplement, and a Greek letter prefix.
UNICODE_IDENTIFIERS = [
    "函数",
    "日本語クラス",
    "λhandler",
    "دالة",
    "функция",
    "함수",
    "café_func",
    "Ωmega",
]


def build_unicode_fixture_source() -> str:
    """Return Python source containing one function or class per test identifier."""
    lines = []
    for i, name in enumerate(UNICODE_IDENTIFIERS):
        if name == "日本語クラス":
            lines.append(f"class {name}:")
            lines.append("    pass")
        else:
            lines.append(f"def {name}():")
            lines.append("    pass")
        # Blank line between definitions for clearer byte offsets.
        if i < len(UNICODE_IDENTIFIERS) - 1:
            lines.append("")
    return "\n".join(lines)


class TestTreeSitterExtractorUnicode:
    """Verify the tree-sitter extractor preserves Unicode identifier names."""

    @pytest.fixture(scope="class")
    def extractor(self):
        return get_extractor("python")

    def test_all_unicode_identifiers_extracted(self, tmp_path: Path, extractor) -> None:
        source = build_unicode_fixture_source().encode("utf-8")
        file_path = tmp_path / "unicode_identifiers.py"
        file_path.write_bytes(source)

        entities, _ = extractor.parse_file(str(file_path), source)
        names = {e.name for e in entities}

        missing = [name for name in UNICODE_IDENTIFIERS if name not in names]
        assert not missing, f"Missing Unicode identifiers: {missing}"

    def test_unicode_identifier_names_are_exact(self, tmp_path: Path, extractor) -> None:
        source = build_unicode_fixture_source().encode("utf-8")
        file_path = tmp_path / "unicode_identifiers.py"
        file_path.write_bytes(source)

        entities, _ = extractor.parse_file(str(file_path), source)

        for expected_name in UNICODE_IDENTIFIERS:
            matches = [e for e in entities if e.name == expected_name]
            assert matches, f"No entity found for {expected_name!r}"
            entity = matches[0]
            assert entity.name == expected_name, (
                f"Entity name mutated: got {entity.name!r}, expected {expected_name!r}"
            )

    def test_cjk_class_extracted(self, tmp_path: Path, extractor) -> None:
        source = "class 日本語クラス:\n    pass\n".encode("utf-8")
        file_path = tmp_path / "cjk_class.py"
        file_path.write_bytes(source)

        entities, _ = extractor.parse_file(str(file_path), source)
        classes = [e for e in entities if e.type == EntityType.CLASS]
        assert any(e.name == "日本語クラス" for e in classes)


class TestFallbackParserUnicode:
    """Verify the regex fallback parser also preserves Unicode identifiers."""

    def test_fallback_parser_extracts_unicode_functions(self, tmp_path: Path) -> None:
        source = build_unicode_fixture_source().encode("utf-8")
        file_path = tmp_path / "unicode_fallback.py"
        file_path.write_bytes(source)

        parser = FallbackParser()
        result = parser.parse_file(file_path, source)
        names = {e.name for e in result.entities}

        # The fallback parser is text-based and may not recover every variant,
        # but it must preserve the names it does extract without mangling.
        missing = [name for name in UNICODE_IDENTIFIERS if name not in names]
        assert not missing, f"Fallback parser missing Unicode identifiers: {missing}"


class TestHierarchicalIdWithUnicode:
    """Ensure Unicode entity names survive hierarchical ID generation."""

    def test_build_descriptor_accepts_unicode(self) -> None:
        from batho.core.schemas import DescriptorSuffix, build_descriptor

        for name in UNICODE_IDENTIFIERS:
            descriptor = build_descriptor(name, DescriptorSuffix.METHOD)
            assert name in descriptor, f"Descriptor lost Unicode name: {descriptor!r}"

    def test_build_descriptor_accepts_dollar_prefix(self) -> None:
        """JavaScript-style $-prefixed identifiers must still be accepted."""
        from batho.core.schemas import DescriptorSuffix, build_descriptor

        descriptor = build_descriptor("$root", DescriptorSuffix.METHOD)
        assert "$root" in descriptor

    def test_build_descriptor_rejects_invalid_still(self) -> None:
        from batho.core.schemas import DescriptorSuffix, build_descriptor

        with pytest.raises(ValueError):
            build_descriptor("has-hyphen", DescriptorSuffix.METHOD)

        with pytest.raises(ValueError):
            build_descriptor("1starts_with_digit", DescriptorSuffix.METHOD)
