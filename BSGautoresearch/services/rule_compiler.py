"""Compile mined convention signals into bsg-plugin.v1 YAML rules."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import yaml

_LOGGER = logging.getLogger(__name__)

_SCHEMA_VERSION = "bsg-plugin.v1"
_PLUGIN_ID = "bsg_autoresearch_generated"
_PLUGIN_NAME = "BSG Autoresearch Generated"
_PLUGIN_VERSION = "1.0.0"

# Map convention roles to BSG entity types and USN tags
_ROLE_TO_ENTITY_MAP: dict[str, dict[str, Any]] = {
    "controller": {
        "entity_types": ["function", "method", "class"],
        "add_usn_tags": ["ApiBoundary"],
        "metadata": {
            "bsg.autoresearch.source": "naming_convention",
            "bsg.autoresearch.role": "controller",
        },
    },
    "model": {
        "entity_types": ["class", "struct", "interface"],
        "add_usn_tags": ["Orm_Model"],
        "metadata": {
            "bsg.autoresearch.source": "naming_convention",
            "bsg.autoresearch.role": "model",
        },
    },
    "service": {
        "entity_types": ["class", "function", "method"],
        "add_usn_tags": [],
        "metadata": {
            "bsg.autoresearch.source": "naming_convention",
            "bsg.autoresearch.role": "service",
        },
    },
    "middleware": {
        "entity_types": ["function", "method", "class"],
        "add_usn_tags": ["AuthMiddleware"],
        "metadata": {
            "bsg.autoresearch.source": "naming_convention",
            "bsg.autoresearch.role": "middleware",
        },
    },
    "route": {
        "entity_types": ["function", "method", "class"],
        "add_usn_tags": ["ApiBoundary"],
        "metadata": {
            "bsg.autoresearch.source": "naming_convention",
            "bsg.autoresearch.role": "route",
        },
    },
    "config": {
        "entity_types": ["variable", "constant", "class", "section", "setting"],
        "add_usn_tags": ["EnvironmentVariable"],
        "metadata": {
            "bsg.autoresearch.source": "naming_convention",
            "bsg.autoresearch.role": "config",
        },
    },
}


def _stable_rule_id(prefix: str, *parts: str) -> str:
    """Generate a deterministic rule ID from prefix + parts."""
    key = ":".join(parts)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{digest}"


def _build_naming_convention_rule(signal: dict[str, Any]) -> dict[str, Any]:
    """Compile a naming convention signal into a bsg-plugin.v1 rule."""

    role = signal["role"]
    count = signal["total_matches"]
    role_map = _ROLE_TO_ENTITY_MAP.get(role, {})

    entity_types = role_map.get("entity_types", ["class"])
    tags = role_map.get("add_usn_tags", [])
    metadata = role_map.get("metadata", {})

    rule_id = _stable_rule_id("autoresearch-naming", role)

    # Build file patterns from known naming conventions
    file_patterns = _file_patterns_for_role(role)

    rule: dict[str, Any] = {
        "rule_id": rule_id,
        "name": f"autoresearch-naming-{role}",
        "description": (
            f"Auto-mined rule: classify entities in files matching {role} naming "
            f"conventions (observed {count} matches across repos)."
        ),
        "severity": "info",
        "priority": 500 + count,  # higher count → higher priority
        "enabled": True,
        "matchers": {
            "entity_types": entity_types,
            "file_patterns": file_patterns,
        },
        "actions": {
            "metadata": metadata,
        },
    }

    if tags:
        rule["actions"]["add_usn_tags"] = tags

    return rule


def _file_patterns_for_role(role: str) -> list[str]:
    """Return glob file patterns for a given role across common languages."""

    patterns: dict[str, list[str]] = {
        "controller": [
            "*controller*",
            "*Controller*",
            "*_views*",
            "views.*",
            "*handler*",
            "*Handler*",
            "*Resource*",
            "*endpoint*",
        ],
        "model": [
            "*model*",
            "*Model*",
            "*entity*",
            "*Entity*",
            "*Dto*",
            "*_schema*",
            "*schema*",
            "models.*",
        ],
        "service": [
            "*service*",
            "*Service*",
            "*provider*",
            "*Provider*",
            "*repository*",
            "*Repository*",
        ],
        "middleware": [
            "*middleware*",
            "*Middleware*",
            "*guard*",
            "*Guard*",
            "*interceptor*",
            "*Interceptor*",
            "*filter*",
            "*Filter*",
            "*layer*",
            "*Layer*",
        ],
        "route": [
            "*route*",
            "*Route*",
            "*router*",
            "*Router*",
            "*urls*",
            "urls.*",
            "*module*",
        ],
        "config": [
            "*config*",
            "*Config*",
            "*settings*",
            "*Settings*",
            "*properties*",
            "*Properties*",
            "appsettings*",
            "*options*",
            "*Options*",
        ],
    }
    return patterns.get(role, [f"*{role}*"])


def _build_motif_rule(signal: dict[str, Any]) -> dict[str, Any]:
    """Compile a relationship motif signal into a bsg-plugin.v1 rule."""

    motif = signal["motif"]
    count = signal["total_matches"]

    rule_id = _stable_rule_id("autoresearch-motif", motif)

    # Infer edge type and source tag from motif name
    edge = "CALLS"
    source_tag = "ApiBoundary"
    if (
        "auth" in motif.lower()
        or "middleware" in motif.lower()
        or "guard" in motif.lower()
    ):
        edge = "WRAPPED_BY"
        source_tag = "AuthMiddleware"
    elif (
        "inherit" in motif.lower()
        or "model" in motif.lower()
        or "eloquent" in motif.lower()
    ):
        edge = "INHERITS"
        source_tag = "Orm_Model"

    rule: dict[str, Any] = {
        "rule_id": rule_id,
        "name": f"autoresearch-motif-{motif}",
        "description": (
            f"Auto-mined rule: detect {motif} relationship pattern "
            f"(observed {count} matches across repos)."
        ),
        "severity": "info",
        "priority": 400 + count,
        "enabled": True,
        "matchers": {
            "usn_tags_any": [source_tag.lower()],
            "ast_edges": {
                "any": [
                    {
                        "edge": edge,
                        "direction": "outbound",
                        "min_count": 1,
                    }
                ],
            },
        },
        "actions": {
            "metadata": {
                "bsg.autoresearch.source": "relationship_motif",
                "bsg.autoresearch.motif": motif,
            },
        },
    }

    return rule


def compile_rules(aggregated: dict[str, Any]) -> dict[str, Any]:
    """Compile aggregated convention signals into a full bsg-plugin.v1 document.

    Returns a dict matching the bsg-plugin-schema-v1.json structure.
    """

    rules: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for signal in aggregated.get("signals", []):
        signal_type = signal.get("type")

        if signal_type == "naming_convention":
            rule = _build_naming_convention_rule(signal)
        elif signal_type == "relationship_motif":
            rule = _build_motif_rule(signal)
        else:
            continue

        if rule["rule_id"] not in seen_ids:
            rules.append(rule)
            seen_ids.add(rule["rule_id"])

    # Sort rules deterministically by rule_id
    rules.sort(key=lambda r: r["rule_id"])

    plugin_doc: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "plugin_id": _PLUGIN_ID,
        "name": _PLUGIN_NAME,
        "version": _PLUGIN_VERSION,
        "enabled": True,
        "description": (
            f"Auto-generated plugin from BSG Autoresearch v1. "
            f"Mined from {aggregated.get('repo_count', 0)} repositories "
            f"across {len(aggregated.get('languages', []))} languages."
        ),
        "rules": rules,
    }

    return plugin_doc


def write_candidate(plugin_doc: dict[str, Any], target_path: Path) -> Path:
    """Write the compiled plugin document as YAML to target_path.

    Creates parent directories if needed. Returns the written path.
    """

    target_path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(
        plugin_doc, default_flow_style=False, sort_keys=False, allow_unicode=True
    )
    target_path.write_text(content, encoding="utf-8")
    _LOGGER.info(
        "wrote candidate plugin to %s (%d rules)",
        target_path,
        len(plugin_doc.get("rules", [])),
    )
    return target_path
