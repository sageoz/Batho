"""batho_plugin/packs.py — generic YAML data-pack loader.

Converts declarative pack YAML into DataPlugin instances (T07/T08). Pack
schema::

    plugin_id: lang-python          # required, unique
    version: "1.0.0"                # required
    class: core                     # core | standard | experimental
    language: python                # optional — scopes data per-language
    requires: [batho_plugin.core]   # optional dependency declarations
    data:
      sets:                         # name → list[str] → frozenset
        builtins: [int, str, ...]
      maps:                         # name → arbitrary JSON-safe value
        comment_syntax:
          line: ["#"]
          block: [["\"", "\""]]

When ``language`` is set, the compiled data is language-scoped
(``per_language[language]``) — the host's override-with-fallback lookup then
returns the pack's data only for that language (a Python file must be pruned
by Python's builtins only). Policy packs (no ``language`` key) compile to
top-level data. Unknown top-level/data keys are rejected at load (T07 gate).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from batho_plugin.api import DataPlugin, PluginData

# stdlib logging — packs.py is SDK surface, not a Tier-3 engine-coupled
# module: no batho.* imports may appear here (the SDK has no engine
# dependency; rule_engine.py is the documented exception).
_LOGGER = logging.getLogger(__name__)

_ALLOWED_TOP_KEYS = frozenset({
    "plugin_id", "version", "class", "language", "data", "requires",
})
_DATA_KEYS = frozenset({"sets", "maps", "per_language"})
_VALID_CLASSES = frozenset({"core", "standard", "experimental"})


class PackValidationError(ValueError):
    """Raised when a pack YAML file is structurally invalid."""


def _compile_data_section(raw: Any, where: str) -> PluginData:
    if raw is None:
        return PluginData()
    if not isinstance(raw, dict):
        raise PackValidationError(f"{where}: 'data' must be a mapping")
    unknown = set(raw) - _DATA_KEYS
    if unknown:
        raise PackValidationError(
            f"{where}: unknown data keys {sorted(unknown)}"
        )
    if "per_language" in raw:
        raise PackValidationError(
            f"{where}: per_language is derived from the 'language' key, "
            "not declared in pack YAML"
        )

    sets: dict[str, frozenset[str]] = {}
    for name, entries in (raw.get("sets") or {}).items():
        if not isinstance(entries, list) or not all(
            isinstance(x, str) for x in entries
        ):
            raise PackValidationError(
                f"{where}: sets.{name} must be a list of strings"
            )
        sets[str(name)] = frozenset(entries)

    maps: dict[str, Any] = {}
    for name, value in (raw.get("maps") or {}).items():
        maps[str(name)] = value

    return PluginData(sets=sets, maps=maps)


class YamlDataPlugin:
    """A YAML-defined :class:`DataPlugin` (core-pack data file)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise PackValidationError(f"{path}: top level must be a mapping")
        unknown = set(raw) - _ALLOWED_TOP_KEYS
        if unknown:
            raise PackValidationError(
                f"{path}: unknown top-level keys {sorted(unknown)}"
            )

        plugin_id = raw.get("plugin_id")
        version = raw.get("version")
        if not plugin_id or not isinstance(plugin_id, str):
            raise PackValidationError(
                f"{path}: 'plugin_id' must be a non-empty string"
            )
        if not version or not isinstance(version, str):
            raise PackValidationError(
                f"{path}: 'version' must be a non-empty string"
            )
        pack_class = raw.get("class", "standard")
        if pack_class not in _VALID_CLASSES:
            raise PackValidationError(
                f"{path}: 'class' must be one of {sorted(_VALID_CLASSES)}"
            )
        language = raw.get("language")
        if language is not None and not isinstance(language, str):
            raise PackValidationError(f"{path}: 'language' must be a string")
        requires = raw.get("requires") or ()
        if not isinstance(requires, list) or not all(
            isinstance(r, str) for r in requires
        ):
            raise PackValidationError(
                f"{path}: 'requires' must be a list of strings"
            )

        self.plugin_id: str = plugin_id
        self.version: str = str(version)
        self.pack_class: str = pack_class
        self.language: str | None = language
        self.requires: tuple[str, ...] = tuple(str(r) for r in requires)
        self._data = _compile_data_section(raw.get("data"), str(path))

    def compile(self) -> PluginData:
        if self.language:
            return PluginData(per_language={self.language: self._data})
        return self._data

    @classmethod
    def from_file(cls, path: Path | str) -> "YamlDataPlugin":
        return cls(Path(path))


def _is_rule_plugin_file(path: Path) -> bool:
    """True when the YAML is a v1/v2 *rule* plugin, not a data pack.

    Rule plugins and data packs can share the same core directory tree
    (spec §16.3): rule files declare ``schema_version: bsg-plugin.vN``;
    data packs do not. A cheap header scan keeps the two loaders disjoint.
    """
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:2048]
    except OSError as exc:
        _LOGGER.debug("rule_plugin_probe_read_failed path=%s error=%s", str(path), str(exc))
        return False
    return "bsg-plugin.v" in head


def load_pack_dir(pack_dir: Path) -> list[DataPlugin]:
    """Load every data-pack ``*.yaml`` under *dir* (sorted, deterministic).

    Language packs live under ``language_packs/``; policy packs sit at the
    pack root; rule plugins (``schema_version: bsg-plugin.*``) are skipped —
    they load through the rule engine, not the pack loader. Missing
    directory → empty list (pack optional).
    """
    if not pack_dir.is_dir():
        return []
    return [
        YamlDataPlugin(p)
        for p in sorted(pack_dir.rglob("*.yaml"))
        if not _is_rule_plugin_file(p)
    ]
