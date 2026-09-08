"""Tests for review round 3 fixes:

- e66a376d: by_raw_name collision — scope-aware disambiguation, no first-wins
- dc2f0e61: index_file AST cache variant includes extraction flags
"""

from __future__ import annotations

from pathlib import Path

import pytest

from batho.core.schemas import EntityType, RelationshipType
from batho.modules.extraction.submodules.parser_factory.factory import create_extractor
from batho.modules.extraction.submodules.parser_factory._queries import PYTHON_QUERY


# ---------------------------------------------------------------------------
# e66a376d: by_raw_name first-wins collision for same-named callables
# ---------------------------------------------------------------------------


class TestIndirectCallRawNameCollision:
    """e66a376d: same-named callables must not resolve first-wins."""

    def test_same_named_methods_module_level_call_no_edge(self):
        """Two classes defining `validate` + bare indirect call at module
        level: the name is ambiguous — no edge may be emitted."""
        extractor = create_extractor("python", PYTHON_QUERY)
        content = (
            b"class ModelA:\n"
            b"    def validate(self):\n"
            b"        return True\n"
            b"\n"
            b"class ModelB:\n"
            b"    def validate(self):\n"
            b"        return False\n"
            b"\n"
            b"def caller(xs):\n"
            b"    return map(validate, xs)\n"
        )
        entities, rels = extractor.parse_file("test.py", content)

        indirect = [
            r for r in rels
            if r.type == RelationshipType.CALLS and r.metadata.get("indirect")
        ]
        assert len(indirect) == 0, (
            "Ambiguous same-named methods must not produce a first-wins edge"
        )

    def test_scoped_call_resolves_to_enclosing_class_method(self):
        """A bare indirect call inside ModelA resolves to ModelA.validate
        (correctly-scoped edge), not ModelB's."""
        extractor = create_extractor("python", PYTHON_QUERY)
        content = (
            b"class ModelA:\n"
            b"    def validate(self):\n"
            b"        return True\n"
            b"\n"
            b"    def run(self, xs):\n"
            b"        return map(validate, xs)\n"
            b"\n"
            b"class ModelB:\n"
            b"    def validate(self):\n"
            b"        return False\n"
        )
        entities, rels = extractor.parse_file("test.py", content)

        indirect = [
            r for r in rels
            if r.type == RelationshipType.CALLS and r.metadata.get("indirect")
        ]
        assert len(indirect) == 1, (
            "Expected exactly one correctly-scoped indirect CALLS edge"
        )
        validate_ents = [
            e for e in entities
            if e.type == EntityType.METHOD and e.name.startswith("ModelA.validate")
        ]
        assert len(validate_ents) == 1
        assert indirect[0].target_id == validate_ents[0].id

    def test_unique_module_function_still_resolves(self):
        """Regression: a unique module-level function with params still
        resolves via the raw-name fallback."""
        extractor = create_extractor("python", PYTHON_QUERY)
        content = (
            b"def func(x):\n"
            b"    return x\n"
            b"\n"
            b"class ModelA:\n"
            b"    def func_like(self):\n"
            b"        return 1\n"
            b"\n"
            b"def caller(xs):\n"
            b"    return map(func, xs)\n"
        )
        entities, rels = extractor.parse_file("test.py", content)

        indirect = [
            r for r in rels
            if r.type == RelationshipType.CALLS and r.metadata.get("indirect")
        ]
        assert len(indirect) > 0
        func_ent = next(e for e in entities if e.name.startswith("func_[") or e.name == "func")
        assert indirect[0].target_id == func_ent.id


# ---------------------------------------------------------------------------
# dc2f0e61: index_file AST cache variant excludes extraction flags
# ---------------------------------------------------------------------------


@pytest.fixture()
def flags_on_root(tmp_path: Path) -> Path:
    """Temp project with extraction flags ON and AST cache enabled."""
    from batho.core.config import set_active_root
    from batho.core.config.loader import _active_root, _get_config_cached_for_root

    root = tmp_path / "proj"
    root.mkdir()
    cache_dir = tmp_path / "ast-cache"
    cache_dir.mkdir()
    (root / "batho.yaml").write_text(
        "extraction:\n"
        "  extract_parameters: true\n"
        "  extract_type_parameters: true\n"
        "bsg:\n"
        "  cache:\n"
        "    enabled: true\n",
        encoding="utf-8",
    )
    (root / "sample.py").write_text(
        "def func(x, y=1):\n"
        "    return x + y\n",
        encoding="utf-8",
    )
    _active_root.set(None)
    _get_config_cached_for_root.cache_clear()
    set_active_root(root)
    yield root
    _active_root.set(None)
    _get_config_cached_for_root.cache_clear()


