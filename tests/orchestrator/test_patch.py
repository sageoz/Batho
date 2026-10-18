"""Integration and edge case tests for Batho's patch orchestrator.

This module validates that the patch pipeline:
1. Rejects execution and yields warning results if another process holds the lock.
2. Prevents concurrent patch runs on the same repository.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from batho.orchestrator.build import run_build, BuildOptions
from batho.orchestrator.patch import run_patch, PatchOptions
from batho.utils.file_io import InterProcessLock


def test_patch_lock_contention(tmp_path: Path):
    """Verify that concurrent patch runs fail immediately and gracefully with a lock conflict error.

    Scenario:
        The repository is initialized with a build. A process acquires and holds the repository's `.batho/batho.lock` file.
        While the lock is held, we trigger `run_patch`.
        The patch operation must fail gracefully immediately without corrupting the active on-disk indexes.

    Execution Flow:
        1. Initialize repo with a small python file.
        2. Run a full build to create the initial Batho bundle.
        3. Identify the lock file path: `.batho/batho.lock`.
        4. Acquire the lock via `InterProcessLock`.
        5. Within the lock context, make a modification to the file and execute `run_patch`.
        6. Assert that the patch result success is False.
        7. Verify that warnings about "already running" or "lock" are present in the patch result.

    Expectations:
        - Patch operations respect exclusive process-wide locking.
        - Failures are clean and prevent concurrent write contamination.
    """
    # First, run a build to create the initial bundle
    (tmp_path / "main.py").write_text("def hello(): pass")
    res = run_build(BuildOptions(root=tmp_path, force_full=True))
    assert res.success
    
    # Acquire the inter-process lock on the repository lock file path
    lock_file = tmp_path / ".batho" / "batho.lock"
    
    with InterProcessLock(lock_file):
        # With the lock held, try to run a patch
        (tmp_path / "main.py").write_text("def hello(): pass\n# modified")
        
        patch_res = run_patch(PatchOptions(root=tmp_path, verbose=False))
        assert patch_res.success is False
        assert any("already running" in w.lower() or "lock" in w.lower() for w in patch_res.warnings)


def test_patch_delete_only_no_crash(tmp_path: Path):
    """Verify that a patch run with only file deletions does not crash with NameError.

    Scenario:
        A repo is built with two files. One file is deleted, leaving no added/modified
        files — only a deletion. The patch must handle this gracefully without
        referencing an undefined `indexer` variable.

    Execution Flow:
        1. Create a repo with two Python files.
        2. Run a full build to create the initial Batho bundle.
        3. Delete one file (leaving the other unchanged).
        4. Run `run_patch` — must succeed without NameError.
        5. Delete the remaining file.
        6. Run `run_patch` again — must still succeed.

    Expectations:
        - Delete-only patch runs return PatchResult(success=True).
        - No NameError or AttributeError is raised.
    """
    (tmp_path / "main.py").write_text("def hello(): pass")
    (tmp_path / "utils.py").write_text("def helper(): pass")
    res = run_build(BuildOptions(root=tmp_path, force_full=True))
    assert res.success

    # Delete one file — patch should handle delete-only gracefully
    (tmp_path / "utils.py").unlink()
    patch_res = run_patch(PatchOptions(root=tmp_path, verbose=False))
    assert patch_res.success

    # Delete the remaining file — still delete-only
    (tmp_path / "main.py").unlink()
    patch_res = run_patch(PatchOptions(root=tmp_path, verbose=False))
    assert patch_res.success


def _w(root: Path, rel: str, content: str) -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def _community_rows(root: Path) -> list[dict]:
    from batho.modules.storage.arrow_bundle.bundle import resolve_bundle_dir
    from batho.modules.storage.arrow_bundle.writer import read_ipc_table

    p = resolve_bundle_dir(root) / "communities.ipc"
    return read_ipc_table(p).to_pylist() if p.exists() else []


def _write_quarantine_plugin(root: Path) -> None:
    pdir = root / ".batho" / "plugins"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "q.yaml").write_text(
        """schema_version: bsg-plugin.v2
