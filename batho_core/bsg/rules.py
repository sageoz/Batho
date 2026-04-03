"""Rule plugins for Batho Structured Graph (BSG).

This module provides a package-local plugin registry and a deterministic
rule-application pipeline. Built-in rules are defined as Python plugins and
custom rules can be loaded from YAML via configuration.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from batho_core.context.schema import Entity, EntityType
from batho_core.utils.logging import get_logger

if TYPE_CHECKING:
    from batho_core.context.codegraph import InMemoryGraph


_LOGGER = get_logger(__name__, component="bsg_rules")


class RuleMatch(BaseModel):
    """Entity matching constraints for a BSG rule."""

    model_config = ConfigDict(extra="forbid")

    entity_types: list[str] = Field(default_factory=list)
    name_patterns: list[str] = Field(default_factory=list)
    file_patterns: list[str] = Field(default_factory=list)


class RuleActions(BaseModel):
    """Mutations performed when a rule matches an entity."""

    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)
    derive_scope_tier: bool = False
    derive_service_tag: bool = False


class RuleDefinition(BaseModel):
    """Normalized BSG rule definition."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    priority: int = 0
    enabled: bool = True
    match: RuleMatch = Field(default_factory=RuleMatch)
    actions: RuleActions = Field(default_factory=RuleActions)
    plugin: str = "custom"


def _builtin_bsg_core_rules() -> list[dict[str, Any]]:
    """Built-in plugin for baseline BSG metadata enrichment."""

    return [
        {
            "name": "bsg-category-tests",
            "description": "Tag test files as TEST category.",
            "priority": 200,
            "file_patterns": [
                "tests/**",
                "**/tests/**",
                "**/test_*.py",
                "**/*_test.py",
                "**/*.spec.ts",
                "**/*.spec.js",
            ],
            "metadata": {"bsg.category": "TEST"},
        },
        {
            "name": "bsg-category-docs",
            "description": "Tag documentation files as DOC category.",
            "priority": 190,
            "file_patterns": ["docs/**", "**/*.md", "**/*.rst", "**/*.adoc"],
            "metadata": {"bsg.category": "DOC"},
        },
        {
            "name": "bsg-category-config",
            "description": "Tag config files as CONFIG category.",
            "priority": 180,
            "file_patterns": [
                "**/*.yaml",
                "**/*.yml",
                "**/*.toml",
                "**/*.json",
                "**/*.ini",
                "**/*.cfg",
                "**/*.conf",
            ],
            "metadata": {"bsg.category": "CONFIG"},
        },
        {
            "name": "bsg-category-infra",
            "description": "Tag infra files as INFRA category.",
            "priority": 175,
            "file_patterns": [
                "**/*.tf",
                "**/*.tfvars",
                "**/Dockerfile",
                "**/docker-compose*.yaml",
                "**/docker-compose*.yml",
            ],
            "metadata": {"bsg.category": "INFRA"},
        },
        {
            "name": "bsg-derive-service-tag",
            "description": "Derive service tag from common multi-service directory layouts.",
            "priority": 120,
            "file_patterns": ["services/*/**", "apps/*/**", "backend/*/**", "frontend/*/**"],
            "actions": {"derive_service_tag": True},
        },
        {
            "name": "bsg-derive-scope-tier",
            "description": "Derive structural scope tier from entity kind and nesting.",
            "priority": 100,
            "actions": {"derive_scope_tier": True},
        },
    ]


_BUILTIN_PLUGINS: dict[str, Callable[[], list[dict[str, Any]]]] = {
    "bsg_core": _builtin_bsg_core_rules,
}


def list_builtin_plugins() -> list[str]:
    """Return deterministic list of built-in plugin names."""

    return sorted(_BUILTIN_PLUGINS.keys())


def _normalize_rule_dict(raw_rule: dict[str, Any]) -> dict[str, Any]:
    """Support compact YAML shape while normalizing to full rule schema."""

    normalized = dict(raw_rule)

    match_data = normalized.pop("match", {}) or {}
    if not isinstance(match_data, dict):
        raise ValueError("'match' must be a mapping")

    actions_data = normalized.pop("actions", {}) or {}
    if not isinstance(actions_data, dict):
        raise ValueError("'actions' must be a mapping")

    for key in ("entity_types", "name_patterns", "file_patterns"):
        if key in normalized:
            match_data[key] = normalized.pop(key)

    if "metadata" in normalized:
        actions_data.setdefault("metadata", normalized.pop("metadata"))
    if "set_metadata" in normalized:
        actions_data.setdefault("metadata", normalized.pop("set_metadata"))
    if "derive_scope_tier" in normalized:
        actions_data["derive_scope_tier"] = normalized.pop("derive_scope_tier")
    if "derive_service_tag" in normalized:
        actions_data["derive_service_tag"] = normalized.pop("derive_service_tag")

    normalized["match"] = match_data
    normalized["actions"] = actions_data
    return normalized


