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
