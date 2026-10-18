"""tests/sdk/test_external_pack.py — T26: external pack config gating."""

from __future__ import annotations

import pytest

from batho_plugin import load_host
from batho_plugin.fingerprint import fingerprint_from_host
from batho_plugin.rule_engine import (
    _discover_packaged_plugins,
    load_effective_rules,
)


def _host(**plugins_cfg):
    return load_host(config={"plugins": plugins_cfg})


def test_external_disabled_by_default():
    host = _host()
    # No external rule plugins registered when disabled.
    assert "bsg_api_contract_guardian" not in host.plugin_ids
    assert "gen_quarantine_unresolved" not in host.plugin_ids
    # Catalog excludes external rules.
    catalog = _discover_packaged_plugins()
    assert "api_contract_guardian" not in catalog


def test_external_enabled_loads_pack():
    host = _host(external={"enabled": True})
    # Rule-pack adapters registered into the host (fingerprint-visible).
    assert "bsg_api_contract_guardian" in host.plugin_ids
    assert "gen_quarantine_unresolved" in host.plugin_ids
    # Rule catalog gains the external files (§16.3 stems — bsg_ dropped).
    catalog = _discover_packaged_plugins({"enabled": True})
    assert "api_contract_guardian" in catalog
    assert "quarantine" in catalog  # stem of quarantine.yaml


def test_external_select_allowlist():
    host = _host(external={"enabled": True, "select": ["quarantine"]})
    ids = set(host.plugin_ids)
    assert "gen_quarantine_unresolved" in ids
    assert "bsg_api_contract_guardian" not in ids
    catalog = _discover_packaged_plugins({"enabled": True, "select": ["quarantine"]})
    assert "quarantine" in catalog
    assert "api_contract_guardian" not in catalog


def test_external_select_by_plugin_id_matches_rule_catalog():
    """select may name a plugin_id as well as a stem — the same contract the
    host applies. If the engine catalog only matched stems, a by-id selection
    would register the plugin on the host (fingerprint/cache-variant visible)
    while silently loading no rules for it."""
    sel = ["bsg_api_contract_guardian"]  # plugin_id; file stem is api_contract_guardian
    host = _host(external={"enabled": True, "select": sel})
    ids = set(host.plugin_ids)
    assert "bsg_api_contract_guardian" in ids
    assert "gen_quarantine_unresolved" not in ids
    catalog = _discover_packaged_plugins({"enabled": True, "select": sel})
    assert "api_contract_guardian" in catalog
    assert "quarantine" not in catalog


def test_external_toggle_changes_fingerprint():
    fp_off = fingerprint_from_host(_host())
    fp_on = fingerprint_from_host(_host(external={"enabled": True}))
    assert fp_off != fp_on
    # select subset differs from full enable too
    fp_sel = fingerprint_from_host(
        _host(external={"enabled": True, "select": ["quarantine"]})
    )
    assert fp_sel != fp_on


def test_external_rules_compile_when_enabled(tmp_path):
    cfg = {
        "enabled": True,
        "auto_load_all_plugins": True,
        "builtin_plugins": [],
        "plugins_external": {"enabled": True},
    }
    rules, stats = load_effective_rules(cfg, tmp_path)
    rule_ids = {r.rule_id for r in rules}
    # interceptor rules present when enabled
    assert any("intercept" in rid or "guardian" in rid or "api" in rid for rid in rule_ids)
    # disabled → absent
    rules_off, _ = load_effective_rules({**cfg, "plugins_external": {}}, tmp_path)
    ids_off = {r.rule_id for r in rules_off}
    assert len(rules_off) < len(rules)
    assert not any("api-contract" in rid for rid in ids_off)
