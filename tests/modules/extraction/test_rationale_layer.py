"""T5: rationale layer — RATIONALE_FOR edges (graph-accuracy-overhaul).

Marker comments (``WHY:`` / ``NOTE:``, comment-syntax-aware per language) are
promoted to COMMENT_BLOCK entities and linked to the symbol they explain;
docstring COMMENT_BLOCKs link via ``parent_id``; markdown documents link to
MODULE entities via unique exact path-segment matches. RATIONALE_FOR is an
annotation edge: never traversed by trace_path (T6 whitelist) and never fed
to community clustering (T4 whitelist).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from batho.modules.storage.arrow_bundle.reader import BathoBundleReader
from batho.orchestrator.build import BuildOptions, run_build


def _build(root: Path, files: dict[str, str]) -> BathoBundleReader:
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        fp = root / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
    result = run_build(BuildOptions(root=root))
    assert result.success, result.warnings
    return BathoBundleReader(root / ".batho" / "artifact")


def _rels(reader: BathoBundleReader, rel_type: str = "RATIONALE_FOR") -> list[dict]:
    return [
        r
        for r in reader._get_table("rels_views").to_pylist()
        if r.get("relation_type") == rel_type
    ]


def _name_map(reader: BathoBundleReader) -> dict[str, str]:
    return {
        r["entity_id"]: str(r.get("name") or "")
        for r in reader._get_table("agent_views").to_pylist()
    }


def _targets(reader: BathoBundleReader) -> list[str]:
    names = _name_map(reader)
    return [names.get(r["target_id"], r["target_id"]) for r in _rels(reader)]


def _comment_entities(reader: BathoBundleReader) -> list[dict]:
    return [
        r
        for r in reader._get_table("agent_views").to_pylist()
        if r.get("entity_type") == "COMMENT_BLOCK"
    ]


# ---------------------------------------------------------------------------
# Marker comments → entities + edges
# ---------------------------------------------------------------------------


def test_marker_inside_function_links_to_it(tmp_path: Path):
    reader = _build(
        tmp_path / "r1",
        {
            "svc.py": (
                "def compute():\n"
                "    # WHY: result must stay deterministic for replay\n"
                "    return 42\n"
            )
        },
    )
    names = _name_map(reader)
    comments = [e for e in _comment_entities(reader) if "::comment@" in e["name"]]
    assert len(comments) == 1
    edges = _rels(reader)
    assert len(edges) == 1
    assert edges[0]["source_id"] == comments[0]["entity_id"]
    assert names[edges[0]["target_id"]].startswith("compute")


def test_comment_between_functions_links_to_following(tmp_path: Path):
    reader = _build(
        tmp_path / "r2",
        {
            "pair.py": (
                "def first():\n"
                "    return 1\n"
                "\n"
                "# NOTE: second validates before running\n"
                "def second():\n"
                "    return first()\n"
            )
        },
    )
    targets = _targets(reader)
    assert len(targets) == 1
    assert targets[0].startswith("second")


def test_comment_inside_function_not_class(tmp_path: Path):
    """A marker inside a method links to the METHOD (smallest span), not the
    enclosing class — the span-precision edge case."""
    reader = _build(
        tmp_path / "r3",
        {
            "svc.py": (
                "class Service:\n"
                "    def run(self):\n"
                "        # WHY: retries are idempotent by design\n"
                "        return self._go()\n"
                "    def _go(self):\n"
                "        return 1\n"
            )
        },
    )
    targets = _targets(reader)
    assert len(targets) == 1
    assert targets[0].startswith("Service.run")


def test_non_marker_comment_creates_no_entity(tmp_path: Path):
    reader = _build(
        tmp_path / "r4",
        {"plain.py": "# just a boring comment\ndef f():\n    return 0\n"},
    )
    assert not any("::comment@" in e["name"] for e in _comment_entities(reader))
    assert _rels(reader) == []


def test_marker_kinds_and_metadata(tmp_path: Path):
    reader = _build(
        tmp_path / "r5",
        {
            "m.py": (
                "# WHY: top-level invariant\n"
                "def f():\n"
                "    # NOTE: cached deliberately\n"
                "    return 1\n"
            )
        },
    )
    edges = _rels(reader)
    assert len(edges) == 2
    kinds_joined = " ".join(str(e.get("metadata_json") or "") for e in edges)
    # edge metadata carries the rationale_kind of the source comment
    assert "why" in kinds_joined and "note" in kinds_joined
    comments = [e for e in _comment_entities(reader) if "::comment@" in e["name"]]
    assert len(comments) == 2


def test_docstring_gets_rationale_edge(tmp_path: Path):
    reader = _build(
        tmp_path / "r6",
        {"d.py": 'def documented():\n    """Does the thing."""\n    return 1\n'},
    )
    doc = [e for e in _comment_entities(reader) if e["name"].endswith("::docstring")]
    assert len(doc) == 1
    edges = _rels(reader)
    assert len(edges) == 1
    assert edges[0]["source_id"] == doc[0]["entity_id"]
    assert "documented" in _name_map(reader)[edges[0]["target_id"]]


def test_every_comment_block_has_edge(tmp_path: Path):
    reader = _build(
        tmp_path / "r7",
        {
            "all.py": (
                'class C:\n    """Class doc."""\n'
                "    def m(self):\n"
                "        # WHY: marker\n"
                "        return 1\n"
            )
        },
    )
    comments = _comment_entities(reader)
    sources = {r["source_id"] for r in _rels(reader)}
    assert comments and all(e["entity_id"] in sources for e in comments)


# ---------------------------------------------------------------------------
# Cross-language comment syntax
# ---------------------------------------------------------------------------


def test_lua_double_dash_marker_pattern():
    """lua `--` comments are in the delimiter table even where the grammar
    itself isn't installed — the pattern is what matters."""
    from batho.modules.extraction.extractor import ASTExtractor

    class _Stub(ASTExtractor):
        def _query_source(self) -> str:
            return ""

    ext = _Stub.__new__(_Stub)
    ext._language_name = "lua"
    ext._parsing_config = {}
    pat = ext._marker_comment_pattern()
    assert pat is not None
    assert pat.search(b"-- WHY: lua uses --")
    assert not pat.search(b"# WHY: hash is not lua")


