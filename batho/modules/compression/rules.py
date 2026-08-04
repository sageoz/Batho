"""Rule plugins for Batho Structured Graph (BSG).

This module implements a deterministic plugin loader and rule-application
pipeline backed by JSON Schema validation and a local Green Cache.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

try:
    from jsonschema import Draft202012Validator
except Exception:  # pragma: no cover - handled by runtime error in validator init
    Draft202012Validator = None  # type: ignore[assignment]

from batho.core.schemas import Entity, EntityType, Relationship, RelationshipType

from batho.utils.logging import get_logger
from batho.utils.path_sanitizer import PathSecurityError, sanitize_path

if TYPE_CHECKING:
    from batho.modules.graph.builder.protocol import GraphBackend


_LOGGER = get_logger(__name__, component="bsg_rules")

_SCHEMA_VERSION = "bsg-plugin.v2"
_CACHE_SCHEMA_VERSION = "bsg-rules-cache.v2"
_CACHE_FILENAME = "rules_cache.bin"

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
    target_metadata_equals: tuple[tuple[str, Any], ...] = ()
    min_count: int = 1

    _target_entity_types_set: set[str] = field(init=False, repr=False, compare=False, default_factory=set)
    _target_usn_tags_any_set: set[str] = field(init=False, repr=False, compare=False, default_factory=set)
    _target_name_patterns_lower: tuple[str, ...] = field(init=False, repr=False, compare=False, default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_target_entity_types_set", set(self.target_entity_types))
        object.__setattr__(self, "_target_usn_tags_any_set", set(self.target_usn_tags_any))
        object.__setattr__(self, "_target_name_patterns_lower", tuple(p.lower() for p in self.target_name_patterns))



@dataclass(frozen=True)
class MetadataCondition:
    """Condition for matching entity metadata.

    Supported operators: exists, length_gt, length_lt, contains_any,
    contains_all, in, not_in, eq, neq, regex_match.
    """

    key: str
    operator: str
    value: Any = None


@dataclass(frozen=True)
class RegexMatcher:
    """Compiled regex matcher applied to an entity field."""

    pattern: str
    target: str = "name"  # name | file_path | signature | metadata
    metadata_key: str | None = None
    case_insensitive: bool = True


@dataclass(frozen=True)
class WhenClause:
    """Condition gate evaluated before action side-effects fire."""

    all_: tuple[MetadataCondition, ...] = ()
    any_: tuple[MetadataCondition, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.all_ and not self.any_


@dataclass(frozen=True)
class RuleMatch:
    entity_types: tuple[str, ...] = ()
    name_patterns: tuple[str, ...] = ()
    file_patterns: tuple[str, ...] = ()
    content_patterns: tuple[str, ...] = ()
    regex_patterns: tuple[RegexMatcher, ...] = ()
    usn_tags_any: tuple[str, ...] = ()
    ast_edges_any: tuple[ASTEdgeMatcher, ...] = ()
    ast_edges_all: tuple[ASTEdgeMatcher, ...] = ()
    metadata_conditions: tuple[MetadataCondition, ...] = ()
    # Bidirectional matchers (v2)
    gap_entity_types: tuple[str, ...] = ()
    has_raw_content: bool | None = None
    has_coverage_gap: bool | None = None
    byte_range_start: int | None = None
    byte_range_end: int | None = None
    content_hash_pattern: str | None = None

    _entity_types_set: set[str] = field(init=False, repr=False, compare=False, default_factory=set)
    _usn_tags_any_set: set[str] = field(init=False, repr=False, compare=False, default_factory=set)
    _name_patterns_lower: tuple[str, ...] = field(init=False, repr=False, compare=False, default_factory=tuple)
    _file_patterns_lower: tuple[str, ...] = field(init=False, repr=False, compare=False, default_factory=tuple)
    _gap_entity_types_lower: tuple[str, ...] = field(init=False, repr=False, compare=False, default_factory=tuple)
    _compiled_hash_pattern: "re.Pattern[str] | None" = field(init=False, repr=False, compare=False, default=None)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_entity_types_set", set(self.entity_types))
        object.__setattr__(self, "_usn_tags_any_set", set(self.usn_tags_any))
        object.__setattr__(self, "_name_patterns_lower", tuple(p.lower() for p in self.name_patterns))
        object.__setattr__(self, "_file_patterns_lower", tuple(p.lower() for p in self.file_patterns))
        object.__setattr__(self, "_gap_entity_types_lower", tuple(t.lower() for t in self.gap_entity_types))
        if self.content_hash_pattern is not None:
            if not _is_safe_regex(self.content_hash_pattern):
                raise ValueError(
                    f"Dangerous/complex content_hash_pattern regex rejected to prevent ReDoS: {self.content_hash_pattern!r}"
                )
            try:
                compiled = re.compile(self.content_hash_pattern)
                object.__setattr__(self, "_compiled_hash_pattern", compiled)
            except re.error as exc:
                raise ValueError(
                    f"Invalid content_hash_pattern regex {self.content_hash_pattern!r}: {exc}"
                ) from exc



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
    # Detection actions
    detect_language: dict[str, Any] = field(default_factory=dict)
    detect_framework: dict[str, Any] = field(default_factory=dict)
    detect_package_manager: dict[str, Any] = field(default_factory=dict)
    detect_infra: dict[str, Any] = field(default_factory=dict)
    assign_category: dict[str, Any] = field(default_factory=dict)
    # Conditional action gate: suppresses actions when clause does not match.
    when: WhenClause = field(default_factory=WhenClause)
    # Bidirectional actions (v2)
    verify_coverage: bool = False
    verify_integrity: bool = False
    add_reconstruction_metadata: dict[str, Any] = field(default_factory=dict)
    flag_for_reconstruction: bool = False
    apply_token_budget: int | None = None



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
    score: int = 0
    tags: tuple[str, ...] = ()
    schema_version: str = _SCHEMA_VERSION
    bidirectional: bool = False

    def to_cache_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "severity": self.severity,
            "score": self.score,
            "tags": list(self.tags),
            "schema_version": self.schema_version,
            "priority": self.priority,
            "enabled": self.enabled,
            "plugin": self.plugin,
            "bidirectional": self.bidirectional,
            "match": {
                "entity_types": list(self.match.entity_types),
                "name_patterns": list(self.match.name_patterns),
                "file_patterns": list(self.match.file_patterns),
                "content_patterns": list(self.match.content_patterns),
                "regex_patterns": [
                    _regex_matcher_to_dict(item) for item in self.match.regex_patterns
                ],
                "usn_tags_any": list(self.match.usn_tags_any),
                "metadata_conditions": [
                    {"key": c.key, "operator": c.operator, "value": c.value}
                    for c in self.match.metadata_conditions
                ],
                "ast_edges": {
                    "any": [
                        _edge_matcher_to_dict(item) for item in self.match.ast_edges_any
                    ],
                    "all": [
                        _edge_matcher_to_dict(item) for item in self.match.ast_edges_all
                    ],
                },
                # Bidirectional matchers (v2)
                "gap_entity_types": list(self.match.gap_entity_types),
                "has_raw_content": self.match.has_raw_content,
                "has_coverage_gap": self.match.has_coverage_gap,
                "byte_range_start": self.match.byte_range_start,
                "byte_range_end": self.match.byte_range_end,
                "content_hash_pattern": self.match.content_hash_pattern,
            },
            "actions": {
                "metadata": dict(self.actions.metadata),
                "add_usn_tags": list(self.actions.add_usn_tags),
                "derive_scope_tier": self.actions.derive_scope_tier,
                "derive_service_tag": self.actions.derive_service_tag,
                "truncate_docstring": self.actions.truncate_docstring,
                "max_docstring_length": self.actions.max_docstring_length,
                "normalize_entry_point": self.actions.normalize_entry_point,
                "detect_language": dict(self.actions.detect_language),
                "detect_framework": dict(self.actions.detect_framework),
                "detect_package_manager": dict(self.actions.detect_package_manager),
                "detect_infra": dict(self.actions.detect_infra),
                "assign_category": dict(self.actions.assign_category),
                "when": _when_clause_to_dict(self.actions.when),
                # Bidirectional actions (v2)
                "verify_coverage": self.actions.verify_coverage,
                "verify_integrity": self.actions.verify_integrity,
                "add_reconstruction_metadata": dict(self.actions.add_reconstruction_metadata),
                "flag_for_reconstruction": self.actions.flag_for_reconstruction,
                "apply_token_budget": self.actions.apply_token_budget,
            },
        }

    @classmethod
    def from_cache_dict(cls, raw: dict[str, Any]) -> "RuleDefinition":
        normalized = _normalize_rule_dict(raw)
        schema_version = str(raw.get("schema_version", _SCHEMA_VERSION))
        return _rule_from_plugin_rule(
            str(raw.get("plugin", "custom")),
            normalized,
            schema_version=schema_version,
            plugin_bidirectional=bool(raw.get("bidirectional", False)),
        )


_PLUGIN_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}
_PLUGIN_VALIDATORS: dict[str, Any] = {}
_PLUGIN_VALIDATOR_LOCK: threading.Lock = threading.Lock()


def _schema_path() -> Path:
    return (
        Path(__file__).resolve().parent
        / "schemas"
        / "bsg-plugin-schema-v2.json"
    )


def _schema_v1_path() -> Path:
    return (
        Path(__file__).resolve().parent
        / "schemas"
        / "bsg-plugin-schema-v1.json"
    )


def _plugins_root() -> Path:
    return Path(__file__).resolve().parent / "plugins"


def _get_plugin_validator(schema_version: str = _SCHEMA_VERSION) -> Any:
    """Return a cached JSON Schema validator for the plugin schema.

    Thread-safe: uses double-checked locking so the validator is built at most
    once per schema version even under concurrent BSG build calls.
    """

    if schema_version not in (_SCHEMA_VERSION, "bsg-plugin.v1"):
        raise ValueError(
            f"Unsupported plugin schema_version '{schema_version}'. "
            f"Expected '{_SCHEMA_VERSION}' or 'bsg-plugin.v1'."
        )

    validator = _PLUGIN_VALIDATORS.get(schema_version)
    if validator is not None:
        return validator

    with _PLUGIN_VALIDATOR_LOCK:
        validator = _PLUGIN_VALIDATORS.get(schema_version)
        if validator is not None:
            return validator

        if Draft202012Validator is None:
            raise RuntimeError(
                "jsonschema is required for BSG plugin validation; install the 'jsonschema' package"
            )

        schema_file = _schema_v1_path() if schema_version == "bsg-plugin.v1" else _schema_path()
        try:
            schema_doc = json.loads(schema_file.read_text(encoding="utf-8"))
        except OSError as exc:
            raise RuntimeError(f"Failed to read plugin schema: {schema_file}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Invalid plugin schema JSON at {schema_file}: {exc}"
            ) from exc

        _PLUGIN_SCHEMA_CACHE[schema_version] = schema_doc
        validator = Draft202012Validator(schema_doc)
        _PLUGIN_VALIDATORS[schema_version] = validator
        return validator


def _detect_plugin_schema_version(raw_data: Any) -> str:
    """Best-effort schema version detection from a raw plugin YAML payload."""

    if isinstance(raw_data, dict):
        declared = raw_data.get("schema_version")
        if isinstance(declared, str) and declared.strip():
            return declared.strip()
    return _SCHEMA_VERSION


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_file(path: Path) -> str:
    try:
        return _hash_bytes(path.read_bytes())
    except OSError:
        return "__missing__"


def _rules_cache_path(root_path: Path) -> Path:
    from batho.core.config.loader import get_config_with_root
    try:
        cfg = get_config_with_root(root_path)
        cache_dir = cfg.get("paths", {}).get("cache_dir")
    except Exception:
        cache_dir = ".batho/cache"
    cache_path = root_path / cache_dir
    cache_path.mkdir(parents=True, exist_ok=True)
    return cache_path / _CACHE_FILENAME






def _read_cache(cache_path: Path) -> dict[str, Any] | None:
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != _CACHE_SCHEMA_VERSION:
        return None
    return payload


def _write_cache(cache_path: Path, payload: dict[str, Any]) -> None:
    """Write cache atomically using tempfile + os.replace to avoid race conditions.

    Uses batho.utils.file_io.write_atomically for proper multiprocessing safety.
    """
    from batho.utils.file_io import write_atomically
    success = write_atomically(
        cache_path,
        payload,
        is_json=True,
        indent=None,  # Compact JSON for cache
        ensure_parent=True,
    )
    if not success:
        raise OSError(f"Failed to write cache atomically to {cache_path}")


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


def _as_dict(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"'{field_name}' must be a mapping")
    return dict(value)


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

    normalized: dict[str, Any] = {
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

    target_metadata_equals = raw_matcher.get("target_metadata_equals")
    if target_metadata_equals is not None:
        if not isinstance(target_metadata_equals, dict):
            raise ValueError("target_metadata_equals must be a mapping")
        normalized["target_metadata_equals"] = dict(target_metadata_equals)

    return normalized


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


def _normalize_regex_matchers(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("'regex_patterns' must be a list")

    normalized: list[dict[str, Any]] = []
    allowed_targets = {"name", "file_path", "signature", "metadata"}
    for item in raw:
        if isinstance(item, str):
            item = {"pattern": item}
        if not isinstance(item, dict):
            raise ValueError("each regex_patterns entry must be a mapping or string")
        pattern = item.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError("regex_patterns entry requires a non-empty 'pattern'")
        target = str(item.get("target", "name")).strip() or "name"
        if target not in allowed_targets:
            raise ValueError(
                f"regex_patterns.target must be one of {sorted(allowed_targets)}"
            )
        metadata_key = item.get("metadata_key")
        if target == "metadata" and (
            not isinstance(metadata_key, str) or not metadata_key.strip()
        ):
            raise ValueError(
                "regex_patterns with target='metadata' require a 'metadata_key'"
            )
        case_insensitive = bool(item.get("case_insensitive", True))
        entry: dict[str, Any] = {
            "pattern": pattern,
            "target": target,
            "case_insensitive": case_insensitive,
        }
        if isinstance(metadata_key, str) and metadata_key.strip():
            entry["metadata_key"] = metadata_key.strip()
        normalized.append(entry)
    return normalized


def _normalize_matchers(raw_matchers: Any) -> dict[str, Any]:
    if raw_matchers is None:
        raw_matchers = {}
    if not isinstance(raw_matchers, dict):
        raise ValueError("'matchers' must be a mapping")

    result: dict[str, Any] = {
        "entity_types": _as_str_list(raw_matchers.get("entity_types"), "entity_types"),
        "name_patterns": _as_str_list(
            raw_matchers.get("name_patterns"), "name_patterns"
        ),
        "file_patterns": _as_str_list(
            raw_matchers.get("file_patterns"), "file_patterns"
        ),
        "content_patterns": _as_str_list(
            raw_matchers.get("content_patterns"), "content_patterns"
        ),
        "usn_tags_any": _as_str_list(raw_matchers.get("usn_tags_any"), "usn_tags_any"),
        "metadata_conditions": raw_matchers.get(
            "metadata_conditions", []
        ),  # Keep as list for schema validation
        "ast_edges": _normalize_ast_edges(raw_matchers.get("ast_edges")),
    }

    # Only include regex_patterns when explicitly declared so the normalised
    # document stays minimal for plugins that don't use them.
    if raw_matchers.get("regex_patterns") is not None:
        result["regex_patterns"] = _normalize_regex_matchers(
            raw_matchers.get("regex_patterns")
        )

    # Bidirectional matchers (v2 only)
    if raw_matchers.get("gap_entity_types") is not None:
        result["gap_entity_types"] = _as_str_list(raw_matchers.get("gap_entity_types"), "gap_entity_types")
    if raw_matchers.get("has_raw_content") is not None:
        result["has_raw_content"] = raw_matchers.get("has_raw_content")
    if raw_matchers.get("has_coverage_gap") is not None:
        result["has_coverage_gap"] = raw_matchers.get("has_coverage_gap")
    if raw_matchers.get("byte_range_start") is not None:
        result["byte_range_start"] = raw_matchers.get("byte_range_start")
    if raw_matchers.get("byte_range_end") is not None:
        result["byte_range_end"] = raw_matchers.get("byte_range_end")
    if raw_matchers.get("content_hash_pattern") is not None:
        result["content_hash_pattern"] = raw_matchers.get("content_hash_pattern")

    return result


def _normalize_when_clause(raw: Any) -> dict[str, Any]:
    """Normalize an `actions.when` block into schema-compatible dict form."""

    if raw is None:
        return {"all": [], "any": []}
    if not isinstance(raw, dict):
        raise ValueError("'actions.when' must be a mapping")

    all_list = raw.get("all") or []
    any_list = raw.get("any") or []
    if not isinstance(all_list, list) or not isinstance(any_list, list):
        raise ValueError("'actions.when.all' and 'actions.when.any' must be lists")

    def _coerce(conditions: list[Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for cond in conditions:
            if not isinstance(cond, dict):
                raise ValueError("actions.when conditions must be mappings")
            out.append(dict(cond))
        return out

    return {
        "all": _coerce(all_list),
        "any": _coerce(any_list),
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

    result: dict[str, Any] = {
        "metadata": dict(metadata),
        "add_usn_tags": _as_str_list(raw_actions.get("add_usn_tags"), "add_usn_tags"),
        "derive_scope_tier": bool(raw_actions.get("derive_scope_tier", False)),
        "derive_service_tag": bool(raw_actions.get("derive_service_tag", False)),
        # BSG Optimization transformations
        "truncate_docstring": bool(raw_actions.get("truncate_docstring", False)),
        "max_docstring_length": int(raw_actions.get("max_docstring_length", 150)),
        "normalize_entry_point": bool(raw_actions.get("normalize_entry_point", False)),
        # Detection actions
        "detect_language": _as_dict(
            raw_actions.get("detect_language"), "detect_language"
        ),
        "detect_framework": _as_dict(
            raw_actions.get("detect_framework"), "detect_framework"
        ),
        "detect_package_manager": _as_dict(
            raw_actions.get("detect_package_manager"), "detect_package_manager"
        ),
        "detect_infra": _as_dict(raw_actions.get("detect_infra"), "detect_infra"),
        "assign_category": _as_dict(
            raw_actions.get("assign_category"), "assign_category"
        ),
    }

    # Bidirectional actions (v2 only)
    if raw_actions.get("verify_coverage") is not None:
        result["verify_coverage"] = bool(raw_actions.get("verify_coverage"))
    if raw_actions.get("verify_integrity") is not None:
        result["verify_integrity"] = bool(raw_actions.get("verify_integrity"))
    if raw_actions.get("add_reconstruction_metadata") is not None:
        result["add_reconstruction_metadata"] = dict(raw_actions.get("add_reconstruction_metadata"))
    if raw_actions.get("flag_for_reconstruction") is not None:
        result["flag_for_reconstruction"] = bool(raw_actions.get("flag_for_reconstruction"))
    if raw_actions.get("apply_token_budget") is not None:
        result["apply_token_budget"] = int(raw_actions.get("apply_token_budget"))

    # Preserve the `when` block only when declared so the normalised document
    # stays minimal for plugins that don't use action gates.
    if raw_actions.get("when") is not None:
        result["when"] = _normalize_when_clause(raw_actions.get("when"))

    return result


def _normalize_rule_dict(raw_rule: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_rule, dict):
        raise ValueError("Rule entries must be mappings")

    normalized = dict(raw_rule)

    # Normalize severity aliases before schema validation so that
    # "warn" -> "warning" and "error"/"critical" -> "block".
    sev_raw = normalized.get("severity")
    if isinstance(sev_raw, str):
        sev_lower = sev_raw.lower().strip()
        if sev_lower in ("warn", "warning"):
            normalized["severity"] = "warning"
        elif sev_lower in ("error", "critical", "block"):
            normalized["severity"] = "block"
        elif sev_lower == "info":
            normalized["severity"] = "info"

    matchers_raw = normalized.get("matchers")
    if matchers_raw is None:
        matchers_raw = normalized.get("match")
    if matchers_raw is None:
        matchers_raw = {}

    for key in (
        "entity_types",
        "name_patterns",
        "file_patterns",
        "content_patterns",
        "usn_tags_any",
        "metadata_conditions",
        "ast_edges",
        "regex_patterns",
        "gap_entity_types",
        "has_raw_content",
        "has_coverage_gap",
        "byte_range_start",
        "byte_range_end",
        "content_hash_pattern",
    ):
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
        "truncate_docstring",
        "max_docstring_length",
        "normalize_entry_point",
        "detect_language",
        "detect_framework",
        "detect_package_manager",
        "detect_infra",
        "assign_category",
        "verify_coverage",
        "verify_integrity",
        "add_reconstruction_metadata",
        "flag_for_reconstruction",
        "apply_token_budget",
        "when",
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

    score_raw = normalized.get("score")
    has_score = score_raw is not None
    if has_score:
        try:
            score = int(score_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Rule '{rule_id}' has invalid 'score': {exc}") from exc
        if score < 0 or score > 1000:
            raise ValueError(
                f"Rule '{rule_id}' score must be between 0 and 1000 (got {score})"
            )
    else:
        score = 0

    tags_raw = normalized.get("tags")
    has_tags = tags_raw is not None
    tags_list = _as_str_list(tags_raw, "tags") if has_tags else []

    result: dict[str, Any] = {
        "rule_id": rule_id.strip(),
        "name": rule_name.strip(),
        "description": str(normalized.get("description", "")),
        "severity": severity,
        "priority": priority,
        "enabled": bool(normalized.get("enabled", True)),
        "matchers": _normalize_matchers(matchers_raw),
        "actions": _normalize_actions(actions_raw),
    }
    if "bidirectional" in normalized:
        result["bidirectional"] = bool(normalized["bidirectional"])
    # Only emit optional fields when they are explicitly declared, so the
    # normalised document mirrors the source plugin faithfully.
    if has_score:
        result["score"] = score
    if has_tags:
        result["tags"] = tags_list
    return result


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
            raise ValueError(
                "Plugin YAML must be a list, a rule mapping, or contain a 'rules' list"
            )
    else:
        raise ValueError("Plugin YAML must be a list or mapping")

    normalized_rules: list[dict[str, Any]] = []
    for raw_rule in rules_raw:
        if not isinstance(raw_rule, dict):
            raise ValueError("Rule entries must be mappings")
        normalized_rules.append(_normalize_rule_dict(raw_rule))

    schema_version = str(plugin_meta.get("schema_version", _SCHEMA_VERSION))
    doc: dict[str, Any] = {
        "schema_version": schema_version,
        "plugin_id": str(plugin_meta.get("plugin_id", plugin_id)),
        "name": str(plugin_meta.get("name", fallback_name)),
        "version": str(plugin_meta.get("version", "1.0.0")),
        "enabled": bool(plugin_meta.get("enabled", True)),
        "description": str(plugin_meta.get("description", "")),
        "rules": normalized_rules,
    }
    if "bidirectional" in plugin_meta:
        doc["bidirectional"] = bool(plugin_meta["bidirectional"])

    depends_on_raw = plugin_meta.get("depends_on")
    if depends_on_raw is not None:
        doc["depends_on"] = _as_str_list(depends_on_raw, "depends_on")

    return doc


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
    schema_version: str | None = None,
) -> None:
    target_version = schema_version or str(
        plugin_doc.get("schema_version", _SCHEMA_VERSION)
    )
    if target_version != _SCHEMA_VERSION:
        raise ValueError(
            f"{source_name}: unsupported schema_version '{target_version}'. "
            f"Expected '{_SCHEMA_VERSION}'."
        )

    validator = _get_plugin_validator(target_version)
    errors = sorted(validator.iter_errors(plugin_doc), key=lambda item: list(item.path))
    if not errors:
        return

    first_error = errors[0]
    pointer = _json_pointer(list(first_error.path))
    line_hint = _find_line_hint(source_text, pointer)
    if line_hint is not None:
        raise ValueError(
            f"{source_name}: line {line_hint}: {first_error.message} ({pointer})"
        )
    raise ValueError(f"{source_name}: {first_error.message} ({pointer})")


def _metadata_conditions_from_list(raw_list: Any) -> tuple[MetadataCondition, ...]:
    conditions: list[MetadataCondition] = []
    for cond in raw_list or []:
        if not isinstance(cond, dict):
            continue
        conditions.append(
            MetadataCondition(
                key=str(cond.get("key", "")),
                operator=str(cond.get("operator", "exists")),
                value=cond.get("value"),
            )
        )
    return tuple(conditions)


def _split_alternatives(text: str) -> list[str]:
    alts = []
    current = []
    depth = 0
    in_class = False
    skip = False
    for c in text:
        if skip:
            current.append(c)
            skip = False
            continue
        if c == '\\':
            current.append(c)
            skip = True
            continue
        if in_class:
            if c == ']':
                in_class = False
            current.append(c)
            continue
        if c == '[':
            in_class = True
            current.append(c)
            continue
        if c == '(':
            depth += 1
            current.append(c)
            continue
        if c == ')':
            depth -= 1
            current.append(c)
            continue
        if c == '|' and depth == 0:
            alts.append("".join(current))
            current = []
        else:
            current.append(c)
    alts.append("".join(current))
    return alts


def _is_safe_regex(pattern: str) -> bool:
    if len(pattern) > 250:
        return False

    stack = []
    skip_next = False
    in_char_class = False
    
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if skip_next:
            skip_next = False
            i += 1
            continue
        if char == '\\':
            # Skip the next character — it is the escaped literal, not a metachar.
            skip_next = True
            i += 1
            continue

        if in_char_class:
            if char == ']':
                in_char_class = False
            i += 1
            continue

        if char == '[':
            in_char_class = True
            i += 1
            continue

        if char == '(':
            stack.append({'has_quantifier': False, 'start_idx': i})
        elif char == ')':
            if stack:
                group_info = stack.pop()
                next_char = None
                if i + 1 < len(pattern):
                    next_char = pattern[i+1]

                is_group_quantified = next_char in ('*', '+', '?') or (next_char == '{')

                if group_info['has_quantifier'] and is_group_quantified:
                    return False

                if is_group_quantified:
                    group_text = pattern[group_info['start_idx'] + 1 : i]
                    alts = _split_alternatives(group_text)
                    if len(alts) > 1:
                        cleaned_alts = []
                        for alt in alts:
                            alt_stripped = alt.lstrip('^$()[]\\')
                            if alt_stripped:
                                cleaned_alts.append(alt_stripped)
                        for idx1, alt1 in enumerate(cleaned_alts):
                            for idx2, alt2 in enumerate(cleaned_alts):
                                if idx1 != idx2 and (alt2.startswith(alt1) or alt1.startswith(alt2)):
                                    return False

                if stack and (group_info['has_quantifier'] or is_group_quantified):
                    stack[-1]['has_quantifier'] = True
        elif char in ('*', '+', '?', '{'):
            if stack:
                stack[-1]['has_quantifier'] = True

        i += 1

    # Count overall quantifiers (non-escaped, outside char classes)
    quantifier_count = 0
    skip_next = False
    in_char_class = False
    for char in pattern:
        if skip_next:
            skip_next = False
            continue
        if char == '\\':
            skip_next = True
            continue
        if in_char_class:
            if char == ']':
                in_char_class = False
            continue
        if char == '[':
            in_char_class = True
            continue
        if char in ('*', '+', '?', '{'):
            quantifier_count += 1

    if quantifier_count > 8:
        return False

    return True


def _regex_matcher_from_dict(raw: dict[str, Any]) -> RegexMatcher:
    pattern = str(raw.get("pattern", ""))
    if not _is_safe_regex(pattern):
        raise ValueError(f"Dangerous/complex regex pattern rejected to prevent ReDoS: {pattern!r}")
    return RegexMatcher(
        pattern=pattern,
        target=str(raw.get("target", "name") or "name"),
        metadata_key=(
            str(raw.get("metadata_key")).strip()
            if isinstance(raw.get("metadata_key"), str) and raw.get("metadata_key").strip()
            else None
        ),
        case_insensitive=bool(raw.get("case_insensitive", True)),
    )


def _regex_matcher_to_dict(matcher: RegexMatcher) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "pattern": matcher.pattern,
        "target": matcher.target,
        "case_insensitive": matcher.case_insensitive,
    }
    if matcher.metadata_key:
        payload["metadata_key"] = matcher.metadata_key
    return payload


def _when_clause_from_dict(raw: Any) -> WhenClause:
    if not isinstance(raw, dict):
        return WhenClause()
    return WhenClause(
        all_=_metadata_conditions_from_list(raw.get("all") or []),
        any_=_metadata_conditions_from_list(raw.get("any") or []),
    )


def _when_clause_to_dict(clause: WhenClause) -> dict[str, list[dict[str, Any]]]:
    return {
        "all": [
            {"key": c.key, "operator": c.operator, "value": c.value}
            for c in clause.all_
        ],
        "any": [
            {"key": c.key, "operator": c.operator, "value": c.value}
            for c in clause.any_
        ],
    }


def _rule_from_plugin_rule(
    plugin_name: str,
    raw_rule: dict[str, Any],
    schema_version: str = _SCHEMA_VERSION,
    plugin_bidirectional: bool = False,
) -> RuleDefinition:
    matchers = raw_rule.get("matchers", {})
    ast_edges = matchers.get("ast_edges", {})

    metadata_conditions = _metadata_conditions_from_list(
        matchers.get("metadata_conditions", [])
    )

    regex_patterns = tuple(
        _regex_matcher_from_dict(item) for item in matchers.get("regex_patterns", [])
    )

    actions_raw = raw_rule.get("actions", {}) or {}

    bidirectional = bool(raw_rule.get("bidirectional", plugin_bidirectional))

    return RuleDefinition(
        rule_id=str(raw_rule["rule_id"]),
        name=str(raw_rule["name"]),
        description=str(raw_rule.get("description", "")),
        severity=str(raw_rule.get("severity", "warning")),
        priority=int(raw_rule.get("priority", 0)),
        enabled=bool(raw_rule.get("enabled", True)),
        plugin=plugin_name,
        score=int(raw_rule.get("score", 0) or 0),
        tags=tuple(str(t) for t in raw_rule.get("tags", []) or []),
        schema_version=schema_version,
        bidirectional=bidirectional,
        match=RuleMatch(
            entity_types=tuple(
                item.lower() for item in matchers.get("entity_types", [])
            ),
            name_patterns=tuple(matchers.get("name_patterns", [])),
            file_patterns=tuple(matchers.get("file_patterns", [])),
            content_patterns=tuple(matchers.get("content_patterns", [])),
            regex_patterns=regex_patterns,
            usn_tags_any=tuple(
                item.lower() for item in matchers.get("usn_tags_any", [])
            ),
            metadata_conditions=metadata_conditions,
            ast_edges_any=tuple(
                _edge_matcher_from_dict(item) for item in ast_edges.get("any", [])
            ),
            ast_edges_all=tuple(
                _edge_matcher_from_dict(item) for item in ast_edges.get("all", [])
            ),
            # Bidirectional matchers (v2)
            gap_entity_types=tuple(matchers.get("gap_entity_types", [])),
            has_raw_content=matchers.get("has_raw_content"),
            has_coverage_gap=matchers.get("has_coverage_gap"),
            byte_range_start=matchers.get("byte_range_start"),
            byte_range_end=matchers.get("byte_range_end"),
            content_hash_pattern=matchers.get("content_hash_pattern"),
        ),
        actions=RuleActions(
            metadata=dict(actions_raw.get("metadata", {})),
            add_usn_tags=tuple(actions_raw.get("add_usn_tags", [])),
            derive_scope_tier=bool(actions_raw.get("derive_scope_tier", False)),
            derive_service_tag=bool(actions_raw.get("derive_service_tag", False)),
            truncate_docstring=bool(actions_raw.get("truncate_docstring", False)),
            max_docstring_length=int(actions_raw.get("max_docstring_length", 150)),
            normalize_entry_point=bool(actions_raw.get("normalize_entry_point", False)),
            detect_language=dict(actions_raw.get("detect_language", {})),
            detect_framework=dict(actions_raw.get("detect_framework", {})),
            detect_package_manager=dict(actions_raw.get("detect_package_manager", {})),
            detect_infra=dict(actions_raw.get("detect_infra", {})),
            assign_category=dict(actions_raw.get("assign_category", {})),
            when=_when_clause_from_dict(actions_raw.get("when")),
            # Bidirectional actions (v2)
            verify_coverage=bool(actions_raw.get("verify_coverage", False)),
            verify_integrity=bool(actions_raw.get("verify_integrity", False)),
            add_reconstruction_metadata=dict(actions_raw.get("add_reconstruction_metadata", {})),
            flag_for_reconstruction=bool(actions_raw.get("flag_for_reconstruction", False)),
            apply_token_budget=actions_raw.get("apply_token_budget"),
        ),
    )


def _edge_matcher_from_dict(raw: dict[str, Any]) -> ASTEdgeMatcher:
    metadata_equals_raw = raw.get("target_metadata_equals")
    metadata_equals: tuple[tuple[str, Any], ...] = ()
    if isinstance(metadata_equals_raw, dict):
        metadata_equals = tuple((str(k), v) for k, v in metadata_equals_raw.items())

    return ASTEdgeMatcher(
        edge=_normalize_edge_name(str(raw.get("edge", ""))),
        direction=str(raw.get("direction", "either")),
        target_entity_types=tuple(
            str(item).lower()
            for item in raw.get("target_entity_types", [])
            if str(item).strip()
        ),
        target_usn_tags_any=tuple(
            str(item).lower()
            for item in raw.get("target_usn_tags_any", [])
            if str(item).strip()
        ),
        target_name_patterns=tuple(
            str(item)
            for item in raw.get("target_name_patterns", [])
            if str(item).strip()
        ),
        target_metadata_equals=metadata_equals,
        min_count=int(raw.get("min_count", 1)),
    )


def _edge_matcher_to_dict(matcher: ASTEdgeMatcher) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "edge": matcher.edge,
        "direction": matcher.direction,
        "target_entity_types": list(matcher.target_entity_types),
        "target_usn_tags_any": list(matcher.target_usn_tags_any),
        "target_name_patterns": list(matcher.target_name_patterns),
        "min_count": matcher.min_count,
    }
    if matcher.target_metadata_equals:
        payload["target_metadata_equals"] = {
            key: value for key, value in matcher.target_metadata_equals
        }
    return payload


def _rule_to_document(rule: RuleDefinition) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "rule_id": rule.rule_id,
        "name": rule.name,
        "description": rule.description,
        "severity": rule.severity,
        "priority": rule.priority,
        "enabled": rule.enabled,
        "bidirectional": rule.bidirectional,
        "matchers": {
            "entity_types": list(rule.match.entity_types),
            "name_patterns": list(rule.match.name_patterns),
            "file_patterns": list(rule.match.file_patterns),
            "content_patterns": list(rule.match.content_patterns),
            "usn_tags_any": list(rule.match.usn_tags_any),
            "metadata_conditions": [
                {"key": c.key, "operator": c.operator, "value": c.value}
                for c in rule.match.metadata_conditions
            ],
            "ast_edges": {
                "any": [
                    _edge_matcher_to_dict(item) for item in rule.match.ast_edges_any
                ],
                "all": [
                    _edge_matcher_to_dict(item) for item in rule.match.ast_edges_all
                ],
            },
        },
        "actions": {
            "metadata": dict(rule.actions.metadata),
            "add_usn_tags": list(rule.actions.add_usn_tags),
            "derive_scope_tier": rule.actions.derive_scope_tier,
            "derive_service_tag": rule.actions.derive_service_tag,
        },
    }

    # Emit optional fields only when non-empty to keep serialised docs tidy.
    if rule.score:
        doc["score"] = rule.score
    if rule.tags:
        doc["tags"] = list(rule.tags)
    if rule.match.regex_patterns:
        doc["matchers"]["regex_patterns"] = [
            _regex_matcher_to_dict(item) for item in rule.match.regex_patterns
        ]
    if not rule.actions.when.is_empty:
        doc["actions"]["when"] = _when_clause_to_dict(rule.actions.when)

    # Bidirectional matchers (v2) — emit only when non-default
    if rule.match.gap_entity_types:
        doc["matchers"]["gap_entity_types"] = list(rule.match.gap_entity_types)
    if rule.match.has_raw_content is not None:
        doc["matchers"]["has_raw_content"] = rule.match.has_raw_content
    if rule.match.has_coverage_gap is not None:
        doc["matchers"]["has_coverage_gap"] = rule.match.has_coverage_gap
    if rule.match.byte_range_start is not None:
        doc["matchers"]["byte_range_start"] = rule.match.byte_range_start
    if rule.match.byte_range_end is not None:
        doc["matchers"]["byte_range_end"] = rule.match.byte_range_end
    if rule.match.content_hash_pattern is not None:
        doc["matchers"]["content_hash_pattern"] = rule.match.content_hash_pattern

    # Bidirectional actions (v2) — emit only when non-default
    if rule.actions.verify_coverage:
        doc["actions"]["verify_coverage"] = rule.actions.verify_coverage
    if rule.actions.verify_integrity:
        doc["actions"]["verify_integrity"] = rule.actions.verify_integrity
    if rule.actions.add_reconstruction_metadata:
        doc["actions"]["add_reconstruction_metadata"] = dict(
            rule.actions.add_reconstruction_metadata
        )
    if rule.actions.flag_for_reconstruction:
        doc["actions"]["flag_for_reconstruction"] = rule.actions.flag_for_reconstruction
    if rule.actions.apply_token_budget is not None:
        doc["actions"]["apply_token_budget"] = rule.actions.apply_token_budget

    return doc


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
    """Resolve a user-supplied custom rules path relative to the repo root.

    The result is routed through `sanitize_path` so that absolute paths,
    traversal, and other unsafe inputs are rejected before the file is read.
    """
    return sanitize_path(path_value, base_dir=root_path, allow_absolute=True)


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


def _rules_config_fingerprint(
    rules_config: dict[str, Any], source_hashes: dict[str, str]
) -> str:
    relevant = {
        "enabled": bool(rules_config.get("enabled", False)),
        "builtin_plugins": rules_config.get("builtin_plugins"),
        "disabled_rules": rules_config.get("disabled_rules"),
        "custom_rules_path": rules_config.get("custom_rules_path"),
        "custom_rules_inline": rules_config.get("custom_rules_inline"),
        "strict_validation": bool(rules_config.get("strict_validation", False)),
        "plugins_overrides": rules_config.get("plugins_overrides") or {},
        "schema_version": _SCHEMA_VERSION,
        "cache_schema_version": _CACHE_SCHEMA_VERSION,
        "source_hashes": source_hashes,
    }
    payload = json.dumps(relevant, sort_keys=True, separators=(",", ":"), default=str)
    return _hash_bytes(payload.encode("utf-8"))


def _detect_dependency_issues(
    plugin_dependencies: dict[str, list[str]],
    loaded_plugins: set[str],
) -> list[dict[str, Any]]:
    """Identify missing plugin dependencies.

    Returns a list of issue dicts with keys: plugin, missing, resolution.
    """

    issues: list[dict[str, Any]] = []
    for plugin_id, deps in sorted(plugin_dependencies.items()):
        for dep in deps:
            normalized_dep = _PLUGIN_ALIASES.get(dep, dep)
            if normalized_dep not in loaded_plugins and dep not in loaded_plugins:
                issues.append(
                    {
                        "plugin": plugin_id,
                        "missing": dep,
                        "resolution": (
                            f"add '{dep}' to rules.builtin_plugins or "
                            "enable the plugin in your batho.yaml"
                        ),
                    }
                )
    return issues


def _rule_match_overlap(a: RuleDefinition, b: RuleDefinition) -> list[str]:
    """Return a list of overlap reasons between two rules, or [] when disjoint.

    Overlap is a heuristic: two rules can both fire on the same entity only when
    their entity_types intersect AND any of (name_patterns, file_patterns,
    usn_tags_any) overlap. Rules that set the same metadata key with different
    values on the same scope are considered conflicting.
    """

    # Disjoint scopes: different entity types (excluding wildcard)
    a_types = set(a.match.entity_types)
    b_types = set(b.match.entity_types)
    if a_types and b_types and not a_types.intersection(b_types) and "*" not in a_types and "*" not in b_types:
        return []

    # If neither rule has any scope restriction at all, they trivially overlap on everything.
    a_restrictive = bool(
        a.match.entity_types
        or a.match.name_patterns
        or a.match.file_patterns
        or a.match.usn_tags_any
    )
    b_restrictive = bool(
        b.match.entity_types
        or b.match.name_patterns
        or b.match.file_patterns
        or b.match.usn_tags_any
    )
    if a_restrictive and b_restrictive:
        # Require at least one overlap axis (name/file/tags). Entity types alone
        # are too coarse to count as an overlap reason.
        axes = 0
        if a.match.name_patterns and b.match.name_patterns:
            shared = set(a.match.name_patterns).intersection(b.match.name_patterns)
            if shared:
                axes += 1
        if a.match.file_patterns and b.match.file_patterns:
            shared = set(a.match.file_patterns).intersection(b.match.file_patterns)
            if shared:
                axes += 1
        if a.match.usn_tags_any and b.match.usn_tags_any:
            shared = set(a.match.usn_tags_any).intersection(b.match.usn_tags_any)
            if shared:
                axes += 1
        if axes == 0:
            return []

    reasons: list[str] = []

    # Metadata key conflict: same key, different constant values assigned.
    shared_keys = set(a.actions.metadata.keys()).intersection(
        b.actions.metadata.keys()
    )
    for key in sorted(shared_keys):
        if a.actions.metadata[key] != b.actions.metadata[key]:
            reasons.append(
                f"metadata key '{key}' assigned different values "
                f"({a.actions.metadata[key]!r} vs {b.actions.metadata[key]!r})"
            )

    # Category / scope_tier / language collisions are particularly noisy.
    if (
        a.actions.assign_category.get("category")
        and b.actions.assign_category.get("category")
        and a.actions.assign_category["category"]
        != b.actions.assign_category["category"]
    ):
        reasons.append(
            f"assign_category conflict "
            f"({a.actions.assign_category['category']!r} vs "
            f"{b.actions.assign_category['category']!r})"
        )

    return reasons


def _detect_rule_conflicts(
    rules: list[RuleDefinition],
) -> list[dict[str, Any]]:
    """Pairwise scan rules for overlapping scopes + conflicting actions."""

    warnings: list[dict[str, Any]] = []
    rule_list = list(rules)
    for i in range(len(rule_list)):
        for j in range(i + 1, len(rule_list)):
            reasons = _rule_match_overlap(rule_list[i], rule_list[j])
            for reason in reasons:
                warnings.append(
                    {
                        "rule_a": rule_list[i].name,
                        "rule_b": rule_list[j].name,
                        "plugin_a": rule_list[i].plugin,
                        "plugin_b": rule_list[j].plugin,
                        "priority_a": rule_list[i].priority,
                        "priority_b": rule_list[j].priority,
                        "overlap": reason,
                    }
                )
    return warnings


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

    def _apply_patch_to_rule(
        existing: RuleDefinition,
        patch: dict[str, Any],
        override_key: str,
    ) -> None:
        """Apply a single patch dict to an existing rule and re-register it."""
        merged_rule = _merge_dict(_rule_to_document(existing), patch)
        try:
            normalized = _normalize_rule_dict(merged_rule)
            wrapper_doc = {
                "schema_version": existing.schema_version,
                "plugin_id": existing.plugin,
                "name": existing.plugin,
                "version": "1.0.0",
                "enabled": True,
                "rules": [normalized],
            }
            _validate_plugin_document(
                wrapper_doc,
                f"override:{override_key}",
                "",
                schema_version=existing.schema_version,
            )
            compiled = _rule_from_plugin_rule(
                existing.plugin,
                normalized,
                schema_version=existing.schema_version,
                plugin_bidirectional=existing.bidirectional,
            )
        except Exception as exc:
            _handle_error(f"Invalid override for {override_key}: {exc}")
            return

        lookup = existing.name.lower()
        if compiled.name.lower() != lookup:
            updated.pop(lookup, None)
        _register_rule(updated, compiled, stats)
        stats["overrides_applied"] = int(stats.get("overrides_applied", 0)) + 1

    # Detect flat rule_overrides format: {rule_name: {severity: ...}}
    # vs nested plugins_overrides format: {plugin_id: {rule_name: {severity: ...}}}
    rule_names_lower = {k.lower() for k in updated.keys()}
    override_keys_lower = [str(k).lower() for k in overrides.keys()]
    is_flat = bool(rule_names_lower) and all(
        k in rule_names_lower for k in override_keys_lower
    )

    if is_flat:
        # Flat format: {rule_name: patch_dict}
        for rule_name, patch in overrides.items():
            if not isinstance(patch, dict):
                _handle_error(f"rule_overrides.{rule_name} must be a mapping")
                continue
            lookup = str(rule_name).strip().lower()
            if not lookup:
                _handle_error("rule_overrides contains an empty rule name")
                continue
            existing = updated.get(lookup)
            if existing is None:
                _handle_error(f"Override target not found: rule={rule_name}")
                continue
            _apply_patch_to_rule(existing, patch, f"rule:{rule_name}")
        return updated

    # Nested format: {plugin_id: {rule_name: patch_dict}}
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
                _handle_error(
                    f"plugins.overrides.{plugin_key} contains an empty rule name"
                )
                continue

            existing = updated.get(lookup)
            if existing is None or not _plugin_matches(existing.plugin, plugin_key):
                _handle_error(
                    f"Override target not found: plugin={plugin_key} rule={rule_name}"
                )
                continue

            _apply_patch_to_rule(existing, patch, f"{plugin_key}.{rule_name}")

    return updated


def load_effective_rules(
    rules_config: dict[str, Any] | None,
    root_path: Path,
    logger: Any | None = None,
    quiet: bool = False,
) -> tuple[list[RuleDefinition], dict[str, Any]]:
    """Load, validate, and cache enabled built-in and custom rules.

    Args:
        quiet: When True, suppress info-level plugin discovery logging
               (used in worker processes to avoid log spam).
    """

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

    auto_load_all = bool(cfg.get("auto_load_all_plugins", True))
    builtin_plugins = cfg.get("builtin_plugins")

    if auto_load_all:
        plugin_catalog = _discover_packaged_plugins()
        builtin_plugins = list(plugin_catalog.keys())
        if quiet:
            log.debug(
                "bsg_auto_loading_all_plugins",
                plugin_count=len(builtin_plugins),
                plugins=builtin_plugins,
            )
        else:
            log.info(
                "bsg_auto_loading_all_plugins",
                plugin_count=len(builtin_plugins),
                plugins=builtin_plugins,
            )
    elif builtin_plugins is None:
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
            custom_rules_path = _resolve_custom_rules_path(
                str(custom_rules_path_value), root_path
            )
        except Exception as exc:
            _handle_error(
                f"Failed to resolve custom rule file '{custom_rules_path_value}': {exc}"
            )

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
    loaded_plugin_versions: dict[str, str] = {}
    loaded_plugin_schema_versions: dict[str, str] = {}
    plugin_dependencies: dict[str, list[str]] = {}

    for alias_name, plugin_name, plugin_path in selected_plugins:
        try:
            raw_data, source_text = _read_yaml_with_text(plugin_path)
            plugin_doc = _normalize_plugin_document(raw_data, plugin_name, plugin_name)
            plugin_schema_version = str(
                plugin_doc.get("schema_version", _SCHEMA_VERSION)
            )
            _validate_plugin_document(
                plugin_doc,
                plugin_path.as_posix(),
                source_text,
                schema_version=plugin_schema_version,
            )
            if not plugin_doc.get("enabled", True):
                continue

            stats["builtin_plugins_loaded"] += 1
            loaded_plugin_versions[plugin_name] = str(
                plugin_doc.get("version", "1.0.0")
            )
            loaded_plugin_schema_versions[plugin_name] = plugin_schema_version

            deps = plugin_doc.get("depends_on") or []
            if deps:
                plugin_dependencies[plugin_name] = list(deps)

            plugin_bidirectional = bool(plugin_doc.get("bidirectional", False))
            for raw_rule in plugin_doc.get("rules", []):
                compiled = _rule_from_plugin_rule(
                    plugin_name,
                    raw_rule,
                    schema_version=plugin_schema_version,
                    plugin_bidirectional=plugin_bidirectional,
                )
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
            plugin_doc = _normalize_plugin_document(
                custom_inline, "custom_inline", "custom_inline"
            )
            plugin_schema_version = str(
                plugin_doc.get("schema_version", _SCHEMA_VERSION)
            )
            _validate_plugin_document(
                plugin_doc,
                "rules.custom_rules_inline",
                "",
                schema_version=plugin_schema_version,
            )
            plugin_bidirectional = bool(plugin_doc.get("bidirectional", False))
            for raw_rule in plugin_doc.get("rules", []):
                compiled = _rule_from_plugin_rule(
                    "custom_inline",
                    raw_rule,
                    schema_version=plugin_schema_version,
                    plugin_bidirectional=plugin_bidirectional,
                )
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
            plugin_schema_version = str(
                plugin_doc.get("schema_version", _SCHEMA_VERSION)
            )
            _validate_plugin_document(
                plugin_doc,
                custom_rules_path.as_posix(),
                source_text,
                schema_version=plugin_schema_version,
            )
            stats["custom_file_count"] = len(plugin_doc.get("rules", []))
            plugin_bidirectional = bool(plugin_doc.get("bidirectional", False))
            for raw_rule in plugin_doc.get("rules", []):
                compiled = _rule_from_plugin_rule(
                    "custom_file",
                    raw_rule,
                    schema_version=plugin_schema_version,
                    plugin_bidirectional=plugin_bidirectional,
                )
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
                _handle_error(
                    f"Failed to parse custom rule file '{custom_rules_path}': {exc}"
                )
        except Exception as exc:
            _handle_error(
                f"Failed to load custom rule file '{custom_rules_path}': {exc}"
            )

    rules_by_name = _apply_rule_overrides(
        rules_by_name=rules_by_name,
        overrides=cfg.get("plugins_overrides") or cfg.get("rule_overrides") or {},
        strict_validation=strict_validation,
        stats=stats,
        logger=log,
    )

    effective_rules: list[RuleDefinition] = []
    for rule in sorted(
        rules_by_name.values(), key=lambda item: (item.priority, item.name.lower())
    ):
        if not rule.enabled:
            stats["rules_disabled"] += 1
            continue
        if rule.name.lower() in disabled_rules:
            stats["rules_disabled"] += 1
            continue
        effective_rules.append(rule)

    stats["rules_loaded"] = len(effective_rules)

    # Phase 1: dependency + conflict detection, executed after effective set resolved.
    dependency_issues = _detect_dependency_issues(
        plugin_dependencies,
        loaded_plugins=set(loaded_plugin_versions.keys()),
    )
    conflict_warnings = _detect_rule_conflicts(effective_rules)

    stats["plugin_versions"] = dict(sorted(loaded_plugin_versions.items()))
    stats["plugin_schema_versions"] = dict(
        sorted(loaded_plugin_schema_versions.items())
    )
    stats["dependency_issues"] = dependency_issues
    stats["conflict_warnings"] = conflict_warnings

    for issue in dependency_issues:
        msg = (
            f"plugin dependency issue: {issue['plugin']} -> "
            f"{issue['missing']}"
        )
        if strict_validation:
            stats["errors"].append(msg)
        else:
            log.warning("bsg_plugin_dependency_issue", **issue)

    if strict_validation and conflict_warnings:
        for warning in conflict_warnings:
            stats["errors"].append(
                f"conflict: rules {warning['rule_a']} and {warning['rule_b']} overlap "
                f"on {warning['overlap']}"
            )

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
            "plugin_versions": dict(stats.get("plugin_versions", {})),
            "plugin_schema_versions": dict(stats.get("plugin_schema_versions", {})),
            "dependency_issues": list(stats.get("dependency_issues", [])),
            "conflict_warnings": list(stats.get("conflict_warnings", [])),
        },
    }

    try:
        _write_cache(cache_path, cache_to_store)
    except Exception as exc:
        log.warning(
            "bsg_rule_cache_write_failed",
            cache_path=cache_path.as_posix(),
            error=str(exc),
        )

    return effective_rules, stats


def _to_relative_posix(file_path: str, root_path: Path | str) -> str:
    """Best-effort relative path normalization for glob matching."""
    file_path_str = str(file_path).replace('\\', '/')
    root_str = str(root_path).replace('\\', '/')
    if not root_str.endswith('/'):
        root_str += '/'
        
    # FAST PATH: String slicing avoids disk I/O
    if file_path_str.startswith(root_str):
        return file_path_str[len(root_str):]

    # Fallback for paths outside the root
    candidate = Path(file_path)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(Path(root_path).resolve()).as_posix()
        except Exception:  # noqa: BLE001
            return candidate.as_posix()
    return candidate.as_posix()


def _pattern_matches_lower(text_lower: str, patterns_lower: tuple[str, ...]) -> bool:
    if not patterns_lower:
        return True
    for pattern_lower in patterns_lower:
        # Handle ** glob pattern (matches zero or more directory levels)
        if "**" in pattern_lower:
            # Convert **/*.py to */*.py and *.py and check both
            # This handles cases like **/pyproject.toml matching both
            # pyproject.toml and src/pyproject.toml
            pattern_variants = [
                pattern_lower,
                pattern_lower.replace("**/", ""),  # */pyproject.toml -> pyproject.toml
                pattern_lower.replace("**/", "*/"),  # keep the * prefix
            ]
            for variant in pattern_variants:
                if fnmatch.fnmatch(text_lower, variant):
                    return True
        elif fnmatch.fnmatch(text_lower, pattern_lower):
            return True
    return False


def _pattern_matches(text: str, patterns: tuple[str, ...]) -> bool:
    if not patterns:
        return True
    return _pattern_matches_lower(text.lower(), tuple(p.lower() for p in patterns))



def _matches_content_patterns(
    file_path: str,
    patterns: tuple[str, ...],
    graph: "GraphBackend",
    file_content_cache: dict[str, str],
    root_path: Path,
) -> bool:
    """Check if file content matches any of the given patterns.

    Args:
        file_path: Relative file path
        patterns: Tuple of patterns to match (case-insensitive substring match)
        graph: "GraphBackend" instance
        file_content_cache: Cache dict to avoid repeated file reads

    Returns:
        True if any pattern matches, False otherwise
    """
    if not patterns:
        return True

    # Check cache first to avoid repeated file I/O
    if file_path not in file_content_cache:
        try:
            full_path = root_path / file_path

            if not full_path.exists():
                file_content_cache[file_path] = ""
            else:
                content = full_path.read_text(encoding="utf-8", errors="ignore")
                file_content_cache[file_path] = content.lower()
        except Exception as exc:
            _LOGGER.debug(
                "content_pattern_read_failed",
                file_path=file_path,
                error=str(exc),
            )
            file_content_cache[file_path] = ""

    content_lower = file_content_cache[file_path]
    if not content_lower:
        return False

    for pattern in patterns:
        if pattern.lower() in content_lower:
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
    return {token for token in re.split(r"[^a-zA-Z0-9]+", with_spaces.lower()) if token}


def _path_token_set(rel_file_path: str) -> set[str]:
    tokens: set[str] = set()
    # FAST PATH: String split instead of Path.parts
    parts = rel_file_path.replace('\\', '/').split('/')
    for part in parts:
        if part and part != ".":
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
    
    # FAST PATH: String slicing instead of Path.suffix
    idx = rel_file_path.rfind('.')
    suffix = rel_file_path[idx:].lower() if idx != -1 else ""
    
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

    # Decorator-based ApiBoundary detection: check entity metadata for
    # decorators that indicate an externally exposed API route, regardless
    # of the function name. This catches functions like `admin_action` that
    # are decorated with `@app.route` / `@router.get` / `@GetMapping`.
    if entity.type in {
        EntityType.FUNCTION,
        EntityType.METHOD,
        EntityType.CLASS,
        EntityType.ENTRY_POINT,
    } and "ApiBoundary" not in tags:
        metadata = entity.metadata if isinstance(entity.metadata, dict) else {}
        decorators = metadata.get("decorators")
        if isinstance(decorators, list):
            for dec in decorators:
                dec_str = str(dec).lower()
                if any(token in dec_str for token in _API_HINT_TOKENS):
                    tags.add("ApiBoundary")
                    break
                # Route decorator patterns not covered by _API_HINT_TOKENS
                if any(
                    pat in dec_str
                    for pat in ("@app.route", "@router.", "@api_view", "mapping", "endpoint")
                ):
                    tags.add("ApiBoundary")
                    break

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


def _apply_semantic_usn_tags(graph: "GraphBackend", root_path: Path) -> int:
    updated = 0

    for entity_id, entity in list(graph.entities.items()):
        rel_file_path = _to_relative_posix(entity.file, root_path)
        inferred = _infer_semantic_tags(entity, rel_file_path)
        if not inferred:
            continue

        metadata = dict(entity.metadata or {})
        existing_raw = metadata.get("bsg.usn")
        existing = (
            {str(item) for item in existing_raw}
            if isinstance(existing_raw, list)
            else set()
        )
        merged = sorted(existing | inferred)

        new_type = entity.type
        merged_lower = [t.lower() for t in merged]
        if "infrastructureconfig" in merged_lower:
            new_type = EntityType.INFRASTRUCTURE_CONFIG
        elif "environmentvariable" in merged_lower:
            new_type = EntityType.ENVIRONMENT_VARIABLE

        if (
            isinstance(existing_raw, list)
            and sorted({str(item) for item in existing_raw}) == merged
            and new_type == entity.type
        ):
            continue

        metadata["bsg.usn"] = merged
        updated_entity = entity.model_copy(update={"metadata": metadata, "type": new_type})
        # update_entity keeps the graph's secondary indexes (_by_type/_by_file)
        # in sync on both backends.
        graph.update_entity(entity_id, updated_entity)

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


def _derive_semantic_relations(graph: "GraphBackend") -> list[Relationship]:
    semantic_relations: list[Relationship] = []
    tags_by_entity = {
        entity_id: _entity_usn_tags(entity)
        for entity_id, entity in graph.entities.items()
    }
    key_tokens_by_entity = {
        entity_id: _semantic_key_tokens(entity.name)
        for entity_id, entity in graph.entities.items()
    }
    seen = {
        (str(rel.source_id), str(rel.target_id), _relationship_type_name(rel))
        for rel in graph.relationships
    }

    def _add(
        source_id: str, target_id: str, rel_type: RelationshipType, reason: str
    ) -> None:
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
                _add(
                    source_id,
                    target_id,
                    RelationshipType.DEPENDS_ON_API,
                    "depends_on_api",
                )

            if "apiboundary" in source_tags and "authmiddleware" in target_tags:
                _add(
                    source_id, target_id, RelationshipType.WRAPPED_BY, "wrapped_by_auth"
                )

            if "loopstatement" in source_tags and "databaseexecution" in target_tags:
                _add(
                    target_id,
                    source_id,
                    RelationshipType.CONTAINED_WITHIN,
                    "db_inside_loop_call",
                )

            if "resourceallocation" in source_tags:
                target_entity = graph.get_entity(target_id)
                if target_entity is not None and _looks_like_cleanup_target(
                    target_entity
                ):
                    _add(
                        source_id,
                        target_id,
                        RelationshipType.CLEANED_BY,
                        "resource_cleanup_call",
                    )

            if (
                "environmentvariable" in source_tags
                and "infrastructureconfig" in target_tags
            ):
                _add(
                    source_id,
                    target_id,
                    RelationshipType.REFERENCED_IN,
                    "env_to_infra_reference",
                )

            if (
                "environmentvariable" in target_tags
                and "infrastructureconfig" in source_tags
            ):
                _add(
                    target_id,
                    source_id,
                    RelationshipType.REFERENCED_IN,
                    "env_to_infra_reference",
                )

        if rel_type_name == "CONTAINS":
            if "loopstatement" in source_tags and "databaseexecution" in target_tags:
                _add(
                    target_id,
                    source_id,
                    RelationshipType.CONTAINED_WITHIN,
                    "db_inside_loop_scope",
                )

    infra_entities = graph.entity_ids_by_type(EntityType.INFRASTRUCTURE_CONFIG)
    env_entities = graph.entity_ids_by_type(EntityType.ENVIRONMENT_VARIABLE)

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


def _append_semantic_relations(
    graph: "GraphBackend", relations: list[Relationship]
) -> int:
    if not relations:
        return 0

    existing = {
        (str(rel.source_id), str(rel.target_id), _relationship_type_name(rel))
        for rel in graph.relationships
    }

    added = 0
    for relation in relations:
        key = (
            relation.source_id,
            relation.target_id,
            _relationship_type_name(relation),
        )
        if key in existing:
            continue

        existing.add(key)
        graph.add_relationship(relation)
        added += 1

    return added


def _target_matches_filters(
    target_entity: Entity | None,
    matcher: ASTEdgeMatcher,
    get_entity_tags_fn = None,
) -> bool:
    if target_entity is None:
        if (
            matcher.target_entity_types
            or matcher.target_usn_tags_any
            or matcher.target_name_patterns
            or matcher.target_metadata_equals
        ):
            return False
        return True

    if matcher.target_entity_types:
        entity_type = str(target_entity.type).lower()
        if (
            "*" not in matcher._target_entity_types_set
            and entity_type not in matcher._target_entity_types_set
        ):
            return False

    if matcher.target_usn_tags_any:
        if get_entity_tags_fn is not None:
            target_tags = get_entity_tags_fn(target_entity.id, target_entity)
        else:
            target_tags = _entity_usn_tags(target_entity)
        if not target_tags.intersection(matcher._target_usn_tags_any_set):
            return False

    if matcher.target_name_patterns and not _pattern_matches_lower(
        target_entity.name.lower(), matcher._target_name_patterns_lower
    ):
        return False

    if matcher.target_metadata_equals:
        target_meta = target_entity.metadata or {}
        for key, expected in matcher.target_metadata_equals:
            if target_meta.get(key) != expected:
                return False

    return True


def _count_edge_matches(
    entity_id: str,
    matcher: ASTEdgeMatcher,
    graph: "GraphBackend",
    outbound: dict[str, list[Any]],
    inbound: dict[str, list[Any]],
    get_entity_tags_fn = None,
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
        if _target_matches_filters(target_entity, matcher, get_entity_tags_fn):
            count += 1

    return count


def _matches_ast_edges(
    entity_id: str,
    match: RuleMatch,
    graph: "GraphBackend",
    outbound: dict[str, list[Any]],
    inbound: dict[str, list[Any]],
    get_entity_tags_fn = None,
) -> bool:
    for matcher in match.ast_edges_all:
        if (
            _count_edge_matches(entity_id, matcher, graph, outbound, inbound, get_entity_tags_fn)
            < matcher.min_count
        ):
            return False

    if match.ast_edges_any:
        for matcher in match.ast_edges_any:
            if (
                _count_edge_matches(entity_id, matcher, graph, outbound, inbound, get_entity_tags_fn)
                >= matcher.min_count
            ):
                return True
        return False

    return True



def _evaluate_metadata_condition(
    metadata: dict[str, Any], cond: MetadataCondition
) -> bool:
    """Evaluate a single metadata condition. Unknown operators fail-safe to False."""

    value = metadata.get(cond.key)

    if cond.operator == "exists":
        return value is not None
    if cond.operator == "length_gt":
        return isinstance(value, str) and len(value) > int(cond.value)
    if cond.operator == "length_lt":
        return isinstance(value, str) and len(value) < int(cond.value)
    if cond.operator == "contains_any":
        if not isinstance(value, str) or not isinstance(cond.value, (list, tuple)):
            return False
        return any(str(marker) in value for marker in cond.value)
    if cond.operator == "contains_all":
        if not isinstance(value, str) or not isinstance(cond.value, (list, tuple)):
            return False
        return all(str(marker) in value for marker in cond.value)
    if cond.operator == "in":
        if not isinstance(cond.value, (list, tuple, set)):
            return False
        return value in cond.value
    if cond.operator == "not_in":
        if not isinstance(cond.value, (list, tuple, set)):
            return False
        return value not in cond.value
    if cond.operator == "eq":
        return value == cond.value
    if cond.operator == "neq":
        return value != cond.value
    if cond.operator == "regex_match":
        if not isinstance(value, str) or not isinstance(cond.value, str):
            return False
        try:
            return re.search(cond.value, value) is not None
        except re.error:
            return False
    return False


def _matches_metadata_conditions(
    entity: Entity,
    conditions: tuple[MetadataCondition, ...],
) -> bool:
    """Check if entity metadata matches all conditions."""
    metadata = entity.metadata or {}
    for cond in conditions:
        if not _evaluate_metadata_condition(metadata, cond):
            return False
    return True


def _matches_when_clause(entity: Entity, clause: WhenClause) -> bool:
    """Evaluate an action `when` gate against an entity's metadata."""

    if clause.is_empty:
        return True
    metadata = entity.metadata or {}
    if clause.all_ and not all(
        _evaluate_metadata_condition(metadata, c) for c in clause.all_
    ):
        return False
    if clause.any_ and not any(
        _evaluate_metadata_condition(metadata, c) for c in clause.any_
    ):
        return False
    return True


