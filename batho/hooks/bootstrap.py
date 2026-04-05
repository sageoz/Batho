from __future__ import annotations

from pathlib import Path

from batho.hooks.constants import DEFAULT_HOOKS_CONFIG_REL_PATH, starter_hooks_yaml


def ensure_hooks_config(root: Path, *, dry_run: bool = False) -> tuple[Path, bool]:
    config_path = root / DEFAULT_HOOKS_CONFIG_REL_PATH
    if config_path.exists():
        return config_path, False

    if dry_run:
        return config_path, True

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(starter_hooks_yaml(), encoding="utf-8")
    return config_path, True