def test_haskell_block_marker_pattern():
    from batho.modules.extraction.extractor import ASTExtractor

    class _Stub(ASTExtractor):
        def _query_source(self) -> str:
            return ""

    ext = _Stub.__new__(_Stub)
    ext._language_name = "haskell"
    ext._parsing_config = {}
    pat = ext._marker_comment_pattern()
    assert pat is not None
    assert pat.search(b"{- WHY: block -}")


def test_marker_tables_cover_supported_languages():
    """EXT-11: languages with extractors must have comment-syntax entries —
    and dead entries (sql has no parser) must not linger in the tables."""
    from batho.modules.extraction.extractor import (
        _BLOCK_COMMENT_PAIRS,
        _LINE_COMMENT_PREFIXES,
    )
    from batho.modules.extraction.submodules.parser_factory.registry import (
        _EXT_TO_LANG,
    )

    supported_langs = set(_EXT_TO_LANG.values())
    covered = set(_LINE_COMMENT_PREFIXES) | set(_BLOCK_COMMENT_PAIRS)
    # Languages without C-style/line comment syntax or handled elsewhere.
    markerless = {
        "markdown",  # rationale flows through the doc→module derivation
        "json", "jsonc", "ini", "dockerfile", "properties", "gitignore",
        "editorconfig", "requirements",
    }
    missing = supported_langs - covered - markerless
    assert not missing, f"supported languages missing marker tables: {missing}"
    assert "sql" not in covered, "sql has no parser — dead table entry"

    for lang in ("objectivec", "agda", "hack", "hcl", "html"):
        assert lang in covered, f"{lang} registered but unmapped"


def test_ts_block_comment_marker(tmp_path: Path):
    reader = _build(
        tmp_path / "r9",
        {
            "b.ts": (
                "/* WHY: block-level rationale */\n"
                "export function blocky(): number {\n    return 1\n}\n"
            )
        },
    )
    comments = [e for e in _comment_entities(reader) if "::comment@" in e["name"]]
    assert len(comments) == 1
    targets = _targets(reader)
    assert any("blocky" in t for t in targets)


