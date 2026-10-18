"""
tests/orchestrator/test_plugins_apply.py

Integration tests for `batho plugins apply` (T08):
  - builds a synthetic artifact via BathoBundleWriter
  - runs retro-enrichment: entities get rule-set metadata without re-extraction
  - idempotent second apply; dry-run doesn't write; telemetry record emitted
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from batho.modules.storage.arrow_bundle.bundle import BathoBundle


def _seed_artifact(root: Path, run_uuid: str = "r1") -> BathoBundle:
    """Write a one-file artifact: function entity + tracking, no metadata."""
    db = BathoBundle(root)
    internal = db.create_run(run_uuid, root_path=str(root))
    db.upsert_file_tracking([{
        "file_path": "app/x.py",
        "content_hash": "hash_x",
        "mtime_ns": 1,
        "inode": None,
        "size": 50,
        "is_indexed": True,
        "last_run_uuid": run_uuid,
    }])
    writer = db._writers[internal]
    writer.write_file_artifact(
        1,
        agent={"entities": [{
            "id": f"{root}/app/x.py::foo",
            "name": "foo",
            "type": "FUNCTION",
            "file": str(root / "app/x.py"),
            "start_line": 1,
            "end_line": 3,
            "signature": "def foo():",
            "is_exported": True,
            "fqn": "x.foo",
            "metadata": {},
        }]},
        storage={"entities": [{
            "id": f"{root}/app/x.py::foo",
            "raw_content": "def foo():\n    pass\n",
            "syntax_glue": {"leading_whitespace": "", "trailing_whitespace": ""},
            "ast_node_type": "function_definition",
            "start_byte": 0,
            "end_byte": 21,
        }]},
        rels=[],
        content_hash="hash_x",
    )
    db.complete_run(run_uuid, entity_count=1, file_count=1)
    return db


def _write_plugin(root: Path) -> Path:
    pdir = root / ".batho" / "plugins"
    pdir.mkdir(parents=True, exist_ok=True)
    plugin = pdir / "quarantine.yaml"
    plugin.write_text(
        """schema_version: bsg-plugin.v2
plugin_id: quarantine_p
name: Quarantine P
version: 1.0.0
enabled: true
rules:
  - rule_id: quarantine-all
    name: quarantine-all
    severity: warning
    matchers:
      name_patterns: ["*"]
    actions:
      metadata:
        bsg.noise: true
        bsg.quarantined: true
