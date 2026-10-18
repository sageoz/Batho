"""End-to-end test for the batho-calibrate pipeline (T13).

Fixture repo (tests/fixtures/enrich_repo — planted dist/ noise, a WHY:
rationale comment, a test_<name> convention pair) is copied to tmp_path and
processed through the real pipeline:

    batho_build → profile.py gap report → validate.py fixture gate on the
    golden plugin → `batho plugins apply` → verify agent-view metadata,
    quarantine flag, rationale + T04 TESTED_BY edges, telemetry → score.py.

Also exercises the bad-plugin negative path for `plugins validate`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from batho.core.schemas import entity_is_quarantined
from batho_plugin.rule_engine import validate_plugin_file
from batho.modules.enrich import (
    build_gap_report,
    build_score_report,
    fixture_gate,
)
from batho.modules.storage.arrow_bundle.bundle import BathoBundle

_FIXTURE_REPO = Path(__file__).resolve().parents[1] / "fixtures" / "enrich_repo"
_FIXTURE_PLUGINS = Path(__file__).resolve().parents[1] / "fixtures" / "plugins"


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    dest = tmp_path / "enrich_repo"
    shutil.copytree(_FIXTURE_REPO, dest)
    return dest


async def _build(repo: Path, tmp_path: Path) -> None:
    from batho.mcp.registry import RepoRegistry
    from batho.mcp.server import create_app

    registry = RepoRegistry(config_path=tmp_path / "mcp-repos.json")
    registry.add("enrich_repo", str(repo))
    app = create_app(registry_path=registry.config_path, disabled_tools=set())
    res = await app.call_tool("batho_build", {"repo": "enrich_repo"})
    assert not res.is_error
    assert res.structured_content["success"] is True


def _write_generated_plugin(repo: Path) -> Path:
    # batho.yaml ships with the fixture (indexer.ignore_defaults=false so the
    # planted dist/ noise is actually indexed + rules.custom_rules_dir set).
    pdir = repo / ".batho" / "plugins"
    pdir.mkdir(parents=True, exist_ok=True)
    dest = pdir / "enrich_fixture.yaml"
    shutil.copy(_FIXTURE_PLUGINS / "golden_plugin.yaml", dest)
    return dest


def _all_entities_and_rels(repo: Path):
    """Flatten artifacts into (file_path, entity) pairs + rels."""
    db = BathoBundle(repo)
    rid = db.get_latest_run_id()
    rid_int = db.get_run_internal_id(rid)
    artifacts = db.get_file_artifacts(rid_int, include_storage=False)
    entities, rels = [], []
    for art in artifacts:
        fpath = art["file_path"]
        for e in art["graph"]["entities"]:
            e = dict(e)
            e["_file_path"] = fpath  # agent-view dicts don't carry `file`
            entities.append(e)
        rels.extend(art["graph"]["relationships"])
    return entities, rels, db, rid_int


@pytest.mark.asyncio
async def test_enrich_e2e_build_profile_validate_apply_score(repo, tmp_path):
    from batho.core.config.loader import reload_config
    from batho.orchestrator.plugins_apply import (
        PluginsApplyOptions,
        run_plugins_apply,
    )

    await _build(repo, tmp_path)

    # --- gap report on the freshly-built artifact (also auto-persisted as
    # run_artifacts.enrich_profile + .batho/report/overview.md by the build) ---
    db0 = BathoBundle(repo)
    report = build_gap_report(db0, root=repo)
    assert report["schema_version"] == "enrich-profile.v1"
    assert report["totals"]["entities"] > 0
    assert report["noise"]["entities_in_noise_paths"] >= 1  # dist/ planted
    gap_names = {g["gap"] for g in report["gaps"]}
    assert "noise_path_entities_not_quarantined" in gap_names
    # build wrote the report files + enrich columns itself
    assert (repo / ".batho" / "report" / "overview.md").exists()

    # --- write plugin into .batho/plugins (fixture gate requires the plugin
    # path to resolve under the repo root — path-sandboxed) ---
    staged = _write_generated_plugin(repo)

    # --- validation: golden plugin passes schema + fixture gate ---
    stage1 = validate_plugin_file(staged, strict=True)
    assert stage1["valid"], stage1["errors"]
    gate = fixture_gate(staged, repo)
    assert gate["passed"], gate
    by_rule = {r["rule"]: r for r in gate["rules"]}
    assert by_rule["quarantine-dist-noise"]["hits"] >= 1
    assert by_rule["tag-app-services"]["hits"] >= 1

    # --- apply: retro-enrichment via plugin (T08) incl. T04 derivations ---
    reload_config()
    result = run_plugins_apply(PluginsApplyOptions(root=repo))
    assert result.success, result.message
    assert result.entities_updated >= 1

    entities, rels, db, rid_int = _all_entities_and_rels(repo)
    by_id = {e["id"]: e for e in entities}

    # quarantine metadata on planted dist/ noise (indexed via
    # indexer.ignore_defaults=false in the fixture's batho.yaml)
    noise_ents = [e for e in entities if "dist/" in e["_file_path"]]
    assert noise_ents, "fixture dist/ entities missing"
    assert any(
        entity_is_quarantined(e.get("id") or "", e.get("metadata"))
        for e in noise_ents
    )

    # service tag applied to app/ entities (file_path is repo-relative)
    app_ents = [e for e in entities if e["_file_path"].startswith("app/")]
    assert any((e.get("metadata") or {}).get("bsg.service_tag") == "core" for e in app_ents)

    # rationale edge: extractor-promoted WHY: comment → enclosing symbol
    rationale = [r for r in rels if r["type"] == "RATIONALE_FOR"]
    assert rationale, "expected extractor RATIONALE_FOR edge on WHY: comment"
    target_names = {by_id.get(r["target_id"], {}).get("name") for r in rationale}
    assert any("run_service" in str(n) for n in target_names)

    # T04 tag-driven edge: test_run_service → run_service TESTED_BY
    # (method names carry `Class.method_[hash]`; match by substring)
    tested = [
        r for r in rels
        if r["type"] == "TESTED_BY"
        and by_id.get(r["source_id"], {}).get("name") == "test_run_service"
        and "run_service" in str(by_id.get(r["target_id"], {}).get("name"))
    ]
    assert tested, "expected TESTED_BY edge from tag-driven post-pass"
    assert tested[0]["metadata"]["edge_class"] == "annotation"

    # telemetry: apply run wrote a rule_stats row
    run_artifacts = db.get_run_artifacts(rid_int)
    rs = (run_artifacts or {}).get("rule_stats") or {}
    assert rs.get("run_kind") == "plugins_apply"
    assert rs.get("rule_hits", {}).get("quarantine-dist-noise", 0) >= 1

    # --- score: applied rules appear with non-stale verdicts ---
    db2 = BathoBundle(repo)
    sreport = build_score_report(db2, repo)
    scored = {r["rule"]: r for r in sreport["rules"]}
    assert "quarantine-dist-noise" in scored
    assert scored["quarantine-dist-noise"]["verdict"] not in ("stale",)

    reload_config()


@pytest.mark.asyncio
async def test_bad_plugin_fails_validation(repo, tmp_path):
    from batho_plugin.rule_engine import validate_plugin_file

    await _build(repo, tmp_path)
    out = validate_plugin_file(_FIXTURE_PLUGINS / "bad_plugin.yaml", strict=True)
    assert not out["valid"] or out["errors"]
