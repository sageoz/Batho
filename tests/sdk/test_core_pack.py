"""tests/sdk/test_core_pack.py — T07/T08: core-pack data plugins.

Equality gates: pack data must be byte-equivalent to the engine constants it
replaces (extractor.py:163-236, pipeline.py:41-48, codegraph.py:844-858,
1138-1160). Engine constants are imported in TESTS ONLY.
"""

from __future__ import annotations

from pathlib import Path

from batho_plugin import load_host
from batho_plugin.fingerprint import fingerprint_from_host
from batho_plugin.hooks import PruneStubHook
from batho_plugin.packs import PackValidationError, YamlDataPlugin

# Engine constants — parity comparison only (never imported by the SDK).
import pytest  # noqa: E402

from batho.modules.extraction.extractor import (  # noqa: E402
    _BUILTINS_BY_LANG,
    _BLOCK_COMMENT_PAIRS,
    _LINE_COMMENT_PREFIXES,
)
from batho.modules.extraction.pipeline import _LANG_TO_MANAGER  # noqa: E402
from batho.modules.graph.builder.codegraph import (  # noqa: E402
    _PRUNABLE_METHOD_NAMES,
    _RESOLUTION_CONFIDENCE,
)

CORE_DIR = Path(__file__).resolve().parents[2] / "sdk" / "batho_plugin" / "core"

HOOK_IDS = (
    "batho_plugin.hooks.language_detect",
    "batho_plugin.hooks.comment_classify",
    "batho_plugin.hooks.property_classify",
    "batho_plugin.hooks.prune_stub",
    "batho_plugin.hooks.stamp_language",
)
DATA_IDS = (
    "lang-python",
    "lang-typescript",
    "lang-javascript",
    "lang-go",
    "lang-rust",
    "pruning-policy",
    "resolution-policy",
    "language-ecosystems",
    "noise-paths",
    "batho_plugin.core.file_detection",
)


def test_five_language_packs_load() -> None:
    """T07: 5 packs load as DataPlugins via the host."""
    host = load_host()
    for lang in ("python", "typescript", "javascript", "go", "rust"):
        assert f"lang-{lang}" in host.plugin_ids, f"missing pack for {lang}"


def test_builtins_equal_engine_constants() -> None:
    """Pack builtins == engine _BUILTINS_BY_LANG per language (T07 gate)."""
    host = load_host()
    for lang in ("python", "typescript", "javascript", "go", "rust"):
        assert host.get_set("builtins", language=lang) == frozenset(
            _BUILTINS_BY_LANG[lang]
        ), f"builtins mismatch for {lang}"
    # Unknown language → no builtins (engine parity: dict.get → empty set).
    assert host.get_set("builtins", language="cobol") == frozenset()


def test_comment_syntax_equal_engine_maps() -> None:
    """comment_syntax == extractor maps for the 5 packed languages."""
    host = load_host()
    for lang in ("python", "typescript", "javascript", "go", "rust"):
        syntax = host.get_map("comment_syntax", language=lang)
        assert tuple(syntax["line"]) == _LINE_COMMENT_PREFIXES[lang], lang
        assert [tuple(p) for p in syntax["block"]] == list(
            _BLOCK_COMMENT_PAIRS.get(lang, ())
        ), lang


def test_lang_to_manager_covers_pipeline_map() -> None:
    """The 5 packed languages match pipeline.py:41-48; java/maven stays
    engine-side until a java pack lands (packs extend, never replace — §5)."""
    host = load_host()
    for lang, manager in _LANG_TO_MANAGER.items():
        got = host.get_map("lang_to_manager", language=lang).get("manager")
        if lang in {"python", "typescript", "javascript", "go", "rust"}:
            assert got == manager, f"{lang}: {got} != {manager}"
        else:
            assert got is None  # no java pack → engine fallback