plugin_id: q_p
name: Q P
version: 1.0.0
enabled: true
rules:
  - rule_id: quarantine-gc
    name: quarantine-gc
    severity: warning
    matchers:
      name_patterns: ["gc"]
    actions:
      metadata:
        bsg.quarantined: true
  - rule_id: tag-domain
    name: tag-domain
    severity: info
    matchers:
      name_patterns: ["f*"]
    actions:
      metadata:
        bsg.domain: authz
""",
        encoding="utf-8",
    )
    (root / "batho.yaml").write_text(
        "rules:\n  enabled: true\n  auto_load_all_plugins: false\n"
        "  builtin_plugins: []\n  custom_rules_dir: .batho/plugins\n"
        "community_detection:\n  enabled: true\n  domain_grouping: true\n",
        encoding="utf-8",
    )


def test_patch_community_rebuild_respects_persisted_metadata(tmp_path: Path):
    """COM-02: the patch-path rebuild used to construct entities with no
    `.metadata` — quarantine flags and domain tags persisted in agent_views
    silently degraded. `gc` is quarantined pre-patch; it must not appear in
    any rebuilt community, and bsg.domain must drive an L0 domain row."""
    from batho.core.config.loader import reload_config
    from batho.orchestrator.plugins_apply import (
        PluginsApplyOptions, run_plugins_apply,
    )

    _w(tmp_path, "a.py", "def fa():\n    return 1\n")
    _w(tmp_path, "b.py", "import a\n\ndef fb():\n    return a.fa()\n")
    _w(tmp_path, "c.py", "import a\n\ndef gc():\n    return a.fa()\n")
    res = run_build(BuildOptions(root=tmp_path, force_full=True))
    assert res.success, res.warnings

    _write_quarantine_plugin(tmp_path)
    reload_config()
    r = run_plugins_apply(PluginsApplyOptions(root=tmp_path))
    assert r.success, r.message

    _w(tmp_path, "d.py", "def fd():\n    return 4\n")
    pres = run_patch(PatchOptions(root=tmp_path, verbose=False))
    assert pres.success, pres.warnings

    rows = _community_rows(tmp_path)
    members = {eid for row in rows for eid in (row.get("member_entity_ids") or [])}
    assert members, "community rebuild produced no rows"
    assert not any(eid.endswith("::gc") for eid in members), (
        f"quarantined entity survived the patch rebuild: {members}"
    )
    assert any(
        (row.get("level") or 0) == 0 and row.get("name") == "authz"
        for row in rows
    ), f"bsg.domain L0 group missing post-patch: {[r.get('name') for r in rows]}"
    reload_config()


def test_patch_preserves_llm_community_labels(tmp_path: Path, monkeypatch):
    """ORC-02: rebuild serializes fresh Community rows with empty llm_* —
    carry_forward_labels must re-stamp labels whose card input is unchanged
    (keyed on card_input_hash, not detection-order community_id)."""
    from batho.modules.graph.community_labels import llm_label_communities
    from batho.modules.storage.arrow_bundle.bundle import (
        BathoBundle, resolve_bundle_dir,
    )
    from batho.modules.storage.arrow_bundle.schemas import COMMUNITIES_SCHEMA
    from batho.modules.storage.arrow_bundle.writer import write_simple_ipc
    from batho.mcp.community_summaries import load_communities
    from batho.orchestrator.plugins_apply import _load_graph_from_artifact

    _w(tmp_path, "a.py", "def alpha_fn():\n    return 1\n")
    _w(tmp_path, "b.py", "import a\n\ndef beta_fn():\n    return a.alpha_fn()\n")
    # raise the card budget so long tmp paths + bsg metadata don't trim
    # top_entities (digest must match the patch-side carry-forward)
    (tmp_path / "batho.yaml").write_text(
        "community_detection:\n  enabled: true\n"
        "  llm:\n    enabled: true\n    max_card_tokens: 4000\n",
        encoding="utf-8",
    )
    res = run_build(BuildOptions(root=tmp_path, force_full=True))
    assert res.success, res.warnings

    monkeypatch.setenv("BATHO_LLM_API_KEY", "k")
    db = BathoBundle(tmp_path)
    rows = load_communities(db._artifact_dir)
    assert rows, "build wrote no communities"
    run_uuid = db.get_latest_run_id()
    graph, _v, _t, _m = _load_graph_from_artifact(
        db, db.get_run_internal_id(run_uuid), tmp_path
    )

    def fake_labeler(card):
        # label tokens must be >=3 chars to survive _card_terms — use the
        # first name segment (alpha_fn -> "alpha")
        name = ((card.get("top_entities") or [{}])[0].get("name") or "x")
        name = name.split("_")[0]
        return {"label": name, "description": "d", "key_terms": [name]}

    stats = llm_label_communities(
        rows, graph,
        {"enabled": True, "provider": "mock", "model": "m1",
         "max_card_tokens": 4000},
        labeler=fake_labeler,
    )
    assert stats["labeled"] >= 1, f"labeling produced nothing: {stats}"
    comm_path = resolve_bundle_dir(tmp_path) / "communities.ipc"
    write_simple_ipc(rows, COMMUNITIES_SCHEMA, comm_path)

    # patch: new unrelated file in a subdirectory — its entities cannot
    # file/dir-attach into the root community, so the labeled community's
    # card input is unchanged → label must survive the rebuild's fresh rows.
    _w(tmp_path, "sub/d.py", "def delta_fn():\n    return 4\n")

    pres = run_patch(PatchOptions(root=tmp_path, verbose=False))
    assert pres.success, pres.warnings

    post = _community_rows(tmp_path)
    assert any(
        r.get("llm_label") and r.get("label_source") == "llm" for r in post
    ), f"llm labels wiped by patch rebuild: {post}"


def test_reset_caches_before_graph_build(tmp_path: Path, monkeypatch):
    """ORC-04: package_roots.reset_caches must fire at run_patch top level —
    unconditionally, before the batch graph build consumes the caches."""
    import batho.modules.extraction.package_roots as pr
    from batho.modules.graph.builder.codegraph import CodeGraphIndexer

    (tmp_path / "main.py").write_text("def hello(): pass")
    res = run_build(BuildOptions(root=tmp_path, force_full=True))
    assert res.success
    (tmp_path / "main.py").write_text("def hello(): return 1\n")

    order: list[str] = []
    real_reset = pr.reset_caches
    real_build = CodeGraphIndexer.build_graph
    monkeypatch.setattr(
        pr, "reset_caches",
        lambda *a, **k: order.append("reset") or real_reset(*a, **k),
    )
    monkeypatch.setattr(
        CodeGraphIndexer, "build_graph",
        lambda *a, **k: order.append("build_graph") or real_build(*a, **k),
    )

    pres = run_patch(PatchOptions(root=tmp_path, verbose=False))
    assert pres.success
    assert "reset" in order and "build_graph" in order
    assert order.index("reset") < order.index("build_graph")


def _run_telemetry(root: Path) -> dict:
    """Latest run's telemetry_metrics dict (None-safe)."""
    from batho.modules.storage.arrow_bundle import get_bundle

    db = get_bundle(root)
    rid = db.get_latest_run_id()
    iid = db.get_run_internal_id(rid)
    arts = db.get_run_artifacts(iid) or {}
    return arts.get("telemetry_metrics") or {}


