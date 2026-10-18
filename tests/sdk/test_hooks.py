"""tests/sdk/test_hooks.py — T06: generic hook implementations.

Parity contract: every hook decision function is byte-identical to the
engine implementation it replaces (spec §4.3/T06). Engine references are
imported in TESTS ONLY — the hooks themselves stay engine-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from batho_plugin import PluginContext, PluginData, PluginHost, Stage
from batho_plugin.hooks import (
    CommentClassifyHook,
    LanguageDetectHook,
    PruneStubHook,
    PropertyClassifyHook,
    StampLanguageHook,
    classify_marker,
    detect_language,
    infer_access_type,
    should_prune,
    stamp_entities,
)

# Engine references — parity comparison only (never imported by the hooks).
from batho.modules.extraction.extractor import (  # noqa: E402
    _BUILTINS_BY_LANG,
    _should_prune_unresolved,
)
from batho.core.schemas import RelationshipType


# ---------------------------------------------------------------------------
# prune_stub parity
# ---------------------------------------------------------------------------

def test_prune_parity_against_engine() -> None:
    """Hook verdicts == engine _should_prune_unresolved on a decision matrix."""
    refs = [
        "len", "range", "print", "self", "cls", "ctx", "null", "undefined",
        "my_func", "MyClass", "obj.method", "path/to/x", "ns:thing", "",
        "  ", "args", "kwargs", "error", "True", "False", "local_var",
    ]
    rel_types = [
        "CALLS", "IMPORTS", "INHERITS", "IMPLEMENTS", "USES", "READS", "WRITES",
    ]
    builtins = frozenset({
        "int", "str", "float", "bool", "dict", "list", "set", "tuple", "len",
        "range", "print", "self", "cls", "None", "True", "False", "object",
        "type", "open", "Exception", "any", "all", "sum", "min", "max",
    })
    imported = frozenset({"my_func", "local_var"})

    for ref in refs:
        for rel in rel_types:
            engine_rel = RelationshipType[rel]
            for filepath in ("batho/modules/x.py", "__external_symbols__"):
                for prune_enabled in (True, False):
                    for lang in ("python", "javascript", None):
                        # True parity: the hook receives exactly the engine's
                        # builtin set for the same language (pack data ==
                        # engine constants); unknown language → empty set.
                        engine_builtins = frozenset(_BUILTINS_BY_LANG.get(lang, set()))
                        engine = _should_prune_unresolved(
                            ref, engine_rel, [], lang, filepath,
                            prune_enabled, imported,
                        )
                        hook = should_prune(
                            ref, rel, lang, filepath, prune_enabled, imported,
                            builtins=engine_builtins, noise_symbols=frozenset(),
                        )
                        assert hook.prune == engine, (
                            f"mismatch ref={ref!r} rel={rel} fp={filepath} "
                            f"enabled={prune_enabled} lang={lang}: "
                            f"hook={hook} engine={engine}"
                        )


def test_prune_uses_host_pack_data() -> None:
    """decide() pulls builtins/noise from the host's language packs."""

    class _LangPack:
        plugin_id = "lang"
        version = "1.0"

        def compile(self) -> PluginData:
            return PluginData(
                sets={"builtins": frozenset({"len"})},
                per_language={
                    "python": PluginData(sets={"builtins": frozenset({"print"})}),
                },
            )

    host = PluginHost()
    host.register_data(_LangPack())
    hook = PruneStubHook()

    assert hook.decide("print", "USES", "python", "batho/a.py", host=host).prune is True
    assert hook.decide("len", "USES", "javascript", "batho/a.py", host=host).prune is True
    assert hook.decide("custom", "USES", "python", "batho/a.py", host=host).prune is True
    assert hook.decide("custom", "CALLS", "python", "batho/a.py", host=host).prune is False


# ---------------------------------------------------------------------------
# language_detect
# ---------------------------------------------------------------------------

def test_language_detect_from_pack_data() -> None:
    ext_map = {".py": "python", ".ts": "typescript", ".PY": "python"}
    assert detect_language("a/b/c.py", ext_map) == "python"
    assert detect_language("a/b/c.ts", ext_map) == "typescript"
    assert detect_language("a/b/c.PY", ext_map) == "python"  # lowercase fallback
    assert detect_language("a/b/c.rst", ext_map) is None  # engine fallback
    assert detect_language("Dockerfile", None, {"Dockerfile": "dockerfile"}) == (
        "dockerfile"
    )


def test_language_detect_hook_dispatch() -> None:
    class _Pack:
        plugin_id = "p"
        version = "1.0"

        def compile(self) -> PluginData:
            return PluginData(maps={"ext_to_language": {".py": "python"}})

    host = PluginHost()
    host.register_data(_Pack())
    hook = LanguageDetectHook()
    host.register_hook(hook)
    ctx = PluginContext(file_path="x/y.py", root_path=Path("."))
    results = host.dispatch(Stage.ON_FILE_DETECTED, ctx)
    assert results[0].detail["language"] == "python"

    ctx2 = PluginContext(file_path="x/y.zzz", root_path=Path("."))
    results2 = host.dispatch(Stage.ON_FILE_DETECTED, ctx2)
    assert results2[0].detail["language"] is None  # engine fallback


# ---------------------------------------------------------------------------
# comment_classify parity
# ---------------------------------------------------------------------------