def test_noise_symbols_extension_point() -> None:
    """Per-language noise extensions are empty (floor lives in the hook —
    engine parity); the key exists as the documented extension point."""
    host = load_host()
    for lang in ("python", "typescript", "javascript", "go", "rust"):
        assert host.get_set("noise_symbols", language=lang) == frozenset()


def test_prunable_methods_equal_engine() -> None:
    """T08 gate: prunable_methods == codegraph.py:1138-1160."""
    host = load_host()
    assert host.get_set("prunable_methods") == _PRUNABLE_METHOD_NAMES
    assert len(_PRUNABLE_METHOD_NAMES) > 0


def test_noise_paths_equal_engine_fallback() -> None:
    """T33 gate: noise-paths pack == gap_report fallback sets."""
    from batho.modules.enrich.gap_report import (
        _NOISE_PATH_MARKERS_FALLBACK,
        _NOISE_SUFFIXES_FALLBACK,
    )

    host = load_host()
    assert host.get_set("noise_path_markers") == frozenset(
        _NOISE_PATH_MARKERS_FALLBACK
    )
    assert host.get_set("noise_suffixes") == frozenset(_NOISE_SUFFIXES_FALLBACK)


def test_strategy_confidence_equal_engine() -> None:
    """T08 gate: strategy_confidence == codegraph.py:844-858 (13 strategies)."""
    host = load_host()
    assert host.get_map("strategy_confidence") == _RESOLUTION_CONFIDENCE


def test_unknown_strategy_default() -> None:
    """Unknown strategy lookup → 0.5 default (engine parity, codegraph:2326)."""
    host = load_host()
    conf = host.get_map("strategy_confidence")
    assert conf.get("nonexistent_strategy", 0.5) == 0.5


def test_language_scoped_compilation() -> None:
    """Language packs compile to per_language data; policies are top-level."""
    pack = YamlDataPlugin(CORE_DIR / "language_packs" / "python.yaml")
    assert pack.pack_class == "core"
    data = pack.compile()
    assert set(data.per_language) == {"python"}
    assert data.sets == {}  # nothing at top level
    assert data.per_language["python"].sets["builtins"] == frozenset(
        _BUILTINS_BY_LANG["python"]
    )

    policy = YamlDataPlugin(CORE_DIR / "pruning_policy.yaml")
    assert policy.language is None  # policy packs are top-level
    assert policy.pack_class == "core"


def test_detection_pack_mirrors_engine_maps() -> None:
    """T12 gate: file_detection pack == engine _EXT_TO_LANG and the
    confidence-1.0 subset of _SPECIAL_FILENAME_MAP — drift between pack and
    engine is a silent detection-parity break."""
    from batho.modules.extraction.submodules.parser_factory.detector import (
        _SPECIAL_FILENAME_MAP,
    )
    from batho.modules.extraction.submodules.parser_factory.registry import (
        _EXT_TO_LANG,
    )

    host = load_host()
    assert host.get_map("ext_to_language") == dict(_EXT_TO_LANG)
    pack_specials = host.get_map("special_filenames")
    engine_specials = {
        name: lang
        for name, (lang, conf) in _SPECIAL_FILENAME_MAP.items()
        if conf == 1.0
    }
    assert pack_specials == engine_specials
    # Sub-1.0-confidence names are deliberately NOT packed — the hook always
    # decides at 1.0 and would raise confidence beyond the engine's verdict.
    assert {n for n, (_, c) in _SPECIAL_FILENAME_MAP.items() if c < 1.0}.isdisjoint(
        pack_specials
    )


