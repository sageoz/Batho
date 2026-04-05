from __future__ import annotations

from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import batho_core.context.categorizer as categorizer_module
import batho_core.context.languages.css as css_module
import batho_core.context.languages.detector as detector_module
import batho_core.context.languages.hcl as hcl_module
import batho_core.context.languages.json as json_module
import batho_core.context.languages.registry as registry_module
import batho_core.context.languages.toml as toml_module
import batho_core.context.languages.yaml as yaml_module
from batho_core.context.categorizer import FileCategorizer
from batho_core.context.codegraph import InMemoryGraph
from batho_core.context.schema import Entity, EntityType, Relationship, RelationshipType
from batho_core.context.symbol_index import SymbolIndex


def _wire_markup_extractor(extractor):
    extractor.logger = SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )

    def _create_entity(
        entity_type,
        name,
        filepath,
        start_line,
        end_line,
        start_byte,
        end_byte,
        metadata=None,
    ):
        return Entity(
            type=entity_type,
            name=name,
            file=filepath,
            start_line=start_line,
            end_line=end_line,
            start_byte=start_byte,
            end_byte=end_byte,
            metadata=metadata or {},
        )

    def _create_relationship(source_id, target_id, rel_type, line):
        return Relationship(
            source_id=source_id,
            target_id=target_id,
            type=rel_type,
            metadata={"line": line},
        )

    extractor._create_entity = _create_entity
    extractor._create_relationship = _create_relationship
    return extractor


def test_json_extractor_branch_paths() -> None:
    extractor = _wire_markup_extractor(json_module.JSONExtractor.__new__(json_module.JSONExtractor))

    assert extractor._extract_elements(b"{broken", "broken.json") == []

    entities: list[Entity] = []
    extractor._process_value([{"key": "value"}], "x.json", "arr", entities, 0, b"[]")
    assert any(entity.name == "arr" and entity.type == EntityType.SECTION for entity in entities)

    assert extractor._serialize_value({"a": 1}) == "<dict>"

    doc = extractor._create_entity(EntityType.DOCUMENT, "document", "x.json", 1, 1, 0, 1, {"language": "json"})
    root = extractor._create_entity(EntityType.SECTION, "root", "x.json", 1, 1, 0, 1, {"language": "json"})
    nested = extractor._create_entity(
        EntityType.SETTING,
        "root.missing.leaf",
        "x.json",
        1,
        1,
        0,
        1,
        {"language": "json"},
    )

    rels = extractor._extract_references(b"{}", "x.json", [doc, root, nested])
    assert any(rel.source_id == root.id and rel.target_id == nested.id for rel in rels)


def test_yaml_extractor_branch_paths(monkeypatch) -> None:
    extractor = _wire_markup_extractor(yaml_module.YAMLExtractor.__new__(yaml_module.YAMLExtractor))

    monkeypatch.setattr(yaml_module, "YAML_AVAILABLE", False)
    assert extractor._extract_elements(b"a: 1", "x.yaml") == []

    monkeypatch.setattr(yaml_module, "YAML_AVAILABLE", True)
    monkeypatch.setattr(yaml_module.yaml, "safe_load", lambda _content: [{"a": 1}, {1: "b"}])
    entities = extractor._extract_elements(b"- a: 1\n- 1: b\n", "x.yaml")
    assert any(entity.name.startswith("document_") for entity in entities)

    assert extractor._extract_elements(b"\xff", "bad.yaml") == []
    assert extractor._serialize_value(["x"]) == "<list>"

    doc = extractor._create_entity(EntityType.DOCUMENT, "document", "x.yaml", 1, 1, 0, 1, {"language": "yaml"})
    root = extractor._create_entity(EntityType.SECTION, "root", "x.yaml", 1, 1, 0, 1, {"language": "yaml"})
    nested = extractor._create_entity(
        EntityType.SETTING,
        "root.missing.leaf",
        "x.yaml",
        1,
        1,
        0,
        1,
        {"language": "yaml"},
    )
    rels = extractor._extract_references(b"root: {}", "x.yaml", [doc, root, nested])
    assert any(rel.source_id == root.id and rel.target_id == nested.id for rel in rels)


