"""tests/sdk/test_core_pack_golden.py — T30: golden-output tests for
class:core plugins (spec §4.5, T20 manifest pairing).

Core-class plugins are exempt from the fixture gate's selectivity cap but
NOT from verification: these tests pin expected prune/tag/category counts
on the fixture corpus under tests/fixtures/language_packs/ so any
regression in core-pack data or hook logic fails loudly in CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from batho_plugin import PluginContext, PluginHost, Stage, load_host
from batho_plugin.hooks import stamp_entities
from batho_plugin.hooks.prune_stub import should_prune
from batho_plugin.rule_engine import apply_bsg_rules_to_entities, load_effective_rules

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "language_packs"
CORE_DIR = Path(__file__).resolve().parent.parent.parent / "sdk" / "batho_plugin" / "core"


def _entity(name: str, file: str, metadata: dict | None = None):
    """Minimal entity stand-in for rule application (duck-typed)."""
    from batho.core.schemas import Entity, EntityType

    return Entity(
        type=EntityType.FUNCTION,
        name=name,
        file=file,
        start_line=1,
        end_line=2,
        start_byte=0,
        end_byte=10,
        signature=name,
        metadata=metadata or {},
        id_override=f"{file}::{name}",
    )


def _fixture_entities() -> list:
    """One entity per fixture file — file_pattern rules key off entity.file."""
    return [
        _entity("app_fn", "src/app.py", {"language": "python"}),
        _entity("ts_fn", "src/index.ts", {"language": "typescript"}),
        _entity("test_fn", "tests/test_app.py", {"language": "python"}),
        _entity("readme", "docs/README.md", {}),
        _entity("settings", "config/settings.yaml", {}),
        _entity("terraform", "main.tf", {}),
    ]


def _load_builtin_rules(root: Path):
    cfg = {
        "enabled": True,
        "auto_load_all_plugins": True,
        "builtin_plugins": [],
        "custom_rules_path": None,
        "custom_rules_dir": "",
        "custom_rules_inline": [],
    }
    rules, _stats = load_effective_rules(cfg, root)
    return list(rules)


def _apply_per_file(entities, rules, root: Path):
    """apply_bsg_rules_to_entities is a per-file API — file_patterns match
    the file arg, not per-entity files. Group fixture entities by file."""
    out = []
    by_file: dict[str, list] = {}
    for e in entities:
        by_file.setdefault(e.file, []).append(e)
    for f, ents in by_file.items():
        updated, _audit = apply_bsg_rules_to_entities(
            entities=ents, relationships=[], rules=rules,
            root_path=str(root.resolve()), file_path=f,
        )
        out.extend(updated)
    return out


def test_category_distribution():
    """T09 consolidation: category writes are byte-identical to the split
    rule set (TEST/DOC/CONFIG/INFRA/SOURCE on the fixture corpus)."""
    rules = _load_builtin_rules(Path("."))
    entities = _apply_per_file(_fixture_entities(), rules, Path("."))
    cats = {}
    for e in entities:
        cat = (e.metadata or {}).get("bsg.category")
        cats[cat] = cats.get(cat, 0) + 1
    assert cats.get("TEST") == 1  # tests/test_app.py
    assert cats.get("DOC") == 1  # docs/README.md (path + extension)
    assert cats.get("SOURCE") == 2  # app.py, index.ts
    # settings.yaml: CONFIG path (config/) + extension catch-all — same value
    assert cats.get("CONFIG") == 1
    # main.tf (repo root): .tf → bsg-category-infra (175); not covered by the
    # p190 config-exact list → INFRA survives. (Dockerfile-style names stay
    # CONFIG — config-exact at p190 has always overwritten infra at p175.)
    assert cats.get("INFRA") == 1


def test_usn_tags_on_categories():
    rules = _load_builtin_rules(Path("."))
    entities = _apply_per_file(_fixture_entities(), rules, Path("."))
    by_name = {e.name: e for e in entities}
    assert "TestArtifact" in (by_name["test_fn"].metadata.get("bsg.usn") or [])
    assert "Documentation" in (by_name["readme"].metadata.get("bsg.usn") or [])
    assert "Configuration" in (by_name["settings"].metadata.get("bsg.usn") or [])
    assert "InfrastructureConfig" in (by_name["terraform"].metadata.get("bsg.usn") or [])


def test_language_stamp_coverage():
    """T10: the stamp hook covers bsg.language for engine-detected files —
    the ecosystem display name, on all entities including stubs (rule parity).
    """
    host = PluginHost()
    from batho_plugin.packs import load_pack_dir

    for plugin in load_pack_dir(CORE_DIR):
        host.register_data(plugin)
    eco = host.get_map("language_ecosystem")
    assert eco["python"] == "Python"
    assert eco["typescript"] == "Node.js"  # ecosystem name, not "TypeScript"
    assert eco["kotlin"] == "Kotlin"

    stub = _entity("stub", "src/app.py", {"stub_resolution_state": "pending", "reference_type": "reads"})
    normal = _entity("fn", "src/app.py", {})
    stamped = stamp_entities([stub, normal], "python", ecosystem=eco.get("python"))
    assert stamped == 2
    assert stub.metadata.get("bsg.language") == "Python"   # stubs stamped (rule parity)
    assert "language" not in stub.metadata                 # bare key stays engine-only
    assert normal.metadata["language"] == "python"
    assert normal.metadata["bsg.language"] == "Python"


def test_prune_counts_per_language():
    """Golden prune counts: builtin pruning per language via pack data."""
    host = load_host(config={"plugins": {}})
    cases = [
        # (ref, language, expect_prune, reason_contains)
        ("len", "python", True, "builtin"),
        ("my_custom_thing_xyz", "python", True, "unimported_simple_name"),
        ("console", "typescript", True, "builtin"),
        ("cap", "go", True, "builtin"),
        ("usize", "rust", True, "builtin"),
    ]
    for ref, lang, expect, reason in cases:
        d = should_prune(
            ref, "USES", lang, "src/app.py", True, frozenset(),
            builtins=host.get_set("builtins", language=lang),
            noise_symbols=host.get_set("noise_symbols", language=lang),
        )
        assert d.prune is expect, f"{lang}:{ref} → {d}"
        if expect:
            assert reason in (d.reason or "")


def test_detection_plugins_load():
    """All 13 detection plugins moved under core/detection/ still compile."""
    rules = _load_builtin_rules(Path("."))
    from batho_plugin.rule_engine import list_builtin_plugins

    catalog = list_builtin_plugins()
    moved = [
        "manifests", "cpp", "csharp", "dart", "elixir", "kotlin", "php",
        "ruby", "scala", "swift", "cicd", "cloud_providers", "test_frameworks",
    ]
    for stem in moved:
        assert stem in catalog, f"{stem} missing from builtin catalog"
    # Slimmed: detect_language rules retain only manifest patterns.
    dart_rules = [r for r in rules if r.rule_id == "detect-dart"]
    assert dart_rules, "detect-dart missing"
    pats = dart_rules[0].match.file_patterns
    assert "**/*.dart" not in pats
    assert "**/pubspec.yaml" in pats


def test_foundation_writes():
    """graph_foundation's derive actions survived the T09 split."""
    rules = _load_builtin_rules(Path("."))
    ids = {r.rule_id for r in rules}
    assert "bsg-derive-service-tag" in ids
    assert "bsg-derive-scope-tier" in ids
    # category rules moved to the categorization plugin
    cat_ids = {r.rule_id for r in rules}
    assert "bsg-category-config" in cat_ids
    assert "bsg-category-infra" in cat_ids


def test_golden_manifest_completeness():
    """Every class:core rule plugin in the SDK core pack is registered in the
    golden manifest (T20's gate depends on it)."""
    import yaml

    manifest = json.loads((CORE_DIR / "golden_manifest.json").read_text())
    registered = set(manifest["plugins"].keys())
    core_plugins = set()
    for f in CORE_DIR.rglob("*.yaml"):
        head = f.read_text(encoding="utf-8")[:2048]
        if "bsg-plugin.v" in head:
            doc = yaml.safe_load(f.read_text())
            if doc.get("class") == "core":
                core_plugins.add(doc["plugin_id"])
    missing = core_plugins - registered
    assert not missing, f"core plugins missing golden registration: {missing}"