""",
        encoding="utf-8",
    )
    (root / "batho.yaml").write_text(
        "rules:\n  enabled: true\n  auto_load_all_plugins: false\n"
        "  builtin_plugins: []\n  custom_rules_dir: .batho/plugins\n",
        encoding="utf-8",
    )
    return plugin


class TestPluginsApply:
    def test_apply_enriches_without_reextraction(self, tmp_path):
        from batho.core.config.loader import reload_config
        from batho.orchestrator.plugins_apply import (
            PluginsApplyOptions, run_plugins_apply,
        )

        _seed_artifact(tmp_path)
        _write_plugin(tmp_path)
        reload_config()
        result = run_plugins_apply(PluginsApplyOptions(root=tmp_path))
        assert result.success, result.message
        assert result.entities_updated >= 1
        assert result.files_rewritten >= 1
        assert result.rule_hits.get("quarantine-all", 0) >= 1

        # metadata_json now carries the quarantine flag in agent_views
        from batho.modules.storage.arrow_bundle.bundle import BathoBundle as BB
        db2 = BB(tmp_path)
        rid = db2.get_latest_run_id()
        rid_int = db2.get_run_internal_id(rid)
        artifacts = db2.get_file_artifacts(rid_int, include_storage=False)
        ent_meta = artifacts[0]["graph"]["entities"][0].get("metadata") or {}
        assert ent_meta.get("bsg.noise") is True
        assert ent_meta.get("bsg.quarantined") is True

        # telemetry record emitted under a plugins_apply run_uuid
        run_artifacts = db2.get_run_artifacts(rid_int)
        rs = (run_artifacts or {}).get("rule_stats") or {}
        assert rs.get("run_kind") == "plugins_apply"
        assert rs.get("rule_hits", {}).get("quarantine-all", 0) >= 1
        # plugin_files keyed by stamped plugin name (custom_dir:<filename>)
        assert "custom_dir:quarantine.yaml" in (rs.get("plugin_files") or {})
        reload_config()

    def test_apply_idempotent_second_run(self, tmp_path):
        from batho.core.config.loader import reload_config
        from batho.orchestrator.plugins_apply import (
            PluginsApplyOptions, run_plugins_apply,
        )

        _seed_artifact(tmp_path)
        _write_plugin(tmp_path)
        reload_config()
        r1 = run_plugins_apply(PluginsApplyOptions(root=tmp_path))
        r2 = run_plugins_apply(PluginsApplyOptions(root=tmp_path))
        assert r1.success and r2.success
        # second run: metadata unchanged → no files rewritten
        assert r2.entities_updated == 0
        assert r2.files_rewritten == 0
        reload_config()

    def test_apply_dry_run_writes_nothing(self, tmp_path):
        from batho.core.config.loader import reload_config
        from batho.orchestrator.plugins_apply import (
            PluginsApplyOptions, run_plugins_apply,
        )
        from batho.modules.storage.arrow_bundle.bundle import BathoBundle as BB

        _seed_artifact(tmp_path)
        _write_plugin(tmp_path)
        reload_config()
        before = BB(tmp_path).get_latest_run_id()
        result = run_plugins_apply(
            PluginsApplyOptions(root=tmp_path, dry_run=True)
        )
        assert result.success and result.dry_run
        assert result.entities_updated >= 1
        assert BB(tmp_path).get_latest_run_id() == before
        reload_config()

    def test_apply_rules_disabled_clean_error(self, tmp_path):
        from batho.core.config.loader import reload_config
        from batho.orchestrator.plugins_apply import (
            PluginsApplyOptions, run_plugins_apply,
        )

        _seed_artifact(tmp_path)
        (tmp_path / "batho.yaml").write_text(
            "rules:\n  enabled: false\n", encoding="utf-8"
        )
        reload_config()
        result = run_plugins_apply(PluginsApplyOptions(root=tmp_path))
        assert not result.success
        assert "rules.enabled is false" in result.message
        reload_config()

    def test_apply_no_artifact_clean_error(self, tmp_path):
        from batho.orchestrator.plugins_apply import (
            PluginsApplyOptions, run_plugins_apply,
        )

        result = run_plugins_apply(PluginsApplyOptions(root=tmp_path))
        assert not result.success
        assert "batho build" in result.message
        # ENR-09: no eager .batho/artifact/ on a bare checkout
        assert not (tmp_path / ".batho").exists()


def _seed_two_entities(
    root: Path, run_uuid: str = "r1", extra_names: tuple[str, ...] = ()
) -> BathoBundle:
    """Two functions in one file — `foo` and `test_foo` — no metadata.

    `extra_names` appends additional entities (e.g. a clean edge target when
    the named ones are quarantined)."""
    db = BathoBundle(root)
    internal = db.create_run(run_uuid, root_path=str(root))
    db.upsert_file_tracking([{
        "file_path": "app/x.py",
        "content_hash": "hash_x",
        "mtime_ns": 1,
        "inode": None,
        "size": 80,
        "is_indexed": True,
        "last_run_uuid": run_uuid,
    }])
    writer = db._writers[internal]

    def ent(name: str, start: int, end: int) -> dict:
        return {
            "id": f"{root}/app/x.py::{name}",
            "name": name,
            "type": "FUNCTION",
            "file": str(root / "app/x.py"),
            "start_line": start,
            "end_line": end,
            "signature": f"def {name}():",
            "is_exported": True,
            "fqn": f"x.{name}",
            "metadata": {},
        }

    writer.write_file_artifact(
        1,
        agent={
            "entities": [ent("foo", 1, 2), ent("test_foo", 4, 6)]
            + [ent(n, 10 + i * 3, 11 + i * 3) for i, n in enumerate(extra_names)]
        },
        storage={"entities": [
            {
                "id": f"{root}/app/x.py::foo",
                "raw_content": "def foo():\n    return 1\n",
                "syntax_glue": {"leading_whitespace": "", "trailing_whitespace": ""},
                "ast_node_type": "function_definition",
                "start_byte": 0,
                "end_byte": 22,
            },
            {
                "id": f"{root}/app/x.py::test_foo",
                "raw_content": "def test_foo():\n    assert foo() == 1\n",
                "syntax_glue": {"leading_whitespace": "", "trailing_whitespace": ""},
                "ast_node_type": "function_definition",
                "start_byte": 23,
                "end_byte": 65,
            },
        ]},
        rels=[],
        content_hash="hash_x",
    )
    db.complete_run(run_uuid, entity_count=2, file_count=1)
    return db


def _write_edge_hint_plugin(root: Path) -> Path:
    pdir = root / ".batho" / "plugins"
    pdir.mkdir(parents=True, exist_ok=True)
    plugin = pdir / "testedby.yaml"
    plugin.write_text(
        """schema_version: bsg-plugin.v2