def test_case_sensitivity_config(tmp_path: Path):
    """Default case-sensitive: `// why:` does not match; opt-in insensitive."""
    reader = _build(
        tmp_path / "r10a",
        {"c.ts": "// why: lowercase\nexport function f() { return 1 }\n"},
    )
    assert not any("::comment@" in e["name"] for e in _comment_entities(reader))

    root = tmp_path / "r10b"
    root.mkdir(parents=True)
    (root / "batho.yaml").write_text(
        "extraction:\n  rationale_markers_case_sensitive: false\n",
        encoding="utf-8",
    )
    reader2 = _build(
        root, {"c.ts": "// why: lowercase\nexport function f() { return 1 }\n"}
    )
    assert any("::comment@" in e["name"] for e in _comment_entities(reader2))


def test_trailing_marker_comment(tmp_path: Path):
    reader = _build(
        tmp_path / "r11",
        {"t.py": "def f():\n    x = compute()  # WHY: memoized\n    return x\n"},
    )
    assert any("::comment@" in e["name"] for e in _comment_entities(reader))


def test_marker_inside_triple_quoted_string_ignored(tmp_path: Path):
    """a5533ba1cea5: `# WHY:` inside a triple-quoted string is a string
    literal, not a comment — it must not produce a COMMENT_BLOCK entity or a
    RATIONALE_FOR edge. The real `# WHY:` line below the string still does."""
    reader = _build(
        tmp_path / "r11b",
        {
            "s.py": (
                "def f():\n"
                '    s = """\n'
                "    # WHY: inside a string literal, not a comment\n"
                '    """\n'
                "    # WHY: real comment\n"
                "    return s\n"
            )
        },
    )
    comments = [e for e in _comment_entities(reader) if "::comment@" in e["name"]]
    # Only the real comment (line 5) is promoted — the string-embedded hit
    # on line 3 produces nothing.
    assert len(comments) == 1
    assert comments[0]["start_line"] == 5
    edges = _rels(reader)
    assert len(edges) == 1
    assert edges[0]["source_id"] == comments[0]["entity_id"]


def test_marker_parent_id_non_target_type_falls_through(tmp_path: Path):
    """EXT-07: a marker comment contained by a NAMESPACE entity gets
    parent_id → NAMESPACE from the containment pass — but NAMESPACE is not a
    rationale target type, so the edge must not take the parent shortcut;
    it attributes to the following FUNCTION instead."""
    reader = _build(
        tmp_path / "r11d",
        {
            "x.cpp": (
                "namespace ns {\n"
                "// WHY: scoped helper\n"
                "int f() { return 1; }\n"
                "}\n"
            )
        },
    )
    names = _name_map(reader)
    edges = _rels(reader)
    assert len(edges) == 1
    target = names.get(edges[0]["target_id"], "")
    assert "f" in target and "ns" not in target.split(".")[-1], (
        f"marker must attribute to function f, not namespace: {target}"
    )
    assert target == "ns.f"


def test_empty_rationale_markers_disables_extraction(tmp_path: Path):
    """EXT-14: an explicit `rationale_markers: []` disables marker extraction
    entirely — it is not a `None` that falls back to defaults."""
    root = tmp_path / "r11e"
    root.mkdir(parents=True)
    (root / "batho.yaml").write_text(
        "extraction:\n  rationale_markers: []\n", encoding="utf-8"
    )
    reader = _build(
        root,
        {"t.py": "def f():\n    # WHY: would normally be extracted\n    return 1\n"},
    )
    assert not any("::comment@" in e["name"] for e in _comment_entities(reader))
    assert _rels(reader) == []


def test_trailing_marker_content_excludes_code_prefix():
    """EXT-08: for `x = 1  # WHY: ...` the entity's raw_content/content_hash
    must cover only the comment slice, not the code prefix — the hash is the
    entity's dedup identity (agent_views stores the FILE hash, so this is a
    unit-level assertion on the emitted entity)."""
    import hashlib

    from batho.modules.extraction.extractor import ASTExtractor

    class _Stub(ASTExtractor):
        def _query_source(self) -> str:
            return ""

    ext = _Stub.__new__(_Stub)
    ext._language_name = "python"
    ext._parsing_config = {}
    ents = ext._extract_marker_comment_entities(
        b"def f():\n    x = 1  # WHY: memoized\n    return x\n",
        "t.py",
        root_node=None,
    )
    assert len(ents) == 1
    comment = ents[0]
    assert comment.raw_content == "# WHY: memoized"
    assert comment.content_hash == hashlib.sha256(b"# WHY: memoized").hexdigest()
    assert comment.start_byte == 20  # at the `#`, not the line start


