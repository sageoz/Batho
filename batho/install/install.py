"""Filesystem install/remove primitives — port of install.sh pass 1+2.

Canonical target gets real copies; mirrors symlink to the canonical copy (or
copy when symlinks are unavailable/``copy=True``). Copied dirs carry an empty
``.batho-skill`` marker so removal can distinguish ours from foreign dirs.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from batho.install.detect import InstallTarget, pack_skills

MARKER = ".batho-skill"


@dataclass
class InstallRecord:
    agent_id: str
    path: Path
    status: str


@dataclass
class InstallResult:
    version: str
    scope: str
    records: list[InstallRecord] = field(default_factory=list)
    receipt_path: Path | None = None


def _link_is_ours(link: Path, src: Path, anchor: Path | None) -> bool:
    """True when `link` points at `src` or resolves inside `anchor` (the
    canonical pack dir) — i.e. a symlink we previously created."""
    try:
        target = link.readlink()
        if target == src:
            return True
        resolved = link.resolve()
    except OSError:
        return False
    if anchor is None:
        return False
    try:
        return anchor.resolve() in (resolved, *resolved.parents)
    except OSError:
        return False


def install_one(
    src: Path,
    dst: Path,
    copy: bool = False,
    force: bool = False,
    link_anchor: Path | None = None,
) -> str:
    """Install one skill dir; returns a status token like install.sh."""
    if dst.is_symlink():
        try:
            if dst.readlink() == src:
                return "link(ok)"
        except OSError:
            pass
        if not force and not _link_is_ours(dst, src, link_anchor):
            # A symlink someone else placed — never hijack it silently.
            return "skipped(not-ours)"
        dst.unlink()
    elif dst.is_dir():
        if not force and not (dst / MARKER).is_file():
            return "skipped(not-ours)"
        shutil.rmtree(dst)
    elif dst.exists():
        if not force:
            return "skipped(not-ours)"
        dst.unlink()

    dst.parent.mkdir(parents=True, exist_ok=True)
    if copy:
        shutil.copytree(src, dst)
        return "copied"
    try:
        dst.symlink_to(src, target_is_directory=True)
        return "linked"
    except OSError:
        shutil.copytree(src, dst)
        return "copied"


def remove_one(dst: Path, anchor: Path | None = None) -> str:
    """Remove a skill dir only if it is ours (symlink or marker-bearing copy)."""
    if dst.is_symlink():
        if anchor is not None:
            try:
                resolved = dst.resolve()
                if anchor.resolve() not in (resolved, *resolved.parents):
                    return "skipped(not-ours)"
            except OSError:
                return "skipped(not-ours)"
        dst.unlink()
        return "removed(link)"
    if dst.is_dir():
        if (dst / MARKER).is_file():
            shutil.rmtree(dst)
            return "removed(copy)"
        return "skipped(not-ours)"
    if dst.exists():
        return "skipped(not-ours)"
    return "absent"


def write_pack(
    skills_src: Path,
    targets: list[InstallTarget],
    canonical: Path,
    copy: bool = False,
    force: bool = False,
) -> list[InstallRecord]:
    """Two-pass install: canonical/custom get real copies, mirrors link to them."""
    names = pack_skills()
    records: list[InstallRecord] = []
    for target in targets:
        for skill in names:
            src = skills_src / skill
            if not src.is_dir():
                records.append(InstallRecord(target.agent_id, target.skills_dir / skill, "missing"))
                continue
            if target.agent_id in ("canonical", "custom"):
                status = install_one(
                    src, target.skills_dir / skill,
                    copy=True, force=force, link_anchor=canonical,
                )
            else:
                status = install_one(
                    canonical / skill, target.skills_dir / skill,
                    copy=copy, force=force, link_anchor=canonical,
                )
            dst = target.skills_dir / skill
            if status == "copied":
                try:
                    (dst / MARKER).touch()
                except OSError:
                    pass
            records.append(InstallRecord(target.agent_id, dst, status))
    return records


def remove_pack_dirs(
    targets: list[InstallTarget], anchor: Path | None = None
) -> list[InstallRecord]:
    """Remove pack skills from each target dir (marker-guarded; `anchor` is
    the canonical pack dir a symlink must resolve into to count as ours)."""
    names = pack_skills()
    records: list[InstallRecord] = []
    for target in targets:
        for skill in names:
            dst = target.skills_dir / skill
            records.append(
                InstallRecord(target.agent_id, dst, remove_one(dst, anchor))
            )
    return records


def remove_orphan_skills(
    targets: list[InstallTarget],
    keep_names: set[str],
    canonical: Path,
) -> list[InstallRecord]:
    """Remove our stale skill dirs that the current pack no longer ships.

    Orphans are skill dirs under a target's skills_dir that are (a) marker-
    bearing copies we installed, or (b) symlinks resolving under the
    canonical pack dir — but whose name is absent from ``keep_names`` (the
    new pack's skill list). Foreign dirs and external symlinks are left
    alone (SKL-05).
    """
    canonical = canonical.resolve()
    records: list[InstallRecord] = []
    seen_dirs: set[Path] = set()
    for target in targets:
        sdir = target.skills_dir
        if sdir in seen_dirs or not sdir.is_dir():
            continue
        seen_dirs.add(sdir)
        for child in sorted(sdir.iterdir()):
            if child.name in keep_names:
                continue
            ours = (child / MARKER).is_file() if child.is_dir() and not child.is_symlink() else False
            if child.is_symlink():
                try:
                    ours = child.resolve().parent == canonical
                except OSError:
                    ours = False
            if not ours:
                continue
            records.append(
                InstallRecord(
                    target.agent_id, child, remove_one(child, canonical)
                )
            )
    return records
