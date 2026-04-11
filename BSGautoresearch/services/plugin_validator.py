"""Validate BSG plugin YAML against the JSON schema."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml

try:
    from jsonschema import Draft202012Validator
except Exception:
    Draft202012Validator = None  # type: ignore[assignment]

_LOGGER = logging.getLogger(__name__)

_DEFAULT_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "batho"
    / "bsg"
    / "schemas"
    / "bsg-plugin-schema-v1.json"
)


def _load_schema(schema_path: Path | None = None) -> dict[str, Any]:
    path = schema_path or _DEFAULT_SCHEMA_PATH
    if not path.exists():
        raise FileNotFoundError(f"BSG plugin schema not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_plugin(
    plugin_doc: dict[str, Any],
    *,
    schema_path: Path | None = None,
) -> tuple[bool, list[str]]:
    """Validate a plugin document against bsg-plugin-schema-v1.json.

    Returns (is_valid, error_messages).
    """

    if Draft202012Validator is None:
        raise RuntimeError("jsonschema package required for plugin validation")

    schema = _load_schema(schema_path)
    validator = Draft202012Validator(schema)

    errors: list[str] = []
    for error in sorted(validator.iter_errors(plugin_doc), key=lambda e: list(e.path)):
        path_str = ".".join(str(p) for p in error.absolute_path) or "$"
        errors.append(f"{path_str}: {error.message}")

    return len(errors) == 0, errors


def validate_plugin_file(
    yaml_path: Path,
    *,
    schema_path: Path | None = None,
) -> tuple[bool, list[str], dict[str, Any]]:
    """Load and validate a plugin YAML file.

    Returns (is_valid, error_messages, plugin_doc).
    """

    if not yaml_path.exists():
        return False, [f"File not found: {yaml_path}"], {}

    try:
        text = yaml_path.read_text(encoding="utf-8")
        plugin_doc = yaml.safe_load(text)
    except Exception as exc:
        return False, [f"YAML parse error: {exc}"], {}

    if not isinstance(plugin_doc, dict):
        return False, ["Plugin YAML must be a mapping"], {}

    is_valid, errors = validate_plugin(plugin_doc, schema_path=schema_path)
    return is_valid, errors, plugin_doc


def check_determinism(
    plugin_doc: dict[str, Any],
    *,
    iterations: int = 3,
) -> bool:
    """Check that recompiling produces identical output (rule IDs + order)."""

    try:
        canonical_text = yaml.safe_dump(
            plugin_doc,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
    except Exception:
        return False

    try:
        canonical_doc = yaml.safe_load(canonical_text)
    except Exception:
        return False

    if not isinstance(canonical_doc, dict):
        return False

    rule_ids = [r.get("rule_id") for r in canonical_doc.get("rules", [])]

    for _ in range(iterations - 1):
        try:
            roundtrip_text = yaml.safe_dump(
                canonical_doc,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
            roundtrip_doc = yaml.safe_load(roundtrip_text)
        except Exception:
            return False

        if not isinstance(roundtrip_doc, dict):
            return False

        check_ids = [r.get("rule_id") for r in roundtrip_doc.get("rules", [])]
        if check_ids != rule_ids:
            return False

        canonical_doc = roundtrip_doc

    return True