plugin_id: testedby_p
name: TestedBy P
version: 1.0.0
enabled: true
rules:
  - rule_id: tested-by-hint
    name: tested-by-hint
    severity: info
    matchers:
      name_patterns: ["test_*"]
    actions:
      metadata:
        bsg.edge_hints:
          - type: REFERS_TO
            target_name_pattern: "foo"
""",
        encoding="utf-8",
    )
    (root / "batho.yaml").write_text(
        "rules:\n  enabled: true\n  auto_load_all_plugins: false\n"
        "  builtin_plugins: []\n  custom_rules_dir: .batho/plugins\n",
        encoding="utf-8",
    )
    return plugin


class TestPluginsApplyTagEdges:
    def test_apply_mints_annotation_edges_from_rule_metadata(self, tmp_path):
        """RUL-01: tag-edge derivation must run AFTER the rule loop — a
        plugin stamping bsg.edge_hints must materialize the annotation edge
        in the rewritten artifact (pre-fix the postpass ran on pre-rule
        state, so apply never minted these edges)."""
        from batho.core.config.loader import reload_config
        from batho.orchestrator.plugins_apply import (
            PluginsApplyOptions, run_plugins_apply,
        )

        _seed_two_entities(tmp_path)
        _write_edge_hint_plugin(tmp_path)
        reload_config()
        result = run_plugins_apply(PluginsApplyOptions(root=tmp_path))
        assert result.success, result.message
        assert result.entities_updated >= 1

        from batho.modules.storage.arrow_bundle.bundle import BathoBundle as BB
        db2 = BB(tmp_path)
        rid = db2.get_latest_run_id()
        arts = db2.get_file_artifacts(
            db2.get_run_internal_id(rid), include_storage=False
        )
        rels = [
            r
            for a in arts
            for r in (a["graph"].get("relationships") or [])
        ]
        tb = [r for r in rels if r.get("type") == "TESTED_BY"]
        assert tb, f"no TESTED_BY edge materialized: {rels}"
        src = tb[0]["source_id"]
        dst = tb[0]["target_id"]
        assert src.endswith("::test_foo"), f"wrong direction: {tb[0]}"
        assert dst.endswith("::foo"), f"wrong target: {tb[0]}"
        reload_config()


def _write_plugin_body(root: Path, rules_yaml: str) -> Path:
    pdir = root / ".batho" / "plugins"
    pdir.mkdir(parents=True, exist_ok=True)
    plugin = pdir / "p.yaml"
    plugin.write_text(
        "schema_version: bsg-plugin.v2\n"
        "plugin_id: p\n"
        "name: P\n"
        "version: 1.0.0\n"
        "enabled: true\n"
        "rules:\n" + rules_yaml,
        encoding="utf-8",
    )
    (root / "batho.yaml").write_text(
        "rules:\n  enabled: true\n  auto_load_all_plugins: false\n"
        "  builtin_plugins: []\n  custom_rules_dir: .batho/plugins\n",
        encoding="utf-8",
    )
    return plugin


def _latest_agent_ents(root: Path):
    from batho.modules.storage.arrow_bundle.bundle import BathoBundle as BB

    db = BB(root)
    rid = db.get_latest_run_id()
    arts = db.get_file_artifacts(
        db.get_run_internal_id(rid), include_storage=False
    )
    return [
        e for a in arts for e in (a["graph"].get("entities") or [])
    ]


def _latest_rels(root: Path):
    from batho.modules.storage.arrow_bundle.bundle import BathoBundle as BB

    db = BB(root)
    rid = db.get_latest_run_id()
    arts = db.get_file_artifacts(
        db.get_run_internal_id(rid), include_storage=False
    )
    return [
        r for a in arts for r in (a["graph"].get("relationships") or [])
    ]


class TestPluginsApplyPhase2:
    def test_subtractive_reapply_removes_stale_rule_outputs(self, tmp_path):
        """ENR-04: after a rule stops stamping `bsg.noise` / minting a
        TESTED_BY edge, the next apply must remove them from the artifact —
        additive-only semantics would leave them forever."""
        from batho.core.config.loader import reload_config
        from batho.orchestrator.plugins_apply import (
            PluginsApplyOptions, run_plugins_apply,
        )

        # `helper` stays unquarantined so the edge_hints path has a live
        # target — RUL-04 suppresses hints to/from quarantined entities.
        _seed_two_entities(tmp_path, extra_names=("helper",))
        _write_plugin_body(
            tmp_path,
            """  - rule_id: stamp-noise
    name: stamp-noise
    severity: info
    matchers:
      name_patterns: ["foo*"]
    actions:
      metadata:
        bsg.noise: true
  - rule_id: tested-by-hint
    name: tested-by-hint
    severity: info
    matchers:
      name_patterns: ["test_*"]
    actions:
      metadata:
        bsg.edge_hints:
          - type: REFERS_TO
            target_name_pattern: "helper"
