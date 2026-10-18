"""Tests for batho.install.install + install_pack orchestration."""

from __future__ import annotations

import os
from pathlib import Path

import batho.install as skills_mod
from batho.install import install_pack, pack_status, remove_pack
from batho.install.detect import InstallTarget
from batho.install.install import remove_one, write_pack

PACK = [
    "batho",
    "batho-setup",
    "batho-specs",
    "batho-execute",
    "batho-review",
    "batho-calibrate",
]


def _skills_src(tmp_path: Path) -> Path:
    src = tmp_path / "src" / "skills"
    for name in PACK:
        d = src / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"# {name}\n")
    return src


def test_canonical_copy_and_symlink_mirror(tmp_path: Path) -> None:
    src = _skills_src(tmp_path)
    canonical = tmp_path / "canon"
    mirror = tmp_path / "mirror"
    targets = [
        InstallTarget("canonical", canonical),
        InstallTarget("claude-code", mirror),
    ]
    records = write_pack(src, targets, canonical)

    assert (canonical / "batho" / "SKILL.md").is_file()
    assert (canonical / "batho" / ".batho-skill").is_file()
    if os.name != "nt":
        assert (mirror / "batho").is_symlink()
        assert (mirror / "batho").readlink() == canonical / "batho"
    assert {r.status for r in records} <= {"copied", "linked"}


def test_rerun_is_idempotent(tmp_path: Path) -> None:
    src = _skills_src(tmp_path)
    canonical = tmp_path / "canon"
    mirror = tmp_path / "mirror"
    targets = [
        InstallTarget("canonical", canonical),
        InstallTarget("claude-code", mirror),
    ]
    write_pack(src, targets, canonical)
    second = {r.path.name: r.status for r in write_pack(src, targets, canonical)}
    assert second["batho"] in {"copied", "link(ok)"}


def test_foreign_dir_skipped_unless_force(tmp_path: Path) -> None:
    src = _skills_src(tmp_path)
    canonical = tmp_path / "canon"
    foreign = canonical / "batho"
    foreign.mkdir(parents=True)
    (foreign / "USER.md").write_text("user content")

    records = write_pack(src, [InstallTarget("canonical", canonical)], canonical)
    assert records[0].status == "skipped(not-ours)"
    assert not (foreign / ".batho-skill").exists()  # foreign dirs must not be tagged
    assert (foreign / "USER.md").is_file()  # untouched

    records = write_pack(
        src, [InstallTarget("canonical", canonical)], canonical, force=True
    )
    assert records[0].status == "copied"
    assert not (foreign / "USER.md").exists()


def test_remove_one_marker_guard(tmp_path: Path) -> None:
    src = _skills_src(tmp_path)
    canonical = tmp_path / "canon"
    mirror = tmp_path / "mirror"
    write_pack(
        src,
        [InstallTarget("canonical", canonical), InstallTarget("kiro", mirror)],
        canonical,
    )

    if os.name != "nt":
        assert remove_one(mirror / "batho") == "removed(link)"
    assert remove_one(canonical / "batho") == "removed(copy)"
    assert remove_one(canonical / "batho") == "absent"

    foreign = tmp_path / "foreign" / "batho"
    foreign.mkdir(parents=True)
    assert remove_one(foreign) == "skipped(not-ours)"
    assert foreign.is_dir()


def test_install_pack_end_to_end(
    isolated_home: Path, empty_path: Path, tmp_path: Path, monkeypatch
) -> None:
    (isolated_home / ".claude").mkdir()  # detected non-native agent
    monkeypatch.setattr(skills_mod, "fetch_pack", lambda *a, **k: _skills_src(tmp_path))
    monkeypatch.setattr(skills_mod, "resolve_latest_version", lambda *a, **k: "v3.1.4")

    result = install_pack(project_root=tmp_path)

    canonical = isolated_home / ".agents" / "skills"
    assert (canonical / "batho" / "SKILL.md").is_file()
    if os.name != "nt":
        assert (isolated_home / ".claude" / "skills" / "batho").is_symlink()

    receipt = pack_status()
    assert receipt is not None
    assert receipt["version"] == "v3.1.4"
    assert str(canonical) in receipt["dirs"]
    assert result.receipt_path is not None and result.receipt_path.is_file()


def test_batho_copy_zero_does_not_force_copy(
    isolated_home: Path, empty_path: Path, tmp_path: Path, monkeypatch
) -> None:
    (isolated_home / ".claude").mkdir()
    monkeypatch.setenv("BATHO_COPY", "0")
    monkeypatch.setattr(skills_mod, "fetch_pack", lambda *a, **k: _skills_src(tmp_path))
    install_pack(project_root=tmp_path)
    if os.name != "nt":
        assert (isolated_home / ".claude" / "skills" / "batho").is_symlink()


def test_remove_pack_uses_receipt_dirs(
    isolated_home: Path, empty_path: Path, tmp_path: Path, monkeypatch
) -> None:
    (isolated_home / ".claude").mkdir()
    monkeypatch.setattr(skills_mod, "fetch_pack", lambda *a, **k: _skills_src(tmp_path))
    install_pack(project_root=tmp_path)

    # foreign dir inside a receipt-owned root must survive
    foreign = isolated_home / ".agents" / "skills" / "foreign-skill"
    foreign.mkdir()
    (foreign / "keep.md").write_text("keep")

    records = remove_pack(project_root=tmp_path)
    assert any(r.status.startswith("removed") for r in records)
    assert foreign.is_dir()
    assert pack_status() is None