def test_marker_inside_string_only_produces_nothing(tmp_path: Path):
    """a5533ba1cea5: a file whose only marker hit lives inside a string
    literal yields zero COMMENT_BLOCK entities and zero RATIONALE_FOR edges."""
    reader = _build(
        tmp_path / "r11c",
        {
            "s.py": (
                "def f():\n"
                '    s = """\n'
                "    # WHY: inside a string literal\n"
                '    """\n'
                "    return s\n"
            )
        },
    )
    assert not any("::comment@" in e["name"] for e in _comment_entities(reader))
    assert _rels(reader) == []


# ---------------------------------------------------------------------------
# Doc → module links (exact path-segment, unique-suffix)
# ---------------------------------------------------------------------------


def test_doc_to_module_exact_segment(tmp_path: Path):
    reader = _build(
        tmp_path / "r12",
        {
            "docs/arch.md": (
                "# Architecture\n\nThe graph lives in app/services/graph_service.py.\n"
            ),
            "app/__init__.py": "",
            "app/services/__init__.py": "",
            "app/services/graph_service.py": "def svc():\n    return 1\n",
        },
    )
    edges = _rels(reader)
    doc_edges = [
        e for e in edges if "docs" in e["source_id"] or "arch" in e["source_id"]
    ]
    assert doc_edges, "expected a DOCUMENT→MODULE rationale edge"
    names = _name_map(reader)
    assert names[doc_edges[0]["target_id"]] == "graph_service"


def test_doc_to_module_edge_annotation_contract(tmp_path: Path):
    """GRH-12: doc→module RATIONALE_FOR edges are heuristic derivations and
    must carry the annotation-edge contract (edge_class + sub-1.0 confidence)
    like the sibling emitters — never a bare derived edge at confidence 1.0."""
    import json

    reader = _build(
        tmp_path / "r12b",
        {
            "docs/arch.md": "# Architecture\n\nLives in app/services/graph_service.py.\n",
            "app/__init__.py": "",
            "app/services/__init__.py": "",
            "app/services/graph_service.py": "def svc():\n    return 1\n",
        },
    )
    doc_edges = [
        e for e in _rels(reader) if "arch" in str(e["source_id"])
    ]
    assert doc_edges, "expected a DOCUMENT→MODULE rationale edge"
    for e in doc_edges:
        meta = json.loads(e.get("metadata_json") or "{}")
        assert meta.get("edge_class") == "annotation"
        assert meta.get("semantic") is True
        assert meta.get("derived") is True
        assert meta.get("reason") == "doc_module_mention"
        assert 0.0 < e["confidence"] < 1.0


def test_doc_ambiguous_suffix_skipped(tmp_path: Path):
    reader = _build(
        tmp_path / "r13",
        {
            "docs/dup.md": "See sub/util.py for details.\n",
            "a/__init__.py": "",
            "a/sub/__init__.py": "",
            "a/sub/util.py": "def ua():\n    return 1\n",
            "b/__init__.py": "",
            "b/sub/__init__.py": "",
            "b/sub/util.py": "def ub():\n    return 1\n",
        },
    )
    # `sub/util.py` suffix matches BOTH a.sub.util and b.sub.util → skipped
    assert _rels(reader) == []


def test_doc_bare_substring_never_links(tmp_path: Path):
    """`core` appearing inside a sentence must not match a `core` module."""
    reader = _build(
        tmp_path / "r14",
        {
            "docs/notes.md": "This is the core of the design, obviously.\n",
            "pkg/__init__.py": "",
            "pkg/core.py": "def c():\n    return 1\n",
        },
    )
    assert _rels(reader) == []


# ---------------------------------------------------------------------------
# Boundary: annotation edges stay out of structural analysis
# ---------------------------------------------------------------------------


def test_rationale_not_traversable(tmp_path: Path):
    from batho.mcp.tools import TRACE_TRAVERSABLE_RELATIONS

    assert "RATIONALE_FOR" not in TRACE_TRAVERSABLE_RELATIONS