""",
        )
        reload_config()
        r1 = run_plugins_apply(PluginsApplyOptions(root=tmp_path))
        assert r1.success, r1.message
        ents = _latest_agent_ents(tmp_path)
        assert any(
            (e.get("metadata") or {}).get("bsg.noise") is True for e in ents
        )
        assert any(
            r.get("type") == "REFERS_TO" for r in _latest_rels(tmp_path)
        )

        # v2: both rules gone — a different plugin writes only bsg.quarantined.
        _write_plugin_body(
            tmp_path,
            """  - rule_id: quarantine-v2
    name: quarantine-v2
    severity: warning
    matchers:
      name_patterns: ["*"]
    actions:
      metadata:
        bsg.quarantined: true
""",
        )
        r2 = run_plugins_apply(PluginsApplyOptions(root=tmp_path))
        assert r2.success, r2.message
        assert r2.files_rewritten >= 1, (
            "stale rule outputs were stripped but never written back"
        )
        ents = _latest_agent_ents(tmp_path)
        for e in ents:
            meta = e.get("metadata") or {}
            assert "bsg.noise" not in meta, f"stale key persisted: {meta}"
            assert "bsg.edge_hints" not in meta
            assert meta.get("bsg.quarantined") is True
        assert not any(
            r.get("type") == "REFERS_TO" for r in _latest_rels(tmp_path)
        ), "stale tag_postpass edge survived rule removal"
        reload_config()

    def test_name_or_type_change_marks_file_dirty(self, tmp_path, monkeypatch):
        """ENR-03: delta detection compares (name, type, metadata) — a rule
        action mutating the entity name must rewrite the file even with no
        metadata change."""
        from batho.core.config.loader import reload_config
        from batho.orchestrator import plugins_apply as pa
        from batho_plugin import rule_engine as rules_mod

        _seed_artifact(tmp_path)
        _write_plugin(tmp_path)
        reload_config()

        real_apply = rules_mod.apply_rule_plugins

        def _renaming_apply(graph, root_path, rules_config, **kw):
            stats = real_apply(graph, root_path, rules_config, **kw)
            for eid, ent in graph.entities.items():
                if ent.name == "foo":
                    graph.update_entity(
                        eid, ent._evolve(name="foo_renamed")
                    )
            return stats

        monkeypatch.setattr(rules_mod, "apply_rule_plugins", _renaming_apply)
        result = pa.run_plugins_apply(pa.PluginsApplyOptions(root=tmp_path))
        assert result.success, result.message
        assert result.files_rewritten >= 1, (
            "entity name change did not mark the file dirty"
        )
        reload_config()

    def test_unpersisted_metadata_matcher_warns(self, tmp_path):
        """ENR-05: a rule matching on a metadata key outside the persisted
        projection must surface a warning rather than silently miss."""
        from batho.core.config.loader import reload_config
        from batho.orchestrator.plugins_apply import (
            PluginsApplyOptions, run_plugins_apply,
        )

        _seed_artifact(tmp_path)
        _write_plugin_body(
            tmp_path,
            """  - rule_id: meta-match
    name: meta-match
    severity: info
    matchers:
      regex_patterns:
        - target: metadata
          metadata_key: unpersisted_field
          pattern: "."
    actions:
      metadata:
        bsg.hit: true