class TestIndexFileCacheVariant:
    """dc2f0e61: index_file must derive its AST cache variant from the
    effective parsing config (bsg.parsing + extraction flags)."""

    def test_effective_parsing_config_merges_extraction_flags(self, flags_on_root):
        from batho.core.config import get_config_cached
        from batho.modules.graph.builder.codegraph import CodeGraphIndexer

        indexer = CodeGraphIndexer(
            cache_path=str(flags_on_root), root=str(flags_on_root)
        )
        merged = indexer._effective_parsing_config()
        assert merged.get("extract_parameters") is True
        assert merged.get("extract_type_parameters") is True
        # Raw bsg.parsing must NOT contain the flags (they come from extraction)
        raw = get_config_cached().get("bsg", {}).get("parsing", {})
        assert "extract_parameters" not in raw

    def test_index_file_writes_under_effective_variant(self, flags_on_root):
        """index_file's cache entry must be readable under the merged-config
        variant and NOT under the raw bsg.parsing variant."""
        from batho.modules.graph.builder.codegraph import CodeGraphIndexer
        from batho.modules.storage.cache.unified_cache import build_ast_cache_variant
        from batho.utils.hash import compute_bytes_hash

        ast_cache_dir = flags_on_root.parent / "ast-cache"
        indexer = CodeGraphIndexer(
            cache_path=str(flags_on_root),
            root=str(flags_on_root),
            ast_cache_dir=str(ast_cache_dir),
        )
        py_file = flags_on_root / "sample.py"
        extractor = create_extractor(
            "python", PYTHON_QUERY, parsing_config=indexer._effective_parsing_config()
        )
        entities, _rels = indexer.index_file(str(py_file), extractor)
        assert any(e.type == EntityType.PARAMETER for e in entities), (
            "extract_parameters=true must emit PARAMETER entities"
        )

        content = py_file.read_bytes()
        file_hash = compute_bytes_hash(content)

        # Entry lives under the effective (flags-merged) variant
        effective_variant = build_ast_cache_variant(
            include_gaps=False, parsing_config=indexer._effective_parsing_config()
        )
        hit = indexer._cache.get_ast(str(py_file), file_hash, effective_variant)
        assert hit is not None, "index_file entry must be found under the effective variant"
        hit_entities, _ = hit
        assert any(e.type == EntityType.PARAMETER for e in hit_entities)

        # Entry must NOT exist under the raw (flags-less) bsg.parsing variant —
        # that was the bug: a flags-OFF build would read the stale hit.
        raw_parsing = dict(indexer._effective_parsing_config())
        raw_parsing.pop("extract_parameters", None)
        raw_parsing.pop("extract_type_parameters", None)
        raw_variant = build_ast_cache_variant(include_gaps=False, parsing_config=raw_parsing)
        assert indexer._cache.get_ast(str(py_file), file_hash, raw_variant) is None, (
            "flags-ON entry must not be served to a flags-OFF build"
        )

    def test_flags_off_build_gets_no_stale_parameter_entities(self, flags_on_root):
        """Enable flags, index_file, then run a flags-OFF extraction against
        the same cache — no PARAMETER entities may be served."""
        from batho.core.config import get_config_cached, set_active_root
        from batho.core.config.loader import _get_config_cached_for_root
        from batho.modules.graph.builder.codegraph import CodeGraphIndexer
        from batho.modules.storage.cache.unified_cache import build_ast_cache_variant
        from batho.utils.hash import compute_bytes_hash

        ast_cache_dir = flags_on_root.parent / "ast-cache"
        indexer = CodeGraphIndexer(
            cache_path=str(flags_on_root),
            root=str(flags_on_root),
            ast_cache_dir=str(ast_cache_dir),
        )
        py_file = flags_on_root / "sample.py"
        extractor = create_extractor(
            "python", PYTHON_QUERY, parsing_config=indexer._effective_parsing_config()
        )
        entities, _rels = indexer.index_file(str(py_file), extractor)
        assert any(e.type == EntityType.PARAMETER for e in entities)

        # Flip flags OFF
        (flags_on_root / "batho.yaml").write_text(
            "bsg:\n  cache:\n    enabled: true\n", encoding="utf-8"
        )
        _get_config_cached_for_root.cache_clear()
        set_active_root(flags_on_root)
        assert get_config_cached()["extraction"]["extract_parameters"] is False

        off_indexer = CodeGraphIndexer(
            cache_path=str(flags_on_root),
            root=str(flags_on_root),
            ast_cache_dir=str(ast_cache_dir),
        )
        off_variant = build_ast_cache_variant(
            include_gaps=False, parsing_config=off_indexer._effective_parsing_config()
        )
        content = py_file.read_bytes()
        file_hash = compute_bytes_hash(content)
        assert off_indexer._cache.get_ast(str(py_file), file_hash, off_variant) is None, (
            "flags-OFF build must not read the flags-ON cache entry"
        )
