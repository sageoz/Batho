"""Tests for batho.install.fetch — download + sha256 verify + extract.

Network-free: releases are served from a local file:// tree.
"""

from __future__ import annotations

import hashlib
import shutil
import tarfile
import urllib.request
from pathlib import Path

import pytest

from batho.install.fetch import (
    SkillsError,
    fetch_pack,
    resolve_latest_version,
    resolve_version,
)

PACK = ["batho", "batho-setup", "batho-specs", "batho-execute", "batho-review"]


def _make_release(tmp_path: Path, tag: str = "v1.0.0", digest_override: str | None = None) -> Path:
    """Build a fake release tree: {tmp}/releases/download/<tag>/{tgz,sums}."""
    src = tmp_path / "src" / "batho-skills-1.0.0" / "skills"
    for name in PACK:
        d = src / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"# {name}\n")
    tgz = tmp_path / "pack.tar.gz"
    with tarfile.open(tgz, "w:gz") as tar:
        tar.add(src.parent, arcname="batho-skills-1.0.0")
    digest = digest_override or hashlib.sha256(tgz.read_bytes()).hexdigest()

    dl = tmp_path / "releases" / "download" / tag
    dl.mkdir(parents=True)
    shutil.copy(tgz, dl / f"batho-skills-{tag.lstrip('v')}.tar.gz")
    # Real release sums list many assets — ours is NOT the first line.
    (dl / "sha256sums.txt").write_text(
        "deadbeef" * 8 + "  batho-skills-batho-1.0.0.tar.gz\n"
        f"{digest}  batho-skills-{tag.lstrip('v')}.tar.gz\n"
        "cafef00d" * 8 + "  install.sh\n"
    )
    return tmp_path / "releases"