def test_marker_scan_is_deterministic(tmp_path: Path):
    files = {
        "d.py": (
            "# WHY: first\n"
            "def a():\n"
            "    # NOTE: inner\n"
            "    return 1\n"
            "def b():\n"
            "    return a()\n"
        )
    }
    r1 = _build(tmp_path / "da", files)
    r2 = _build(tmp_path / "db", files)
    k1 = sorted((r["source_id"].split("/")[-1], r["relation_type"]) for r in _rels(r1))
    k2 = sorted((r["source_id"].split("/")[-1], r["relation_type"]) for r in _rels(r2))
    assert len(k1) == len(k2) == 2
    assert [t for _, t in k1] == [t for _, t in k2]


# ---------------------------------------------------------------------------
# Doc-link dedupe + suffix index (reviews eed081593f86 / 417761f45804):
# per-doc dedupe comes from get_rels_by_endpoint, not a global rel scan;
# token matching goes through a precomputed suffix map.
# ---------------------------------------------------------------------------


def test_doc_module_link_not_duplicated(tmp_path: Path):
    """A pre-existing RATIONALE_FOR doc→module edge is not re-added — the
    per-doc dedupe set (get_rels_by_endpoint) catches it."""
    from batho.core.schemas import (
        Entity, EntityType, Relationship, RelationshipType,
    )
    from batho.modules.graph.builder.codegraph import (
        CodeGraphIndexer, InMemoryGraph,
    )

    root = tmp_path / "r16"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "arch.md").write_text(
        "See app/svc.py for details.\n", encoding="utf-8"
    )
    indexer = CodeGraphIndexer(cache_path=str(tmp_path / "c"), root=str(root))
    graph = InMemoryGraph()
    graph.add_entity(Entity(
        type=EntityType.DOCUMENT, name="arch", file="docs/arch.md",
        start_line=1, end_line=1, metadata={"language": "markdown"},
        id_override="doc1",
    ))
    graph.add_entity(Entity(
        type=EntityType.MODULE, name="svc", file="app/svc.py",
        start_line=1, end_line=1, metadata={"module_path": "app.svc"},
        id_override="mod1",
    ))
    graph.add_relationship(Relationship(
        source_id="doc1", target_id="mod1",
        type=RelationshipType.RATIONALE_FOR,
    ))

    added = indexer._derive_rationale_doc_links(graph)
    assert added == 0
    rels = [
        r for r in graph.relationships
        if r.type == RelationshipType.RATIONALE_FOR
    ]
    assert len(rels) == 1
    indexer.close()


def test_doc_module_suffix_map_still_links(tmp_path: Path):
    """Unique-suffix doc tokens still link through the precomputed suffix
    map (same semantics as the old per-token scan)."""
    from batho.core.schemas import (
        Entity, EntityType, RelationshipType,
    )
    from batho.modules.graph.builder.codegraph import (
        CodeGraphIndexer, InMemoryGraph,
    )

    root = tmp_path / "r17"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "arch.md").write_text(
        "The store lives in pkg/store.py.\n", encoding="utf-8"
    )
    indexer = CodeGraphIndexer(cache_path=str(tmp_path / "c2"), root=str(root))
    graph = InMemoryGraph()
    graph.add_entity(Entity(
        type=EntityType.DOCUMENT, name="arch", file="docs/arch.md",
        start_line=1, end_line=1, metadata={"language": "markdown"},
        id_override="doc1",
    ))
    graph.add_entity(Entity(
        type=EntityType.MODULE, name="store", file="backend/pkg/store.py",
        start_line=1, end_line=1,
        metadata={"module_path": "backend.pkg.store"},
        id_override="mod1",
    ))

    added = indexer._derive_rationale_doc_links(graph)
    assert added == 1
    rel = next(
        r for r in graph.relationships
        if r.type == RelationshipType.RATIONALE_FOR
    )
    assert rel.source_id == "doc1" and rel.target_id == "mod1"
    indexer.close()


# ---------------------------------------------------------------------------
# EXT-02 / EXT-03 regressions — comment-node spans, continuation markers,
# skip_comments opt-out
# ---------------------------------------------------------------------------


