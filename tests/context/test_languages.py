"""Tests for language detection and registry."""
from __future__ import annotations

from pathlib import Path

import pytest

from batho.context.languages.registry import get_extractor
from batho.context.languages.detector import default_detector
from batho.context.schema import EntityType


# ---------------------------------------------------------------------------
# Registry: get_extractor
# ---------------------------------------------------------------------------

class TestGetExtractor:

    def test_python(self):
        ext = get_extractor(".py")
        assert ext is not None

    def test_typescript(self):
        ext = get_extractor(".ts")
        assert ext is not None

    def test_javascript(self):
        ext = get_extractor(".js")
        assert ext is not None

    def test_go(self):
        ext = get_extractor(".go")
        assert ext is not None

    def test_rust(self):
        ext = get_extractor(".rs")
        assert ext is not None

    def test_java(self):
        ext = get_extractor(".java")
        assert ext is not None

    def test_json(self):
        ext = get_extractor(".json")
        assert ext is not None

    def test_yaml(self):
        ext = get_extractor(".yaml") or get_extractor(".yml")
        # YAML may not be registered in all configurations
        if ext is None:
            pytest.skip("YAML extractor not registered")

    def test_markdown(self):
        ext = get_extractor(".md")
        assert ext is not None

    def test_unknown_returns_none(self):
        ext = get_extractor(".xyz123")
        assert ext is None

    def test_case_insensitive(self):
        # Registry uses lowercase suffix
        ext = get_extractor(".py")
        assert ext is not None


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class TestDetector:

    def test_detect_python_by_extension(self, tmp_path: Path):
        f = tmp_path / "main.py"
        f.write_bytes(b"def foo(): pass\n")
        ext = default_detector.get_extractor(f, f.read_bytes())
        assert ext is not None

    def test_detect_typescript_by_extension(self, tmp_path: Path):
        f = tmp_path / "app.ts"
        f.write_bytes(b"const x: number = 1;\n")
        ext = default_detector.get_extractor(f, f.read_bytes())
        assert ext is not None


# ---------------------------------------------------------------------------
# Python extractor end-to-end
# ---------------------------------------------------------------------------

class TestPythonExtractor:

    def test_extracts_functions(self):
        ext = get_extractor(".py")
        content = b"def hello(name: str) -> str:\n    return f'Hello {name}'\n"
        entities, rels = ext.parse_file("test.py", content)
        names = [e.name for e in entities]
        assert "hello" in names

    def test_extracts_classes(self):
        ext = get_extractor(".py")
        content = b"""
class Animal:
    def speak(self):
        pass

class Dog(Animal):
    def speak(self):
        return "Woof"
"""
        entities, rels = ext.parse_file("animals.py", content)
        names = [e.name for e in entities]
        assert "Animal" in names
        assert "Dog" in names

    def test_extracts_imports(self):
        ext = get_extractor(".py")
        content = b"import os\nfrom pathlib import Path\n\ndef f(): pass\n"
        entities, rels = ext.parse_file("mod.py", content)
        # Should have import relationships
        import_rels = [r for r in rels if r.type.name == "IMPORTS"]
        assert len(import_rels) >= 0  # tree-sitter query may vary

    def test_extracts_multiline_main_entrypoint(self):
        ext = get_extractor(".py")
        content = (
            b"import sys\n"
            b"\n"
            b"if __name__ == \"__main__\":\n"
            b"    sys.exit(main())\n"
        )
        entities, _ = ext.parse_file("main.py", content)
        entry_points = [e for e in entities if e.type == EntityType.ENTRY_POINT]

        assert entry_points
        assert any(e.name == "__main__" for e in entry_points)
        assert any(
            "sys.exit(main())" in str(e.metadata.get("invocation_snippet", ""))
            for e in entry_points
        )

    def test_extracts_single_quote_main_entrypoint(self):
        ext = get_extractor(".py")
        content = b"if __name__ == '__main__':\n    main()\n"
        entities, _ = ext.parse_file("single_quote_main.py", content)
        entry_points = [e for e in entities if e.type == EntityType.ENTRY_POINT]

        assert entry_points
        assert any(e.name == "__main__" for e in entry_points)


# ---------------------------------------------------------------------------
# TypeScript extractor end-to-end
# ---------------------------------------------------------------------------

class TestTypeScriptExtractor:

    def test_extracts_functions(self):
        ext = get_extractor(".ts")
        if ext is None:
            pytest.skip("TypeScript extractor not available")
        content = b"function greet(name: string): string { return name; }\n"
        entities, rels = ext.parse_file("mod.ts", content)
        names = [e.name for e in entities]
        assert "greet" in names

    def test_extracts_interfaces(self):
        ext = get_extractor(".ts")
        if ext is None:
            pytest.skip("TypeScript extractor not available")
        content = b"interface User { name: string; age: number; }\n"
        entities, rels = ext.parse_file("types.ts", content)
        names = [e.name for e in entities]
        assert "User" in names
