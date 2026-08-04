"""Tests for expanded StdlibSymbolTable and EXTERNAL_SYMBOL materialization."""
import pytest
from pathlib import Path
import tempfile

from batho.modules.dependency.stdlib_tables import StdlibSymbolTable
from batho.modules.extraction.scope_manager import ScopeManager
from batho.modules.dependency.indexer import DependencyIndexer


EXPECTED_LANGUAGES = [
    "python", "javascript", "typescript", "go", "rust",
    "c", "cpp", "java", "ruby", "csharp", "php",
    "kotlin", "swift", "scala", "dart", "haskell",
    "lua", "r", "perl", "julia", "zig", "bash",
    "objc", "erlang", "ocaml", "hack", "verilog",
]


class TestStdlibSymbolTableExpansion:
    """Tests for the expanded StdlibSymbolTable covering all 27 languages."""

    def test_all_languages_present(self):
        table = StdlibSymbolTable()
        for lang in EXPECTED_LANGUAGES:
            assert lang in table._TABLES, f"Language '{lang}' missing from _TABLES"

    def test_all_languages_have_modules(self):
        table = StdlibSymbolTable()
        for lang in EXPECTED_LANGUAGES:
            mods = table.get_all_modules(lang)
            assert len(mods) > 0, f"Language '{lang}' has no modules"

    def test_all_languages_have_symbols(self):
        table = StdlibSymbolTable()
        for lang in EXPECTED_LANGUAGES:
            mods = table.get_all_modules(lang)
            total = sum(len(v) for v in mods.values())
            assert total > 0, f"Language '{lang}' has no symbols"

    def test_is_stdlib_module(self):
        table = StdlibSymbolTable()
        assert table.is_stdlib_module("python", "os")
        assert table.is_stdlib_module("go", "fmt")
        assert table.is_stdlib_module("rust", "std::io")
        assert table.is_stdlib_module("java", "java.lang")
        assert table.is_stdlib_module("cpp", "vector")
        assert table.is_stdlib_module("c", "stdio")
        assert not table.is_stdlib_module("python", "nonexistent_module")
        assert not table.is_stdlib_module("nonexistent_lang", "os")

    def test_get_symbols(self):
        table = StdlibSymbolTable()
        syms = table.get_symbols("python", "os")
        assert "path" in syms
        assert "environ" in syms
        syms = table.get_symbols("go", "fmt")
        assert "Println" in syms
        syms = table.get_symbols("java", "java.lang")
        assert "String" in syms

    def test_case_insensitive(self):
        table = StdlibSymbolTable()
        assert table.get_all_modules("Python") == table.get_all_modules("python")
        assert table.get_all_modules("RUST") == table.get_all_modules("rust")


class TestIndexerAllLanguages:
    """Tests that the indexer processes all 27 languages."""

    def test_index_stdlib_all_languages(self):
        scope = ScopeManager()
        cfg = {"stdlib": {"enabled": True, "languages": EXPECTED_LANGUAGES}}
        with tempfile.TemporaryDirectory() as tmp:
            indexer = DependencyIndexer(Path(tmp), scope, cfg)
            indexer._index_stdlib()

        assert indexer.stats.stdlib_modules_indexed > 0
        assert indexer.stats.symbols_indexed > 0
        assert scope.global_symbol_count > 0

    def test_index_stdlib_symbol_ids_have_language(self):
        scope = ScopeManager()
        cfg = {"stdlib": {"enabled": True, "languages": ["python", "go"]}}
        with tempfile.TemporaryDirectory() as tmp:
            indexer = DependencyIndexer(Path(tmp), scope, cfg)
            indexer._index_stdlib()

        symbols = scope.get_global_symbols()
        found_python = False
        found_go = False
        for _part, syms in symbols.items():
            for _name, info in syms.items():
                if "python" in info["symbol_id"]:
                    found_python = True
                if "golang" in info["symbol_id"]:
                    found_go = True
        assert found_python, "No Python symbol IDs found"
        assert found_go, "No Go symbol IDs found"


class TestExternalSymbolMaterialization:
    """Tests that _materialize_external_symbols creates EXTERNAL_SYMBOL entities."""

    def test_materialize_creates_entities(self):
        from batho.modules.graph.builder.codegraph import _materialize_external_symbols
        from batho.core.schemas import EntityType

        scope = ScopeManager()
        scope.add_external_symbol(name="os.path", symbol_id="batho pip python 3.x os/path().", symbol_type="function")
        scope.add_external_symbol(name="fmt.Println", symbol_id="batho go golang 1.21 fmt/Println.", symbol_type="function")

        class FakeGraph:
            def __init__(self):
                self.entities = {}
            def add_entity(self, ent):
                self.entities[ent.id] = ent

        graph = FakeGraph()
        count = _materialize_external_symbols(graph, scope)
        assert count == 2
        for ent in graph.entities.values():
            assert ent.type == EntityType.EXTERNAL_SYMBOL

    def test_materialize_skips_existing(self):
        from batho.modules.graph.builder.codegraph import _materialize_external_symbols

        scope = ScopeManager()
        scope.add_external_symbol(name="os.path", symbol_id="batho pip python 3.x os/path().", symbol_type="function")

        class FakeGraph:
            def __init__(self):
                self.entities = {"batho pip python 3.x os/path().": "already_exists"}
            def add_entity(self, ent):
                self.entities[ent.id] = ent

        graph = FakeGraph()
        count = _materialize_external_symbols(graph, scope)
        assert count == 0
