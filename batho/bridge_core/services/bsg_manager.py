"""BSG Memory Manager - Loads and evaluates bidirectional sync rules."""

from __future__ import annotations

import json
import zlib
import zstandard as zstd
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from batho.context.codegraph import InMemoryGraph
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.services.bsg_manager")


@dataclass
class PolicyGap:
    """A detected policy violation."""
    rule: str
    severity: str  # "error", "warning", "info"
    file: str
    line: int
    message: str
    remediation: str | None = None
    entity_id: str | None = None


@dataclass
class PluginInfo:
    """BSG Plugin metadata."""
    plugin_id: str
    category: str
    version: str
    rules_count: int
    hits: int


class BSGMemoryManager:
    """
    Manages BSG (Bidirectional Sync Graph) rules in memory.
    
    Loads compressed bsg_blob payloads from storage and provides
    rule evaluation against the InMemoryGraph for dashboard display.
    """
    
    def __init__(self, graph: InMemoryGraph, bsg_payloads: list[dict] | None = None):
        self.graph = graph
        self._rules: list[dict] = []
        self._plugins: dict[str, PluginInfo] = {}
        self._hits: dict[str, int] = {}
        
        if bsg_payloads:
            self._load_payloads(bsg_payloads)
    
    @classmethod
    def from_blobs(cls, graph: InMemoryGraph, blobs: list[bytes]) -> "BSGMemoryManager":
        """Initialize from compressed bsg_blob bytes."""
        payloads = []
        dctx = zstd.ZstdDecompressor()
        for blob in blobs:
            try:
                decompressed = dctx.decompress(blob)
                payload = json.loads(decompressed.decode("utf-8"))
                payloads.append(payload)
            except Exception as e:
                LOGGER.warning("bsg_blob_decompress_failed", error=str(e))
        return cls(graph, payloads)
    
    def _load_payloads(self, payloads: list[dict]) -> None:
        """Load rules from BSG payloads."""
        for payload in payloads:
            # Extract rules from payload
            rules = payload.get("rules", [])
            for rule in rules:
                self._rules.append(rule)
                plugin_id = rule.get("plugin", "unknown")
                self._hits[rule.get("id", "unknown")] = 0
            
            # Track plugins
            plugin_info = payload.get("plugin_info", {})
            if plugin_info:
                plugin_id = plugin_info.get("id", "unknown")
                self._plugins[plugin_id] = PluginInfo(
                    plugin_id=plugin_id,
                    category=plugin_info.get("category", "unknown"),
                    version=plugin_info.get("version", "1.0.0"),
                    rules_count=len(rules),
                    hits=0,
                )
    
    def evaluate_all(self) -> list[PolicyGap]:
        """Evaluate all rules against the graph."""
        gaps = []
        for rule in self._rules:
            rule_gaps = self._evaluate_rule(rule)
            gaps.extend(rule_gaps)
            self._hits[rule.get("id", "unknown")] += len(rule_gaps)
        return gaps
    
    def evaluate_for_file(self, file_path: str) -> list[PolicyGap]:
        """Evaluate rules against specific file."""
        entities = self.graph.entities_by_file(file_path)
        gaps = []
        
        for rule in self._rules:
            for entity in entities:
                if self._rule_matches_entity(rule, entity):
                    gap = self._create_gap(rule, entity)
                    if gap:
                        gaps.append(gap)
        
        return gaps
    
    def get_plugins_catalog(self) -> list[PluginInfo]:
        """Return plugin catalog with current stats."""
        # Update hit counts
        for plugin in self._plugins.values():
            plugin.hits = sum(
                self._hits.get(r.get("id"), 0)
                for r in self._rules
                if r.get("plugin") == plugin.plugin_id
            )
        return list(self._plugins.values())
    
    def get_rules_with_stats(self, filters: dict[str, Any] | None = None) -> list[dict]:
        """Return rules with execution statistics."""
        rules = []
        for rule in self._rules:
            # Apply filters
            if filters:
                if "plugin" in filters and rule.get("plugin") != filters["plugin"]:
                    continue
                if "severity" in filters and rule.get("severity") != filters["severity"]:
                    continue
            
            rule_data = {
                "id": rule.get("id"),
                "name": rule.get("name"),
                "plugin": rule.get("plugin"),
                "severity": rule.get("severity", "info"),
                "description": rule.get("description"),
                "hits": self._hits.get(rule.get("id"), 0),
                "enabled": rule.get("enabled", True),
            }
            rules.append(rule_data)
        
        return rules
    
    def _evaluate_rule(self, rule: dict) -> list[PolicyGap]:
        """Evaluate a single rule against the graph."""
        gaps = []
        rule_type = rule.get("type")
        
        if rule_type == "pattern":
            # Pattern-based rule (regex, AST pattern)
            gaps = self._evaluate_pattern_rule(rule)
        elif rule_type == "relationship":
            # Relationship-based rule (dependency check)
            gaps = self._evaluate_relationship_rule(rule)
        elif rule_type == "metric":
            # Metric threshold rule
            gaps = self._evaluate_metric_rule(rule)
        
        return gaps
    
    def _evaluate_pattern_rule(self, rule: dict) -> list[PolicyGap]:
        """Evaluate a pattern-based rule."""
        gaps = []
        pattern = rule.get("pattern", {})
        
        # Iterate all entities
        for entity_id, entity in self.graph.entities.items():
            if self._pattern_matches(entity, pattern):
                gaps.append(PolicyGap(
                    rule=rule.get("name", "Unknown"),
                    severity=rule.get("severity", "warning"),
                    file=entity.file,
                    line=entity.start_line,
                    message=rule.get("message", f"Pattern match: {rule.get('name')}"),
                    remediation=rule.get("remediation"),
                    entity_id=entity_id,
                ))
        
        return gaps
    
    def _evaluate_relationship_rule(self, rule: dict) -> list[PolicyGap]:
        """Evaluate a relationship-based rule."""
        gaps = []
        # Implementation for relationship checks
        return gaps
    
    def _evaluate_metric_rule(self, rule: dict) -> list[PolicyGap]:
        """Evaluate a metric threshold rule."""
        gaps = []
        # Implementation for metric checks
        return gaps
    
    def _rule_matches_entity(self, rule: dict, entity) -> bool:
        """Check if rule applies to entity."""
        entity_types = rule.get("entity_types", [])
        if entity_types and entity.type.value not in entity_types:
            return False
        return True
    
    def _pattern_matches(self, entity, pattern: dict) -> bool:
        """Check if entity matches pattern."""
        # Implement pattern matching logic
        name_pattern = pattern.get("name")
        if name_pattern and entity.name:
            import re
            if re.search(name_pattern, entity.name):
                return True
        return False
    
    def _create_gap(self, rule: dict, entity) -> PolicyGap | None:
        """Create a policy gap for rule violation."""
        return PolicyGap(
            rule=rule.get("name", "Unknown"),
            severity=rule.get("severity", "warning"),
            file=entity.file,
            line=entity.start_line,
            message=rule.get("message", f"Rule violation: {rule.get('name')}"),
            remediation=rule.get("remediation"),
            entity_id=entity.id,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert BSG data to dictionary for API responses."""
        return {
            "rules": self._rules,
            "plugins": [
                {
                    "id": p.plugin_id,
                    "category": p.category,
                    "version": p.version,
                    "rules_count": p.rules_count,
                    "hits": p.hits,
                }
                for p in self._plugins.values()
            ],
            "hits": self._hits,
        }


__all__ = ["BSGMemoryManager", "PolicyGap", "PluginInfo"]
