"""tests/core/config/test_plugins_config.py — T24: plugins.* config section.

Defaults, strictness (unknown keys rejected), and the select allowlist
(PLUGIN_ARCHITECTURE_SPEC §8.2).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from batho.core.config.models import (
    PluginCoreConfig,
    PluginExternalConfig,
    PluginHostConfig,
    PluginTelemetryConfig,
    PluginsConfig,
)


def test_defaults() -> None:
    cfg = PluginsConfig()
    assert cfg.core.required is True
    assert cfg.external.enabled is False  # opt-in
    assert cfg.external.select == []
    assert cfg.fingerprint_in_cache is True
    assert cfg.reextract_on_drift is True
    assert cfg.telemetry.hooks_metadata is False
    assert cfg.host.dispatch_order == "priority_then_id"
    assert cfg.overrides == {}


def test_unknown_top_level_keys_rejected() -> None:
    with pytest.raises(ValidationError, match="bogus"):
        PluginsConfig.model_validate({"bogus_key": 1})


def test_unknown_submodel_keys_rejected() -> None:
    with pytest.raises(ValidationError):
        PluginCoreConfig.model_validate({"bogus": 1})
    with pytest.raises(ValidationError):
        PluginExternalConfig.model_validate({"bogus": 1})
    with pytest.raises(ValidationError):
        PluginTelemetryConfig.model_validate({"bogus": 1})
    with pytest.raises(ValidationError):
        PluginHostConfig.model_validate({"dispatch_order": "shuffled"})


def test_external_select_allowlist() -> None:
    cfg = PluginExternalConfig.model_validate(
        {"enabled": True, "select": ["interceptors", "quarantine"]}
    )
    assert cfg.enabled is True
    assert cfg.select == ["interceptors", "quarantine"]


def test_overrides_still_accepted() -> None:
    """Legacy rule-engine overrides key keeps working (backward compat)."""
    cfg = PluginsConfig.model_validate(
        {"overrides": {"bsg_graph_foundation": {"rule": {"priority": 5}}}}
    )
    assert cfg.overrides["bsg_graph_foundation"]["rule"]["priority"] == 5


def test_full_section_roundtrip() -> None:
    cfg = PluginsConfig.model_validate(
        {
            "core": {"required": False},
            "external": {"enabled": True, "select": ["domain_taxonomy"]},
            "fingerprint_in_cache": False,
            "reextract_on_drift": False,
            "telemetry": {"hooks_metadata": True},
            "host": {"dispatch_order": "priority_then_id"},
        }
    )
    assert cfg.core.required is False
    assert cfg.external.enabled is True
    assert cfg.fingerprint_in_cache is False
    assert cfg.reextract_on_drift is False
    assert cfg.telemetry.hooks_metadata is True
    dumped = cfg.model_dump()
    assert "metadata_schema" not in dumped
    assert set(dumped) == {
        "overrides", "core", "external", "fingerprint_in_cache",
        "reextract_on_drift", "telemetry", "host",
    }


def test_yaml_example_builtin_plugins_mirrors_default() -> None:
    """batho.yaml / batho.yaml.example list the documented 7-stem default so
    disabling auto_load_all_plugins resolves the identical plugin set."""
    from pathlib import Path

    import yaml

    from batho.core.config.models import DEFAULT_RULES_BUILTIN_PLUGINS

    repo = Path(__file__).resolve().parents[3]
    for name in ("batho.yaml", "batho.yaml.example"):
        doc = yaml.safe_load((repo / name).read_text(encoding="utf-8"))
        listed = tuple(doc["rules"]["builtin_plugins"])
        assert listed == DEFAULT_RULES_BUILTIN_PLUGINS, (
            f"{name} builtin_plugins diverged from DEFAULT_RULES_BUILTIN_PLUGINS"
        )