def test_pack_schema_validation(tmp_path) -> None:
    """Unknown keys, bad class, and bad sets shapes are rejected at load."""
    def write(name: str, content: str) -> Path:
        p = tmp_path / name
        p.write_text(content)
        return p

    with pytest.raises(PackValidationError, match="unknown top-level keys"):
        YamlDataPlugin(write("a.yaml", "plugin_id: x\nversion: '1'\n"
                             "class: core\nbogus: 1\n"))
    with pytest.raises(PackValidationError, match="'class' must be one of"):
        YamlDataPlugin(write("b.yaml", "plugin_id: x\nversion: '1'\n"
                             "class: ultra\ndata: {}\n"))
    with pytest.raises(PackValidationError, match="must be a list"):
        YamlDataPlugin(write("c.yaml", "plugin_id: x\nversion: '1'\n"
                             "class: core\ndata:\n  sets:\n    k: notalist\n"))


def test_core_pack_registered_in_host() -> None:
    """load_host() registers 5 hooks + 10 data packs = 15 plugin ids."""
    host = load_host()
    ids = host.plugin_ids
    for hook_id in HOOK_IDS:
        assert hook_id in ids, f"missing hook {hook_id}"
    for data_id in DATA_IDS:
        assert data_id in ids, f"missing data plugin {data_id}"
    assert len(ids) == 15
    for reg in host.hook_registrations():
        assert "batho_plugin.core" in getattr(reg.plugin, "requires", ())


def test_policies_fingerprinted() -> None:
    """Policy packs participate in the plugin fingerprint (T08 gate)."""
    host = load_host()
    fp1 = fingerprint_from_host(host)
    assert len(fp1) == 64
    assert fingerprint_from_host(load_host()) == fp1  # stable


def test_prune_hook_uses_pack_builtins() -> None:
    """End-to-end: the prune hook's builtins now flow from the YAML packs."""
    hook = PruneStubHook()
    host = load_host()
    # 'print' is a python builtin (pack data) → pruned on USES.
    assert hook.decide(
        "print", "USES", "python", "batho/a.py", host=host
    ).reason == "builtin"
    # 'unwrap' is NOT a python builtin and not imported → the extractor's
    # rule 6 prunes it (engine parity); the graph-builder's prunable_methods
    # policy applies later at resolution time (T18).
    decision = hook.decide("unwrap", "USES", "python", "batho/a.py", host=host)
    assert decision.prune is True
    assert decision.reason == "unimported_simple_name"


class TestCodegraphPolicyLookups:
    """T18: CodeGraphIndexer resolution/prune tables come from the host."""

    def test_resolution_confidence_fallback_without_host(self):
        from batho.modules.graph.builder.codegraph import (
            CodeGraphIndexer,
            _RESOLUTION_CONFIDENCE,
        )

        idx = CodeGraphIndexer()
        assert idx._resolution_confidence_map() is _RESOLUTION_CONFIDENCE
        assert idx._resolution_confidence_map()["ambiguous"] == _RESOLUTION_CONFIDENCE["ambiguous"]

    def test_resolution_confidence_from_host(self):
        from batho_plugin import PluginData, PluginHost
        from batho_plugin.api import DataPlugin
        from batho.modules.graph.builder.codegraph import CodeGraphIndexer

        class _P:
            plugin_id = "test-res"
            version = "9.9.9"

            def compile(self):
                return PluginData(maps={"strategy_confidence": {"x": 0.99}})

        host = PluginHost()
        host.register_data(_P())
        idx = CodeGraphIndexer()
        idx._plugin_host = host
        m = idx._resolution_confidence_map()
        assert m == {"x": 0.99}
        assert idx._resolution_confidence_map().get("y", 0.5) == 0.5

    def test_prunable_methods_from_host(self):
        from batho_plugin import PluginData, PluginHost
        from batho.modules.graph.builder.codegraph import CodeGraphIndexer

        class _P:
            plugin_id = "test-prune"
            version = "9.9.9"

            def compile(self):
                return PluginData(sets={"prunable_methods": frozenset({"zz"})})

        host = PluginHost()
        host.register_data(_P())
        idx = CodeGraphIndexer()
        idx._plugin_host = host
        assert idx._prunable_methods_set() == frozenset({"zz"})