def test_patch_persists_plugin_fingerprint(tmp_path: Path):
    """T23: a patch run records plugin provenance in run_artifacts telemetry."""
    (tmp_path / "main.py").write_text("def hello(): pass")
    assert run_build(BuildOptions(root=tmp_path, force_full=True)).success
    (tmp_path / "main.py").write_text("def hello(): return 1\n")
    assert run_patch(PatchOptions(root=tmp_path)).success
    tm = _run_telemetry(tmp_path)
    fp = tm.get("plugin_fingerprint")
    assert fp is not None and len(fp) == 64
    assert tm.get("plugin_fingerprint_drift") is False
    assert tm.get("metadata_schema") == "batho-meta.v2"


def test_patch_plugin_fingerprint_drift(tmp_path: Path, monkeypatch):
    """T23: a changed plugin fingerprint is reported as drift in the patch
    summary (warnings + telemetry flag)."""
    (tmp_path / "main.py").write_text("def hello(): pass")
    assert run_build(BuildOptions(root=tmp_path, force_full=True)).success
    base_fp = _run_telemetry(tmp_path).get("plugin_fingerprint")
    assert base_fp  # build recorded a fingerprint

    # Simulate a plugin-set change (e.g., pack version bump) by pinning the
    # fingerprint the patch computes.
    import batho_plugin.fingerprint as fp_mod

    monkeypatch.setattr(
        fp_mod, "fingerprint_from_host", lambda h: "d" * 64
    )
    (tmp_path / "main.py").write_text("def hello(): return 2\n")
    res = run_patch(PatchOptions(root=tmp_path))
    assert res.success
    assert any("plugin_fingerprint_drift" in w for w in res.warnings), (
        res.warnings
    )
    tm = _run_telemetry(tmp_path)
    assert tm.get("plugin_fingerprint_drift") is True
    assert tm.get("plugin_fingerprint") == "d" * 64


