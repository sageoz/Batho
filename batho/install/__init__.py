"""Batho installer — skill pack + MCP registration (backing `batho install`).

Public API:
    install_pack          — fetch + verify + install the pack (canonical + mirrors)
    remove_pack           — uninstall receipt-owned files and mirrors
    pack_status           — receipt contents, or None when not installed
    auto_sync_if_needed   — fail-open sync used by `batho mcp` startup
    (MCP registration lives in batho.install.mcp_config)
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from batho.install.detect import (
    InstallTarget,
    canonical_dir,
    compute_targets,
    pack_skills,
)
from batho.install.fetch import (
    SkillsError,
    fetch_pack,
    resolve_latest_version,
    resolve_version,
)
from batho.install.install import (
    InstallRecord,
    InstallResult,
    remove_orphan_skills,
    remove_pack_dirs,
    write_pack,
)
from batho.install.receipt import (
    read_last_check,
    read_receipt,
    remove_receipt,
    write_last_check,
    write_receipt,
)

__all__ = [
    "InstallRecord",
    "InstallResult",
    "InstallTarget",
    "SkillsError",
    "auto_sync_if_needed",
    "install_pack",
    "pack_status",
    "remove_pack",
]


def install_pack(
    agents: list[str] | None = None,
    scope: str = "global",
    base_url: str | None = None,
    version: str | None = None,
    project_root: Path | None = None,
    copy: bool = False,
    force: bool = False,
    all_agents: bool = False,
) -> InstallResult:
    """Fetch the pack, install to canonical + mirror dirs, write the receipt."""
    scope = scope or os.environ.get("BATHO_SCOPE", "global")
    proot = (project_root or Path.cwd()).resolve()
    targets = compute_targets(scope, proot, agents=agents, all_agents=all_agents)
    canonical = canonical_dir(scope, proot)

    resolved = resolve_version(version)
    old_receipt = read_receipt()
    with tempfile.TemporaryDirectory(prefix="batho-skills-") as tmp:
        skills_src = fetch_pack(Path(tmp), base_url=base_url, version=resolved)
        if resolved == "latest":
            try:
                resolved = resolve_latest_version(base_url)
            except SkillsError:
                pass  # receipt keeps "latest" — drift check will retry next run
        records = write_pack(
            skills_src,
            targets,
            canonical,
            copy=copy or os.environ.get("BATHO_COPY") == "1",
            force=force,
        )

    # SKL-05: drop stale skills the new pack no longer ships — scan the
    # current targets plus every dir the previous receipt recorded.
    keep = set(pack_skills())
    extra_dirs = [
        InstallTarget("receipt", Path(d))
        for d in (old_receipt or {}).get("dirs", [])
    ]
    records += remove_orphan_skills(targets + extra_dirs, keep, canonical)

    # SKL-05: only persist a receipt when at least one skill actually
    # landed — an all-skipped/missing install must not look "installed".
    landed = {
        "copied", "linked", "link(ok)",
    }
    rp = (
        write_receipt(resolved, scope, [str(t.skills_dir) for t in targets])
        if any(r.status in landed for r in records)
        else None
    )
    return InstallResult(version=resolved, scope=scope, records=records, receipt_path=rp)


def remove_pack(scope: str = "global", project_root: Path | None = None) -> list[InstallRecord]:
    """Remove pack skills from the dirs recorded in the receipt (receipt-owned only)."""
    proot = (project_root or Path.cwd()).resolve()
    receipt = read_receipt()
    receipt_dirs = receipt.get("dirs") if receipt else None
    if isinstance(receipt_dirs, list) and receipt_dirs:
        # SKL-09: receipt contents are untrusted input — require a list of
        # absolute paths, expanduser each, skip anything malformed.
        targets = []
        for d in receipt_dirs:
            try:
                p = Path(d).expanduser()
            except (TypeError, RuntimeError):
                continue
            if p.is_absolute():
                targets.append(InstallTarget("receipt", p))
    else:
        targets = compute_targets(scope or "global", proot)
    anchor = canonical_dir(scope or "global", proot)
    records = remove_pack_dirs(targets, anchor=anchor)
    remove_receipt()
    return records


def pack_status() -> dict[str, Any] | None:
    """Return the receipt dict when the pack is installed, else None."""
    return read_receipt()


def _sync_disabled(root_cfg: dict[str, Any] | None) -> bool:
    """Env var wins, then batho.yaml `skills.auto_install` (default: enabled)."""
    if os.environ.get("BATHO_NO_SKILL_SYNC", "").lower() in {"1", "true", "yes"}:
        return True
    skills_cfg = (root_cfg or {}).get("skills", {})
    if isinstance(skills_cfg, dict) and skills_cfg.get("auto_install") is False:
        return True
    return False


def auto_sync_if_needed(
    root_cfg: dict[str, Any] | None = None,
    project_root: Path | None = None,
) -> bool:
    """Install/refresh the pack when missing or version-drifted.

    Returns True when a sync ran. Raises SkillsError on failure — the caller
    (cmd_mcp) wraps this fail-open. `project_root` is the MCP --root — a
    project-scope install must resolve its canonical dir there, not cwd.
    """
    if _sync_disabled(root_cfg):
        return False

    proot = (project_root or Path.cwd()).resolve()

    receipt = read_receipt()
    if receipt is None:
        install_pack(project_root=proot)
        return True

    scope = receipt.get("scope", "global")

    # SKL-05: presence-based drift — a receipt that says "installed" but
    # whose canonical dir lost pack skills on disk counts as drifted.
    try:
        canonical = canonical_dir(scope, proot)
        on_disk = canonical.is_dir() and all(
            (canonical / s).is_dir() for s in pack_skills()
        )
    except Exception:
        on_disk = True  # probe failure must not force a sync
    if not on_disk:
        install_pack(scope=scope, force=True, project_root=proot)
        return True

    # SKL-02: compare the receipt against the EFFECTIVE target version —
    # resolve_version(None) honors the BATHO_VERSION pin the same way
    # install_pack does. A pinned install must not re-download just because
    # upstream moved on; the latest-tag check (and its network call) only
    # applies when the target is "latest".
    target = resolve_version(None)
    if target == "latest":
        # SKL-08: throttle the upstream HEAD request — at most one per 24h;
        # a fresh sidecar means "receipt version is still the latest we saw".
        checked = read_last_check()
        if checked is None:
            target = resolve_latest_version()
            write_last_check(target)
        else:
            target = checked["version"]
    if receipt.get("version") != target:
        install_pack(scope=scope, force=True, project_root=proot)
        return True
    return False