""",
        )
        reload_config()
        result = run_plugins_apply(PluginsApplyOptions(root=tmp_path))
        assert result.success, result.message
        assert result.warnings, "no metadata-projection warning surfaced"
        assert "unpersisted_field" in result.warnings[0]
        reload_config()

    def test_persisted_metadata_matcher_no_warning(self, tmp_path):
        """ENR-05: `docstring` is in the persisted allowlist — no warning."""
        from batho.core.config.loader import reload_config
        from batho.orchestrator.plugins_apply import (
            PluginsApplyOptions, run_plugins_apply,
        )

        _seed_artifact(tmp_path)
        _write_plugin_body(
            tmp_path,
            """  - rule_id: doc-match
    name: doc-match
    severity: info
    matchers:
      metadata_conditions:
        - key: docstring
          operator: exists
    actions:
      metadata:
        bsg.hit: true
""",
        )
        reload_config()
        result = run_plugins_apply(PluginsApplyOptions(root=tmp_path))
        assert result.success, result.message
        assert not result.warnings
        reload_config()


def test_strip_preserves_hook_owned_and_engine_keys():
    """T21: _strip_rule_owned_state removes rule-owned bsg.* stamps but keeps
    the E2 hook keys (access_type, rationale_kind, marker_comment,
    line_scan_fallback — never bsg-prefixed), the hook-stamped bsg.language,
    and the bsg.index_id run nonce."""
    from batho.core.schemas import Entity, EntityType
    from batho.modules.graph.builder.codegraph import InMemoryGraph
    from batho.orchestrator.plugins_apply import _strip_rule_owned_state

    ent = Entity(
        type=EntityType.FUNCTION,
        name="f", file="src/a.py", start_line=1, end_line=2,
        start_byte=0, end_byte=5, signature="def f()",
        metadata={
            "access_type": "read",          # E2 hook key — survives
            "rationale_kind": "marker",     # E2 hook key — survives
            "marker_comment": "NOTE",       # E2 hook key — survives
            "line_scan_fallback": True,     # E2 hook key — survives
            "language": "python",           # engine key — survives
            "bsg.language": "Python",       # hook-stamped (T10) — survives
            "bsg.index_id": "idx-1",        # run nonce — survives
            "bsg.category": "SOURCE",       # rule-owned — stripped
            "bsg.scope_tier": "module",     # rule-owned — stripped
            "bsg.rules": ["category-source-extension"],  # stripped
        },
        id_override="src/a.py::f",
    )
    graph = InMemoryGraph(entities={ent.id: ent}, relationships=[])
    _strip_rule_owned_state(graph)
    meta = graph.entities[ent.id].metadata
    for k in ("access_type", "rationale_kind", "marker_comment",
              "line_scan_fallback", "language", "bsg.language", "bsg.index_id"):
        assert k in meta, f"{k} should survive the strip"
    for k in ("bsg.category", "bsg.scope_tier", "bsg.rules"):
        assert k not in meta, f"{k} should be stripped"