def test_patch_no_plugins_records_no_fingerprint(tmp_path: Path):
    """--no-plugins patch: no normal fingerprint in telemetry."""
    (tmp_path / "main.py").write_text("def hello(): pass")
    assert run_build(BuildOptions(root=tmp_path, force_full=True)).success
    (tmp_path / "main.py").write_text("def hello(): return 3\n")
    res = run_patch(PatchOptions(root=tmp_path, no_plugins=True))
    assert res.success
    tm = _run_telemetry(tmp_path)
    assert tm.get("plugin_fingerprint") is None


def _tracked_on_disk(root: Path) -> int:
    """Tracked paths that exist on disk (excludes synthetic rows like
    ``__external_symbols__``)."""
    from batho.modules.storage.arrow_bundle import get_bundle

    return sum(
        1
        for p in get_bundle(root).get_all_file_tracking()
        if (root / p).is_file()
    )


def _pin_fingerprint(monkeypatch, value: str = "d" * 64) -> None:
    """Force ``fingerprint_from_host`` to return *value* on the patch run."""
    import batho_plugin.fingerprint as fp_mod

    monkeypatch.setattr(fp_mod, "fingerprint_from_host", lambda h: value)


def test_patch_drift_escalates_to_full_reextract(tmp_path: Path, monkeypatch):
    """Drift + zero file changes: the change set escalates to every tracked
    file — a run is produced instead of the "No changes detected" return."""
    (tmp_path / "a.py").write_text("def fa():\n    return 1\n")
    (tmp_path / "b.py").write_text("def fb():\n    return 2\n")
    assert run_build(BuildOptions(root=tmp_path, force_full=True)).success
    expected = _tracked_on_disk(tmp_path)

    _pin_fingerprint(monkeypatch)
    res = run_patch(PatchOptions(root=tmp_path, verbose=False))

    assert res.success, res.warnings
    assert res.run_id
    assert res.changes_applied == expected
    assert res.modified == expected
    assert res.added == 0 and res.deleted == 0
    assert any("plugin_fingerprint_drift" in w for w in res.warnings)
    assert any("full re-extraction" in w for w in res.warnings)
    tm = _run_telemetry(tmp_path)
    assert tm.get("plugin_fingerprint_drift") is True
    assert tm.get("plugin_fingerprint") == "d" * 64


def test_patch_drift_reextract_stamps_unchanged_entities(tmp_path: Path, monkeypatch):
    """A rule plugin added post-build stamps entities of *unchanged* files
    after drift escalation — proof every tracked file was re-extracted under
    the current plugin/rule set rather than skipped."""
    from batho.core.config.loader import reload_config
    from batho.modules.storage.arrow_bundle import get_bundle

    (tmp_path / "a.py").write_text("def fa():\n    return 1\n")
    (tmp_path / "b.py").write_text("def fb():\n    return 2\n")
    assert run_build(BuildOptions(root=tmp_path, force_full=True)).success

    pdir = tmp_path / ".batho" / "plugins"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "drift_stamp.yaml").write_text(
        """schema_version: bsg-plugin.v2
plugin_id: drift_stamp
name: Drift Stamp
version: 1.0.0
enabled: true
rules:
  - rule_id: drift-stamp
    name: drift-stamp
    severity: info
    matchers:
      name_patterns: ["f*"]
    actions:
      metadata:
        bsg.domain: drifted
""",
        encoding="utf-8",
    )
    (tmp_path / "batho.yaml").write_text(
        "rules:\n  enabled: true\n  auto_load_all_plugins: false\n"
        "  builtin_plugins: []\n  custom_rules_dir: .batho/plugins\n",
        encoding="utf-8",
    )
    reload_config()

    _pin_fingerprint(monkeypatch)
    res = run_patch(PatchOptions(root=tmp_path, verbose=False))
    assert res.success, res.warnings

    db = get_bundle(tmp_path)
    arts = db.get_file_artifacts(db.get_run_internal_id(res.run_id))
    metas = [
        (e.get("metadata") or {})
        for a in arts
        if a.get("file_path") == "a.py"
        for e in (a.get("graph") or {}).get("entities") or []
    ]
    assert any(m.get("bsg.domain") == "drifted" for m in metas), metas
    reload_config()


