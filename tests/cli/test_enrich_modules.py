"""
tests/cli/test_enrich_modules.py

Tests for the enrichment runtime (T10/T11/T12), now in `batho.modules.enrich`:
  - build_gap_report over a synthetic artifact (enrich-profile.v1)
  - fixture_gate verdicts (`batho plugins validate` stage 2)
  - build_score_report fitness scoring from persisted rule_stats telemetry
"""

from __future__ import annotations

from pathlib import Path

import pytest

from batho.modules.enrich import (
    build_gap_report,
    build_score_report,
    fixture_gate,
)
from batho.modules.storage.arrow_bundle.bundle import BathoBundle


def _seed_multi_artifact(root: Path, n_files: int = 5, ents_per_file: int = 4) -> BathoBundle:
    """Artifact with N source entities + 1 noise-dir entity + 1 unresolved stub."""
    db = BathoBundle(root)
    internal = db.create_run("r1", root_path=str(root))
    writer = db._writers[internal]
    file_id = 0
    for i in range(n_files):
        file_id += 1
        fp = f"app/f{i}.py"
        db.upsert_file_tracking([{
            "file_path": fp, "content_hash": f"h{i}", "mtime_ns": 1,
            "inode": None, "size": 10, "is_indexed": True, "last_run_id": "r1",
        }])
        agent_ents, storage_ents = [], []
        for j in range(ents_per_file):
            eid = f"{root}/{fp}::func{j}"
            agent_ents.append({
                "id": eid, "name": f"func{j}", "type": "FUNCTION",
                "file": str(root / fp), "start_line": j * 5 + 1,
                "end_line": j * 5 + 4, "signature": f"def func{j}():",
                "is_exported": True, "fqn": f"f{i}.func{j}", "metadata": {},
            })
            storage_ents.append({
                "id": eid, "raw_content": f"def func{j}():\n    pass\n",
                "syntax_glue": {"leading_whitespace": "", "trailing_whitespace": ""},
                "ast_node_type": "function_definition",
                "start_byte": j * 20, "end_byte": j * 20 + 19,
            })
        writer.write_file_artifact(
            file_id, agent={"entities": agent_ents},
            storage={"entities": storage_ents}, rels=[], content_hash=f"h{i}",
        )
    # noise-dir file + unresolved stub
    file_id += 1
    db.upsert_file_tracking([{
        "file_path": "node_modules/pkg/index.js", "content_hash": "hn",
        "mtime_ns": 1, "inode": None, "size": 10, "is_indexed": True,
        "last_run_id": "r1",
    }])
    writer.write_file_artifact(
        file_id,
        agent={"entities": [{
            "id": f"{root}/node_modules/pkg/index.js::dep",
            "name": "dep", "type": "FUNCTION", "file": str(root / "node_modules/pkg/index.js"),
            "start_line": 1, "end_line": 2, "signature": "function dep()",
            "is_exported": True, "fqn": "pkg.dep", "metadata": {},
        }, {
            "id": "unresolved:foo::bar", "name": "bar", "type": "EXTERNAL_SYMBOL",
            "file": "", "start_line": 0, "end_line": 0, "signature": None,
            "is_exported": False, "fqn": "foo.bar",
            "metadata": {"stub_resolution_state": "pending"},
        }]},
        storage={"entities": []}, rels=[], content_hash="hn",
    )
    db.complete_run("r1", entity_count=n_files * ents_per_file + 2, file_count=file_id)
    return db


@pytest.fixture()
def artifact_root(tmp_path):
    root = tmp_path
    _seed_multi_artifact(root)
    return root


class TestProfile:
    def test_report_structure(self, artifact_root):
        db = BathoBundle(artifact_root)
        report = build_gap_report(db, root=artifact_root)
        assert report["schema_version"] == "enrich-profile.v1"
        assert report["totals"]["entities"] == 22
        assert report["totals"]["unresolved_stubs"] == 1
        # dep entity + unresolved stub (stored under the node_modules file)
        assert report["noise"]["entities_in_noise_paths"] == 2
        assert "entity_type_distribution" in report
        assert report["degree"]["inbound_histogram"]["max"] == 0
        gaps = {g["gap"] for g in report["gaps"]}
        assert "noise_path_entities_not_quarantined" in gaps
        assert "unresolved_stub_density" in gaps

    def test_unbuilt_root_clean_error(self, tmp_path):
        db = BathoBundle(tmp_path)
        with pytest.raises(RuntimeError, match="batho build"):
            build_gap_report(db, root=tmp_path)