def test_toml_extractor_non_string_key_path() -> None:
    extractor = _wire_markup_extractor(toml_module.TOMLExtractor.__new__(toml_module.TOMLExtractor))

    entities: list[Entity] = []
    extractor._process_value({1: "one"}, "x.toml", "root", entities, 0, b"root = {}")
    assert any(entity.name.endswith(".1") for entity in entities)


def test_css_and_hcl_initializers_call_base_init(monkeypatch) -> None:
    calls: list[str] = []

    def _fake_base_init(self, language: str, parsing_config=None):
        _ = self, parsing_config
        calls.append(language)

    monkeypatch.setattr(css_module.MarkupConfigExtractor, "__init__", _fake_base_init)
    css_module.CSSExtractor()
    hcl_module.HCLExtractor()

    assert "css" in calls
    assert "hcl" in calls


def test_css_and_hcl_decode_and_reference_branches() -> None:
    css_extractor = _wire_markup_extractor(css_module.CSSExtractor.__new__(css_module.CSSExtractor))
    hcl_extractor = _wire_markup_extractor(hcl_module.HCLExtractor.__new__(hcl_module.HCLExtractor))

    assert css_extractor._extract_elements(b"\xff", "bad.css") == []
    assert css_extractor._extract_references(b"\xff", "bad.css", []) == []

    doc = hcl_extractor._create_entity(EntityType.DOCUMENT, "document", "x.tf", 1, 1, 0, 1, {"language": "hcl"})
    rels = hcl_extractor._extract_references(b"module.network", "x.tf", [doc])
    assert any(rel.target_id == "module.network" for rel in rels)


def test_detector_branch_paths(monkeypatch) -> None:
    result = detector_module.DetectionResult(
        language="python",
        confidence=0.8,
        method="test",
    )
    assert result.is_confident() is True

    monkeypatch.setattr(detector_module, "is_language_available", lambda _language: False)
    assert result.is_available() is False

    shebang = detector_module.detect_by_shebang(b"#!/usr/bin/env ruby\nputs 'x'\n")
    assert shebang is not None
    assert shebang.language == "ruby"

    magic = detector_module.detect_by_magic_bytes(b"\x7fELF\x00\x00\x00")
    assert magic is not None
    assert magic.language == "c"

    detector = detector_module.LanguageDetector(min_confidence=0.99)
    monkeypatch.setattr(detector, "detect", lambda _path, _content: None)
    monkeypatch.setattr(
        detector_module,
        "detect_by_special_filename",
        lambda _path, _content: detector_module.DetectionResult("docker", 1.0, "special_filename"),
    )
    assert detector.detect_with_fallback(Path("Dockerfile"), b"") is not None

    monkeypatch.setattr(detector_module, "detect_by_special_filename", lambda _path, _content: None)
    monkeypatch.setattr(
        detector_module,
        "detect_by_extension",
        lambda _path, _content: detector_module.DetectionResult("python", 1.0, "extension"),
    )
    fallback = detector.detect_with_fallback(Path("x.py"), b"")
    assert fallback is not None
    assert fallback.language == "python"

    class _Unavailable:
        language = "python"
        method = "heuristics"

        @staticmethod
        def is_available() -> bool:
            return False

    monkeypatch.setattr(detector, "detect_with_fallback", lambda _path, _content: _Unavailable())
    assert detector.get_extractor(Path("x.py"), b"") is None

    sentinel_a = object()
    sentinel_b = object()
    monkeypatch.setattr(
        detector_module,
        "default_detector",
        SimpleNamespace(
            detect=lambda _path, _content: sentinel_a,
            detect_with_fallback=lambda _path, _content: sentinel_b,
        ),
    )
    assert detector_module.detect_language("x.py", b"") is sentinel_a
    assert detector_module.detect_language_with_fallback("x.py", b"") is sentinel_b