def test_patch_drift_reextract_disabled_warn_only(tmp_path: Path, monkeypatch):
    """plugins.reextract_on_drift: false restores warn-only legacy behavior —
    zero changes still early-returns, warning marks re-extract disabled."""
    (tmp_path / "batho.yaml").write_text(
        "plugins:\n  reextract_on_drift: false\n", encoding="utf-8"
    )
    (tmp_path / "a.py").write_text("def fa():\n    return 1\n")
    assert run_build(BuildOptions(root=tmp_path, force_full=True)).success

    _pin_fingerprint(monkeypatch)
    res = run_patch(PatchOptions(root=tmp_path, verbose=False))

    assert res.success, res.warnings
    assert not res.run_id
    assert res.changes_applied == 0
    assert any("No changes detected" in w for w in res.warnings)
    drift = [w for w in res.warnings if "plugin_fingerprint_drift" in w]
    assert drift and "reextract_on_drift disabled" in drift[0]


def test_patch_drift_preserves_real_change_types(tmp_path: Path, monkeypatch):
    """Drift + real ADDED/DELETED: real change types are preserved and
    synthesized MODIFIEDs union in only for paths absent from the scan."""
    (tmp_path / "a.py").write_text("def fa():\n    return 1\n")
    (tmp_path / "b.py").write_text("def fb():\n    return 2\n")
    (tmp_path / "c.py").write_text("def fc():\n    return 3\n")
    assert run_build(BuildOptions(root=tmp_path, force_full=True)).success

    (tmp_path / "c.py").unlink()
    (tmp_path / "d.py").write_text("def fd():\n    return 4\n")

    _pin_fingerprint(monkeypatch)
    res = run_patch(PatchOptions(root=tmp_path, verbose=False))

    assert res.success, res.warnings
    assert res.added == 1, res.warnings
    assert res.deleted == 1, res.warnings
    assert res.modified == 2, res.warnings
    assert res.changes_applied == 4


def test_patch_drift_does_not_resescalate(tmp_path: Path, monkeypatch):
    """The escalated run records the current fingerprint, so a second patch
    under the same plugin set sees no drift and early-returns."""
    (tmp_path / "a.py").write_text("def fa():\n    return 1\n")
    assert run_build(BuildOptions(root=tmp_path, force_full=True)).success

    _pin_fingerprint(monkeypatch)
    first = run_patch(PatchOptions(root=tmp_path, verbose=False))
    assert first.success and first.changes_applied == 1

    second = run_patch(PatchOptions(root=tmp_path, verbose=False))
    assert second.success, second.warnings
    assert second.changes_applied == 0
    assert any("No changes detected" in w for w in second.warnings)
    assert not any("plugin_fingerprint_drift" in w for w in second.warnings)


def test_patch_drift_skips_tracked_but_missing_paths(tmp_path: Path, monkeypatch):
    """Tracked paths with no on-disk file (``__external_symbols__`` is tracked
    but synthesized, and scan_changes never reports it) must not become
    phantom MODIFIEDs under escalation."""
    from batho.modules.storage.arrow_bundle import get_bundle

    (tmp_path / "a.py").write_text(
        "import definitely_not_a_pkg_zz\n\ndef fa():\n    return 1\n"
    )
    assert run_build(BuildOptions(root=tmp_path, force_full=True)).success
    tracked = get_bundle(tmp_path).get_all_file_tracking()
    assert "__external_symbols__" in tracked, (
        f"fixture produced no external-symbol row: {sorted(tracked)}"
    )

    _pin_fingerprint(monkeypatch)
    res = run_patch(PatchOptions(root=tmp_path, verbose=False))

    assert res.success, res.warnings
    on_disk = sum(1 for p in tracked if (tmp_path / p).is_file())
    assert res.changes_applied == on_disk
    assert res.modified == on_disk