class TestFixtureGate:
    def _plugin(self, root: Path, rules_yaml: str) -> Path:
        pdir = root / "staging"
        pdir.mkdir(exist_ok=True)
        p = pdir / "cand.yaml"
        p.write_text(
            "schema_version: bsg-plugin.v2\nplugin_id: cand_p\nname: Cand\n"
            "version: 1.0.0\nenabled: true\nrules:\n" + rules_yaml,
            encoding="utf-8",
        )
        return p

    TARGETED_RULE = """  - rule_id: tag-func0-f0
    name: tag-func0-f0
    description: tag only func0 in f0.py — narrow to stay selective
    severity: info
    priority: 10
    enabled: true
    matchers:
      file_patterns: ["**/f0.py"]
      name_patterns: ["func0"]
    actions:
      metadata:
        bsg.domain: demo
"""

    BROAD_RULE = """  - rule_id: tag-all
    name: tag-all
    description: matches everything
    severity: info
    priority: 10
    enabled: true
    matchers:
      name_patterns: ["*"]
    actions:
      metadata:
        bsg.domain: demo
"""

    MISS_RULE = """  - rule_id: tag-none
    name: tag-none
    description: matches nothing
    severity: info
    priority: 10
    enabled: true
    matchers:
      name_patterns: ["zzz_no_such_entity_zzz"]
    actions:
      metadata:
        bsg.domain: demo
"""

    def test_golden_plugin_passes(self, artifact_root):
        plugin = self._plugin(artifact_root, self.TARGETED_RULE)
        out = fixture_gate(plugin, artifact_root, selectivity_pct=10.0)
        assert out["passed"], out
        r = out["rules"][0]
        assert r["hits"] >= 1
        assert r["hit_pct"] < 10.0
        assert r["delta_nonempty"] is True

    def test_zero_hit_fails(self, artifact_root):
        plugin = self._plugin(artifact_root, self.MISS_RULE)
        out = fixture_gate(plugin, artifact_root)
        assert not out["passed"]
        assert "zero hits" in out["rules"][0]["reasons"][0]

    def test_selectivity_breach_fails(self, artifact_root):
        plugin = self._plugin(artifact_root, self.BROAD_RULE)
        out = fixture_gate(plugin, artifact_root, selectivity_pct=10.0)
        assert not out["passed"]
        assert any("selectivity" in rsn for rsn in out["rules"][0]["reasons"])

    def test_deterministic_verdict(self, artifact_root):
        plugin = self._plugin(artifact_root, self.TARGETED_RULE)
        a = fixture_gate(plugin, artifact_root)
        b = fixture_gate(plugin, artifact_root)
        assert a["passed"] == b["passed"]
        assert [r["hits"] for r in a["rules"]] == [r["hits"] for r in b["rules"]]