def _parse_rule(raw_rule: dict[str, Any], plugin_name: str) -> RuleDefinition:
    normalized = _normalize_rule_dict(raw_rule)
    normalized["plugin"] = plugin_name
    return RuleDefinition.model_validate(normalized)


def _read_custom_rules_file(custom_rules_path: Path) -> list[dict[str, Any]]:
    """Load custom rules from YAML. Supports root list or rules: list."""

    data = yaml.safe_load(custom_rules_path.read_text(encoding="utf-8"))
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("rules"), list):
            return data["rules"]
        if "name" in data:
            return [data]
    raise ValueError("Custom rules YAML must be a list or contain a 'rules' list")


def _resolve_custom_rules_path(path_value: str, root_path: Path) -> Path:
    candidate = Path(path_value).expanduser()
    if candidate.is_absolute():
        return candidate
    return (root_path / candidate).resolve()


def load_effective_rules(
    rules_config: dict[str, Any] | None,
    root_path: Path,
    logger: Any | None = None,
) -> tuple[list[RuleDefinition], dict[str, Any]]:
    """Load and validate enabled built-in and custom rules."""

    log = logger or _LOGGER
    cfg = rules_config or {}
    enabled = bool(cfg.get("enabled", False))

    stats: dict[str, Any] = {
        "enabled": enabled,
        "builtin_plugins_requested": 0,
        "builtin_plugins_loaded": 0,
        "rules_loaded": 0,
        "rules_disabled": 0,
        "custom_inline_count": 0,
        "custom_file_count": 0,
        "errors": [],
    }

    if not enabled:
        return [], stats

    strict_validation = bool(cfg.get("strict_validation", False))
    builtin_plugins = cfg.get("builtin_plugins")
    if builtin_plugins is None:
        builtin_plugins = ["bsg_core"]
    disabled_rules = {
        str(name).strip().lower()
        for name in (cfg.get("disabled_rules") or [])
        if str(name).strip()
    }

    rules_by_name: dict[str, RuleDefinition] = {}

    def _handle_error(message: str) -> None:
        stats["errors"].append(message)
        if strict_validation:
            raise ValueError(message)
        log.warning("bsg_rule_validation_error", error=message)

    if not isinstance(builtin_plugins, list):
        _handle_error("rules.builtin_plugins must be a list")
        builtin_plugins = []

    stats["builtin_plugins_requested"] = len(builtin_plugins)
    for plugin_name in builtin_plugins:
        provider = _BUILTIN_PLUGINS.get(str(plugin_name))
        if provider is None:
            _handle_error(f"Unknown built-in rule plugin: {plugin_name}")
            continue

        stats["builtin_plugins_loaded"] += 1
        for raw_rule in provider():
            try:
                parsed_rule = _parse_rule(raw_rule, plugin_name=str(plugin_name))
                rules_by_name[parsed_rule.name] = parsed_rule
            except (ValidationError, ValueError, TypeError) as exc:
                _handle_error(f"Invalid built-in rule in plugin '{plugin_name}': {exc}")

    custom_inline = cfg.get("custom_rules_inline") or []
    if not isinstance(custom_inline, list):
        _handle_error("rules.custom_rules_inline must be a list")
        custom_inline = []

    stats["custom_inline_count"] = len(custom_inline)
    for raw_rule in custom_inline:
        if not isinstance(raw_rule, dict):
            _handle_error("Inline custom rule entries must be mappings")
            continue
        try:
            parsed_rule = _parse_rule(raw_rule, plugin_name="custom_inline")
            rules_by_name[parsed_rule.name] = parsed_rule
        except (ValidationError, ValueError, TypeError) as exc:
            _handle_error(f"Invalid inline custom rule: {exc}")

    custom_rules_path = cfg.get("custom_rules_path")
    if custom_rules_path:
        try:
            resolved_path = _resolve_custom_rules_path(str(custom_rules_path), root_path)
            custom_rules = _read_custom_rules_file(resolved_path)
            stats["custom_file_count"] = len(custom_rules)
            for raw_rule in custom_rules:
                if not isinstance(raw_rule, dict):
                    _handle_error("File custom rule entries must be mappings")
                    continue
                try:
                    parsed_rule = _parse_rule(raw_rule, plugin_name="custom_file")
                    rules_by_name[parsed_rule.name] = parsed_rule
                except (ValidationError, ValueError, TypeError) as exc:
                    _handle_error(f"Invalid file custom rule: {exc}")
        except Exception as exc:  # noqa: BLE001
            _handle_error(f"Failed to load custom rule file '{custom_rules_path}': {exc}")

    effective_rules: list[RuleDefinition] = []
    for rule in sorted(rules_by_name.values(), key=lambda item: (item.priority, item.name.lower())):
        if not rule.enabled:
            stats["rules_disabled"] += 1
            continue
        if rule.name.lower() in disabled_rules:
            stats["rules_disabled"] += 1
            continue
        effective_rules.append(rule)

    stats["rules_loaded"] = len(effective_rules)
    return effective_rules, stats


