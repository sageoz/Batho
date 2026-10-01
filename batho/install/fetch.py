"""Download + verify + extract the batho-skills release tarball.

Mirrors ``fetch_pack`` in batho-skills ``install.sh`` using only the stdlib:
``urllib.request`` for HTTP, ``hashlib`` for sha256, ``tarfile`` for extraction.
"""

from __future__ import annotations

import hashlib
import os
import re
import tarfile
import time
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "https://github.com/sageoz/batho-skills/releases"
DEFAULT_TIMEOUT = 10.0
# The pack is markdown — a hard byte cap turns a hostile/degenerate endpoint
# (BATHO_BASE_URL override, compromised asset, redirect chain) into a clean
# failure instead of a disk fill (SKL-06).
MAX_PACK_BYTES = 64 * 1024 * 1024
# Same idea for the extracted payload: bound total bytes and member count.
MAX_EXTRACT_BYTES = 256 * 1024 * 1024
MAX_EXTRACT_MEMBERS = 10_000
# Wall-clock deadline per download — `timeout` alone is per-socket-op, so a
# server dripping one byte per <timeout interval could stall forever.
MAX_DOWNLOAD_SECONDS = 30.0


class SkillsError(Exception):
    """Fatal skill-pack error (network, checksum, malformed archive)."""


def _base_url(base_url: str | None) -> str:
    url = (base_url or os.environ.get("BATHO_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    if url.startswith("http://") and os.environ.get("BATHO_ALLOW_HTTP") != "1":
        raise SkillsError(
            f"insecure base URL {url!r}: use https:// or set BATHO_ALLOW_HTTP=1"
        )
    return url


def resolve_version(version: str | None = None) -> str:
    """Resolve the target release tag: arg → BATHO_VERSION env → 'latest'."""
    v = (version or os.environ.get("BATHO_VERSION") or "latest").strip()
    if v.lower() == "latest":
        return "latest"
    if not v.startswith("v"):
        v = f"v{v}"
    return v


def resolve_latest_version(
    base_url: str | None = None, timeout: float = DEFAULT_TIMEOUT
) -> str:
    """Resolve the latest release tag via the /releases/latest redirect.

    Reads the final URL after redirect (no GitHub API call); raises SkillsError
    when the tag cannot be determined.
    """
    url = f"{_base_url(base_url)}/latest"
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final = resp.url
    except Exception as exc:
        raise SkillsError(f"could not resolve latest release: {exc}") from exc
    m = re.search(r"/tag/([^/?#]+)", final)
    if not m:
        raise SkillsError(f"could not resolve latest release tag from {final}")
    return m.group(1)


def _download(url: str, dest: Path, timeout: float) -> None:
    deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
    written = 0
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp, dest.open("wb") as fh:
            while chunk := resp.read(1 << 20):
                written += len(chunk)
                if written > MAX_PACK_BYTES:
                    raise SkillsError(
                        f"pack download exceeds {MAX_PACK_BYTES}-byte cap: {url}"
                    )
                if time.monotonic() > deadline:
                    raise SkillsError(
                        f"download exceeded {MAX_DOWNLOAD_SECONDS:.0f}s deadline: {url}"
                    )
                fh.write(chunk)
    except SkillsError:
        raise
    except Exception as exc:
        raise SkillsError(f"download failed: {url} ({exc})") from exc


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _expected_sha256(sums_text: str, filename: str) -> str:
    """Find the checksum for ``filename`` in sha256sums.txt content.

    The release sums file lists many assets (per-skill tarballs, installers);
    match by filename. Falls back to the first line for minimal sums files.
    """
    first: str | None = None
    for line in sums_text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if first is None:
            first = parts[0]
        if parts[-1].lstrip("*") == filename:
            return parts[0]
    if first is None:
        raise SkillsError("checksum file was empty")
    return first


def fetch_pack(
    dest_dir: Path,
    base_url: str | None = None,
    version: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Path:
    """Download, checksum-verify, and extract the pack; returns the skills dir.

    ``dest_dir`` must be a writable temp/work dir. Raises SkillsError on any
    failure; callers decide whether that is fatal (CLI) or a warning (mcp).
    """
    base = _base_url(base_url)
    ver = resolve_version(version)
    if ver == "latest":
        tgz_name = "batho-skills.tar.gz"
        tgz_url = f"{base}/latest/download/{tgz_name}"
        sums_url = f"{base}/latest/download/sha256sums.txt"
    else:
        tgz_name = f"batho-skills-{ver.removeprefix('v')}.tar.gz"
        tgz_url = f"{base}/download/{ver}/{tgz_name}"
        sums_url = f"{base}/download/{ver}/sha256sums.txt"

    dest_dir.mkdir(parents=True, exist_ok=True)
    tgz = dest_dir / "pack.tar.gz"
    _download(tgz_url, tgz, timeout)

    sums = dest_dir / "sha256sums.txt"
    _download(sums_url, sums, timeout)
    expected = _expected_sha256(sums.read_text(encoding="utf-8"), tgz_name)
    actual = _sha256(tgz)
    # Authenticity anchor (SKL-03): sha256sums.txt is fetched from the same
    # origin as the tarball, so it only proves the download isn't
    # corrupt/tampered downstream — it cannot detect a compromised release.
    # BATHO_EXPECTED_SHA256 pins an out-of-band digest (install.sh parity);
    # when set it is verified BEFORE extraction and failure is fatal.
    pinned = os.environ.get("BATHO_EXPECTED_SHA256", "").strip().lower()
    if pinned and actual != pinned:
        raise SkillsError(
            f"pinned digest mismatch for pack tarball "
            f"(BATHO_EXPECTED_SHA256={pinned}, got {actual}) — aborting"
        )
    if actual != expected:
        raise SkillsError(
            f"checksum mismatch for pack tarball "
            f"(expected {expected}, got {actual}) — aborting"
        )

    extract_dir = dest_dir / "extract"
    extract_dir.mkdir(exist_ok=True)
    try:
        with tarfile.open(tgz) as tar:
            tar.extractall(extract_dir, filter="data")
    except (tarfile.TarError, OSError) as exc:
        raise SkillsError(f"tar extract failed: {exc}") from exc

    # SKL-06: bound the extracted payload — a valid-checksum tarball could
    # still be a zip bomb or carry tens of thousands of members.
    total_bytes = 0
    member_count = 0
    for p in extract_dir.rglob("*"):
        member_count += 1
        if p.is_file() and not p.is_symlink():
            total_bytes += p.stat().st_size
        if member_count > MAX_EXTRACT_MEMBERS:
            raise SkillsError(
                f"pack archive exceeds {MAX_EXTRACT_MEMBERS}-member cap"
            )
        if total_bytes > MAX_EXTRACT_BYTES:
            raise SkillsError(
                f"pack archive exceeds {MAX_EXTRACT_BYTES}-byte extracted cap"
            )

    for candidate in sorted(extract_dir.glob("*/skills")) + [extract_dir / "skills"]:
        if candidate.is_dir():
            return candidate
    raise SkillsError("archive did not contain a skills/ directory")