def test_patch_drift_escalates_when_fingerprint_not_in_cache(
    tmp_path: Path, monkeypatch
):
    """plugins.fingerprint_in_cache: false keeps the AST cache variant stable
    across drift — the per-path delete_ast_by_path purge must still force a
    genuine reparse (zero cache hits on the escalated run)."""
    from batho.core.config.loader import reload_config
    from batho.modules.storage.cache.unified_cache import BathoCache

    (tmp_path / "batho.yaml").write_text(
        "plugins:\n  fingerprint_in_cache: false\n"
        "bsg:\n  parallel:\n    enabled: false\n",
        encoding="utf-8",
    )
    (tmp_path / "a.py").write_text("def fa():\n    return 1\n")
    (tmp_path / "b.py").write_text("def fb():\n    return 2\n")
    assert run_build(BuildOptions(root=tmp_path, force_full=True)).success
    expected = _tracked_on_disk(tmp_path)

    hits: list[str] = []
    real_get_ast = BathoCache.get_ast

    def spy(self, file_path, file_hash, variant=None):
        result = real_get_ast(self, file_path, file_hash, variant)
        if result is not None:
            hits.append(file_path)
        return result

    monkeypatch.setattr(BathoCache, "get_ast", spy)
    _pin_fingerprint(monkeypatch)
    res = run_patch(PatchOptions(root=tmp_path, verbose=False))

    assert res.success, res.warnings
    assert res.changes_applied == expected
    assert hits == [], f"escalated run served stale AST cache entries: {hits}"
    reload_config()


def test_patch_leaves_no_tmp_ipc_debris(tmp_path: Path):
    """The patch merge consumes the per-run writer tmps — no ``*.tmp.ipc``
    debris may remain in the artifact dir after a successful patch."""
    from batho.modules.storage.arrow_bundle import resolve_bundle_dir

    (tmp_path / "a.py").write_text("def fa():\n    return 1\n")
    assert run_build(BuildOptions(root=tmp_path, force_full=True)).success
    (tmp_path / "a.py").write_text("def fa():\n    return 2\n")
    res = run_patch(PatchOptions(root=tmp_path, verbose=False))

    assert res.success, res.warnings
    leftovers = list(resolve_bundle_dir(tmp_path).glob("*.tmp.ipc"))
    assert leftovers == [], f"leaked tmp streams: {leftovers}"


def test_patch_drift_synthesizes_added_for_unhashed_tracked_paths(
    tmp_path: Path, monkeypatch
):
    """A tracked on-disk path with no prior content hash is synthesized as
    ADDED, not MODIFIED — PatchResult accounting stays truthful."""
    from batho.modules.storage.arrow_bundle import get_bundle

    (tmp_path / "a.py").write_text("def fa():\n    return 1\n")
    (tmp_path / "b.py").write_text("def fb():\n    return 2\n")
    assert run_build(BuildOptions(root=tmp_path, force_full=True)).success
    expected = _tracked_on_disk(tmp_path)

    db = get_bundle(tmp_path)
    real_hashes = db.get_all_file_hashes
    monkeypatch.setattr(
        db,
        "get_all_file_hashes",
        lambda: {p: h for p, h in real_hashes().items() if p != "b.py"},
    )
    _pin_fingerprint(monkeypatch)
    res = run_patch(PatchOptions(root=tmp_path, verbose=False))

    assert res.success, res.warnings
    assert res.changes_applied == expected
    assert res.added == 1
    assert res.modified == expected - 1