class TestScore:
    def _emit_telemetry(self, root: Path, run_uuid: str, rule_stats: dict):
        db = BathoBundle(root)
        internal = db.create_run(run_uuid, root_path=str(root))
        db.complete_run(run_uuid, is_patch=True)
        db.finalize_run_artifacts(
            internal, artifacts={"rule_stats": rule_stats}
        )

    def test_score_verdicts(self, artifact_root):
        self._emit_telemetry(artifact_root, "run2", {
            "schema_version": "rule-stats.v1",
            "run_kind": "plugins_apply",
            "rules_fingerprint": "abc",
            "rules_loaded": 2,
            "rules_loaded_names": ["good_rule", "dead_rule", "silent_rule"],
            "entities_updated": 3,
            "rule_hits": {"good_rule": 3},
            "plugin_hits": {"custom_dir:good": 3},
            "rule_perf": {"good_rule": {"match_calls": 10, "total_ns": 500,
                                       "avg_ns": 50}},
            "interception_totals": {},
            "plugin_files": {"custom_dir:good": str(artifact_root / "p.yaml")},
            "per_rule": [
                {"rule": "good_rule", "plugin": "custom_dir:good",
                 "entities_matched": 3, "files_touched": 2},
            ],
        })
        db = BathoBundle(artifact_root)
        report = build_score_report(db, artifact_root, entity_count=22)
        by_rule = {r["rule"]: r for r in report["rules"]}
        # loaded-but-zero-hit rules surface via rules_loaded_names →
        # regenerate/disable verdicts are reachable
        for dead in ("dead_rule", "silent_rule"):
            assert dead in by_rule
            assert by_rule[dead]["verdict"] in ("regenerate", "disable")
            assert by_rule[dead]["total_hits"] == 0
            assert by_rule[dead]["latest_hits"] == 0
        # plugin file missing → stale (good_rule's plugin file doesn't exist)
        assert by_rule["good_rule"]["verdict"] == "stale"
        # entity_count param feeds coverage even before the run's own
        # context_overview row is flushed
        assert by_rule["good_rule"]["coverage_pct"] is not None
        assert by_rule["good_rule"]["avg_ns"] == 50

    def test_score_legacy_payload_zero_carry(self, artifact_root):
        """Legacy payloads (no rules_loaded_names): a rule that hit in an
        earlier run but is absent from the latest rule_hits records 0 —
        latest_hits reflects the latest run, not the last hitting run."""
        self._emit_telemetry(artifact_root, "runA", {
            "schema_version": "rule-stats.v1",
            "rules_loaded": 1,
            "rule_hits": {"once_rule": 7},
            "per_rule": [{"rule": "once_rule", "plugin": "p"}],
        })
        self._emit_telemetry(artifact_root, "runB", {
            "schema_version": "rule-stats.v1",
            "rules_loaded": 1,
            "rule_hits": {},
            "per_rule": [],
        })
        db = BathoBundle(artifact_root)
        report = build_score_report(db, artifact_root)
        by_rule = {r["rule"]: r for r in report["rules"]}
        assert by_rule["once_rule"]["latest_hits"] == 0
        assert by_rule["once_rule"]["trend"] == "falling"
        assert by_rule["once_rule"]["verdict"] == "shadow"

    def test_no_telemetry_returns_none(self, artifact_root):
        db = BathoBundle(artifact_root)
        assert build_score_report(db, artifact_root) is None


class TestAtomicReportWrites:
    def test_mid_write_failure_leaves_no_partial(self, tmp_path, monkeypatch):
        """ENR-01: report writes are tmp+rename — a torn write_text must
        never leave a truncated overview.md at the final path."""
        from batho.modules.enrich import report as report_mod

        real_write = Path.write_text

        def torn(self, content, *a, **k):
            real_write(self, str(content)[:5])
            raise OSError("simulated mid-write crash")

        monkeypatch.setattr(Path, "write_text", torn)
        written = report_mod.write_enrich_reports(tmp_path, profile=None)
        assert written == {}
        report_dir = tmp_path / ".batho" / "report"
        assert not (report_dir / "overview.md").exists()
        assert not (report_dir / "score.md").exists()

    def test_happy_path_writes_final_files(self, tmp_path):
        from batho.modules.enrich import report as report_mod

        written = report_mod.write_enrich_reports(
            tmp_path, profile=None, score=None
        )
        report_dir = tmp_path / ".batho" / "report"
        assert (report_dir / "overview.md").exists()
        assert "overview" in written
        assert not (report_dir / ".overview.md.tmp").exists()


class TestCommunitiesStat:
    def test_communities_read_from_ipc(self, tmp_path):
        """ENR-02: the communities section must come from communities.ipc
        via the manifest path — the previous `reader.get_communities()` call
        was dead code (the method doesn't exist) and always yielded 0."""
        from batho.modules.enrich.gap_report import build_gap_report
        from batho.modules.storage.arrow_bundle.bundle import (
            resolve_bundle_dir,
        )
        from batho.modules.storage.arrow_bundle.schemas import (
            COMMUNITIES_SCHEMA,
        )
        from batho.modules.storage.arrow_bundle.writer import (
            write_simple_ipc,
        )

        _seed_multi_artifact(tmp_path)
        bundle_dir = resolve_bundle_dir(tmp_path)
        bundle_dir.mkdir(parents=True, exist_ok=True)
        comm_path = bundle_dir / "communities.ipc"
        write_simple_ipc(
            [
                {
                    "community_id": 1,
                    "name": "svc-a",
                    "entity_count": 3,
                    "file_count": 1,
                    "is_singleton": False,
                },
                {
                    "community_id": 2,
                    "name": "tiny",
                    "entity_count": 1,
                    "file_count": 1,
                    "is_singleton": True,
                },
            ],
            COMMUNITIES_SCHEMA,
            comm_path,
        )
        db = BathoBundle(tmp_path)
        db.register_simple_file("communities", "communities.ipc")

        db = BathoBundle(tmp_path)
        report = build_gap_report(db, root=tmp_path)
        assert report["communities"]["count"] == 2
        assert report["communities"]["singletons"] == 1


