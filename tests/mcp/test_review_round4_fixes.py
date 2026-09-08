"""Tests for review round 4 fixes (MCP):

- 8d4f2a91: cross_file_edges applies T15 legacy normalization (forward types,
  swapped endpoints) and excludes legacy CONTAINED_WITHIN from the dependency
  aggregation
- 9b1e47c2: entity_types filter values are normalized to uppercase
- 4c8d1a36: batho://schema exposes the deprecated type lists
"""

from __future__ import annotations

import asyncio
import json

import pyarrow as pa

from batho.mcp.entity_resolution import EndpointResolver
from batho.mcp.tools import _expand_entity_categories


AGENT_SCHEMA = pa.schema([
    pa.field("file_id", pa.int64(), nullable=False),
    pa.field("entity_id", pa.large_utf8(), nullable=False),
    pa.field("name", pa.utf8(), nullable=False),
    pa.field("entity_type", pa.utf8(), nullable=False),
])

RELS_SCHEMA = pa.schema([
    pa.field("file_id", pa.int64(), nullable=False),
    pa.field("source_id", pa.large_utf8(), nullable=False),
    pa.field("target_id", pa.large_utf8(), nullable=False),
    pa.field("relation_type", pa.utf8(), nullable=False),
    pa.field("metadata_json", pa.utf8(), nullable=True),
    pa.field("roles", pa.int32(), nullable=True),
    pa.field("confidence", pa.float32(), nullable=True),
])


class _FakeReader:
    """Duck-typed BathoBundleReader backed by in-memory Arrow tables."""

    def __init__(self, agent_rows, rels_rows, files, generation=1, root="/repo"):
        self._agent = pa.Table.from_pylist(agent_rows, schema=AGENT_SCHEMA)
        self._rels = pa.Table.from_pylist(rels_rows, schema=RELS_SCHEMA)
        self._files = files
        self.generation = generation
        self.root = root

    def _get_table(self, logical_name):
        if logical_name == "agent_views":
            return self._agent
        if logical_name == "rels_views":
            return self._rels
        return pa.table({})

    def get_all_file_tracking(self):
        return {
            fp: {"file_id": fid, "file_path": fp, "is_indexed": True}
            for fp, fid in self._files.items()
        }

    def get_manifest(self):
        return {"generation": self.generation}

    def get_latest_run_id(self):
        return "run-1"

    def get_run(self, run_uuid):
        return {"root_path": self.root}


def _legacy_resolver(rels_rows: list[dict]) -> EndpointResolver:
    """Resolver over a pre-T15 shaped artifact (legacy inverse type rows)."""
    agent_rows = [
        {"file_id": 1, "entity_id": "ent-main-main", "name": "main", "entity_type": "FUNCTION"},
        {"file_id": 2, "entity_id": "ent-utils-helper", "name": "helper", "entity_type": "FUNCTION"},
    ]
    files = {"main.py": 1, "utils.py": 2}
    return EndpointResolver(_FakeReader(agent_rows, rels_rows, files))


class TestCrossFileEdgesLegacyNormalization:
    """8d4f2a91: cross_file_edges re-classifies legacy inverse types."""

    def test_called_by_becomes_forward_calls_with_swapped_endpoints(self):
        """Legacy CALLED_BY (source=callee, target=caller, stored under the
        caller's file) becomes a forward CALLS edge (source=caller file)."""
        resolver = _legacy_resolver([
            {"file_id": 1, "source_id": "ent-utils-helper", "target_id": "ent-main-main",
             "relation_type": "CALLED_BY", "metadata_json": None, "roles": 0, "confidence": 1.0},
        ])
        edges = resolver.cross_file_edges()
        assert len(edges) == 1
        rel, sf, tf = edges[0]
        assert rel["relation_type"] == "CALLS"
        assert (sf, tf) == (1, 2)

    def test_cross_file_contained_within_excluded(self):
        """Legacy CONTAINED_WITHIN rows must not leak into the aggregation."""
        resolver = _legacy_resolver([
            {"file_id": 1, "source_id": "ent-main-main", "target_id": "ent-utils-helper",
             "relation_type": "CONTAINED_WITHIN", "metadata_json": None, "roles": 0, "confidence": 1.0},
            {"file_id": 1, "source_id": "ent-main-main", "target_id": "ent-utils-helper",
             "relation_type": "CALLS", "metadata_json": None, "roles": 0, "confidence": 1.0},
        ])
        edges = resolver.cross_file_edges()
        assert len(edges) == 1
        assert edges[0][0]["relation_type"] == "CALLS"

    def test_forward_rows_unchanged(self):
        resolver = _legacy_resolver([
            {"file_id": 1, "source_id": "ent-main-main", "target_id": "ent-utils-helper",
             "relation_type": "CALLS", "metadata_json": None, "roles": 0, "confidence": 1.0},
        ])
        edges = resolver.cross_file_edges()
        assert len(edges) == 1
        assert edges[0][0]["relation_type"] == "CALLS"
        assert (edges[0][1], edges[0][2]) == (1, 2)


def _legacy_resolver(rels_rows: list[dict]) -> EndpointResolver:
    agent_rows = [
        {"file_id": 1, "entity_id": "ent-main-main", "name": "main", "entity_type": "FUNCTION"},
        {"file_id": 2, "entity_id": "ent-utils-helper", "name": "helper", "entity_type": "FUNCTION"},
    ]
    files = {"main.py": 1, "utils.py": 2}
    return EndpointResolver(_FakeReader(agent_rows, rels_rows, files))


class TestEntityTypesCaseNormalization:
    """9b1e47c2: entity_types values are normalized to uppercase."""

    def test_lowercase_normalized(self):
        merged, err = _expand_entity_categories(None, ["function", "CLASS"])
        assert err is None
        assert merged == ["CLASS", "FUNCTION"]

    def test_none_passthrough(self):
        merged, err = _expand_entity_categories(None, None)
        assert merged is None
        assert err is None

    def test_categories_merge_with_normalized_types(self):
        merged, err = _expand_entity_categories(["external"], ["function"])
        assert err is None
        assert "FUNCTION" in merged
        assert "EXTERNAL_SYMBOL" in merged


class TestSchemaDeprecatedLists:
    """4c8d1a36: batho://schema exposes the deprecated type lists."""

    def test_schema_includes_deprecated_lists(self):
        from batho.mcp.server import create_app
        app = create_app()
        result = asyncio.run(app.read_resource("batho://schema"))
        content = result.contents[0].content if hasattr(result, "contents") else str(result)
        data = json.loads(content)

        assert data["deprecated_entity_types"] == [
            "ATTRIBUTE", "GLOBAL_STATEMENT", "IMPORT_BLOCK", "UNRESOLVED",
        ]
        assert data["deprecated_relation_types"] == [
            "CALLED_BY", "CONTAINED_WITHIN", "IMPORTED_BY", "REFERENCED_IN",
        ]
