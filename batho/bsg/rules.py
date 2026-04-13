"""Rule plugins for Batho Structured Graph (BSG).

This module implements a deterministic plugin loader and rule-application
pipeline backed by JSON Schema validation and a local Green Cache.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import pickle
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

import yaml

try:
    from jsonschema import Draft202012Validator
except Exception:  # pragma: no cover - handled by runtime error in validator init
    Draft202012Validator = None  # type: ignore[assignment]

from batho.config import get_config_cached
from batho.context.storage import register_artifact_for_path
from batho.context.schema import Entity, EntityType, Relationship, RelationshipType
from batho.utils.logging import get_logger

if TYPE_CHECKING:
    from batho.context.codegraph import InMemoryGraph


_LOGGER = get_logger(__name__, component="bsg_rules")

_SCHEMA_VERSION = "bsg-plugin.v1"
_CACHE_SCHEMA_VERSION = "bsg-rules-cache.v1"
_CACHE_FILENAME = "rules_cache.bin"
_INTERCEPTION_SCHEMA_VERSION = "interception-stats.v1"
_INTERCEPTION_FILENAME = "interception_stats.json"

_PLUGIN_ALIASES: dict[str, str] = {
    "bsg_core": "bsg_graph_foundation",
}

_EDGE_ALIASES: dict[str, str] = {
    "INHERITS_FROM": "INHERITS",
}

_API_HINT_TOKENS = {
    "api",
    "route",
    "routes",
    "controller",
    "controllers",
    "endpoint",
    "endpoints",
    "handler",
    "handlers",
    "request",
    "response",
    "graphql",
}

_AUTH_HINT_TOKENS = {
    "auth",
    "oauth",
    "jwt",
    "token",
    "session",
    "guard",
    "permission",
    "authorize",
    "authentication",
    "middleware",
    "security",
}

_ORM_HINT_TOKENS = {
    "orm",
    "model",
    "models",
    "entity",
    "entities",
    "schema",
    "table",
    "column",
    "migration",
}

_DB_HINT_TOKENS = {
    "db",
    "database",
    "query",
    "queries",
    "sql",
    "repo",
    "repository",
    "select",
    "insert",
    "update",
    "delete",
    "find",
    "fetch",
    "execute",
    "cursor",
}

_ENV_HINT_TOKENS = {
    "env",
    "environment",
    "config",
    "setting",
    "settings",
    "secret",
    "token",
    "apikey",
    "api",
    "key",
    "variable",
}

_INFRA_PATH_HINT_TOKENS = {
    "infra",
    "infrastructure",
    "terraform",
    "k8s",
    "kubernetes",
    "helm",
    "deploy",
    "deployment",
    "manifests",
    "docker",
    "iac",
}

_INFRA_FILE_SUFFIXES = {".tf", ".tfvars", ".hcl"}

_LOOP_HINT_TOKENS = {
    "loop",
    "iterate",
    "iterator",
    "batch",
    "foreach",
    "for",
    "while",
}

_RESOURCE_HINT_TOKENS = {
    "open",
    "connect",
    "connection",
    "client",
    "socket",
    "stream",
    "session",
    "resource",
    "acquire",
    "allocate",
    "create",
}

_CLEANUP_HINT_TOKENS = {
    "close",
    "disconnect",
    "release",
    "cleanup",
    "dispose",
    "teardown",
    "shutdown",
    "stop",
}

_EXCEPTION_HINT_TOKENS = {
    "except",
    "catch",
    "handler",
    "rescue",
    "error",
    "fallback",
    "ignore",
    "noop",
}

_KEY_TOKEN_STOPWORDS = {
    "env",
    "environment",
    "config",
    "configuration",
    "variable",
    "variables",
    "setting",
    "settings",
    "key",
    "keys",
    "secret",
    "token",
    "value",
}

_REFERENCED_IN_GENERIC_TOKENS = {
    "app",
    "service",
    "name",
    "env",
    "environment",
    "config",
    "setting",
    "settings",
    "key",
    "secret",
    "token",
    "url",
    "host",
    "port",
    "path",
}

@dataclass(frozen=True)
class ASTEdgeMatcher:
    edge: str
    direction: str = "either"
    target_entity_types: tuple[str, ...] = ()
    target_usn_tags_any: tuple[str, ...] = ()
    target_name_patterns: tuple[str, ...] = ()
    min_count: int = 1


@dataclass(frozen=True)
class MetadataCondition:
    """Condition for matching entity metadata."""
    key: str
    operator: str  # exists, length_gt, contains_any, in, eq
    value: Any = None


@dataclass(frozen=True)
class RuleMatch:
    entity_types: tuple[str, ...] = ()
    name_patterns: tuple[str, ...] = ()
    file_patterns: tuple[str, ...] = ()
    usn_tags_any: tuple[str, ...] = ()
    ast_edges_any: tuple[ASTEdgeMatcher, ...] = ()
    ast_edges_all: tuple[ASTEdgeMatcher, ...] = ()
    metadata_conditions: tuple[MetadataCondition, ...] = ()


@dataclass(frozen=True)
class RuleActions:
    metadata: dict[str, Any] = field(default_factory=dict)
    add_usn_tags: tuple[str, ...] = ()
    derive_scope_tier: bool = False
    derive_service_tag: bool = False
    # BSG Optimization transformations
    truncate_docstring: bool = False
    max_docstring_length: int = 150
    normalize_entry_point: bool = False


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    name: str
    description: str
    severity: str
    priority: int
    enabled: bool
    plugin: str
    match: RuleMatch
    actions: RuleActions

    def to_cache_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "severity": self.severity,
            "priority": self.priority,
            "enabled": self.enabled,
            "plugin": self.plugin,
            "match": {
                "entity_types": list(self.match.entity_types),
                "name_patterns": list(self.match.name_patterns),
                "file_patterns": list(self.match.file_patterns),
                "usn_tags_any": list(self.match.usn_tags_any),
                "metadata_conditions": [
                    {"key": c.key, "operator": c.operator, "value": c.value}
                    for c in self.match.metadata_conditions
                ],
                "ast_edges": {
                    "any": [_edge_matcher_to_dict(item) for item in self.match.ast_edges_any],
                    "all": [_edge_matcher_to_dict(item) for item in self.match.ast_edges_all],
                },
            },
            "actions": {
                "metadata": dict(self.actions.metadata),
                "add_usn_tags": list(self.actions.add_usn_tags),
                "derive_scope_tier": self.actions.derive_scope_tier,
                "derive_service_tag": self.actions.derive_service_tag,
                "truncate_docstring": self.actions.truncate_docstring,
                "max_docstring_length": self.actions.max_docstring_length,
                "normalize_entry_point": self.actions.normalize_entry_point,
            },
        }

    @classmethod
    def from_cache_dict(cls, raw: dict[str, Any]) -> "RuleDefinition":
        normalized = _normalize_rule_dict(raw)
        return _rule_from_plugin_rule(str(raw.get("plugin", "custom")), normalized)


_PLUGIN_SCHEMA_CACHE: dict[str, Any] | None = None
_PLUGIN_VALIDATOR: Any | None = None


def _schema_path() -> Path:
    return Path(__file__).resolve().parent / "schemas" / "bsg-plugin-schema-v1.json"


def _plugins_root() -> Path:
    return Path(__file__).resolve().parent / "plugins"


def _get_plugin_validator() -> Any:
    global _PLUGIN_SCHEMA_CACHE
    global _PLUGIN_VALIDATOR

    if _PLUGIN_VALIDATOR is not None:
        return _PLUGIN_VALIDATOR

    if Draft202012Validator is None:
        raise RuntimeError(
            "jsonschema is required for BSG plugin validation; install the 'jsonschema' package"
        )

    schema_file = _schema_path()
    try:
        _PLUGIN_SCHEMA_CACHE = json.loads(schema_file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Failed to read plugin schema: {schema_file}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid plugin schema JSON at {schema_file}: {exc}") from exc

    _PLUGIN_VALIDATOR = Draft202012Validator(_PLUGIN_SCHEMA_CACHE)
    return _PLUGIN_VALIDATOR


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_file(path: Path) -> str:
    try:
        return _hash_bytes(path.read_bytes())
    except OSError:
        return "__missing__"


def _rules_cache_path(root_path: Path) -> Path:
    ctn_dir_name = str(get_config_cached().get("paths", {}).get("ctn_dir", ".ctn"))
    ctn_dir = root_path / ctn_dir_name
    ctn_dir.mkdir(parents=True, exist_ok=True)
    return ctn_dir / _CACHE_FILENAME


def _interception_stats_path(root_path: Path) -> Path:
    ctn_dir_name = str(get_config_cached().get("paths", {}).get("ctn_dir", ".ctn"))
    ctn_dir = root_path / ctn_dir_name
    ctn_dir.mkdir(parents=True, exist_ok=True)
    return ctn_dir / _INTERCEPTION_FILENAME


def _read_cache(cache_path: Path) -> dict[str, Any] | None:
    if not cache_path.exists():
        return None
    try:
        payload = pickle.loads(cache_path.read_bytes())
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != _CACHE_SCHEMA_VERSION:
        return None
    return payload


def _write_cache(cache_path: Path, payload: dict[str, Any]) -> None:
    tmp_path = cache_path.with_suffix(".tmp")
    tmp_path.write_bytes(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
    tmp_path.replace(cache_path)
    register_artifact_for_path(
        cache_path,
        "rules_cache_binary",
        producer="bsg.rules",
        metadata={"schema_version": payload.get("schema_version", _CACHE_SCHEMA_VERSION)},
        schema_version=_CACHE_SCHEMA_VERSION,
    )


def _plugin_display_name(plugin_id: str) -> str:
    name = plugin_id.strip()
    if name.startswith("bsg_"):
        name = name[4:]
    elif name.startswith("bsg-"):
        name = name[4:]
    words = [item for item in name.replace("-", "_").split("_") if item]
    if not words:
        return plugin_id
    return " ".join(word.capitalize() for word in words)


def _load_interception_stats(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": _INTERCEPTION_SCHEMA_VERSION,
            "plugins": {},
        }

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "schema_version": _INTERCEPTION_SCHEMA_VERSION,
            "plugins": {},
        }

    if not isinstance(payload, dict):
        return {
            "schema_version": _INTERCEPTION_SCHEMA_VERSION,
            "plugins": {},
        }

    plugins = payload.get("plugins")
    if not isinstance(plugins, dict):
        payload["plugins"] = {}

    payload["schema_version"] = _INTERCEPTION_SCHEMA_VERSION
    return payload


def _write_interception_stats(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(path)
    register_artifact_for_path(
        path,
        "interception_stats_json",
        producer="bsg.rules",
        metadata={"schema_version": payload.get("schema_version", _INTERCEPTION_SCHEMA_VERSION)},
        schema_version=_INTERCEPTION_SCHEMA_VERSION,
    )


def _record_interceptions(
    root_path: Path,
    plugin_hits: dict[str, int],
) -> tuple[dict[str, int], str]:
    stats_path = _interception_stats_path(root_path)
    payload = _load_interception_stats(stats_path)
    plugins = payload.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
        payload["plugins"] = plugins

    totals: dict[str, int] = {}
    for plugin_id, hit_count in sorted(plugin_hits.items()):
        if hit_count <= 0:
            continue

        existing = plugins.get(plugin_id)
        if not isinstance(existing, dict):
            existing = {
                "plugin_id": plugin_id,
                "name": _plugin_display_name(plugin_id),
                "interceptions": 0,
            }

        existing["plugin_id"] = plugin_id
        existing["name"] = str(existing.get("name") or _plugin_display_name(plugin_id))
        existing["interceptions"] = int(existing.get("interceptions", 0)) + hit_count
        plugins[plugin_id] = existing
        totals[plugin_id] = int(existing["interceptions"])

    _write_interception_stats(stats_path, payload)
    return totals, stats_path.as_posix()


def _discover_packaged_plugins() -> dict[str, Path]:
    root = _plugins_root()
    if not root.exists():
        return {}

    plugin_paths: dict[str, Path] = {}
    for path in sorted(root.rglob("*.yaml")):
        plugin_paths[path.stem] = path
    for path in sorted(root.rglob("*.yml")):
        plugin_paths[path.stem] = path

    return plugin_paths


def list_builtin_plugins() -> list[str]:
    discovered = set(_discover_packaged_plugins().keys())
    discovered.update(_PLUGIN_ALIASES.keys())
    return sorted(discovered)


def _as_str_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"'{field_name}' must be a list")

    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"'{field_name}' entries must be strings")
        text = item.strip()
        if text:
            result.append(text)
    return result


def _normalize_edge_name(edge: str) -> str:
    return _EDGE_ALIASES.get(edge.upper(), edge.upper())


def _normalize_edge_matcher(raw_matcher: Any) -> dict[str, Any]:
    if isinstance(raw_matcher, str):
        raw_matcher = {"edge": raw_matcher}

    if not isinstance(raw_matcher, dict):
        raise ValueError("ast edge matcher must be a mapping")

    edge = raw_matcher.get("edge")
    if not isinstance(edge, str) or not edge.strip():
        raise ValueError("ast edge matcher requires an 'edge' string")

    direction = raw_matcher.get("direction", "either")
    if not isinstance(direction, str):
        raise ValueError("ast edge matcher direction must be a string")

    min_count = raw_matcher.get("min_count", 1)
    if not isinstance(min_count, int) or min_count < 1:
        raise ValueError("ast edge matcher min_count must be an integer >= 1")

    return {
        "edge": _normalize_edge_name(edge),
        "direction": direction,
        "target_entity_types": _as_str_list(
            raw_matcher.get("target_entity_types"), "target_entity_types"
        ),
        "target_usn_tags_any": _as_str_list(
            raw_matcher.get("target_usn_tags_any"), "target_usn_tags_any"
        ),
        "target_name_patterns": _as_str_list(
            raw_matcher.get("target_name_patterns"), "target_name_patterns"
        ),
        "min_count": min_count,
    }


def _normalize_ast_edges(raw_ast_edges: Any) -> dict[str, list[dict[str, Any]]]:
    if raw_ast_edges is None:
        return {"any": [], "all": []}

    if isinstance(raw_ast_edges, list):
        any_edges = raw_ast_edges
        all_edges: list[Any] = []
    elif isinstance(raw_ast_edges, dict):
        any_edges = raw_ast_edges.get("any") or []
        all_edges = raw_ast_edges.get("all") or []
    else:
        raise ValueError("'ast_edges' must be a list or mapping")

    if not isinstance(any_edges, list) or not isinstance(all_edges, list):
        raise ValueError("'ast_edges.any' and 'ast_edges.all' must be lists")

    return {
        "any": [_normalize_edge_matcher(item) for item in any_edges],
        "all": [_normalize_edge_matcher(item) for item in all_edges],
    }


def _normalize_matchers(raw_matchers: Any) -> dict[str, Any]:
    if raw_matchers is None:
        raw_matchers = {}
    if not isinstance(raw_matchers, dict):
        raise ValueError("'matchers' must be a mapping")

    return {
        "entity_types": _as_str_list(raw_matchers.get("entity_types"), "entity_types"),
        "name_patterns": _as_str_list(raw_matchers.get("name_patterns"), "name_patterns"),
        "file_patterns": _as_str_list(raw_matchers.get("file_patterns"), "file_patterns"),
        "usn_tags_any": _as_str_list(raw_matchers.get("usn_tags_any"), "usn_tags_any"),
        "metadata_conditions": raw_matchers.get("metadata_conditions", []),  # Keep as list for schema validation
        "ast_edges": _normalize_ast_edges(raw_matchers.get("ast_edges")),
    }


def _normalize_actions(raw_actions: Any) -> dict[str, Any]:
    if raw_actions is None:
        raw_actions = {}
    if not isinstance(raw_actions, dict):
        raise ValueError("'actions' must be a mapping")

    metadata = raw_actions.get("metadata")
    if metadata is None:
        metadata = raw_actions.get("set_metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("'actions.metadata' must be a mapping")

    return {
        "metadata": dict(metadata),
        "add_usn_tags": _as_str_list(raw_actions.get("add_usn_tags"), "add_usn_tags"),
        "derive_scope_tier": bool(raw_actions.get("derive_scope_tier", False)),
        "derive_service_tag": bool(raw_actions.get("derive_service_tag", False)),
        # BSG Optimization transformations
        "truncate_docstring": bool(raw_actions.get("truncate_docstring", False)),
        "max_docstring_length": int(raw_actions.get("max_docstring_length", 150)),
        "normalize_entry_point": bool(raw_actions.get("normalize_entry_point", False)),
    }


def _normalize_rule_dict(raw_rule: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_rule, dict):
        raise ValueError("Rule entries must be mappings")

    normalized = dict(raw_rule)

    matchers_raw = normalized.get("matchers")
    if matchers_raw is None:
        matchers_raw = normalized.get("match")
    if matchers_raw is None:
        matchers_raw = {}

    for key in ("entity_types", "name_patterns", "file_patterns", "usn_tags_any", "ast_edges"):
        if key in normalized:
            if not isinstance(matchers_raw, dict):
                raise ValueError("'matchers' must be a mapping")
            matchers_raw[key] = normalized[key]

    actions_raw = normalized.get("actions")
    if actions_raw is None:
        actions_raw = {}
    for key in (
        "metadata",
        "set_metadata",
        "add_usn_tags",
        "derive_scope_tier",
        "derive_service_tag",
    ):
        if key in normalized:
            if not isinstance(actions_raw, dict):
                raise ValueError("'actions' must be a mapping")
            actions_raw[key] = normalized[key]

    rule_name = normalized.get("name") or normalized.get("rule_id")
    if not isinstance(rule_name, str) or not rule_name.strip():
        raise ValueError("Rule requires a non-empty 'name' or 'rule_id'")

    rule_id = normalized.get("rule_id") or rule_name
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise ValueError("Rule requires a non-empty 'rule_id'")

    severity = str(normalized.get("severity", "warning")).lower().strip()
    priority = normalized.get("priority", 0)

    return {
        "rule_id": rule_id.strip(),
        "name": rule_name.strip(),
        "description": str(normalized.get("description", "")),
        "severity": severity,
        "priority": priority,
        "enabled": bool(normalized.get("enabled", True)),
        "matchers": _normalize_matchers(matchers_raw),
        "actions": _normalize_actions(actions_raw),
    }


def _normalize_plugin_document(
    raw_data: Any,
    plugin_id: str,
    fallback_name: str,
) -> dict[str, Any]:
    if isinstance(raw_data, list):
        rules_raw = raw_data
        plugin_meta: dict[str, Any] = {}
    elif isinstance(raw_data, dict):
        plugin_meta = dict(raw_data)
        if isinstance(plugin_meta.get("rules"), list):
            rules_raw = plugin_meta.get("rules") or []
        elif "name" in plugin_meta or "rule_id" in plugin_meta:
            rules_raw = [plugin_meta]
            plugin_meta = {}
        else:
            raise ValueError("Plugin YAML must be a list, a rule mapping, or contain a 'rules' list")
    else:
        raise ValueError("Plugin YAML must be a list or mapping")

    normalized_rules: list[dict[str, Any]] = []
    for raw_rule in rules_raw:
        if not isinstance(raw_rule, dict):
            raise ValueError("Rule entries must be mappings")
        normalized_rules.append(_normalize_rule_dict(raw_rule))

    return {
        "schema_version": str(plugin_meta.get("schema_version", _SCHEMA_VERSION)),
        "plugin_id": str(plugin_meta.get("plugin_id", plugin_id)),
        "name": str(plugin_meta.get("name", fallback_name)),
        "version": str(plugin_meta.get("version", "1.0.0")),
        "enabled": bool(plugin_meta.get("enabled", True)),
        "description": str(plugin_meta.get("description", "")),
        "rules": normalized_rules,
    }


def _json_pointer(path_tokens: list[Any]) -> str:
    if not path_tokens:
        return "$"

    pointer = "$"
    for token in path_tokens:
        if isinstance(token, int):
            pointer = f"{pointer}[{token}]"
        else:
            pointer = f"{pointer}.{token}"
    return pointer


def _find_line_hint(source_text: str, pointer: str) -> int | None:
    if not source_text:
        return None

    if pointer == "$":
        return 1

    lines = source_text.splitlines()
    tokens = [token for token in pointer.replace("$.", "").split(".") if token]
    for token in reversed(tokens):
        if token.endswith("]") and "[" in token:
            token = token.split("[", 1)[0]
        if not token:
            continue
        marker = f"{token}:"
        for idx, line in enumerate(lines, start=1):
            if marker in line:
                return idx

    return None


def _validate_plugin_document(
    plugin_doc: dict[str, Any],
    source_name: str,
    source_text: str,
) -> None:
    validator = _get_plugin_validator()
    errors = sorted(validator.iter_errors(plugin_doc), key=lambda item: list(item.path))
    if not errors:
        return

    first_error = errors[0]
    pointer = _json_pointer(list(first_error.path))
    line_hint = _find_line_hint(source_text, pointer)
    if line_hint is not None:
        raise ValueError(f"{source_name}: line {line_hint}: {first_error.message} ({pointer})")
    raise ValueError(f"{source_name}: {first_error.message} ({pointer})")


def _rule_from_plugin_rule(plugin_name: str, raw_rule: dict[str, Any]) -> RuleDefinition:
    matchers = raw_rule.get("matchers", {})
    ast_edges = matchers.get("ast_edges", {})
    
    # Parse metadata_conditions
    metadata_conditions = []
    for cond in matchers.get("metadata_conditions", []):
        if isinstance(cond, dict):
            metadata_conditions.append(
                MetadataCondition(
                    key=str(cond.get("key", "")),
                    operator=str(cond.get("operator", "exists")),
                    value=cond.get("value"),
                )
            )

    return RuleDefinition(
        rule_id=str(raw_rule["rule_id"]),
        name=str(raw_rule["name"]),
        description=str(raw_rule.get("description", "")),
        severity=str(raw_rule.get("severity", "warning")),
        priority=int(raw_rule.get("priority", 0)),
        enabled=bool(raw_rule.get("enabled", True)),
        plugin=plugin_name,
        match=RuleMatch(
            entity_types=tuple(item.lower() for item in matchers.get("entity_types", [])),
            name_patterns=tuple(matchers.get("name_patterns", [])),
            file_patterns=tuple(matchers.get("file_patterns", [])),
            usn_tags_any=tuple(item.lower() for item in matchers.get("usn_tags_any", [])),
            metadata_conditions=tuple(metadata_conditions),
            ast_edges_any=tuple(_edge_matcher_from_dict(item) for item in ast_edges.get("any", [])),
            ast_edges_all=tuple(_edge_matcher_from_dict(item) for item in ast_edges.get("all", [])),
        ),
        actions=RuleActions(
            metadata=dict(raw_rule.get("actions", {}).get("metadata", {})),
            add_usn_tags=tuple(raw_rule.get("actions", {}).get("add_usn_tags", [])),
            derive_scope_tier=bool(raw_rule.get("actions", {}).get("derive_scope_tier", False)),
            derive_service_tag=bool(raw_rule.get("actions", {}).get("derive_service_tag", False)),
            truncate_docstring=bool(raw_rule.get("actions", {}).get("truncate_docstring", False)),
            max_docstring_length=int(raw_rule.get("actions", {}).get("max_docstring_length", 150)),
            normalize_entry_point=bool(raw_rule.get("actions", {}).get("normalize_entry_point", False)),
        ),
    )


def _edge_matcher_from_dict(raw: dict[str, Any]) -> ASTEdgeMatcher:
    return ASTEdgeMatcher(
        edge=_normalize_edge_name(str(raw.get("edge", ""))),
        direction=str(raw.get("direction", "either")),
        target_entity_types=tuple(
            str(item).lower() for item in raw.get("target_entity_types", []) if str(item).strip()
        ),
        target_usn_tags_any=tuple(
            str(item).lower() for item in raw.get("target_usn_tags_any", []) if str(item).strip()
        ),
        target_name_patterns=tuple(
            str(item) for item in raw.get("target_name_patterns", []) if str(item).strip()
        ),
        min_count=int(raw.get("min_count", 1)),
    )


def _edge_matcher_to_dict(matcher: ASTEdgeMatcher) -> dict[str, Any]:
    return {
        "edge": matcher.edge,
        "direction": matcher.direction,
        "target_entity_types": list(matcher.target_entity_types),
        "target_usn_tags_any": list(matcher.target_usn_tags_any),
        "target_name_patterns": list(matcher.target_name_patterns),
        "min_count": matcher.min_count,
    }


def _rule_to_document(rule: RuleDefinition) -> dict[str, Any]:
    return {
        "rule_id": rule.rule_id,
        "name": rule.name,
        "description": rule.description,
        "severity": rule.severity,
        "priority": rule.priority,
        "enabled": rule.enabled,
        "matchers": {
            "entity_types": list(rule.match.entity_types),
            "name_patterns": list(rule.match.name_patterns),
            "file_patterns": list(rule.match.file_patterns),
            "usn_tags_any": list(rule.match.usn_tags_any),
            "ast_edges": {
                "any": [_edge_matcher_to_dict(item) for item in rule.match.ast_edges_any],
                "all": [_edge_matcher_to_dict(item) for item in rule.match.ast_edges_all],
            },
        },
        "actions": {
            "metadata": dict(rule.actions.metadata),
            "add_usn_tags": list(rule.actions.add_usn_tags),
            "derive_scope_tier": rule.actions.derive_scope_tier,
            "derive_service_tag": rule.actions.derive_service_tag,
        },
    }


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_yaml_with_text(path: Path) -> tuple[Any, str]:
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return data, text


def _resolve_custom_rules_path(path_value: str, root_path: Path) -> Path:
    candidate = Path(path_value).expanduser()
    if candidate.is_absolute():
        return candidate
    return (root_path / candidate).resolve()


def _compute_source_hashes(
    builtin_plugin_paths: list[Path],
    custom_rules_path: Path | None,
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(builtin_plugin_paths, key=lambda item: item.as_posix()):
        hashes[path.as_posix()] = _hash_file(path)
    if custom_rules_path is not None:
        hashes[custom_rules_path.as_posix()] = _hash_file(custom_rules_path)
    return hashes


def _rules_config_fingerprint(rules_config: dict[str, Any], source_hashes: dict[str, str]) -> str:
    relevant = {
        "enabled": bool(rules_config.get("enabled", False)),
        "builtin_plugins": rules_config.get("builtin_plugins"),
        "disabled_rules": rules_config.get("disabled_rules"),
        "custom_rules_path": rules_config.get("custom_rules_path"),
        "custom_rules_inline": rules_config.get("custom_rules_inline"),
        "strict_validation": bool(rules_config.get("strict_validation", False)),
        "plugins_overrides": rules_config.get("plugins_overrides") or {},
        "schema_version": _SCHEMA_VERSION,
        "source_hashes": source_hashes,
    }
    payload = json.dumps(relevant, sort_keys=True, separators=(",", ":"), default=str)
    return _hash_bytes(payload.encode("utf-8"))


def _load_rules_from_cache(cache_payload: dict[str, Any]) -> list[RuleDefinition]:
    raw_rules = cache_payload.get("rules")
    if not isinstance(raw_rules, list):
        return []

    rules: list[RuleDefinition] = []
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            continue
        try:
            rules.append(RuleDefinition.from_cache_dict(raw_rule))
        except Exception:
            continue
    return rules


def _register_rule(
    rules_by_name: dict[str, RuleDefinition],
    rule: RuleDefinition,
    stats: dict[str, Any],
) -> None:
    key = rule.name.lower()
    previous = rules_by_name.get(key)
    if previous is not None:
        stats.setdefault("shadowed_rules", []).append(
            {
                "rule": rule.name,
                "previous_plugin": previous.plugin,
                "new_plugin": rule.plugin,
            }
        )
    rules_by_name[key] = rule


def _plugin_matches(rule_plugin: str, override_plugin: str) -> bool:
    if override_plugin == "*":
        return True

    normalized_override = _PLUGIN_ALIASES.get(override_plugin, override_plugin)
    normalized_plugin = _PLUGIN_ALIASES.get(rule_plugin, rule_plugin)
    return normalized_plugin == normalized_override


def _apply_rule_overrides(
    rules_by_name: dict[str, RuleDefinition],
    overrides: Any,
    strict_validation: bool,
    stats: dict[str, Any],
    logger: Any,
) -> dict[str, RuleDefinition]:
    if not overrides:
        return rules_by_name

    updated = dict(rules_by_name)

    def _handle_error(message: str) -> None:
        stats["errors"].append(message)
        if strict_validation:
            raise ValueError(message)
        logger.warning("bsg_rule_override_error", error=message)

    if not isinstance(overrides, dict):
        _handle_error("plugins.overrides must be a mapping")
        return updated

    for plugin_name, plugin_overrides in overrides.items():
        plugin_key = str(plugin_name)
        if not isinstance(plugin_overrides, dict):
            _handle_error(f"plugins.overrides.{plugin_key} must be a mapping")
            continue

        for rule_name, patch in plugin_overrides.items():
            if not isinstance(patch, dict):
                _handle_error(
                    f"plugins.overrides.{plugin_key}.{rule_name} must be a mapping"
                )
                continue

            lookup = str(rule_name).strip().lower()
            if not lookup:
                _handle_error(f"plugins.overrides.{plugin_key} contains an empty rule name")
                continue

            existing = updated.get(lookup)
            if existing is None or not _plugin_matches(existing.plugin, plugin_key):
                _handle_error(
                    f"Override target not found: plugin={plugin_key} rule={rule_name}"
                )
                continue

            merged_rule = _merge_dict(_rule_to_document(existing), patch)
            try:
                normalized = _normalize_rule_dict(merged_rule)
                wrapper_doc = {
                    "schema_version": _SCHEMA_VERSION,
                    "plugin_id": existing.plugin,
                    "name": existing.plugin,
                    "version": "1.0.0",
                    "enabled": True,
                    "rules": [normalized],
                }
                _validate_plugin_document(wrapper_doc, f"override:{plugin_key}.{rule_name}", "")
                compiled = _rule_from_plugin_rule(existing.plugin, normalized)
            except Exception as exc:
                _handle_error(
                    f"Invalid override for plugin={plugin_key} rule={rule_name}: {exc}"
                )
                continue

            if compiled.name.lower() != lookup:
                updated.pop(lookup, None)
            _register_rule(updated, compiled, stats)
            stats["overrides_applied"] = int(stats.get("overrides_applied", 0)) + 1

    return updated


def load_effective_rules(
    rules_config: dict[str, Any] | None,
    root_path: Path,
    logger: Any | None = None,
) -> tuple[list[RuleDefinition], dict[str, Any]]:
    """Load, validate, and cache enabled built-in and custom rules."""

    log = logger or _LOGGER
    cfg = rules_config or {}
    enabled = bool(cfg.get("enabled", False))
    strict_validation = bool(cfg.get("strict_validation", False))

    cache_path = _rules_cache_path(root_path)

    stats: dict[str, Any] = {
        "enabled": enabled,
        "cache_hit": False,
        "cache_path": cache_path.as_posix(),
        "builtin_plugins_requested": 0,
        "builtin_plugins_loaded": 0,
        "rules_loaded": 0,
        "rules_disabled": 0,
        "custom_inline_count": 0,
        "custom_file_count": 0,
        "overrides_applied": 0,
        "shadowed_rules": [],
        "errors": [],
    }

    if not enabled:
        return [], stats

    disabled_rules = {
        str(name).strip().lower()
        for name in (cfg.get("disabled_rules") or [])
        if str(name).strip()
    }

    builtin_plugins = cfg.get("builtin_plugins")
    if builtin_plugins is None:
        builtin_plugins = ["bsg_core"]

    def _handle_error(message: str) -> None:
        stats["errors"].append(message)
        if strict_validation:
            raise ValueError(message)
        log.warning("bsg_rule_validation_error", error=message)

    if not isinstance(builtin_plugins, list):
        _handle_error("rules.builtin_plugins must be a list")
        builtin_plugins = []

    plugin_catalog = _discover_packaged_plugins()
    selected_plugins: list[tuple[str, str, Path]] = []
    seen_plugins: set[str] = set()

    for raw_name in builtin_plugins:
        alias_name = str(raw_name).strip()
        if not alias_name:
            continue
        canonical_name = _PLUGIN_ALIASES.get(alias_name, alias_name)

        if canonical_name in seen_plugins:
            continue

        plugin_path = plugin_catalog.get(canonical_name)
        if plugin_path is None:
            _handle_error(f"Unknown built-in rule plugin: {alias_name}")
            continue

        selected_plugins.append((alias_name, canonical_name, plugin_path))
        seen_plugins.add(canonical_name)

    stats["builtin_plugins_requested"] = len(builtin_plugins)

    custom_rules_path: Path | None = None
    custom_rules_path_value = cfg.get("custom_rules_path")
    if custom_rules_path_value:
        try:
            custom_rules_path = _resolve_custom_rules_path(str(custom_rules_path_value), root_path)
        except Exception as exc:
            _handle_error(f"Failed to resolve custom rule file '{custom_rules_path_value}': {exc}")

    source_hashes = _compute_source_hashes(
        builtin_plugin_paths=[item[2] for item in selected_plugins],
        custom_rules_path=custom_rules_path,
    )
    config_fingerprint = _rules_config_fingerprint(cfg, source_hashes)

    cache_payload = _read_cache(cache_path)
    if cache_payload is not None:
        if (
            cache_payload.get("config_fingerprint") == config_fingerprint
            and cache_payload.get("source_hashes") == source_hashes
        ):
            cached_rules = _load_rules_from_cache(cache_payload)
            cached_stats = cache_payload.get("load_stats")
            if isinstance(cached_stats, dict):
                stats.update({k: v for k, v in cached_stats.items() if k != "errors"})
                cached_errors = cached_stats.get("errors")
                if isinstance(cached_errors, list):
                    stats["errors"] = cached_errors
            stats["cache_hit"] = True
            stats["rules_loaded"] = len(cached_rules)
            return cached_rules, stats

    rules_by_name: dict[str, RuleDefinition] = {}

    for alias_name, plugin_name, plugin_path in selected_plugins:
        try:
            raw_data, source_text = _read_yaml_with_text(plugin_path)
            plugin_doc = _normalize_plugin_document(raw_data, plugin_name, plugin_name)
            _validate_plugin_document(plugin_doc, plugin_path.as_posix(), source_text)
            if not plugin_doc.get("enabled", True):
                continue

            stats["builtin_plugins_loaded"] += 1
            for raw_rule in plugin_doc.get("rules", []):
                compiled = _rule_from_plugin_rule(plugin_name, raw_rule)
                _register_rule(rules_by_name, compiled, stats)
        except Exception as exc:
            _handle_error(f"Invalid built-in plugin '{alias_name}': {exc}")

    custom_inline = cfg.get("custom_rules_inline") or []
    if not isinstance(custom_inline, list):
        _handle_error("rules.custom_rules_inline must be a list")
        custom_inline = []

    stats["custom_inline_count"] = len(custom_inline)
    if custom_inline:
        try:
            plugin_doc = _normalize_plugin_document(custom_inline, "custom_inline", "custom_inline")
            _validate_plugin_document(plugin_doc, "rules.custom_rules_inline", "")
            for raw_rule in plugin_doc.get("rules", []):
                compiled = _rule_from_plugin_rule("custom_inline", raw_rule)
                _register_rule(rules_by_name, compiled, stats)
        except Exception as exc:
            _handle_error(f"Invalid inline custom rules: {exc}")

    if custom_rules_path is not None:
        try:
            raw_data, source_text = _read_yaml_with_text(custom_rules_path)
            plugin_doc = _normalize_plugin_document(
                raw_data,
                "custom_file",
                custom_rules_path.stem,
            )
            _validate_plugin_document(plugin_doc, custom_rules_path.as_posix(), source_text)
            stats["custom_file_count"] = len(plugin_doc.get("rules", []))
            for raw_rule in plugin_doc.get("rules", []):
                compiled = _rule_from_plugin_rule("custom_file", raw_rule)
                _register_rule(rules_by_name, compiled, stats)
        except yaml.YAMLError as exc:
            line_hint = None
            mark = getattr(exc, "problem_mark", None)
            if mark is not None:
                line_hint = int(mark.line) + 1
            if line_hint is not None:
                _handle_error(
                    f"Failed to parse custom rule file '{custom_rules_path}': line {line_hint}: {exc}"
                )
            else:
                _handle_error(f"Failed to parse custom rule file '{custom_rules_path}': {exc}")
        except Exception as exc:
            _handle_error(f"Failed to load custom rule file '{custom_rules_path}': {exc}")

    rules_by_name = _apply_rule_overrides(
        rules_by_name=rules_by_name,
        overrides=cfg.get("plugins_overrides") or {},
        strict_validation=strict_validation,
        stats=stats,
        logger=log,
    )

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

    cache_to_store = {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "config_fingerprint": config_fingerprint,
        "source_hashes": source_hashes,
        "rules": [rule.to_cache_dict() for rule in effective_rules],
        "load_stats": {
            "enabled": enabled,
            "builtin_plugins_requested": stats.get("builtin_plugins_requested", 0),
            "builtin_plugins_loaded": stats.get("builtin_plugins_loaded", 0),
            "rules_loaded": stats.get("rules_loaded", 0),
            "rules_disabled": stats.get("rules_disabled", 0),
            "custom_inline_count": stats.get("custom_inline_count", 0),
            "custom_file_count": stats.get("custom_file_count", 0),
            "overrides_applied": stats.get("overrides_applied", 0),
            "shadowed_rules": list(stats.get("shadowed_rules", [])),
            "errors": list(stats.get("errors", [])),
        },
    }

    try:
        _write_cache(cache_path, cache_to_store)
    except Exception as exc:
        log.warning("bsg_rule_cache_write_failed", cache_path=cache_path.as_posix(), error=str(exc))

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


def _pattern_matches(value: str, patterns: tuple[str, ...]) -> bool:
    if not patterns:
        return True

    lowered = value.lower()
    for pattern in patterns:
        if fnmatch.fnmatch(lowered, pattern.lower()):
            return True
    return False


def _entity_usn_tags(entity: Entity) -> set[str]:
    metadata = entity.metadata if isinstance(entity.metadata, dict) else {}
    tags = metadata.get("bsg.usn")
    if not isinstance(tags, list):
        return set()
    return {str(item).strip().lower() for item in tags if str(item).strip()}


def _tokenize_identifier(value: str) -> set[str]:
    if not value:
        return set()
    with_spaces = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return {
        token
        for token in re.split(r"[^a-zA-Z0-9]+", with_spaces.lower())
        if token
    }


def _path_token_set(rel_file_path: str) -> set[str]:
    tokens: set[str] = set()
    for part in Path(rel_file_path).parts:
        tokens.update(_tokenize_identifier(part))
    return tokens


def _path_has_hint_tokens(rel_file_path: str, hints: set[str]) -> bool:
    return bool(_path_token_set(rel_file_path).intersection(hints))


def _semantic_tokens_for_entity(entity: Entity, rel_file_path: str) -> set[str]:
    tokens = _tokenize_identifier(entity.name)
    if entity.signature:
        tokens.update(_tokenize_identifier(entity.signature))
    tokens.update(_path_token_set(rel_file_path))
    return tokens


def _semantic_key_tokens(value: str) -> set[str]:
    return {
        token
        for token in _tokenize_identifier(value)
        if len(token) > 2 and token not in _KEY_TOKEN_STOPWORDS
    }


def _infer_semantic_tags(entity: Entity, rel_file_path: str) -> set[str]:
    tokens = _semantic_tokens_for_entity(entity, rel_file_path)
    suffix = Path(rel_file_path).suffix.lower()
    tags: set[str] = set()

    if entity.type in {
        EntityType.FUNCTION,
        EntityType.METHOD,
        EntityType.CLASS,
        EntityType.STRUCT,
        EntityType.INTERFACE,
        EntityType.ENTRY_POINT,
    } and (
        tokens.intersection(_API_HINT_TOKENS)
        or _path_has_hint_tokens(rel_file_path, _API_HINT_TOKENS)
    ):
        tags.add("ApiBoundary")

    if tokens.intersection(_AUTH_HINT_TOKENS) or _path_has_hint_tokens(
        rel_file_path,
        _AUTH_HINT_TOKENS,
    ):
        tags.add("AuthMiddleware")

    if entity.type in {
        EntityType.CLASS,
        EntityType.STRUCT,
        EntityType.INTERFACE,
        EntityType.FIELD,
        EntityType.CONSTANT,
    } and tokens.intersection(_ORM_HINT_TOKENS):
        tags.add("Orm_Model")

    if entity.type in {
        EntityType.CLASS,
        EntityType.STRUCT,
        EntityType.INTERFACE,
        EntityType.SECTION,
        EntityType.SETTING,
        EntityType.CONSTANT,
        EntityType.VARIABLE,
    } and tokens.intersection(_ORM_HINT_TOKENS):
        tags.add("DatabaseSchema")

    if entity.type in {
        EntityType.VARIABLE,
        EntityType.CONSTANT,
        EntityType.SETTING,
        EntityType.FIELD,
        EntityType.PROPERTY,
        EntityType.SECTION,
    } and (
        tokens.intersection(_ENV_HINT_TOKENS)
        or (entity.name.isupper() and "_" in entity.name)
    ):
        tags.add("EnvironmentVariable")

    if suffix in _INFRA_FILE_SUFFIXES or _path_has_hint_tokens(
        rel_file_path,
        _INFRA_PATH_HINT_TOKENS,
    ):
        tags.add("InfrastructureConfig")

    if entity.type in {
        EntityType.FUNCTION,
        EntityType.METHOD,
        EntityType.VARIABLE,
        EntityType.CONSTANT,
        EntityType.FIELD,
        EntityType.PROPERTY,
    } and tokens.intersection(_DB_HINT_TOKENS):
        tags.add("DatabaseExecution")

    if entity.type in {EntityType.FUNCTION, EntityType.METHOD} and tokens.intersection(
        _LOOP_HINT_TOKENS
    ):
        tags.add("LoopStatement")

    if entity.type in {
        EntityType.FUNCTION,
        EntityType.METHOD,
        EntityType.VARIABLE,
        EntityType.CONSTANT,
        EntityType.FIELD,
        EntityType.CLASS,
        EntityType.STRUCT,
    } and tokens.intersection(_RESOURCE_HINT_TOKENS):
        tags.add("ResourceAllocation")

    if entity.type in {EntityType.FUNCTION, EntityType.METHOD} and tokens.intersection(
        _EXCEPTION_HINT_TOKENS
    ):
        tags.add("ExceptionHandler")
        tags.add("CatchClause")

    return tags


def _apply_semantic_usn_tags(graph: InMemoryGraph, root_path: Path) -> int:
    updated = 0

    for entity_id, entity in list(graph.entities.items()):
        rel_file_path = _to_relative_posix(entity.file, root_path)
        inferred = _infer_semantic_tags(entity, rel_file_path)
        if not inferred:
            continue

        metadata = dict(entity.metadata or {})
        existing_raw = metadata.get("bsg.usn")
        existing = {str(item) for item in existing_raw} if isinstance(existing_raw, list) else set()
        merged = sorted(existing | inferred)

        if isinstance(existing_raw, list) and sorted({str(item) for item in existing_raw}) == merged:
            continue

        metadata["bsg.usn"] = merged
        graph.entities[entity_id] = entity.model_copy(update={"metadata": metadata})
        updated += 1

    return updated


def _relationship_type_name(relation: Any) -> str:
    rel_type = getattr(relation, "type", "")
    if hasattr(rel_type, "name"):
        return _normalize_edge_name(str(rel_type.name))
    return _normalize_edge_name(str(rel_type))


def _looks_like_cleanup_target(entity: Entity) -> bool:
    tokens = _tokenize_identifier(entity.name)
    if entity.signature:
        tokens.update(_tokenize_identifier(entity.signature))
    return bool(tokens.intersection(_CLEANUP_HINT_TOKENS))


def _derive_semantic_relations(graph: InMemoryGraph) -> list[Relationship]:
    semantic_relations: list[Relationship] = []
    tags_by_entity = {entity_id: _entity_usn_tags(entity) for entity_id, entity in graph.entities.items()}
    key_tokens_by_entity = {
        entity_id: _semantic_key_tokens(entity.name)
        for entity_id, entity in graph.entities.items()
    }
    seen = {
        (str(rel.source_id), str(rel.target_id), _relationship_type_name(rel))
        for rel in graph.relationships
    }

    def _add(source_id: str, target_id: str, rel_type: RelationshipType, reason: str) -> None:
        if source_id == target_id:
            return
        if source_id not in graph.entities or target_id not in graph.entities:
            return

        key = (source_id, target_id, rel_type.name)
        if key in seen:
            return

        seen.add(key)
        semantic_relations.append(
            Relationship(
                source_id=source_id,
                target_id=target_id,
                type=rel_type,
                metadata={"semantic": True, "reason": reason},
            )
        )

    for relation in graph.relationships:
        source_id = str(getattr(relation, "source_id", ""))
        target_id = str(getattr(relation, "target_id", ""))
        if source_id not in graph.entities or target_id not in graph.entities:
            continue

        source_tags = tags_by_entity.get(source_id, set())
        target_tags = tags_by_entity.get(target_id, set())
        rel_type_name = _relationship_type_name(relation)

        if rel_type_name in {"CALLS", "IMPORTS", "USES"}:
            if "apiboundary" in target_tags:
                _add(source_id, target_id, RelationshipType.DEPENDS_ON_API, "depends_on_api")

            if "apiboundary" in source_tags and "authmiddleware" in target_tags:
                _add(source_id, target_id, RelationshipType.WRAPPED_BY, "wrapped_by_auth")

            if "loopstatement" in source_tags and "databaseexecution" in target_tags:
                _add(target_id, source_id, RelationshipType.CONTAINED_WITHIN, "db_inside_loop_call")

            if "resourceallocation" in source_tags:
                target_entity = graph.get_entity(target_id)
                if target_entity is not None and _looks_like_cleanup_target(target_entity):
                    _add(source_id, target_id, RelationshipType.CLEANED_BY, "resource_cleanup_call")

            if "environmentvariable" in source_tags and "infrastructureconfig" in target_tags:
                _add(source_id, target_id, RelationshipType.REFERENCED_IN, "env_to_infra_reference")

            if "environmentvariable" in target_tags and "infrastructureconfig" in source_tags:
                _add(target_id, source_id, RelationshipType.REFERENCED_IN, "env_to_infra_reference")

        if rel_type_name == "CONTAINS":
            if "loopstatement" in source_tags and "databaseexecution" in target_tags:
                _add(target_id, source_id, RelationshipType.CONTAINED_WITHIN, "db_inside_loop_scope")

    infra_entities = [
        entity_id
        for entity_id, tags in tags_by_entity.items()
        if "infrastructureconfig" in tags
    ]
    env_entities = [
        entity_id
        for entity_id, tags in tags_by_entity.items()
        if "environmentvariable" in tags
    ]

    infra_token_index: dict[str, set[str]] = defaultdict(set)
    infra_tokens_by_id: dict[str, set[str]] = {}
    for infra_id in infra_entities:
        infra_tokens = key_tokens_by_entity.get(infra_id, set())
        infra_tokens_by_id[infra_id] = infra_tokens
        for token in infra_tokens:
            infra_token_index[token].add(infra_id)

    scored_env_cache: dict[tuple[str, ...], list[str]] = {}

    for env_id in env_entities:
        env_tokens = key_tokens_by_entity.get(env_id, set())
        env_key = tuple(sorted(env_tokens))
        best_infra = scored_env_cache.get(env_key)

        if best_infra is None:
            candidate_infra: set[str] = set()
            for token in env_tokens:
                candidate_infra.update(infra_token_index.get(token, set()))

            scored_candidates: list[tuple[int, str]] = []
            for infra_id in candidate_infra:
                infra_tokens = infra_tokens_by_id.get(infra_id, set())
                shared = env_tokens.intersection(infra_tokens)
                if not shared:
                    continue

                strong = {
                    token
                    for token in shared
                    if len(token) >= 4 and token not in _REFERENCED_IN_GENERIC_TOKENS
                }

                # Guardrails: require either multiple shared tokens or at least one
                # non-generic strong token to avoid REFERENCED_IN fan-out.
                if len(shared) < 2 and not strong:
                    continue

                score = (len(shared) * 10) + len(strong)
                scored_candidates.append((score, infra_id))

            best_infra = [
                infra_id
                for _, infra_id in sorted(
                    scored_candidates, key=lambda item: (-item[0], item[1])
                )[:3]
            ]
            scored_env_cache[env_key] = best_infra

        for infra_id in best_infra:
            _add(env_id, infra_id, RelationshipType.REFERENCED_IN, "env_name_overlap")

    return semantic_relations


def _append_semantic_relations(graph: InMemoryGraph, relations: list[Relationship]) -> int:
    if not relations:
        return 0

    existing = {
        (str(rel.source_id), str(rel.target_id), _relationship_type_name(rel))
        for rel in graph.relationships
    }

    added = 0
    for relation in relations:
        key = (relation.source_id, relation.target_id, _relationship_type_name(relation))
        if key in existing:
            continue

        existing.add(key)
        graph.add_relationship(relation)
        added += 1

    return added


def _target_matches_filters(
    target_entity: Entity | None,
    matcher: ASTEdgeMatcher,
) -> bool:
    if target_entity is None:
        if matcher.target_entity_types or matcher.target_usn_tags_any or matcher.target_name_patterns:
            return False
        return True

    if matcher.target_entity_types:
        entity_type = str(target_entity.type).lower()
        if "*" not in matcher.target_entity_types and entity_type not in matcher.target_entity_types:
            return False

    if matcher.target_usn_tags_any:
        target_tags = _entity_usn_tags(target_entity)
        if not target_tags.intersection(set(matcher.target_usn_tags_any)):
            return False

    if matcher.target_name_patterns and not _pattern_matches(target_entity.name, matcher.target_name_patterns):
        return False

    return True


def _count_edge_matches(
    entity_id: str,
    matcher: ASTEdgeMatcher,
    graph: InMemoryGraph,
    outbound: dict[str, list[Any]],
    inbound: dict[str, list[Any]],
) -> int:
    candidates: list[tuple[Any, str]] = []
    if matcher.direction == "outbound":
        candidates.extend(
            (relation, str(getattr(relation, "target_id", "")))
            for relation in outbound.get(entity_id, [])
        )
    elif matcher.direction == "inbound":
        candidates.extend(
            (relation, str(getattr(relation, "source_id", "")))
            for relation in inbound.get(entity_id, [])
        )
    else:
        candidates.extend(
            (relation, str(getattr(relation, "target_id", "")))
            for relation in outbound.get(entity_id, [])
        )
        candidates.extend(
            (relation, str(getattr(relation, "source_id", "")))
            for relation in inbound.get(entity_id, [])
        )

    count = 0
    for relation, other_id in candidates:
        rel_type_name = _normalize_edge_name(
            relation.type.name if hasattr(relation.type, "name") else str(relation.type)
        )
        if rel_type_name != matcher.edge:
            continue

        target_entity = graph.get_entity(other_id)
        if _target_matches_filters(target_entity, matcher):
            count += 1

    return count


def _matches_ast_edges(
    entity_id: str,
    match: RuleMatch,
    graph: InMemoryGraph,
    outbound: dict[str, list[Any]],
    inbound: dict[str, list[Any]],
) -> bool:
    for matcher in match.ast_edges_all:
        if _count_edge_matches(entity_id, matcher, graph, outbound, inbound) < matcher.min_count:
            return False

    if match.ast_edges_any:
        for matcher in match.ast_edges_any:
            if _count_edge_matches(entity_id, matcher, graph, outbound, inbound) >= matcher.min_count:
                return True
        return False

    return True


def _matches_metadata_conditions(
    entity: Entity,
    conditions: tuple[MetadataCondition, ...],
) -> bool:
    """Check if entity metadata matches all conditions."""
    metadata = entity.metadata or {}
    
    for cond in conditions:
        value = metadata.get(cond.key)
        
        if cond.operator == "exists":
            if value is None:
                return False
        elif cond.operator == "length_gt":
            if not isinstance(value, str) or len(value) <= cond.value:
                return False
        elif cond.operator == "contains_any":
            if not isinstance(value, str):
                return False
            if not any(str(marker) in value for marker in cond.value):
                return False
        elif cond.operator == "in":
            if value not in cond.value:
                return False
        elif cond.operator == "eq":
            if value != cond.value:
                return False
        else:
            # Unknown operator - fail safe
            return False
    
    return True


def _matches_rule(
    rule: RuleDefinition,
    entity_id: str,
    entity: Entity,
    rel_file_path: str,
    graph: InMemoryGraph,
    outbound: dict[str, list[Any]],
    inbound: dict[str, list[Any]],
) -> bool:
    if rule.match.entity_types:
        entity_type = str(entity.type).lower()
        if "*" not in rule.match.entity_types and entity_type not in rule.match.entity_types:
            return False

    if rule.match.usn_tags_any:
        entity_tags = _entity_usn_tags(entity)
        if not entity_tags.intersection(set(rule.match.usn_tags_any)):
            return False

    if not _pattern_matches(entity.name, rule.match.name_patterns):
        return False

    if not _pattern_matches(rel_file_path, rule.match.file_patterns):
        return False

    if not _matches_ast_edges(entity_id, rule.match, graph, outbound, inbound):
        return False

    if rule.match.metadata_conditions:
        if not _matches_metadata_conditions(entity, rule.match.metadata_conditions):
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


def apply_semantic_overlay(
    graph: InMemoryGraph,
    root_path: Path,
    logger: Any | None = None,
) -> dict[str, int]:
    """Infer semantic tags and derive semantic relationships in-place.

    This can be applied independently of rule execution to make semantic
    relationships available to downstream indexing and rendering stages.
    """

    log = logger or _LOGGER
    semantic_tags_added = 0
    semantic_edges_added = 0

    try:
        semantic_tags_added = _apply_semantic_usn_tags(graph=graph, root_path=root_path)
        semantic_relations = _derive_semantic_relations(graph)
        semantic_edges_added = _append_semantic_relations(graph=graph, relations=semantic_relations)
    except Exception as exc:
        log.warning("bsg_semantic_overlay_failed", error=str(exc))

    return {
        "semantic_tags_added": semantic_tags_added,
        "semantic_edges_added": semantic_edges_added,
    }


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

    semantic_stats = apply_semantic_overlay(graph=graph, root_path=root_path, logger=log)
    semantic_tags_added = int(semantic_stats.get("semantic_tags_added", 0))
    semantic_edges_added = int(semantic_stats.get("semantic_edges_added", 0))

    outbound: dict[str, list[Any]] = {}
    inbound: dict[str, list[Any]] = {}
    for relation in graph.relationships:
        outbound.setdefault(relation.source_id, []).append(relation)
        inbound.setdefault(relation.target_id, []).append(relation)

    rule_hits: dict[str, int] = {rule.name: 0 for rule in rules}
    updated_entities = 0

    for entity_id, entity in list(graph.entities.items()):
        rel_file_path = _to_relative_posix(entity.file, root_path)
        metadata = dict(entity.metadata or {})
        matched_rules: list[str] = []
        changed = False

        for rule in rules:
            if not _matches_rule(
                rule=rule,
                entity_id=entity_id,
                entity=entity,
                rel_file_path=rel_file_path,
                graph=graph,
                outbound=outbound,
                inbound=inbound,
            ):
                continue

            matched_rules.append(rule.name)
            rule_hits[rule.name] += 1

            for key, value in rule.actions.metadata.items():
                if metadata.get(key) != value:
                    metadata[key] = value
                    changed = True

            if rule.actions.add_usn_tags:
                current_tags = metadata.get("bsg.usn")
                existing = current_tags if isinstance(current_tags, list) else []
                merged_tags = sorted({str(item) for item in existing} | set(rule.actions.add_usn_tags))
                if existing != merged_tags:
                    metadata["bsg.usn"] = merged_tags
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

            # BSG Optimization: Truncate docstring
            if rule.actions.truncate_docstring:
                docstring = metadata.get("docstring")
                if docstring and isinstance(docstring, str):
                    max_len = rule.actions.max_docstring_length
                    if len(docstring) > max_len:
                        metadata["docstring"] = docstring[:max_len] + "..."
                        changed = True

            # BSG Optimization: Normalize entry point
            if rule.actions.normalize_entry_point and entity.type == EntityType.ENTRY_POINT:
                if entity.name != "__main__":
                    # Store original name in metadata
                    metadata["invocation_snippet"] = entity.name
                    # Update entity name - need to track this for later update
                    # Note: We can't modify entity.name directly since it's frozen
                    # We'll need to track this in metadata and handle in a post-processing step
                    metadata["bsg.normalized_name"] = "__main__"
                    changed = True

        if matched_rules:
            existing_rules = metadata.get("bsg.rules")
            existing_list = existing_rules if isinstance(existing_rules, list) else []
            combined = sorted(set(existing_list + matched_rules))
            if existing_rules != combined:
                metadata["bsg.rules"] = combined
                changed = True

        if changed:
            graph.entities[entity_id] = entity.model_copy(update={"metadata": metadata})
            updated_entities += 1

    # Post-processing: Apply entry point name normalization
    # (Must be done after metadata updates since entity names are frozen)
    for entity_id, entity in list(graph.entities.items()):
        normalized_name = entity.metadata.get("bsg.normalized_name") if entity.metadata else None
        if normalized_name and entity.name != normalized_name:
            graph.entities[entity_id] = entity.model_copy(update={"name": normalized_name})

    applied_count = sum(1 for count in rule_hits.values() if count > 0)
    plugin_hits: dict[str, int] = {}
    for rule in rules:
        hit_count = int(rule_hits.get(rule.name, 0))
        if hit_count <= 0:
            continue
        plugin_hits[rule.plugin] = int(plugin_hits.get(rule.plugin, 0)) + hit_count

    interception_totals: dict[str, int] = {}
    interception_stats_path = _interception_stats_path(root_path).as_posix()
    if plugin_hits:
        try:
            interception_totals, interception_stats_path = _record_interceptions(
                root_path=root_path,
                plugin_hits=plugin_hits,
            )
        except Exception as exc:
            log.warning(
                "bsg_interception_stats_write_failed",
                error=str(exc),
                stats_path=interception_stats_path,
            )

    summary = {
        **load_stats,
        "entities_updated": updated_entities,
        "rules_applied": applied_count,
        "semantic_tags_added": semantic_tags_added,
        "semantic_edges_added": semantic_edges_added,
        "plugin_hits": {name: count for name, count in sorted(plugin_hits.items()) if count > 0},
        "rule_hits": {name: count for name, count in sorted(rule_hits.items()) if count > 0},
        "interception_totals": {name: count for name, count in sorted(interception_totals.items())},
        "interception_stats_path": interception_stats_path,
    }

    log.info(
        "bsg_rules_applied",
        rules_loaded=summary.get("rules_loaded", 0),
        rules_applied=summary["rules_applied"],
        entities_updated=summary["entities_updated"],
        cache_hit=summary.get("cache_hit", False),
    )

    return summary