def test_classify_marker_parity() -> None:
    """Byte-identical to extractor.py:2156-2179."""
    for marker in (
        "WHY:", "NOTE:", "FIXME:", "TODO:", "HACK:", "XXX:", "why:", "tOdo:",
    ):
        expected_kind = marker.rstrip(":").strip().lower() or "comment"
        meta = classify_marker(marker, "python", has_parse_tree=True)
        assert meta == {
            "rationale_kind": expected_kind,
            "marker_comment": True,
            "language": "python",
        }
        meta_fb = classify_marker(marker, "python", has_parse_tree=False)
        assert meta_fb["line_scan_fallback"] is True
    assert classify_marker("::", "python", True)["rationale_kind"] == "comment"


def test_comment_classify_hook_stamps_entities() -> None:
    @dataclass
    class _Ent:
        metadata: dict = field(default_factory=dict)

    ents = [
        _Ent(metadata={"_marker_text": "WHY:"}),
        _Ent(metadata={"other": 1}),
    ]
    ctx = PluginContext(
        file_path="a.py",
        root_path=Path("."),
        language="python",
        tree_root=object(),  # parse tree present
        entities=ents,
    )
    result = CommentClassifyHook().on_comment_classify(ctx)
    assert result.detail["classified"] == 1
    assert ents[0].metadata == {
        "rationale_kind": "why",
        "marker_comment": True,
        "language": "python",
    }
    assert ents[1].metadata == {"other": 1}


# ---------------------------------------------------------------------------
# property_classify parity
# ---------------------------------------------------------------------------

def _find_functions(node):
    """All function_definition nodes, in document order."""
    out = []
    if node.type == "function_definition":
        out.append(node)
    for child in node.children:
        out.extend(_find_functions(child))
    return out


def test_property_classify_python_setter() -> None:
    """Real tree-sitter tree: @x.setter → write; @property → read."""
    from batho.modules.extraction.extractor import get_pooled_parser

    parser = get_pooled_parser("python")
    setter_src = (
        b"class A:\n"
        b"    @property\n"
        b"    def x(self):\n"
        b"        return 1\n"
        b"    @x.setter\n"
        b"    def x(self, v):\n"
        b"        self._x = v\n"
    )
    tree = parser.parse(setter_src)
    functions = _find_functions(tree.root_node)
    assert len(functions) == 2
    # First function = the @property getter → read.
    assert infer_access_type(functions[0], setter_src, "python") == "read"
    # Second function = the @x.setter → write (decorated_definition parent).
    assert infer_access_type(functions[1], setter_src, "python") == "write"

    plain_src = (
        b"class A:\n"
        b"    @property\n"
        b"    def x(self):\n"
        b"        return 1\n"
    )
    tree2 = parser.parse(plain_src)
    node2 = _find_functions(tree2.root_node)[0]
    assert infer_access_type(node2, plain_src, "python") == "read"


def test_property_classify_ts_accessor_text() -> None:
    """TS accessor capture text 'set' → write (T03 fix parity)."""

    class _FakeNode:
        parent = None
        type = "property"

    assert (
        infer_access_type(_FakeNode(), None, "typescript", accessor_text="set")
        == "write"
    )
    assert (
        infer_access_type(_FakeNode(), None, "typescript", accessor_text="get")
        == "read"
    )


# ---------------------------------------------------------------------------
# stamp_language
# ---------------------------------------------------------------------------

def test_stamp_language_batch() -> None:
    @dataclass
    class _Ent:
        metadata: dict = field(default_factory=dict)

    ents = [_Ent(metadata={}), _Ent(metadata={"language": "old"})]
    stamped = stamp_entities(ents, "python")
    assert stamped == 2
    assert ents[0].metadata["language"] == "python"
    assert ents[1].metadata["language"] == "python"  # unconditional (engine parity)
    assert stamp_entities(ents, None) == 0  # no language → no-op


def test_stamp_language_skips_contextual_stubs() -> None:
    """Contextual stubs are never stamped (engine parity — stub metadata is
    persisted verbatim by the writer; a language stamp would leak)."""
    @dataclass
    class _Ent:
        metadata: dict = field(default_factory=dict)

    stub = _Ent(metadata={"stub_resolution_state": "pending", "reference_type": "reads"})
    normal = _Ent(metadata={})
    stamped = stamp_entities([stub, normal := _Ent(metadata={})], "python")
    assert stamped == 1
    assert "language" not in stub.metadata
    assert normal.metadata["language"] == "python"


def test_stamp_language_hook_batch_per_file() -> None:
    @dataclass
    class _Ent:
        metadata: dict = field(default_factory=dict)

    ents = [_Ent(metadata={}) for _ in range(5)]
    ctx = PluginContext(
        file_path="a.py", root_path=Path("."), language="python", entities=ents
    )
    hook = StampLanguageHook()
    host = PluginHost()
    host.register_hook(hook)
    results = host.dispatch(Stage.ON_POST_ENTITIES, ctx)
    assert results[0].detail["stamped"] == 5
    assert all(e.metadata["language"] == "python" for e in ents)


def test_hooks_registered_and_dispatched() -> None:
    """All five hooks validate against the host stage contract."""
    host = PluginHost()
    host.register_hook(PruneStubHook())
    host.register_hook(LanguageDetectHook())
    host.register_hook(CommentClassifyHook())
    host.register_hook(PropertyClassifyHook())
    host.register_hook(StampLanguageHook())
    assert len(host.plugin_ids) == 5
    ctx = PluginContext(file_path="a.py", root_path=Path("."))
    # Every hook dispatches cleanly on its declared stage.
    for stage in Stage:
        host.dispatch(stage, ctx)  # must not raise