def test_resolve_version(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert resolve_version("1.2.0") == "v1.2.0"
    assert resolve_version("v1.2.0") == "v1.2.0"
    assert resolve_version() == "latest"
    assert resolve_version("LATEST") == "latest"
    assert resolve_version(" latest ") == "latest"
    monkeypatch.setenv("BATHO_VERSION", "2.0.0")
    assert resolve_version() == "v2.0.0"
    assert resolve_version("9.9") == "v9.9"  # explicit arg beats env


def test_base_url_rejects_http(isolated_home: Path, tmp_path: Path) -> None:
    with pytest.raises(SkillsError, match="insecure base URL"):
        fetch_pack(tmp_path / "w", base_url="http://example.com/releases", version="v1.0.0")


def test_fetch_pack_good_path(isolated_home: Path, tmp_path: Path) -> None:
    releases = _make_release(tmp_path)
    dest = tmp_path / "work"
    skills_dir = fetch_pack(dest, base_url=f"file://{releases}", version="v1.0.0")
    assert (skills_dir / "batho" / "SKILL.md").is_file()
    assert {p.name for p in skills_dir.iterdir()} == set(PACK)


def test_fetch_pack_checksum_mismatch(isolated_home: Path, tmp_path: Path) -> None:
    # Wrong digest on OUR asset's line (decoys still valid hex).
    releases = _make_release(tmp_path, digest_override="0" * 64)
    with pytest.raises(SkillsError, match="checksum mismatch"):
        fetch_pack(tmp_path / "w", base_url=f"file://{releases}", version="v1.0.0")


def test_fetch_pack_missing_artifact(isolated_home: Path, tmp_path: Path) -> None:
    releases = _make_release(tmp_path)
    with pytest.raises(SkillsError, match="download failed"):
        fetch_pack(tmp_path / "w", base_url=f"file://{releases}", version="v9.9.9")


def test_fetch_pack_no_skills_dir(isolated_home: Path, tmp_path: Path) -> None:
    # tarball without a skills/ directory
    src = tmp_path / "src" / "pack" / "docs"
    src.mkdir(parents=True)
    (src / "x.txt").write_text("x")
    tgz = tmp_path / "pack.tar.gz"
    with tarfile.open(tgz, "w:gz") as tar:
        tar.add(src.parent, arcname="pack")
    dl = tmp_path / "releases" / "download" / "v1.0.0"
    dl.mkdir(parents=True)
    shutil.copy(tgz, dl / "batho-skills-1.0.0.tar.gz")
    (dl / "sha256sums.txt").write_text(
        f"{hashlib.sha256(tgz.read_bytes()).hexdigest()}  batho-skills-1.0.0.tar.gz\n"
    )
    with pytest.raises(SkillsError, match="skills/"):
        fetch_pack(tmp_path / "w", base_url=f"file://{tmp_path}/releases", version="v1.0.0")


def test_resolve_latest_version_from_redirect(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Resp:
        url = "https://github.com/sageoz/batho-skills/releases/tag/v9.9.9"

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert resolve_latest_version() == "v9.9.9"


def test_resolve_latest_version_failure(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*a: object, **k: object) -> None:
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    with pytest.raises(SkillsError, match="could not resolve"):
        resolve_latest_version()


# ── SKL-03: pinned authenticity anchor ─────────────────────────────────────

def test_pinned_digest_match_succeeds(isolated_home, tmp_path, monkeypatch):
    releases = _make_release(tmp_path)
    tgz = releases / "download" / "v1.0.0" / "batho-skills-1.0.0.tar.gz"
    digest = hashlib.sha256(tgz.read_bytes()).hexdigest()
    monkeypatch.setenv("BATHO_EXPECTED_SHA256", digest)
    skills_dir = fetch_pack(
        tmp_path / "w", base_url=f"file://{releases}", version="v1.0.0"
    )
    assert (skills_dir / "batho" / "SKILL.md").is_file()


def test_pinned_digest_mismatch_fails(isolated_home, tmp_path, monkeypatch):
    """BATHO_EXPECTED_SHA256 is an authenticity anchor — a tarball whose
    checksum matches the same-origin sums file must still be rejected when
    the pinned digest differs."""
    releases = _make_release(tmp_path)
    monkeypatch.setenv("BATHO_EXPECTED_SHA256", "f" * 64)
    with pytest.raises(SkillsError, match="pinned digest mismatch"):
        fetch_pack(
            tmp_path / "w", base_url=f"file://{releases}", version="v1.0.0"
        )


# ── SKL-06: bounded download + extraction ──────────────────────────────────

def test_download_size_cap(isolated_home, tmp_path, monkeypatch):
    import batho.install.fetch as fetch_mod

    releases = _make_release(tmp_path)
    monkeypatch.setattr(fetch_mod, "MAX_PACK_BYTES", 16)
    with pytest.raises(SkillsError, match="byte cap"):
        fetch_pack(
            tmp_path / "w", base_url=f"file://{releases}", version="v1.0.0"
        )


def test_download_deadline(isolated_home, tmp_path, monkeypatch):
    import batho.install.fetch as fetch_mod

    releases = _make_release(tmp_path)
    monkeypatch.setattr(fetch_mod, "MAX_DOWNLOAD_SECONDS", -1.0)
    with pytest.raises(SkillsError, match="deadline"):
        fetch_pack(
            tmp_path / "w", base_url=f"file://{releases}", version="v1.0.0"
        )


def test_extract_member_cap(isolated_home, tmp_path, monkeypatch):
    import batho.install.fetch as fetch_mod

    releases = _make_release(tmp_path)
    monkeypatch.setattr(fetch_mod, "MAX_EXTRACT_MEMBERS", 2)
    with pytest.raises(SkillsError, match="member cap"):
        fetch_pack(
            tmp_path / "w", base_url=f"file://{releases}", version="v1.0.0"
        )


def test_tar_slip_rejected(isolated_home, tmp_path):
    """A '../evil' member must fail extraction — filter='data' raises a
    TarError subclass which surfaces as SkillsError."""
    src = tmp_path / "src" / "pack" / "skills"
    src.mkdir(parents=True)
    (src / "x.md").write_text("x")
    tgz = tmp_path / "slip.tar.gz"
    with tarfile.open(tgz, "w:gz") as tar:
        tar.add(src.parent, arcname="pack")
        evil = tarfile.TarInfo(name="../evil")
        data = b"pwned"
        evil.size = len(data)
        import io
        tar.addfile(evil, io.BytesIO(data))
    dl = tmp_path / "releases" / "download" / "v1.0.0"
    dl.mkdir(parents=True)
    shutil.copy(tgz, dl / "batho-skills-1.0.0.tar.gz")
    (dl / "sha256sums.txt").write_text(
        f"{hashlib.sha256(tgz.read_bytes()).hexdigest()}  "
        "batho-skills-1.0.0.tar.gz\n"
    )
    with pytest.raises(SkillsError):
        fetch_pack(tmp_path / "w", base_url=f"file://{tmp_path}/releases", version="v1.0.0")