class TestPatchRunTelemetryScope:
    def test_patch_rule_stats_do_not_poison_trends(self, artifact_root):
        """ORC-01: a patch run's delta-scoped rule_stats (run_kind="patch")
        must not enter whole-repo history — pre-fix an empty patch row read
        as "every rule hit 0" → phantom falling trends/regenerate verdicts."""
        db = BathoBundle(artifact_root)
        self_emit = TestScore._emit_telemetry
        self_emit(self, artifact_root, "runA", {
            "schema_version": "rule-stats.v1",
            "run_kind": "plugins_apply",
            "rules_loaded": 1,
            "rules_loaded_names": ["my_rule"],
            "rule_hits": {"my_rule": 5},
            "per_rule": [{"rule": "my_rule", "plugin": "p"}],
        })
        # patch run: changed-file subgraph only, no hits in the delta
        self_emit(self, artifact_root, "runP", {
            "schema_version": "rule-stats.v1",
            "run_kind": "patch",
            "rules_loaded": 1,
            "rules_loaded_names": ["my_rule"],
            "rule_hits": {},
            "per_rule": [],
        })
        db = BathoBundle(artifact_root)
        report = build_score_report(db, artifact_root)
        by_rule = {r["rule"]: r for r in report["rules"]}
        assert by_rule["my_rule"]["latest_hits"] == 5
        assert by_rule["my_rule"]["trend"] != "falling", (
            f"patch delta row poisoned the trend: {by_rule['my_rule']}"
        )


class TestMiscatCount:
    """ENR-08: generated_or_vendor_files_marked_source must report the true
    total, not the sample-capped length."""

    def test_count_is_true_total_not_cap(self, tmp_path):
        db = BathoBundle(tmp_path)
        internal = db.create_run("r1", root_path=str(tmp_path))
        writer = db._writers[internal]
        n_miscat = 12  # > default sample_k=8
        db.upsert_file_tracking([{
            "file_path": "node_modules/pkg/gen.js", "content_hash": "hn",
            "mtime_ns": 1, "inode": None, "size": 10, "is_indexed": True,
            "last_run_id": "r1",
        }])
        agent_ents = [
            {
                "id": f"{tmp_path}/node_modules/pkg/gen.js::e{i}",
                "name": f"e{i}", "type": "FUNCTION",
                "file": str(tmp_path / "node_modules/pkg/gen.js"),
                "start_line": i, "end_line": i + 1,
                "signature": f"function e{i}()", "is_exported": True,
                "fqn": f"pkg.e{i}",
                "metadata": {"bsg.category": "SOURCE"},
            }
            for i in range(n_miscat)
        ]
        writer.write_file_artifact(
            1,
            agent={"entities": agent_ents},
            storage={"entities": []}, rels=[], content_hash="hn",
        )
        db.complete_run("r1", entity_count=n_miscat, file_count=1)

        db2 = BathoBundle(tmp_path)
        report = build_gap_report(db2, root=tmp_path)
        gap = next(
            g for g in report["gaps"]
            if g["gap"] == "generated_or_vendor_files_marked_source"
        )
        assert gap["count"] == n_miscat
        assert len(gap["samples"]) == 8  # samples stay capped


class TestDisableVerdict:
    """ENR-07: disable requires >=3 observed runs of zero hits; fewer runs
    only earn 'regenerate' (insufficient evidence)."""

    def _zero_hit_stats(self):
        return {
            "schema_version": "rule-stats.v1",
            "rules_loaded": 1,
            "rules_loaded_names": ["dead_rule"],
            "rule_hits": {},
            "per_rule": [{"rule": "dead_rule", "plugin": "custom_dir:p"}],
        }

    def test_zero_hits_three_runs_disable(self, artifact_root):
        emit = TestScore._emit_telemetry
        for i in range(3):
            emit(self, artifact_root, f"z{i}", self._zero_hit_stats())
        db = BathoBundle(artifact_root)
        report = build_score_report(db, artifact_root)
        by_rule = {r["rule"]: r for r in report["rules"]}
        assert by_rule["dead_rule"]["verdict"] == "disable"

    def test_zero_hits_few_runs_regenerate(self, artifact_root):
        emit = TestScore._emit_telemetry
        for i in range(2):
            emit(self, artifact_root, f"z{i}", self._zero_hit_stats())
        db = BathoBundle(artifact_root)
        report = build_score_report(db, artifact_root)
        by_rule = {r["rule"]: r for r in report["rules"]}
        assert by_rule["dead_rule"]["verdict"] == "regenerate"