def _matches_regex_patterns(
    entity: Entity,
    rel_file_path: str,
    matchers: tuple[RegexMatcher, ...],
    compiled_cache: dict[tuple[str, bool], re.Pattern[str]],
) -> bool:
    """All regex matchers must match (AND semantics)."""

    if not matchers:
        return True

    for matcher in matchers:
        flags = re.IGNORECASE if matcher.case_insensitive else 0
        key = (matcher.pattern, matcher.case_insensitive)
        compiled = compiled_cache.get(key)
        if compiled is None:
            try:
                compiled = re.compile(matcher.pattern, flags)
            except re.error:
                return False
            compiled_cache[key] = compiled

        if matcher.target == "name":
            target_value = entity.name
        elif matcher.target == "file_path":
            target_value = rel_file_path
        elif matcher.target == "signature":
            target_value = entity.signature or ""
        elif matcher.target == "metadata" and matcher.metadata_key:
            raw = (entity.metadata or {}).get(matcher.metadata_key)
            target_value = "" if raw is None else str(raw)
        else:
            return False

        if not compiled.search(target_value):
            return False

    return True


def _matches_rule(
    rule: RuleDefinition,
    entity_id: str,
    entity: Entity,
    rel_file_path: str,
    graph: "GraphBackend",
    outbound: dict[str, list[Any]],
    inbound: dict[str, list[Any]],
    file_content_cache: dict[str, str],
    regex_cache: dict[tuple[str, bool], re.Pattern[str]] | None = None,
    entity_type_lower: str | None = None,
    entity_name_lower: str | None = None,
    rel_file_path_lower: str | None = None,
    entity_tags: set[str] | None = None,
    get_entity_tags_fn = None,
    root_path: Path | None = None,
) -> bool:
    if rule.match.entity_types:
        ent_type = entity_type_lower if entity_type_lower is not None else str(entity.type).lower()
        if (
            "*" not in rule.match._entity_types_set
            and ent_type not in rule.match._entity_types_set
        ):
            return False

    if rule.match.usn_tags_any:
        ent_tags = entity_tags if entity_tags is not None else _entity_usn_tags(entity)
        if not ent_tags.intersection(rule.match._usn_tags_any_set):
            return False

    if rule.match.name_patterns:
        ent_name = entity_name_lower if entity_name_lower is not None else entity.name.lower()
        if not _pattern_matches_lower(ent_name, rule.match._name_patterns_lower):
            return False

    if rule.match.file_patterns:
        fp_lower = rel_file_path_lower if rel_file_path_lower is not None else rel_file_path.lower()
        if not _pattern_matches_lower(fp_lower, rule.match._file_patterns_lower):
            return False

    if rule.match.regex_patterns:
        local_cache = regex_cache if regex_cache is not None else {}
        if not _matches_regex_patterns(
            entity, rel_file_path, rule.match.regex_patterns, local_cache
        ):
            return False

    if rule.match.content_patterns:
        if not _matches_content_patterns(
            rel_file_path,
            rule.match.content_patterns,
            graph,
            file_content_cache,
            root_path if root_path is not None else Path("."),
        ):
            return False

    if not _matches_ast_edges(entity_id, rule.match, graph, outbound, inbound, get_entity_tags_fn):
        return False

    if rule.match.metadata_conditions:
        if not _matches_metadata_conditions(entity, rule.match.metadata_conditions):
            return False

    # Bidirectional matchers (v2)
    if rule.match.gap_entity_types:
        ent_type = entity_type_lower if entity_type_lower is not None else str(entity.type).lower()
        if ent_type not in rule.match._gap_entity_types_lower:
            return False

    if rule.match.has_raw_content is not None:
        has_raw = entity.raw_content is not None
        if has_raw != rule.match.has_raw_content:
            return False

    if rule.match.has_coverage_gap is not None:
        if entity.start_byte > entity.end_byte:
            return False
        # Check if entity has coverage gap (end_byte - start_byte != raw_content length)
        if entity.raw_content is None and entity.raw_bytes is None:
            return False
        byte_length = len(entity.raw_bytes) if entity.raw_bytes is not None else len(entity.raw_content.encode("utf-8"))
        has_gap = (entity.end_byte - entity.start_byte) != byte_length
        if has_gap != rule.match.has_coverage_gap:
            return False

    if rule.match.byte_range_start is not None:
        if entity.start_byte < rule.match.byte_range_start:
            return False

    if rule.match.byte_range_end is not None:
        if entity.end_byte > rule.match.byte_range_end:
            return False

    if rule.match._compiled_hash_pattern is not None:
        if not entity.content_hash:
            return False
        if not rule.match._compiled_hash_pattern.search(entity.content_hash):
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
    # FAST PATH: String split instead of Path.parts
    parts = [part for part in rel_file_path.replace('\\', '/').split('/') if part and part != "."]
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