def test_patch_drift_skips_traversal_and_absolute_tracked_paths(
    tmp_path: Path, monkeypatch
):
    """Tracked paths escaping the repo root (``..`` traversal or absolute)
    must never be synthesized into the change set."""
    from batho.modules.storage.arrow_bundle import get_bundle

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def fa():\n    return 1\n")
    (tmp_path / "outside.py").write_text("def ev():\n    return 9\n")
    assert run_build(BuildOptions(root=repo, force_full=True)).success
    expected = _tracked_on_disk(repo)

    db = get_bundle(repo)
    real_tracking = db.get_all_file_tracking
    calls = {"n": 0}

    def polluted():
        calls["n"] += 1
        rows = real_tracking()
        if calls["n"] > 1:  # keep scan_changes() clean
            rows["../outside.py"] = {"file_id": 999_999}
            rows["/abs/outside.py"] = {"file_id": 999_998}
        return rows

    monkeypatch.setattr(db, "get_all_file_tracking", polluted)
    _pin_fingerprint(monkeypatch)
    res = run_patch(PatchOptions(root=repo, verbose=False))

    assert res.success, res.warnings
    assert res.changes_applied == expected
    assert res.modified == expected
    assert res.added == 0 and res.deleted == 0


def test_patch_drift_tracking_read_failure_reports_honestly(
    tmp_path: Path, monkeypatch
):
    """If the tracking table cannot be read, drift cannot escalate — the
    warning must say so instead of claiming a full re-extraction."""
    from batho.modules.storage.arrow_bundle import get_bundle

    (tmp_path / "a.py").write_text("def fa():\n    return 1\n")
    assert run_build(BuildOptions(root=tmp_path, force_full=True)).success

    db = get_bundle(tmp_path)
    real_tracking = db.get_all_file_tracking
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:  # scan_changes() gets real data
            return real_tracking()
        raise RuntimeError("simulated tracking read failure")

    monkeypatch.setattr(db, "get_all_file_tracking", flaky)
    _pin_fingerprint(monkeypatch)
    res = run_patch(PatchOptions(root=tmp_path, verbose=False))

    assert res.success, res.warnings
    assert res.changes_applied == 0
    assert not res.run_id
    drift = [w for w in res.warnings if "plugin_fingerprint_drift" in w]
    assert drift and "tracked-file list unavailable" in drift[0]
    assert not any("full re-extraction" in w for w in res.warnings)


def test_patch_drift_respects_ignore_spec_on_synthesized_paths(
    tmp_path: Path, monkeypatch
):
    """A tracked file that is now ignored (new .gitignore rule) is reported
    DELETED by the scan — drift escalation must not resurrect it."""
    (tmp_path / "a.py").write_text("def fa():\n    return 1\n")
    (tmp_path / "b.py").write_text("def fb():\n    return 2\n")
    assert run_build(BuildOptions(root=tmp_path, force_full=True)).success
    expected = _tracked_on_disk(tmp_path)

    (tmp_path / ".gitignore").write_text("b.py\n")

    _pin_fingerprint(monkeypatch)
    res = run_patch(PatchOptions(root=tmp_path, verbose=False))

    assert res.success, res.warnings
    assert res.deleted == 1
    assert res.modified == expected - 1
    assert res.added == 0
    assert res.changes_applied == expected


def test_patch_deleted_file_changelog_keeps_file_path(tmp_path: Path):
    """Deleted files must record `removed` changelog rows carrying file_path —
    the row outlives the file_tracking entry, so history stays queryable and
    reunites if the path is recreated (new file_id, same path)."""
    from batho.modules.storage.arrow_bundle import get_bundle

    (tmp_path / "a.py").write_text("def fa():\n    return 1\n")
    (tmp_path / "b.py").write_text("def fb():\n    return 2\n")
    assert run_build(BuildOptions(root=tmp_path, force_full=True)).success

    (tmp_path / "b.py").unlink()
    res = run_patch(PatchOptions(root=tmp_path, verbose=False))
    assert res.success and res.deleted == 1, res.warnings

    db = get_bundle(tmp_path)
    hist = db.get_file_changelog_raw("b.py")
    assert hist, "no changelog rows recorded for deleted file"
    assert all(r["file_path"] == "b.py" for r in hist)
    assert {r["change_kind"] for r in hist} == {"removed"}

    # Recreate the path — history must unify under the same file_path
    # even though the recreated file gets a different file_id.
    (tmp_path / "b.py").write_text("def fb2():\n    return 7\n")
    res2 = run_patch(PatchOptions(root=tmp_path, verbose=False))
    assert res2.success and res2.added == 1, res2.warnings

    hist2 = db.get_file_changelog_raw("b.py")
    kinds = {r["change_kind"] for r in hist2}
    assert "removed" in kinds and "added" in kinds
    assert len(hist2) > len(hist)
