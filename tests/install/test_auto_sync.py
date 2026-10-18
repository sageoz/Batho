"""Tests for auto_sync_if_needed + the fail-open cmd_mcp hook."""

from __future__ import annotations

import argparse
from pathlib import Path

import batho.install as skills_mod
import batho.install.fetch as fetch_mod
from batho.install import auto_sync_if_needed
from batho.install.receipt import write_receipt


def test_env_opt_out(isolated_home: Path, monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("BATHO_NO_SKILL_SYNC", "1")
    monkeypatch.setattr(skills_mod, "install_pack", lambda **k: calls.append(k))
    assert auto_sync_if_needed() is False
    assert calls == []


def test_config_opt_out(isolated_home: Path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(skills_mod, "install_pack", lambda **k: calls.append(k))
    assert auto_sync_if_needed(root_cfg={"skills": {"auto_install": False}}) is False
    assert calls == []


def test_missing_receipt_triggers_install(isolated_home: Path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(skills_mod, "install_pack", lambda **k: calls.append(k))
    assert auto_sync_if_needed(root_cfg={}) is True
    assert len(calls) == 1


def test_version_drift_triggers_update(isolated_home: Path, monkeypatch) -> None:
    write_receipt("v1.0.0", "global", [])
    calls = []
    monkeypatch.setattr(fetch_mod, "resolve_latest_version", lambda *a, **k: "v2.0.0")
    monkeypatch.setattr(skills_mod, "resolve_latest_version", lambda *a, **k: "v2.0.0")
    monkeypatch.setattr(skills_mod, "install_pack", lambda **k: calls.append(k))
    assert auto_sync_if_needed(root_cfg={}) is True
    assert calls == [{
        "scope": "global", "force": True, "project_root": Path.cwd().resolve()
    }]


def test_current_version_no_sync(isolated_home: Path, monkeypatch) -> None:
    from batho.install.detect import pack_skills

    write_receipt("v2.0.0", "global", [])
    # SKL-05: presence is part of drift — seed the canonical dir with the
    # pack skills so version-only state is the variable under test.
    canonical = isolated_home / ".agents" / "skills"
    for name in pack_skills():
        (canonical / name).mkdir(parents=True)
    calls = []
    monkeypatch.setattr(skills_mod, "resolve_latest_version", lambda *a, **k: "v2.0.0")
    monkeypatch.setattr(skills_mod, "install_pack", lambda **k: calls.append(k))
    assert auto_sync_if_needed(root_cfg={}) is False
    assert calls == []


def test_cmd_mcp_fail_open(tmp_path: Path, monkeypatch) -> None:
    """Sync failure must not prevent the MCP server from starting."""
    import batho.cli.mcp as cli_mcp
    import batho.core.config as config_mod
    import batho.mcp.server as server_mod

    monkeypatch.setattr(config_mod, "get_config_with_root", lambda *a, **k: {})

    def _boom(**k):
        raise RuntimeError("network down")

    monkeypatch.setattr(skills_mod, "auto_sync_if_needed", _boom)

    ran = []
    monkeypatch.setattr(server_mod, "run_server", lambda **k: ran.append(k))

    args = argparse.Namespace(root=str(tmp_path), no_watch=True, enable_tool=[])
    assert cli_mcp.cmd_mcp(args) == 0
    assert len(ran) == 1  # server started despite the sync failure


def test_config_opt_out_survives_model_validation(tmp_path: Path, monkeypatch) -> None:
    """Loader-level regression (CFG-01): a real batho.yaml
    `skills.auto_install: false` must survive Config.model_validate. The
    earlier test passed a hand-built dict straight into root_cfg — the shape
    the loader never produced, masking the silent drop."""
    (tmp_path / "batho.yaml").write_text(
        "skills:\n  auto_install: false\n", encoding="utf-8"
    )
    from batho.core.config import get_config_with_root

    cfg = get_config_with_root(tmp_path)
    assert cfg.get("skills", {}).get("auto_install") is False, (
        f"skills section dropped by validation: {sorted(cfg)}"
    )
    calls = []
    monkeypatch.setattr(skills_mod, "install_pack", lambda **k: calls.append(k))
    assert auto_sync_if_needed(root_cfg=cfg) is False
    assert calls == []


def test_pinned_version_no_drift_no_network(isolated_home, monkeypatch):
    """SKL-02: BATHO_VERSION pin + matching receipt → no sync, and NO
    network call — the latest-tag check must be skipped entirely."""
    from batho.install.detect import pack_skills

    monkeypatch.setenv("BATHO_VERSION", "v1.0.0")
    write_receipt("v1.0.0", "global", [])
    canonical = isolated_home / ".agents" / "skills"
    for name in pack_skills():
        (canonical / name).mkdir(parents=True)
    calls = []
    monkeypatch.setattr(skills_mod, "install_pack", lambda **k: calls.append(k))

    def _no_network(*a, **k):
        raise AssertionError("network call during pinned drift check")

    monkeypatch.setattr(skills_mod, "resolve_latest_version", _no_network)
    assert auto_sync_if_needed(root_cfg={}) is False
    assert calls == []


def test_pinned_version_mismatch_syncs_to_pin(isolated_home, monkeypatch):
    """SKL-02: receipt at a different version than the pin → sync once."""
    monkeypatch.setenv("BATHO_VERSION", "v1.0.0")
    write_receipt("v0.9.0", "global", [])
    calls = []
    monkeypatch.setattr(skills_mod, "install_pack", lambda **k: calls.append(k))
    assert auto_sync_if_needed(root_cfg={}) is True
    assert calls == [{"scope": "global", "force": True,
                     "project_root": Path.cwd().resolve()}]


def test_missing_canonical_skills_count_as_drift(isolated_home, monkeypatch):
    """SKL-05(b): receipt present, version current, but the canonical dir
    lost a pack skill on disk → presence drift → re-sync."""
    write_receipt("v9.9.9", "global", [])
    monkeypatch.setattr(
        skills_mod, "resolve_latest_version", lambda *a, **k: "v9.9.9"
    )
    canonical = isolated_home / ".agents" / "skills"
    canonical.mkdir(parents=True)
    (canonical / "batho").mkdir()  # only 1 of 5 pack skills on disk
    calls = []
    monkeypatch.setattr(skills_mod, "install_pack", lambda **k: calls.append(k))
    assert auto_sync_if_needed(root_cfg={}) is True
    assert calls == [{"scope": "global", "force": True,
                     "project_root": Path.cwd().resolve()}]


def test_full_canonical_no_drift(isolated_home, monkeypatch):
    """Receipt + all pack skills present on disk → no sync."""
    from batho.install.detect import pack_skills

    write_receipt("v9.9.9", "global", [])
    monkeypatch.setattr(
        skills_mod, "resolve_latest_version", lambda *a, **k: "v9.9.9"
    )
    canonical = isolated_home / ".agents" / "skills"
    for name in pack_skills():
        (canonical / name).mkdir(parents=True)
    calls = []
    monkeypatch.setattr(skills_mod, "install_pack", lambda **k: calls.append(k))
    assert auto_sync_if_needed(root_cfg={}) is False
    assert calls == []


def test_version_check_throttled_24h(isolated_home: Path, monkeypatch) -> None:
    """SKL-08: a fresh skills-last-check sidecar skips the upstream HEAD
    request entirely; the resolved tag is reused within the TTL."""
    from batho.install.detect import pack_skills
    from batho.install.receipt import last_check_path, write_last_check

    write_receipt("v2.0.0", "global", [])
    canonical = isolated_home / ".agents" / "skills"
    for name in pack_skills():
        (canonical / name).mkdir(parents=True)

    calls = []
    monkeypatch.setattr(
        skills_mod, "resolve_latest_version",
        lambda *a, **k: calls.append(1) or "v9.9.9",
    )
    monkeypatch.setattr(
        skills_mod, "install_pack", lambda **k: calls.append(k)
    )

    # Seed a fresh check recording the receipt's own version
    write_last_check("v2.0.0")
    assert auto_sync_if_needed(root_cfg={}) is False
    assert calls == []  # no HEAD request, no install


def test_stale_check_reprobes(isolated_home: Path, monkeypatch) -> None:
    """SKL-08: an expired sidecar (>24h) re-probes and rewrites the cache."""
    import json as _json
    from datetime import datetime, timedelta, timezone
    from batho.install.detect import pack_skills
    from batho.install.receipt import last_check_path

    write_receipt("v2.0.0", "global", [])
    canonical = isolated_home / ".agents" / "skills"
    for name in pack_skills():
        (canonical / name).mkdir(parents=True)

    stale = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    last_check_path().write_text(_json.dumps({
        "checked_at": stale, "version": "v1.9.0"}))

    probes = []
    monkeypatch.setattr(
        skills_mod, "resolve_latest_version",
        lambda *a, **k: probes.append(1) or "v2.0.0",
    )
    assert auto_sync_if_needed(root_cfg={}) is False
    assert len(probes) == 1
    # sidecar rewritten with the new probe
    assert _json.loads(last_check_path().read_text())["version"] == "v2.0.0"


def test_project_scope_uses_project_root(
    isolated_home: Path, tmp_path: Path, monkeypatch
) -> None:
    """SKL-10: a project-scope receipt must resolve canonical under the MCP
    --root, not Path.cwd() — so presence checks and re-installs land where
    the pack was originally installed."""
    from batho.install.detect import pack_skills

    proot = tmp_path / "proj"
    proot.mkdir()
    write_receipt("v1.0.0", "project", [])
    # canonical under the project root, partially present
    canonical = proot / ".agents" / "skills"
    (canonical / pack_skills()[0]).mkdir(parents=True)

    calls = []
    monkeypatch.setattr(
        skills_mod, "install_pack", lambda **k: calls.append(k)
    )
    assert auto_sync_if_needed(root_cfg={}, project_root=proot) is True
    assert calls == [{
        "scope": "project", "force": True, "project_root": proot,
    }]