def test_multiline_block_marker_spans_whole_comment(tmp_path: Path):
    """A /* */ marker must end at the comment node end — not end-of-line —
    so a following def on the next line has a pure-whitespace gap."""
    reader = _build(
        tmp_path / "r_ml",
        {
            "b.ts": (
                "/* WHY: multi-line rationale\n"
                "   more detail */\n"
                "export function blocky(): number {\n    return 1\n}\n"
            )
        },
    )
    comments = [e for e in _comment_entities(reader) if "::comment@" in e["name"]]
    assert len(comments) == 1
    assert comments[0]["end_line"] > comments[0]["start_line"]
    assert any("blocky" in t for t in _targets(reader))


def test_same_line_def_after_block_comment(tmp_path: Path):
    """`/* WHY: x */ export function f() {}` — the def starts before EOL;
    the truncated end_byte used to swallow it (overlapping span + no edge)."""
    reader = _build(
        tmp_path / "r_sl",
        {
            "b.ts": (
                "/* WHY: same-line def */\n"
                "/* WHY: inline */ export function inl() { return 1 }\n"
            )
        },
    )
    assert any("inl" in t for t in _targets(reader))
    names = _name_map(reader)
    contains = [
        r
        for r in reader._get_table("rels_views").to_pylist()
        if r.get("relation_type") == "CONTAINS"
        and "::comment@" in names.get(r["source_id"], "")
    ]
    assert not any("inl" in names.get(r["target_id"], "") for r in contains)


def test_block_continuation_marker(tmp_path: Path):
    """`* WHY:` on a continuation line inside /* */ has no opener on the
    line — accepted only because the byte sits inside the comment node."""
    reader = _build(
        tmp_path / "r_cont",
        {
            "b.ts": (
                "/**\n * WHY: documented body marker\n */\n"
                "export function jsdocy(): number { return 2 }\n"
            )
        },
    )
    comments = [e for e in _comment_entities(reader) if "::comment@" in e["name"]]
    assert len(comments) == 1
    assert any("jsdocy" in t for t in _targets(reader))


def test_skip_comments_suppresses_marker_entities(tmp_path: Path):
    """EXT-03: `bsg.parsing.skip_comments: true` must suppress marker
    COMMENT_BLOCK entities — they're comments, not exempt signals."""
    root = tmp_path / "r_skip"
    root.mkdir(parents=True)
    (root / "batho.yaml").write_text(
        "bsg:\n  parsing:\n    skip_comments: true\n", encoding="utf-8"
    )
    reader = _build(
        root,
        {"c.ts": "// WHY: hidden\nexport function g() { return 1 }\n"},
    )
    assert not any("::comment@" in e["name"] for e in _comment_entities(reader))


# ---------------------------------------------------------------------------
# EXT-05: annotation-edge contract — edge_class + INFERRED confidence
# ---------------------------------------------------------------------------

def test_rationale_for_edges_carry_annotation_contract(tmp_path: Path):
    """Every RATIONALE_FOR edge must carry metadata.edge_class='annotation'
    and INFERRED-grade confidence (< 1.0) — the contract in
    schemas.ANNOTATION_RELATIONS that G4/G6 filters key on."""
    import json
    reader = _build(
        tmp_path / "ext05",
        {
            "svc.py": (
                "def compute():\n"
                "    # WHY: result must stay deterministic for replay\n"
                "    return 42\n"
            )
        },
    )
    edges = _rels(reader)
    assert edges, "no RATIONALE_FOR edges emitted"
    for e in edges:
        meta = json.loads(e.get("metadata_json") or "{}")
        assert meta.get("edge_class") == "annotation", meta
        assert meta.get("semantic") is True
        conf = e.get("confidence")
        assert conf is not None and conf < 1.0, conf


def test_doc_module_rationale_edges_carry_annotation_contract(tmp_path: Path):
    """The second emitter (_derive_rationale_doc_links) must follow the same
    contract — DOCUMENT → MODULE edges derived from path mentions."""
    import json
    reader = _build(
        tmp_path / "ext05doc",
        {
            "pkg/util.py": "def helper():\n    return 1\n",
            "notes.md": "See pkg/util.py for the helper implementation.\n",
        },
    )
    edges = _rels(reader)
    assert edges, "no doc→module RATIONALE_FOR edges emitted"
    for e in edges:
        meta = json.loads(e.get("metadata_json") or "{}")
        assert meta.get("edge_class") == "annotation", meta
        conf = e.get("confidence")
        assert conf is not None and conf < 1.0, conf