def _apply_rule_actions(
    rule: "RuleDefinition",
    entity: "Entity",
    rel_file_path: str,
    metadata: dict[str, Any],
    entity_tags_cache: dict[str, set[str]],
) -> tuple[bool, set[str]]:
    """Apply all actions of a matched rule to *metadata* in-place.

    Returns ``(changed, updated_entity_tags)`` so callers can propagate tag
    cache updates without re-deriving them.  ``entity_tags_cache`` is mutated
    when ``add_usn_tags`` fires.
    """
    changed = False
    entity_id = entity.id
    entity_tags = entity_tags_cache.get(entity_id, set())

    for key, value in rule.actions.metadata.items():
        if metadata.get(key) != value:
            metadata[key] = value
            changed = True

    if rule.actions.add_usn_tags:
        current_tags = metadata.get("bsg.usn")
        existing = current_tags if isinstance(current_tags, list) else []
        merged_tags = sorted(
            {str(item) for item in existing} | set(rule.actions.add_usn_tags)
        )
        if existing != merged_tags:
            metadata["bsg.usn"] = merged_tags
            changed = True
            entity_tags = {str(t).strip().lower() for t in merged_tags if str(t).strip()}
            entity_tags_cache[entity_id] = entity_tags

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

    if rule.actions.truncate_docstring:
        docstring = metadata.get("docstring")
        if docstring and isinstance(docstring, str):
            max_len = rule.actions.max_docstring_length
            if max_len > 0 and len(docstring) > max_len:
                metadata["docstring"] = docstring[:max_len] + "..."
                changed = True

    if (
        rule.actions.normalize_entry_point
        and entity.type == EntityType.ENTRY_POINT
    ):
        raw_value = metadata.get("invocation_snippet")
        raw_snippet = (
            str(raw_value)
            if isinstance(raw_value, str) and raw_value.strip()
            else entity.name
        )
        normalized_snippet = raw_snippet.replace("'", '"')
        if (
            (
                "__name__" in normalized_snippet
                and '"__main__"' in normalized_snippet
            )
            or raw_snippet == "__name__"
        ) and entity.name != "__main__":
            metadata["invocation_snippet"] = raw_snippet
            metadata["bsg.normalized_name"] = "__main__"
            changed = True

    if rule.actions.detect_language:
        language = rule.actions.detect_language.get("language")
        if language and metadata.get("bsg.language") != language:
            metadata["bsg.language"] = language
            changed = True

    if rule.actions.detect_framework:
        framework = rule.actions.detect_framework.get("framework")
        language = rule.actions.detect_framework.get("language")
        if framework:
            current_frameworks = metadata.get("bsg.frameworks", [])
            if not isinstance(current_frameworks, list):
                current_frameworks = []
            framework_added = False
            if framework not in current_frameworks:
                metadata["bsg.frameworks"] = current_frameworks + [framework]
                framework_added = True
            if language and metadata.get("bsg.language") != language:
                metadata["bsg.language"] = language
                changed = True
            elif framework_added:
                changed = True

    if rule.actions.detect_package_manager:
        package_manager = rule.actions.detect_package_manager.get("package_manager")
        if package_manager and metadata.get("bsg.package_manager") != package_manager:
            metadata["bsg.package_manager"] = package_manager
            changed = True

    if rule.actions.detect_infra:
        infra_type = rule.actions.detect_infra.get("infra_type")
        if infra_type:
            current_infra = metadata.get("bsg.infra", [])
            if not isinstance(current_infra, list):
                current_infra = []
            if infra_type not in current_infra:
                metadata["bsg.infra"] = current_infra + [infra_type]
                changed = True

    if rule.actions.assign_category:
        category = rule.actions.assign_category.get("category")
        if category and metadata.get("bsg.category") != category:
            metadata["bsg.category"] = category
            changed = True

    if rule.actions.verify_coverage:
        metadata["bsg.verify_coverage"] = True
        changed = True

    if rule.actions.verify_integrity:
        metadata["bsg.verify_integrity"] = True
        changed = True

    if rule.actions.add_reconstruction_metadata:
        for key, value in rule.actions.add_reconstruction_metadata.items():
            if metadata.get(f"bsg.reconstruction.{key}") != value:
                metadata[f"bsg.reconstruction.{key}"] = value
                changed = True

    if rule.actions.flag_for_reconstruction:
        metadata["bsg.flag_for_reconstruction"] = True
        changed = True

    if rule.actions.apply_token_budget is not None:
        metadata["bsg.token_budget"] = rule.actions.apply_token_budget
        changed = True

    return changed, entity_tags