def test_registry_branch_paths(monkeypatch) -> None:
    registry_module._language_available_cache.clear()
    monkeypatch.setattr(
        registry_module,
        "get_language",
        lambda _identifier: (_ for _ in ()).throw(RuntimeError("missing parser")),
    )
    assert registry_module.is_language_available("python") is False

    registry_module.set_parsing_config({"skip_comments": True})
    assert registry_module.get_parsing_config()["skip_comments"] is True

    monkeypatch.setattr(registry_module, "is_language_available", lambda _lang: False)
    assert registry_module._get_extractor_instance("python") is None

    class _FakeExtractor:
        def __init__(self, parsing_config=None):
            self.parsing_config = parsing_config

    monkeypatch.setattr(registry_module, "is_language_available", lambda _lang: True)
    monkeypatch.setattr(registry_module, "_instances", {})
    monkeypatch.setattr(registry_module, "_LANG_TO_CLASS", {})

    def _discover():
        registry_module._LANG_TO_CLASS["fake"] = _FakeExtractor

    monkeypatch.setattr(registry_module, "discover_and_register_all", _discover)
    assert isinstance(registry_module._get_extractor_instance("fake"), _FakeExtractor)

    monkeypatch.setattr(registry_module, "_auto_discovery_done", True)
    registry_module._discover_language_modules()

    monkeypatch.setattr(registry_module, "_auto_discovery_done", False)
    monkeypatch.setattr(registry_module, "_LANG_TO_CLASS", {})

    def _import_module(name: str):
        if name.endswith(".c"):
            raise ImportError("missing")
        if name.endswith(".cpp"):
            raise RuntimeError("boom")
        return SimpleNamespace()

    monkeypatch.setattr(registry_module.importlib, "import_module", _import_module)
    registry_module._discover_language_modules()
    assert registry_module._auto_discovery_done is True

    assert registry_module.get_language_for_extension(".PY") == "python"
    assert ".py" in registry_module.get_extensions_for_language("python")


def test_categorizer_branch_paths() -> None:
    categorizer = FileCategorizer()

    assert categorizer.categorize("__pycache__/cache.bin") == "cache"
    assert categorizer._is_doc_file([], "README.extra.md", "readme.extra", ".md") is True
    assert categorizer._is_config_file(["config"], "x.txt", "x", ".txt") is True
    assert categorizer._is_config_file([], "custom.config.cjs", "custom.config", ".cjs") is True
    assert categorizer._is_source_file(["assets"], "logo.bin", ".bin") is False
    assert categorizer._is_cache_file(["tmp", "cache", "file"]) is True
    assert categorizer._get_folder_category(PurePosixPath("single"), ["single"]) == "root"

    assert categorizer.categorize("assets/logo.bin") == "assets"
    assert categorizer_module.categorize_file("src/main.py") == "source"


def test_symbol_index_branch_paths() -> None:
    graph = InMemoryGraph()
    blank = Entity(
        type=EntityType.FUNCTION,
        name="   ",
        file="src/blank.py",
        start_line=1,
        end_line=1,
    )
    client_a = Entity(
        type=EntityType.MODULE,
        name="pkg.alpha.client",
        file="pkg/alpha/client.py",
        start_line=1,
        end_line=1,
    )
    client_b = Entity(
        type=EntityType.MODULE,
        name="pkg.beta.client",
        file="pkg/beta/client.py",
        start_line=1,
        end_line=1,
    )

    graph.add_entity(blank)
    graph.add_entity(client_a)
    graph.add_entity(client_b)

    index = SymbolIndex.build(graph)
    assert "" not in index.names
    assert index._choose_best((), None) is None
    assert index.resolve_candidates(["client"], source_file="pkg/alpha/client.py") == client_a.id
