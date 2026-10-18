"""Tests for batho.install.detect — vendored table + target computation."""

from __future__ import annotations

from pathlib import Path

import pytest

from batho.install.detect import (
    canonical_dir,
    compute_targets,
    load_agent_table,
    pack_skills,
)


def test_vendored_table_loads() -> None:
    table = load_agent_table()
    assert len(table["agents"]) == 22
    assert pack_skills(table) == [
        "batho",
        "batho-setup",
        "batho-specs",
        "batho-execute",
        "batho-review",
        "batho-calibrate",
    ]


def test_canonical_only_when_nothing_detected(
    isolated_home: Path, empty_path: Path, tmp_path: Path
) -> None:
    targets = compute_targets("global", tmp_path)
    assert [t.agent_id for t in targets] == ["canonical"]
    assert targets[0].skills_dir == isolated_home / ".agents" / "skills"


def test_detected_non_native_agent_gets_mirror(
    isolated_home: Path, empty_path: Path, tmp_path: Path
) -> None:
    (isolated_home / ".claude").mkdir()
    targets = compute_targets("global", tmp_path)
    by_id = {t.agent_id: t for t in targets}
    assert "claude-code" in by_id  # reads_agents_dir=false → mirror
    assert by_id["claude-code"].skills_dir == isolated_home / ".claude" / "skills"


def test_detected_native_agent_gets_no_mirror(
    isolated_home: Path, empty_path: Path, tmp_path: Path
) -> None:
    (isolated_home / ".cursor").mkdir()  # reads_agents_dir=true
    ids = [t.agent_id for t in compute_targets("global", tmp_path)]
    assert "cursor" not in ids

    forced = compute_targets("global", tmp_path, agents=["cursor"])
    by_id = {t.agent_id: t for t in forced}
    assert by_id["cursor"].skills_dir == isolated_home / ".cursor" / "skills"


def test_bin_detection(isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    kiro_bin = bindir / "kiro"
    kiro_bin.touch()
    kiro_bin.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    ids = [t.agent_id for t in compute_targets("global", tmp_path)]
    assert "kiro" in ids  # reads_agents_dir=false → mirrored when bin-detected


def test_project_scope_uses_project_dirs(
    isolated_home: Path, empty_path: Path, tmp_path: Path
) -> None:
    (isolated_home / ".claude").mkdir()
    targets = compute_targets("project", tmp_path)
    by_id = {t.agent_id: t for t in targets}
    assert by_id["canonical"].skills_dir == tmp_path / ".agents" / "skills"
    assert by_id["claude-code"].skills_dir == tmp_path / ".claude" / "skills"


def test_all_agents_writes_every_native_dir(
    isolated_home: Path, empty_path: Path, tmp_path: Path
) -> None:
    targets = compute_targets("global", tmp_path, all_agents=True)
    ids = {t.agent_id for t in targets}
    assert "canonical" in ids
    assert "claude-code" in ids and "cursor" in ids
    assert "zed" not in ids  # no native dirs in the table → nothing to write


def test_unknown_agent_raises(
    isolated_home: Path, empty_path: Path, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="unknown agent"):
        compute_targets("global", tmp_path, agents=["not-an-agent"])


def test_install_dir_env_override(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    custom = tmp_path / "custom-skills"
    monkeypatch.setenv("BATHO_INSTALL_DIR", str(custom))
    targets = compute_targets("global", tmp_path)
    assert len(targets) == 1
    assert targets[0].agent_id == "custom"
    assert targets[0].skills_dir == custom
