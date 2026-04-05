from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from batho.hooks.constants import DEFAULT_HOOKS_CONFIG_REL_PATH, DEFAULT_ROOT_CONFIG_REL_PATH
from batho.hooks.models import HooksFile


class HooksConfigError(ValueError):
    pass


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise HooksConfigError(f"Invalid YAML object in {path}")
    return payload


def resolve_hooks_settings(root: Path) -> tuple[Path, bool]:
    root_cfg = root / DEFAULT_ROOT_CONFIG_REL_PATH
    enabled = True
    include = True

    if root_cfg.exists():
        try:
            payload = _load_yaml(root_cfg)
            hooks_section = payload.get("hooks")
            if isinstance(hooks_section, dict):
                if "enabled" in hooks_section:
                    enabled = bool(hooks_section.get("enabled"))
                if "include" in hooks_section:
                    include = bool(hooks_section.get("include"))
        except Exception:
            pass

    config_path = (root / DEFAULT_HOOKS_CONFIG_REL_PATH).resolve()
    return config_path, bool(enabled and include)


def load_hooks_file(path: Path) -> HooksFile:
    try:
        payload = _load_yaml(path)
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise HooksConfigError(f"Failed loading hooks config: {exc}") from exc

    try:
        return HooksFile.model_validate(payload)
    except ValidationError as exc:
        raise HooksConfigError(f"Invalid hooks config: {exc}") from exc