def test_all_skipped_install_writes_no_receipt(
    isolated_home: Path, empty_path: Path, tmp_path: Path, monkeypatch
) -> None:
    """SKL-05(a): when every record is skipped/missing, the receipt must NOT
    be written — otherwise the install looks successful forever."""
    canonical = isolated_home / ".agents" / "skills"
    for name in PACK:
        foreign = canonical / name
        foreign.mkdir(parents=True)
        (foreign / "USER.md").write_text("user content")
    monkeypatch.setattr(
        skills_mod, "fetch_pack", lambda *a, **k: _skills_src(tmp_path)
    )
    monkeypatch.setattr(
        skills_mod, "resolve_latest_version", lambda *a, **k: "v3.1.4"
    )
    result = install_pack(project_root=tmp_path)
    assert all(r.status == "skipped(not-ours)" for r in result.records)
    assert result.receipt_path is None
    assert pack_status() is None


def test_orphan_skill_dirs_removed_on_update(
    isolated_home: Path, empty_path: Path, tmp_path: Path, monkeypatch
) -> None:
    """SKL-05(c): a marker-bearing copy / canonical-pointing symlink for a
    skill the new pack no longer ships must be removed; foreign orphans and
    external symlinks survive."""
    src = _skills_src(tmp_path)
    canonical = isolated_home / ".agents" / "skills"
    mirror = isolated_home / ".claude" / "skills"
    (isolated_home / ".claude").mkdir()

    monkeypatch.setattr(skills_mod, "fetch_pack", lambda *a, **k: src)
    monkeypatch.setattr(
        skills_mod, "resolve_latest_version", lambda *a, **k: "v3.1.4"
    )
    install_pack(project_root=tmp_path)

    # Simulate leftovers from an older pack generation.
    stale_copy = canonical / "oldskill"
    stale_copy.mkdir()
    (stale_copy / ".batho-skill").touch()
    mirror.mkdir(parents=True, exist_ok=True)
    stale_link = mirror / "oldskill"
    if os.name != "nt":
        stale_link.symlink_to(stale_copy, target_is_directory=True)
    ext_link = mirror / "external-skill"
    outside = tmp_path / "outside" / "external-skill"
    outside.mkdir(parents=True)
    if os.name != "nt":
        ext_link.symlink_to(outside, target_is_directory=True)
    foreign = canonical / "foreign-skill"
    foreign.mkdir()
    (foreign / "keep.md").write_text("keep")

    install_pack(project_root=tmp_path, force=True)

    assert not stale_copy.exists(), "marker-bearing orphan survived"
    assert not stale_link.exists(), "canonical-pointing symlink survived"
    assert foreign.is_dir(), "foreign dir removed"
    if os.name != "nt":
        assert ext_link.is_symlink(), "external symlink removed"
        assert outside.is_dir()


class TestForeignSymlinks:
    """SKL-09: foreign symlinks are never hijacked on install and never
    unlinked on remove — only links resolving into the canonical dir."""

    def test_install_skips_foreign_symlink(self, tmp_path: Path) -> None:
        from batho.install.install import install_one

        src = tmp_path / "src" / "batho"
        src.mkdir(parents=True)
        foreign_target = tmp_path / "elsewhere" / "real"
        foreign_target.mkdir(parents=True)
        dst = tmp_path / "mirror" / "batho"
        dst.parent.mkdir()
        dst.symlink_to(foreign_target, target_is_directory=True)

        assert install_one(src, dst, link_anchor=tmp_path / "canonical") == \
            "skipped(not-ours)"
        assert dst.is_symlink()
        assert dst.readlink() == foreign_target  # untouched

    def test_install_replaces_our_symlink(self, tmp_path: Path) -> None:
        from batho.install.install import install_one

        canonical = tmp_path / "canonical"
        src = canonical / "batho"
        src.mkdir(parents=True)
        dst = tmp_path / "mirror" / "batho"
        dst.parent.mkdir()
        dst.symlink_to(src, target_is_directory=True)

        assert install_one(
            src, dst, link_anchor=canonical
        ) == "link(ok)"

    def test_remove_skips_foreign_symlink(self, tmp_path: Path) -> None:
        foreign_target = tmp_path / "elsewhere" / "real"
        foreign_target.mkdir(parents=True)
        dst = tmp_path / "mirror" / "batho"
        dst.parent.mkdir()
        dst.symlink_to(foreign_target, target_is_directory=True)

        assert remove_one(dst, anchor=tmp_path / "canonical") == \
            "skipped(not-ours)"
        assert dst.is_symlink()

    def test_remove_unlinks_canonical_symlink(self, tmp_path: Path) -> None:
        canonical = tmp_path / "canonical"
        (canonical / "batho").mkdir(parents=True)
        dst = tmp_path / "mirror" / "batho"
        dst.parent.mkdir()
        dst.symlink_to(canonical / "batho", target_is_directory=True)

        assert remove_one(dst, anchor=canonical) == "removed(link)"
        assert not dst.exists() and not dst.is_symlink()


def test_remove_pack_validates_receipt_dirs(
    tmp_path: Path, isolated_home: Path
) -> None:
    """SKL-09: malformed receipt dirs entries are skipped, not expanded."""
    from batho.install.receipt import write_receipt

    marker_dir = tmp_path / "legit" / "skills" / "batho"
    marker_dir.mkdir(parents=True)
    (marker_dir / ".batho-skill").touch()
    write_receipt("v1.0.0", "global", [
        str(marker_dir.parent),          # legit absolute path
        "relative/path",                  # malformed — not absolute
        "",                               # malformed — empty
    ])
    records = remove_pack(scope="global")
    paths = [str(r.path) for r in records]
    assert not any("relative" in p for p in paths)
    assert not marker_dir.exists()  # the legit dir was still cleaned