def apply_semantic_overlay(
    graph: "GraphBackend",
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
        semantic_edges_added = _append_semantic_relations(
            graph=graph, relations=semantic_relations
        )
    except Exception as exc:
        log.warning("bsg_semantic_overlay_failed", error=str(exc))

    return {
        "semantic_tags_added": semantic_tags_added,
        "semantic_edges_added": semantic_edges_added,
    }


def apply_rule_plugins(
    graph: "GraphBackend",
    root_path: Path,
    rules_config: dict[str, Any] | None,
    logger: Any | None = None,
    profile: bool = False,
    trace: bool = False,
    bidirectional_only: bool = False,
) -> dict[str, Any]:
    """Apply configured BSG rules in-place and return execution stats.

    Args:
        graph: "GraphBackend" to annotate.
        root_path: Repository root; used for relative path matching and artifacts.
        rules_config: The `rules` block from batho.yaml (or equivalent dict).
        logger: Optional structured logger.
        profile: When True, collect per-rule match/apply timing metrics in memory.
        trace: When True, the returned summary includes a `trace_log` entry per
            entity/rule with match outcomes and actions.
        bidirectional_only: When True, only run bidirectional flow plugins.
    """

    log = logger or _LOGGER
    rules, load_stats = load_effective_rules(
        rules_config=rules_config, root_path=root_path, logger=log
    )

    # Filter rules if bidirectional_only is True
    if bidirectional_only:
        rules = [r for r in rules if r.bidirectional]

    if not load_stats.get("enabled", False):
        return {
            **load_stats,
            "entities_updated": 0,
            "rules_applied": 0,
            "rule_hits": {},
        }

    semantic_stats = apply_semantic_overlay(
        graph=graph, root_path=root_path, logger=log
    )
    semantic_tags_added = int(semantic_stats.get("semantic_tags_added", 0))
    semantic_edges_added = int(semantic_stats.get("semantic_edges_added", 0))

    outbound: dict[str, list[Any]] = {}
    inbound: dict[str, list[Any]] = {}
    for relation in graph.relationships:
        outbound.setdefault(relation.source_id, []).append(relation)
        inbound.setdefault(relation.target_id, []).append(relation)

    rule_hits: dict[str, int] = {rule.name: 0 for rule in rules}
    rule_timings_ns: dict[str, int] = {rule.name: 0 for rule in rules}
    rule_match_calls: dict[str, int] = {rule.name: 0 for rule in rules}
    rule_when_skipped: dict[str, int] = {rule.name: 0 for rule in rules}
    updated_entities = 0

    # File content cache to avoid repeated I/O for content_patterns matching
    file_content_cache: dict[str, str] = {}
    # Compiled regex cache shared across rule evaluations
    regex_cache: dict[tuple[str, bool], re.Pattern[str]] = {}
    trace_log: list[dict[str, Any]] = []

    # Rules pre-filtering by entity type cache
    rules_by_type_cache: dict[str, list[RuleDefinition]] = {}

    def get_rules_for_type(ent_type_lower: str) -> list[RuleDefinition]:
        if ent_type_lower not in rules_by_type_cache:
            rules_by_type_cache[ent_type_lower] = [
                r for r in rules
                if not r.match.entity_types
                or "*" in r.match._entity_types_set
                or ent_type_lower in r.match._entity_types_set
            ]
        return rules_by_type_cache[ent_type_lower]

    entity_tags_cache: dict[str, set[str]] = {}

    def get_entity_tags(ent_id: str, ent: Entity) -> set[str]:
        if ent_id not in entity_tags_cache:
            entity_tags_cache[ent_id] = _entity_usn_tags(ent)
        return entity_tags_cache[ent_id]

    overall_start_ns = time.perf_counter_ns()

    for entity_id, entity in list(graph.entities.items()):
        rel_file_path = _to_relative_posix(entity.file, root_path)
        rel_file_path_lower = rel_file_path.lower()
        entity_name_lower = entity.name.lower()
        entity_type_lower = str(entity.type).lower()

        metadata = dict(entity.metadata or {})
        matched_rules: list[str] = []
        changed = False

        entity_rules = get_rules_for_type(entity_type_lower)
        entity_tags = get_entity_tags(entity_id, entity)

        for rule in entity_rules:
            match_start_ns = time.perf_counter_ns() if profile else 0
            rule_match_calls[rule.name] += 1
            matched = _matches_rule(
                rule=rule,
                entity_id=entity_id,
                entity=entity,
                rel_file_path=rel_file_path,
                graph=graph,
                outbound=outbound,
                inbound=inbound,
                file_content_cache=file_content_cache,
                regex_cache=regex_cache,
                entity_type_lower=entity_type_lower,
                entity_name_lower=entity_name_lower,
                rel_file_path_lower=rel_file_path_lower,
                entity_tags=entity_tags,
                get_entity_tags_fn=get_entity_tags,
                root_path=root_path,
            )
            if profile:
                rule_timings_ns[rule.name] += (
                    time.perf_counter_ns() - match_start_ns
                )

            if not matched:
                if trace:
                    trace_log.append(
                        {
                            "entity_id": entity_id,
                            "entity_name": entity.name,
                            "file": rel_file_path,
                            "rule": rule.name,
                            "plugin": rule.plugin,
                            "matched": False,
                        }
                    )
                continue

            # Conditional action gate: matcher fires but actions are suppressed
            # when the `when` clause does not hold on this entity.
            if not _matches_when_clause(entity, rule.actions.when):
                rule_when_skipped[rule.name] += 1
                if trace:
                    trace_log.append(
                        {
                            "entity_id": entity_id,
                            "entity_name": entity.name,
                            "file": rel_file_path,
                            "rule": rule.name,
                            "plugin": rule.plugin,
                            "matched": True,
                            "when_skipped": True,
                        }
                    )
                continue

            matched_rules.append(rule.name)
            rule_hits[rule.name] += 1

            if trace:
                trace_log.append(
                    {
                        "entity_id": entity_id,
                        "entity_name": entity.name,
                        "file": rel_file_path,
                        "rule": rule.name,
                        "plugin": rule.plugin,
                        "matched": True,
                        "when_skipped": False,
                    }
                )

            action_changed, entity_tags = _apply_rule_actions(
                rule, entity, rel_file_path, metadata, entity_tags_cache
            )
            if action_changed:
                changed = True

        if matched_rules:
            existing_rules = metadata.get("bsg.rules")
            existing_list = existing_rules if isinstance(existing_rules, list) else []
            combined = sorted(set(existing_list + matched_rules))
            if existing_rules != combined:
                metadata["bsg.rules"] = combined
                changed = True

        if changed:
            graph.update_entity(entity_id, entity.model_copy(update={"metadata": metadata}))
            updated_entities += 1

    # Post-processing: Apply entry point name normalization
    # (Must be done after metadata updates since entity names are frozen)
    for entity_id, entity in list(graph.entities.items()):
        normalized_name = (
            entity.metadata.get("bsg.normalized_name") if entity.metadata else None
        )
        if normalized_name and entity.name != normalized_name:
            graph.update_entity(
                entity_id,
                entity.model_copy(update={"name": normalized_name}),
            )

    applied_count = sum(1 for count in rule_hits.values() if count > 0)
    plugin_hits: dict[str, int] = {}
    for rule in rules:
        hit_count = int(rule_hits.get(rule.name, 0))
        if hit_count <= 0:
            continue
        plugin_hits[rule.plugin] = int(plugin_hits.get(rule.plugin, 0)) + hit_count

    interception_totals: dict[str, int] = {}
    for plugin_id, hit_count in sorted(plugin_hits.items()):
        if hit_count > 0:
            interception_totals[plugin_id] = hit_count

    # Build per-plugin rule_details with severity for J10 override compliance.
    # Maps plugin_id -> list of {rule, severity, hits} for rules with hits > 0.
    plugin_rule_details: dict[str, list[dict[str, Any]]] = {}
    for rule in rules:
        hit_count = int(rule_hits.get(rule.name, 0))
        if hit_count <= 0:
            continue
        plugin_rule_details.setdefault(rule.plugin, []).append({
            "rule": rule.name,
            "severity": rule.severity,
            "hits": hit_count,
        })

    security_audit = {
        "schema_version": "interception-stats.v1",
        "plugins": {
            plugin_id: {
                "plugin_id": plugin_id,
                "name": _plugin_display_name(plugin_id),
                "interceptions": hit_count,
                "rule_details": plugin_rule_details.get(plugin_id, []),
            }
            for plugin_id, hit_count in interception_totals.items()
        }
    }

    overall_elapsed_ns = time.perf_counter_ns() - overall_start_ns

    summary = {
        **load_stats,
        "entities_updated": updated_entities,
        "rules_applied": applied_count,
        "semantic_tags_added": semantic_tags_added,
        "semantic_edges_added": semantic_edges_added,
        "plugin_hits": {
            name: count for name, count in sorted(plugin_hits.items()) if count > 0
        },
        "rule_hits": {
            name: count for name, count in sorted(rule_hits.items()) if count > 0
        },
        "rule_when_skipped": {
            name: count for name, count in sorted(rule_when_skipped.items()) if count > 0
        },
        "interception_totals": {
            name: count for name, count in sorted(interception_totals.items())
        },
        "interception_stats_path": None,
        "security_audit": security_audit,
    }

    if profile:
        rule_perf = {}
        for rule in rules:
            hits = int(rule_hits.get(rule.name, 0))
            match_calls = int(rule_match_calls.get(rule.name, 0))
            total_ns = int(rule_timings_ns.get(rule.name, 0))
            when_skipped = int(rule_when_skipped.get(rule.name, 0))
            rule_perf[rule.name] = {
                "plugin": rule.plugin,
                "priority": rule.priority,
                "hits": hits,
                "match_calls": match_calls,
                "when_skipped": when_skipped,
                "total_ns": total_ns,
                "avg_ns": int(total_ns / match_calls) if match_calls else 0,
            }

        perf_payload = {
            "schema_version": "bsg-perf.v1",
            "total_elapsed_ns": int(overall_elapsed_ns),
            "entities_scanned": len(graph.entities),
            "rule_count": len(rules),
            "rules": dict(sorted(rule_perf.items())),
        }
        summary["perf_stats_path"] = None
        summary["rule_perf"] = perf_payload

    if trace:
        summary["trace_log"] = trace_log

    log.info(
        "bsg_rules_applied",
        rules_loaded=summary.get("rules_loaded", 0),
        rules_applied=summary["rules_applied"],
        entities_updated=summary["entities_updated"],
        cache_hit=summary.get("cache_hit", False),
    )

    return summary


def validate_plugin_file(
    plugin_path: Path,
    strict: bool = False,
) -> dict[str, Any]:
    """Validate a plugin YAML file against the BSG plugin schema.

    Args:
        plugin_path: Path to a plugin YAML file.
        strict: When True, promote structural warnings (unreachable rules,
            duplicate rule_ids, overlap hints) into errors.

    Returns a dict with validation results:
    - valid: bool
    - plugin_file: str
    - schema_version: str
    - rule_count: int
    - warnings: list[str]
    - errors: list[str]
    - conflict_warnings: list[dict]
    - depends_on: list[str]
    """

    result: dict[str, Any] = {
        "valid": False,
        "plugin_file": str(plugin_path),
        "schema_version": None,
        "rule_count": 0,
        "warnings": [],
        "errors": [],
        "conflict_warnings": [],
        "depends_on": [],
    }

    if not plugin_path.exists():
        result["errors"].append(f"File not found: {plugin_path}")
        return result

    try:
        raw_data, source_text = _read_yaml_with_text(plugin_path)
        plugin_doc = _normalize_plugin_document(
            raw_data, plugin_path.stem, plugin_path.stem
        )

        schema_version = str(plugin_doc.get("schema_version", _SCHEMA_VERSION))
        result["schema_version"] = schema_version
        result["depends_on"] = list(plugin_doc.get("depends_on", []) or [])

        # Validate against schema
        _validate_plugin_document(
            plugin_doc,
            plugin_path.as_posix(),
            source_text,
            schema_version=schema_version,
        )

        # Count rules
        rules = plugin_doc.get("rules", [])
        result["rule_count"] = len(rules) if isinstance(rules, list) else 0

        if not plugin_doc.get("enabled", True):
            result["warnings"].append("Plugin is marked as disabled")

        compiled_rules: list[RuleDefinition] = []
        seen_rule_ids: dict[str, int] = {}
        plugin_bidirectional = bool(plugin_doc.get("bidirectional", False))
        for idx, raw_rule in enumerate(rules if isinstance(rules, list) else []):
            try:
                compiled = _rule_from_plugin_rule(
                    plugin_path.stem,
                    raw_rule,
                    schema_version=schema_version,
                    plugin_bidirectional=plugin_bidirectional,
                )
                compiled_rules.append(compiled)
                if compiled.rule_id in seen_rule_ids:
                    result["warnings"].append(
                        f"duplicate rule_id '{compiled.rule_id}' "
                        f"at indexes {seen_rule_ids[compiled.rule_id]} and {idx}"
                    )
                else:
                    seen_rule_ids[compiled.rule_id] = idx
            except Exception as exc:
                result["warnings"].append(f"Rule {idx}: {exc}")

        # Structural checks: regex compilation, empty matchers
        for compiled in compiled_rules:
            for rgx in compiled.match.regex_patterns:
                try:
                    re.compile(
                        rgx.pattern,
                        re.IGNORECASE if rgx.case_insensitive else 0,
                    )
                except re.error as exc:
                    result["warnings"].append(
                        f"rule '{compiled.name}' has invalid regex '{rgx.pattern}': {exc}"
                    )

            m = compiled.match
            if not (
                m.entity_types
                or m.name_patterns
                or m.file_patterns
                or m.content_patterns
                or m.regex_patterns
                or m.usn_tags_any
                or m.metadata_conditions
                or m.ast_edges_any
                or m.ast_edges_all
                or m.gap_entity_types
                or m.has_raw_content is not None
                or m.has_coverage_gap is not None
                or m.byte_range_start is not None
                or m.byte_range_end is not None
                or m.content_hash_pattern is not None
                or compiled.actions.derive_scope_tier
                or compiled.actions.derive_service_tag
            ):
                result["warnings"].append(
                    f"rule '{compiled.name}' has no matchers and no derive actions; "
                    "it will match every entity"
                )

        # Intra-plugin conflict scan
        conflict_warnings = _detect_rule_conflicts(compiled_rules)
        result["conflict_warnings"] = conflict_warnings

        if strict and (result["warnings"] or conflict_warnings):
            for warning in result["warnings"]:
                result["errors"].append(warning)
            for conflict in conflict_warnings:
                result["errors"].append(
                    f"rule conflict: {conflict['rule_a']} <-> {conflict['rule_b']}: "
                    f"{conflict['overlap']}"
                )
            result["valid"] = not result["errors"]
        else:
            result["valid"] = not result["errors"]

    except yaml.YAMLError as exc:
        line_hint = None
        mark = getattr(exc, "problem_mark", None)
        if mark is not None:
            line_hint = int(mark.line) + 1
        if line_hint is not None:
            result["errors"].append(f"YAML parse error at line {line_hint}: {exc}")
        else:
            result["errors"].append(f"YAML parse error: {exc}")
    except ValueError as exc:
        result["errors"].append(str(exc))
    except Exception as exc:
        result["errors"].append(f"Validation failed: {exc}")

    return result


def apply_bsg_rules_to_entities(
    entities: list[Entity],
    relationships: list[Relationship],
    rules: list[RuleDefinition],
    root_path: str,
    file_path: str,
) -> tuple[list[Entity], dict[str, Any]]:
    """Apply non-bidirectional BSG rules to a single file's entities.

    Skips rules with bidirectional=True (those need full graph topology).
    Returns the updated entities list with BSG metadata applied, plus a
    per-file security_audit fragment.
    """
    if not entities or not rules:
        return entities, {}

    from pathlib import Path

    root = Path(root_path)
    rel_file_path = _to_relative_posix(file_path, root)
    rel_file_path_lower = rel_file_path.lower()

    # Filter to non-bidirectional rules only
    applicable_rules = [r for r in rules if not r.bidirectional]
    if not applicable_rules:
        return entities, {}

    # Pre-compute file content for content_patterns matching
    file_content_cache: dict[str, str] = {}
    regex_cache: dict[tuple[str, bool], re.Pattern[str]] = {}

    # Build outbound/inbound maps from this file's relationships only
    outbound: dict[str, list[Any]] = {}
    inbound: dict[str, list[Any]] = {}
    entity_ids = {e.id for e in entities}
    for rel in relationships:
        if rel.source_id in entity_ids:
            outbound.setdefault(rel.source_id, []).append(rel)
        if rel.target_id in entity_ids:
            inbound.setdefault(rel.target_id, []).append(rel)

    # Rules pre-filter by entity type cache
    rules_by_type_cache: dict[str, list[RuleDefinition]] = {}

    def get_rules_for_type(ent_type_lower: str) -> list[RuleDefinition]:
        if ent_type_lower not in rules_by_type_cache:
            rules_by_type_cache[ent_type_lower] = [
                r for r in applicable_rules
                if not r.match.entity_types
                or "*" in r.match._entity_types_set
                or ent_type_lower in r.match._entity_types_set
            ]
        return rules_by_type_cache[ent_type_lower]

    entity_tags_cache: dict[str, set[str]] = {}

    def get_entity_tags(ent_id: str, ent: Entity) -> set[str]:
        if ent_id not in entity_tags_cache:
            entity_tags_cache[ent_id] = _entity_usn_tags(ent)
        return entity_tags_cache[ent_id]

    updated_entities = []
    file_security_audit: dict[str, Any] = {
        "schema_version": "interception-stats.v1",
        "plugins": {},
    }
    plugin_hits: dict[str, int] = {}
    file_rule_hits: dict[str, int] = {}  # rule_name -> hit count (per-file)

    for entity in entities:
        entity_id = entity.id
        ent_type_lower = str(entity.type).lower()
        entity_name_lower = entity.name.lower()

        metadata = dict(entity.metadata or {})
        matched_rules: list[str] = []
        changed = False

        entity_rules = get_rules_for_type(ent_type_lower)
        entity_tags = get_entity_tags(entity_id, entity)

        for rule in entity_rules:
            # Check basic matchers (entity_type, name, file, usn_tags, regex, content)
            if rule.match.entity_types:
                if (
                    "*" not in rule.match._entity_types_set
                    and ent_type_lower not in rule.match._entity_types_set
                ):
                    continue

            if rule.match.usn_tags_any:
                if not entity_tags.intersection(rule.match._usn_tags_any_set):
                    continue

            if rule.match.name_patterns:
                if not _pattern_matches_lower(entity_name_lower, rule.match._name_patterns_lower):
                    continue

            if rule.match.file_patterns:
                if not _pattern_matches_lower(rel_file_path_lower, rule.match._file_patterns_lower):
                    continue

            if rule.match.regex_patterns:
                if not _matches_regex_patterns(
                    entity, rel_file_path, rule.match.regex_patterns, regex_cache
                ):
                    continue

            if rule.match.content_patterns:
                if not _matches_content_patterns(
                    rel_file_path,
                    rule.match.content_patterns,
                    None,  # graph not needed for per-file
                    file_content_cache,
                    root,
                ):
                    continue

            if rule.match.metadata_conditions:
                if not _matches_metadata_conditions(entity, rule.match.metadata_conditions):
                    continue

            # Skip ast_edges matchers for per-file processing
            if rule.match.ast_edges_any or rule.match.ast_edges_all:
                continue

            # Check bidirectional matchers (v2) - skip if present
            if (
                rule.match.gap_entity_types
                or rule.match.has_raw_content is not None
                or rule.match.has_coverage_gap is not None
                or rule.match.byte_range_start is not None
                or rule.match.byte_range_end is not None
                or rule.match.content_hash_pattern is not None
            ):
                continue

            # Conditional action gate
            if not _matches_when_clause(entity, rule.actions.when):
                continue

            matched_rules.append(rule.name)
            plugin_hits[rule.plugin] = plugin_hits.get(rule.plugin, 0) + 1
            file_rule_hits[rule.name] = file_rule_hits.get(rule.name, 0) + 1

            action_changed, entity_tags = _apply_rule_actions(
                rule, entity, rel_file_path, metadata, entity_tags_cache
            )
            if action_changed:
                changed = True

        if matched_rules:
            existing_rules = metadata.get("bsg.rules")
            existing_list = existing_rules if isinstance(existing_rules, list) else []
            combined = sorted(set(existing_list + matched_rules))
            if existing_rules != combined:
                metadata["bsg.rules"] = combined
                changed = True

        if changed:
            updated_entities.append(entity.model_copy(update={"metadata": metadata}))
        else:
            updated_entities.append(entity)

    # Build per-file security_audit fragment
    rule_severity_map = {r.name: r.severity for r in rules}
    for plugin_id, hits in plugin_hits.items():
        if hits > 0:
            # Collect per-rule details for this plugin
            details = [
                {"rule": name, "severity": rule_severity_map.get(name, "unknown"), "hits": count}
                for name, count in file_rule_hits.items()
                if count > 0 and any(r.name == name and r.plugin == plugin_id for r in rules)
            ]
            file_security_audit["plugins"][plugin_id] = {
                "plugin_id": plugin_id,
                "name": _plugin_display_name(plugin_id),
                "interceptions": hits,
                "rule_details": details,
            }

    return updated_entities, file_security_audit
