from __future__ import annotations

import os
from pathlib import Path

from batho.hooks.constants import MANAGED_HOOK_MARKER, SUPPORTED_GIT_CLIENT_HOOKS


class HookInstallError(ValueError):
    pass


def git_hooks_dir(root: Path) -> Path:
    return root / ".git" / "hooks"


def ensure_git_hooks_dir(root: Path) -> Path:
    hooks_dir = git_hooks_dir(root)
    if not hooks_dir.exists() or not hooks_dir.is_dir():
        raise HookInstallError(f"Missing git hooks directory: {hooks_dir}")
    return hooks_dir


def is_batho_managed_script(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:512]
    except OSError:
        return False
    return MANAGED_HOOK_MARKER in head


def render_hook_script(hook_name: str, root: Path) -> str:
    root_abs = root.resolve().as_posix()
    return (
        "#!/usr/bin/env sh\n"
        f"{MANAGED_HOOK_MARKER} hook={hook_name}\n"
        "set -eu\n\n"
        f'REPO_ROOT="{root_abs}"\n'
        f'exec batho hooks run --hook "{hook_name}" --root "$REPO_ROOT"\n'
    )


def install_hooks(
    root: Path,
    hook_names: list[str],
    *,
    force: bool = False,
    dry_run: bool = False,
    skip_unsupported: bool = False,
) -> dict[str, object]:
    hooks_dir = ensure_git_hooks_dir(root)
    installed: list[str] = []
    unchanged: list[str] = []
    skipped: list[dict[str, str]] = []
    warnings: list[str] = []

    for hook_name in hook_names:
        if hook_name not in SUPPORTED_GIT_CLIENT_HOOKS:
            if skip_unsupported:
                msg = f"Skipping non-git hook '{hook_name}' during install"
                warnings.append(msg)
                skipped.append({"hook": hook_name, "reason": "unsupported_for_install"})
                continue
            raise HookInstallError(
                f"Unsupported git hook name for install: {hook_name}"
            )

        target = hooks_dir / hook_name
        content = render_hook_script(hook_name, root)

        if target.exists() and not is_batho_managed_script(target) and not force:
            skipped.append({"hook": hook_name, "reason": "unmanaged_collision"})
            continue

        try:
            current = (
                target.read_text(encoding="utf-8", errors="ignore")
                if target.exists()
                else None
            )
        except OSError:
            current = None

        if current == content and target.exists():
            if not dry_run:
                target.chmod(target.stat().st_mode | 0o111)
            unchanged.append(hook_name)
            continue

        if dry_run:
            installed.append(hook_name)
            continue

        target.write_text(content, encoding="utf-8")
        target.chmod(target.stat().st_mode | 0o111)
        installed.append(hook_name)

    return {
        "installed": installed,
        "unchanged": unchanged,
        "skipped": skipped,
        "warnings": warnings,
        "dry_run": dry_run,
    }


def remove_hooks(
    root: Path, hook_names: list[str], *, dry_run: bool = False
) -> dict[str, object]:
    hooks_dir = ensure_git_hooks_dir(root)
    removed: list[str] = []
    skipped: list[dict[str, str]] = []

    for hook_name in hook_names:
        target = hooks_dir / hook_name
        if not target.exists():
            skipped.append({"hook": hook_name, "reason": "missing"})
            continue
        if not is_batho_managed_script(target):
            skipped.append({"hook": hook_name, "reason": "unmanaged"})
            continue

        if dry_run:
            removed.append(hook_name)
            continue

        try:
            target.unlink()
        except (PermissionError, OSError) as exc:
            skipped.append({"hook": hook_name, "reason": f"permission_error: {exc}"})
            continue

        removed.append(hook_name)

    return {
        "removed": removed,
        "skipped": skipped,
        "dry_run": dry_run,
    }


def hook_status(root: Path, hook_name: str) -> dict[str, object]:
    hooks_dir = git_hooks_dir(root)
    target = hooks_dir / hook_name
    managed = is_batho_managed_script(target)
    exists = target.exists()
    executable = os.access(target, os.X_OK) if exists else False

    return {
        "hook": hook_name,
        "supported_git_hook": hook_name in SUPPORTED_GIT_CLIENT_HOOKS,
        "path": str(target),
        "exists": exists,
        "managed": managed,
        "executable": executable,
        "installed": bool(exists and managed and executable),
    }
