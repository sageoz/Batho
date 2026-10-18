"""batho_plugin/external — optional external pack (spec §16.3, T26).

Ships proven rule plugins (interceptors + generated enrichment packs) as
opt-in defaults. Loaded ONLY when ``plugins.external.enabled`` is true;
``plugins.external.select`` is an optional stem/plugin_id allowlist.

Rule YAMLs here are discovered by the rule engine via
``_discover_packaged_plugins(external_cfg)`` — the host-side
``get_plugins()`` registers the same plugins (id/version/rule_ids) so the
plugin fingerprint reflects the external set and AST caches invalidate
correctly on toggle (spec §9).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# stdlib logging — external/__init__ is SDK surface: no batho.* imports.
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RulePackPlugin:
    """Adapter exposing a YAML rule plugin to PluginHost.register_rule()."""

    plugin_id: str
    version: str
    rule_ids: tuple[str, ...]
    path: str  # informational — source file
    plugin_class: str = "standard"


def _external_root() -> Path:
    return Path(__file__).resolve().parent


def _plugin_id_for(path: Path) -> str | None:
    """Top-level ``plugin_id`` of a rule YAML, or None when unreadable."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        _LOGGER.debug("external_plugin_id_read_failed path=%s error=%s", str(path), str(exc))
        return None
    if not isinstance(doc, dict):
        return None
    pid = doc.get("plugin_id")
    return str(pid) if pid else None


def discover_external_rule_files(select: tuple[str, ...] | list[str] | None = None) -> list[Path]:
    """v2 rule-plugin YAMLs under external/, optionally allowlist-filtered.

    ``select`` entries match the file STEM or the YAML's ``plugin_id`` — the
    same contract as PluginHost._load_pack, so a selection cannot register a
    plugin on the host (fingerprint/cache-variant visible) while silently
    skipping its rule YAML in the engine catalog.
    """
    from batho_plugin.packs import _is_rule_plugin_file

    root = _external_root()
    selected = {str(s).strip() for s in (select or []) if str(s).strip()}
    out: list[Path] = []
    for ext in ("*.yaml", "*.yml"):
        for path in sorted(root.rglob(ext)):
            if not _is_rule_plugin_file(path):
                continue
            if selected and path.stem not in selected:
                if _plugin_id_for(path) not in selected:
                    continue
            out.append(path)
    return sorted(out)


def get_plugins() -> list[RulePackPlugin]:
    """Rule-pack adapters for every external YAML — fingerprint-visible."""
    plugins: list[RulePackPlugin] = []
    for path in discover_external_rule_files():
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            _LOGGER.warning("external_plugin_skip_unreadable path=%s error=%s", str(path), str(exc))
            continue
        rule_ids = tuple(
            str(r.get("rule_id") or r.get("name") or "")
            for r in doc.get("rules", [])
            if isinstance(r, dict)
        )
        plugins.append(
            RulePackPlugin(
                plugin_id=str(doc.get("plugin_id") or path.stem),
                version=str(doc.get("version") or "0.0.0"),
                rule_ids=tuple(r for r in rule_ids if r),
                path=path.name,
                plugin_class=str(doc.get("class") or "standard"),
            )
        )
    return plugins


__all__ = ["RulePackPlugin", "discover_external_rule_files", "get_plugins"]
