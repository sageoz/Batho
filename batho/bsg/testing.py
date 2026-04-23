"""BSG plugin testing utilities.

This module provides two layers for authoring and running plugin tests
without standing up a full Batho indexing pipeline:

1. :class:`MockGraphBuilder` — a tiny fluent builder that produces an
   :class:`batho.context.codegraph.InMemoryGraph` populated with synthetic
   entities and relationships.

2. :func:`run_plugin_fixture` — a runner that accepts a YAML fixture with a
   ``given`` (inputs) block and an ``expect`` (assertions) block, applies the
   plugin's rules through :func:`apply_rule_plugins`, and returns a structured
   pass/fail report.

Fixture DSL (YAML)
------------------

.. code-block:: yaml

    name: hardcoded-secret-flags-password-fields
    plugin:
      # One of `path` (YAML plugin file), `builtin` (a packaged plugin_id),
      # or `inline` (a list of rule dicts).
      builtin: bsg_hardcoded_secret_catcher
    given:
      entities:
        - type: variable
          name: API_PASSWORD
          file: src/config.py
          start_line: 1
          end_line: 1
      relationships: []
    expect:
      entity:
        name: API_PASSWORD
        metadata:
          bsg.intercept.category: SECURITY
        usn_tags_include:
          - SecretCandidate
      rules_applied_includes:
        - likely-hardcoded-secret

The runner raises ``FixtureError`` for authoring mistakes (unknown entity type,
missing expectations, etc.). Assertions that fail populate the returned
report's ``failures`` list instead of raising, so tests can aggregate
multiple fixture outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from batho.bsg.rules import apply_rule_plugins
from batho.context.codegraph import InMemoryGraph
from batho.context.schema import Entity, EntityType, Relationship, RelationshipType


class FixtureError(ValueError):
    """Raised for structural problems in a fixture file."""


# ---------------------------------------------------------------------------
# Mock graph builder
# ---------------------------------------------------------------------------


def _coerce_entity_type(raw: Any) -> EntityType:
    if isinstance(raw, EntityType):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        raise FixtureError(f"entity type must be a non-empty string: {raw!r}")
    key = raw.strip().upper()
    try:
        return EntityType[key]
    except KeyError as exc:
        raise FixtureError(f"unknown entity type: {raw!r}") from exc


def _coerce_relationship_type(raw: Any) -> RelationshipType:
    if isinstance(raw, RelationshipType):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        raise FixtureError(
            f"relationship type must be a non-empty string: {raw!r}"
        )
    key = raw.strip().upper()
    try:
        return RelationshipType[key]
    except KeyError as exc:
        raise FixtureError(f"unknown relationship type: {raw!r}") from exc


class MockGraphBuilder:
    """Fluent builder that produces an :class:`InMemoryGraph` for plugin tests."""

    def __init__(self, root: str | Path | None = None) -> None:
        self._graph = InMemoryGraph()
        if root is not None:
            # InMemoryGraph exposes a ``root`` attribute used by file-content
            # matchers; respect the caller's preference when provided.
            try:
                self._graph.root = str(root)  # type: ignore[attr-defined]
            except Exception:
                pass

    def add_entity(
        self,
        *,
        type: str | EntityType,
        name: str,
        file: str,
        start_line: int = 1,
        end_line: int | None = None,
        start_byte: int = 0,
        end_byte: int = 0,
        signature: str | None = None,
        metadata: dict[str, Any] | None = None,
        parent_id: str | None = None,
    ) -> Entity:
        entity = Entity(
            type=_coerce_entity_type(type),
            name=name,
            file=file,
            start_line=int(start_line),
            end_line=int(end_line if end_line is not None else start_line),
            start_byte=int(start_byte),
            end_byte=int(end_byte),
            signature=signature,
            metadata=dict(metadata or {}),
            parent_id=parent_id,
        )
        self._graph.add_entity(entity)
        return entity

    def add_relationship(
        self,
        *,
        source: str | Entity,
        target: str | Entity,
        type: str | RelationshipType,
        metadata: dict[str, Any] | None = None,
    ) -> Relationship:
        source_id = source.id if isinstance(source, Entity) else source
        target_id = target.id if isinstance(target, Entity) else target
        relationship = Relationship(
            source_id=source_id,
            target_id=target_id,
            type=_coerce_relationship_type(type),
            metadata=dict(metadata or {}),
        )
        self._graph.add_relationship(relationship)
        return relationship

    def add_from_fixture(self, given: dict[str, Any]) -> dict[str, Entity]:
        """Populate the graph from a fixture ``given`` block.

        Returns a mapping from entity ``name`` to the created ``Entity`` so
        assertions can look entities up later.
        """

        entities_raw = given.get("entities") or []
        if not isinstance(entities_raw, list):
            raise FixtureError("given.entities must be a list")

        by_name: dict[str, Entity] = {}
        for spec in entities_raw:
            if not isinstance(spec, dict):
                raise FixtureError(
                    "each given.entities item must be a mapping"
                )
            entity = self.add_entity(**spec)
            by_name[entity.name] = entity

        relationships_raw = given.get("relationships") or []
        if relationships_raw and not isinstance(relationships_raw, list):
            raise FixtureError("given.relationships must be a list")

        for spec in relationships_raw:
            if not isinstance(spec, dict):
                raise FixtureError(
                    "each given.relationships item must be a mapping"
                )
            src_key = spec.get("source")
            tgt_key = spec.get("target")
            if src_key not in by_name or tgt_key not in by_name:
                raise FixtureError(
                    "given.relationships.source/target must reference entities "
                    "declared in given.entities (by name)"
                )
            self.add_relationship(
                source=by_name[src_key],
                target=by_name[tgt_key],
                type=spec.get("type", "CALLS"),
                metadata=spec.get("metadata") or {},
            )

        return by_name

    def build(self) -> InMemoryGraph:
        return self._graph


# ---------------------------------------------------------------------------
# Fixture runner
# ---------------------------------------------------------------------------


@dataclass
class FixtureReport:
    """Outcome of running a single fixture."""

    name: str
    fixture_path: str | None = None
    passed: bool = True
    failures: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def assert_passed(self) -> None:
        if not self.passed:
            joined = "\n".join(f"- {f}" for f in self.failures)
            raise AssertionError(
                f"Fixture '{self.name}' failed:\n{joined}"
            )


def _build_rules_config(plugin_spec: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plugin_spec, dict):
        raise FixtureError("fixture.plugin must be a mapping")

    rules_cfg: dict[str, Any] = {
        "enabled": True,
        "auto_load_all_plugins": False,
        "builtin_plugins": [],
    }

    if "builtin" in plugin_spec:
        rules_cfg["builtin_plugins"] = [str(plugin_spec["builtin"])]
    elif "builtins" in plugin_spec:
        rules_cfg["builtin_plugins"] = [
            str(item) for item in plugin_spec.get("builtins") or []
        ]
    elif "path" in plugin_spec:
        path = Path(str(plugin_spec["path"])).expanduser()
        rules_cfg["custom_rules_path"] = str(path)
    elif "inline" in plugin_spec:
        inline = plugin_spec["inline"]
        if not isinstance(inline, list):
            raise FixtureError("plugin.inline must be a list of rule mappings")
        rules_cfg["custom_rules_inline"] = inline
    else:
        raise FixtureError(
            "fixture.plugin requires one of: builtin, builtins, path, inline"
        )

    # Allow fixtures to tweak the rule loader (e.g., enable strict mode, pin
    # disabled_rules). This keeps the runner flexible without being leaky.
    for passthrough_key in (
        "strict_validation",
        "disabled_rules",
        "plugins_overrides",
    ):
        if passthrough_key in plugin_spec:
            rules_cfg[passthrough_key] = plugin_spec[passthrough_key]

    return rules_cfg


def _find_entity_by_name(graph: InMemoryGraph, name: str) -> Entity | None:
    for entity in graph.entities.values():
        if entity.name == name:
            return entity
    return None


def _check_entity_expectation(
    graph: InMemoryGraph, spec: dict[str, Any], report: FixtureReport
) -> None:
    name = spec.get("name")
    if not isinstance(name, str) or not name.strip():
        report.failures.append("expect.entity.name is required")
        return

    entity = _find_entity_by_name(graph, name)
    if entity is None:
        report.failures.append(f"entity '{name}' not found in graph after rule application")
        return

    metadata = entity.metadata or {}

    expected_metadata = spec.get("metadata") or {}
    if expected_metadata and not isinstance(expected_metadata, dict):
        report.failures.append(
            "expect.entity.metadata must be a mapping"
        )
    else:
        for key, expected_value in expected_metadata.items():
            actual = metadata.get(key)
            if actual != expected_value:
                report.failures.append(
                    f"entity '{name}': metadata[{key!r}] expected {expected_value!r}, got {actual!r}"
                )

    forbidden_metadata = spec.get("metadata_absent") or []
    if forbidden_metadata and not isinstance(forbidden_metadata, list):
        report.failures.append(
            "expect.entity.metadata_absent must be a list of keys"
        )
    else:
        for key in forbidden_metadata:
            if key in metadata:
                report.failures.append(
                    f"entity '{name}': metadata key {key!r} should be absent but is present ({metadata[key]!r})"
                )

    expected_tags = spec.get("usn_tags_include") or []
    if expected_tags:
        if not isinstance(expected_tags, list):
            report.failures.append(
                "expect.entity.usn_tags_include must be a list"
            )
        else:
            tags = metadata.get("bsg.usn")
            tag_set = {str(t) for t in tags} if isinstance(tags, list) else set()
            for tag in expected_tags:
                if tag not in tag_set:
                    report.failures.append(
                        f"entity '{name}': expected USN tag {tag!r} not present (have: {sorted(tag_set)})"
                    )

    forbidden_tags = spec.get("usn_tags_absent") or []
    if forbidden_tags:
        if not isinstance(forbidden_tags, list):
            report.failures.append(
                "expect.entity.usn_tags_absent must be a list"
            )
        else:
            tags = metadata.get("bsg.usn")
            tag_set = {str(t) for t in tags} if isinstance(tags, list) else set()
            for tag in forbidden_tags:
                if tag in tag_set:
                    report.failures.append(
                        f"entity '{name}': USN tag {tag!r} should be absent"
                    )

    expected_rules = spec.get("rules_include") or []
    if expected_rules:
        if not isinstance(expected_rules, list):
            report.failures.append(
                "expect.entity.rules_include must be a list"
            )
        else:
            applied = metadata.get("bsg.rules")
            applied_set = {str(r) for r in applied} if isinstance(applied, list) else set()
            for rule_name in expected_rules:
                if rule_name not in applied_set:
                    report.failures.append(
                        f"entity '{name}': expected rule {rule_name!r} to fire (fired: {sorted(applied_set)})"
                    )


def _check_expectations(
    graph: InMemoryGraph,
    stats: dict[str, Any],
    expect: dict[str, Any],
    report: FixtureReport,
) -> None:
    entity_expectations = expect.get("entity")
    if isinstance(entity_expectations, dict):
        _check_entity_expectation(graph, entity_expectations, report)
    elif isinstance(entity_expectations, list):
        for spec in entity_expectations:
            if isinstance(spec, dict):
                _check_entity_expectation(graph, spec, report)
            else:
                report.failures.append("expect.entity items must be mappings")

    rule_hits = stats.get("rule_hits") or {}

    expected_rules_applied = expect.get("rules_applied_includes") or []
    if isinstance(expected_rules_applied, list):
        for rule_name in expected_rules_applied:
            if not rule_hits.get(rule_name, 0):
                report.failures.append(
                    f"expected rule {rule_name!r} to have fired at least once"
                )

    forbidden_rules = expect.get("rules_applied_excludes") or []
    if isinstance(forbidden_rules, list):
        for rule_name in forbidden_rules:
            if rule_hits.get(rule_name, 0):
                report.failures.append(
                    f"rule {rule_name!r} should not have fired but did "
                    f"({rule_hits[rule_name]} times)"
                )

    min_rules_applied = expect.get("min_rules_applied")
    if isinstance(min_rules_applied, int):
        if int(stats.get("rules_applied", 0)) < min_rules_applied:
            report.failures.append(
                f"expected at least {min_rules_applied} rules applied, "
                f"got {stats.get('rules_applied', 0)}"
            )


def run_plugin_fixture(
    fixture: dict[str, Any] | str | Path,
    *,
    root_path: str | Path | None = None,
    fixture_name: str | None = None,
) -> FixtureReport:
    """Run a single fixture and return a :class:`FixtureReport`.

    Args:
        fixture: Fixture content as a mapping, a path, or a path-like string.
        root_path: Optional filesystem root. Defaults to a temp-like current
            working directory; only relevant for rules that read file
            content.
        fixture_name: Overrides the fixture's ``name`` for reporting.
    """

    fixture_path: str | None = None
    if isinstance(fixture, (str, Path)):
        fixture_path = str(fixture)
        data = yaml.safe_load(Path(fixture).read_text(encoding="utf-8"))
    else:
        data = fixture

    if not isinstance(data, dict):
        raise FixtureError("fixture must be a YAML mapping or equivalent dict")

    name = fixture_name or str(data.get("name") or fixture_path or "<fixture>")
    report = FixtureReport(name=name, fixture_path=fixture_path)

    given = data.get("given") or {}
    expect = data.get("expect") or {}
    plugin_spec = data.get("plugin") or {}

    if not isinstance(given, dict):
        raise FixtureError("fixture.given must be a mapping")
    if not isinstance(expect, dict):
        raise FixtureError("fixture.expect must be a mapping")

    builder = MockGraphBuilder(root=root_path)
    builder.add_from_fixture(given)
    graph = builder.build()

    rules_cfg = _build_rules_config(plugin_spec)
    effective_root = Path(root_path) if root_path is not None else Path.cwd()

    stats = apply_rule_plugins(
        graph=graph,
        root_path=effective_root,
        rules_config=rules_cfg,
    )
    report.stats = stats

    load_errors = stats.get("errors") or []
    if load_errors:
        for err in load_errors:
            report.failures.append(f"rule loader error: {err}")

    _check_expectations(graph, stats, expect, report)

    report.passed = not report.failures
    return report


def run_fixture_directory(
    fixtures_dir: str | Path,
    *,
    root_path: str | Path | None = None,
) -> list[FixtureReport]:
    """Run every ``*.yaml``/``*.yml`` fixture under ``fixtures_dir``."""

    base = Path(fixtures_dir)
    if not base.exists() or not base.is_dir():
        raise FixtureError(f"fixture directory not found: {base}")

    reports: list[FixtureReport] = []
    for path in sorted(base.rglob("*.yaml")):
        reports.append(run_plugin_fixture(path, root_path=root_path))
    for path in sorted(base.rglob("*.yml")):
        reports.append(run_plugin_fixture(path, root_path=root_path))
    return reports


def summarize_reports(reports: Iterable[FixtureReport]) -> dict[str, Any]:
    """Aggregate a list of fixture reports into a single summary dict."""

    reports = list(reports)
    passed = [r for r in reports if r.passed]
    failed = [r for r in reports if not r.passed]
    return {
        "total": len(reports),
        "passed": len(passed),
        "failed": len(failed),
        "failures": [
            {
                "fixture": r.name,
                "path": r.fixture_path,
                "failures": list(r.failures),
            }
            for r in failed
        ],
    }


__all__ = [
    "FixtureError",
    "FixtureReport",
    "MockGraphBuilder",
    "run_fixture_directory",
    "run_plugin_fixture",
    "summarize_reports",
]