def _to_relative_posix(file_path: str, root_path: Path) -> str:
    """Best-effort relative path normalization for glob matching."""

    candidate = Path(file_path)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(root_path.resolve()).as_posix()
        except Exception:  # noqa: BLE001
            return candidate.as_posix()
    return candidate.as_posix()


def _pattern_matches(value: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    lowered = value.lower()
    for pattern in patterns:
        if fnmatch.fnmatch(lowered, pattern.lower()):
            return True
    return False


def _matches_rule(rule: RuleDefinition, entity: Entity, rel_file_path: str) -> bool:
    if rule.match.entity_types:
        normalized_types = {item.lower() for item in rule.match.entity_types}
        entity_type = str(entity.type)
        if "*" not in normalized_types and entity_type not in normalized_types:
            return False

    if not _pattern_matches(entity.name, rule.match.name_patterns):
        return False

    if not _pattern_matches(rel_file_path, rule.match.file_patterns):
        return False

    return True


def _derive_scope_tier(entity: Entity) -> str:
    """Map entity shape to one of GLOBAL/MODULE/CLASS/LOCAL tiers."""

    if entity.type in {
        EntityType.MODULE,
        EntityType.NAMESPACE,
        EntityType.ENTRY_POINT,
        EntityType.DOCUMENT,
    }:
        return "GLOBAL"

    if entity.type in {
        EntityType.CLASS,
        EntityType.STRUCT,
        EntityType.INTERFACE,
        EntityType.TRAIT,
        EntityType.ENUM,
        EntityType.SECTION,
    }:
        return "MODULE"

    if entity.type in {EntityType.METHOD, EntityType.FIELD, EntityType.PROPERTY}:
        return "CLASS"

    if entity.parent_id:
        return "LOCAL"

    return "MODULE"


def _derive_service_tag(rel_file_path: str) -> str | None:
    parts = [part for part in Path(rel_file_path).parts if part and part != "."]
    if not parts:
        return None

    for marker in ("services", "service", "apps", "modules"):
        if marker in parts:
            idx = parts.index(marker)
            if idx + 1 < len(parts):
                return parts[idx + 1]

    if len(parts) >= 2 and parts[0] in {"backend", "frontend", "api"}:
        return parts[1]

    return None


def apply_rule_plugins(
    graph: InMemoryGraph,
    root_path: Path,
    rules_config: dict[str, Any] | None,
    logger: Any | None = None,
) -> dict[str, Any]:
    """Apply configured BSG rules in-place and return execution stats."""

    log = logger or _LOGGER
    rules, load_stats = load_effective_rules(rules_config=rules_config, root_path=root_path, logger=log)

    if not load_stats.get("enabled", False):
        return {
            **load_stats,
            "entities_updated": 0,
            "rules_applied": 0,
            "rule_hits": {},
        }

    rule_hits: dict[str, int] = {rule.name: 0 for rule in rules}
    updated_entities = 0

    for entity_id, entity in list(graph.entities.items()):
        rel_file_path = _to_relative_posix(entity.file, root_path)
        metadata = dict(entity.metadata or {})
        matched_rules: list[str] = []
        changed = False

        for rule in rules:
            if not _matches_rule(rule, entity, rel_file_path):
                continue

            matched_rules.append(rule.name)
            rule_hits[rule.name] += 1

            for key, value in rule.actions.metadata.items():
                if metadata.get(key) != value:
                    metadata[key] = value
                    changed = True

            if rule.actions.derive_scope_tier:
                scope_tier = _derive_scope_tier(entity)
                if metadata.get("bsg.scope_tier") != scope_tier:
                    metadata["bsg.scope_tier"] = scope_tier
                    changed = True

            if rule.actions.derive_service_tag:
                service_tag = _derive_service_tag(rel_file_path)
                if service_tag and metadata.get("bsg.service_tag") != service_tag:
                    metadata["bsg.service_tag"] = service_tag
                    changed = True

        if matched_rules:
            existing = metadata.get("bsg.rules")
            existing_list = existing if isinstance(existing, list) else []
            combined = sorted(set(existing_list + matched_rules))
            if existing != combined:
                metadata["bsg.rules"] = combined
                changed = True

        if changed:
            graph.entities[entity_id] = entity.model_copy(update={"metadata": metadata})
            updated_entities += 1

    applied_count = sum(1 for count in rule_hits.values() if count > 0)
    summary = {
        **load_stats,
        "entities_updated": updated_entities,
        "rules_applied": applied_count,
        "rule_hits": {name: count for name, count in sorted(rule_hits.items()) if count > 0},
    }

    log.info(
        "bsg_rules_applied",
        rules_loaded=summary.get("rules_loaded", 0),
        rules_applied=summary["rules_applied"],
        entities_updated=summary["entities_updated"],
    )

    return summary
