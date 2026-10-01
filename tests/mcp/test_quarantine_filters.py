"""
tests/mcp/test_quarantine_filters.py

Unit tests for T03 quarantine exclusion flags (batho-calibrate):
  - metadata_is_quarantined / entity_is_quarantined helpers
  - _quarantined_entity_ids Arrow-level detection
  - writer persists metadata_json for flagged entities
  - community detection excludes flagged entities
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pyarrow as pa

from batho.core.schemas import (
    RelationshipType,
    entity_is_quarantined,
    metadata_is_quarantined,
)
from batho.mcp.tools import _quarantined_entity_ids
from batho.modules.graph.community import detect_communities
from batho.modules.storage.arrow_bundle.writer import BathoBundleWriter


class TestMetadataHelpers:
    def test_noise_flag_quarantines(self):
        assert metadata_is_quarantined({"bsg.noise": True}) is True

    def test_quarantined_flag_quarantines(self):
        assert metadata_is_quarantined({"bsg.quarantined": True}) is True

    def test_false_values_do_not_quarantine(self):
        assert metadata_is_quarantined({"bsg.noise": False}) is False
        assert metadata_is_quarantined({"bsg.quarantined": 0}) is False

    def test_empty_or_missing_metadata_clean(self):
        assert metadata_is_quarantined(None) is False
        assert metadata_is_quarantined({}) is False
        assert metadata_is_quarantined({"other": 1}) is False

    def test_entity_unresolved_prefix(self):
        assert entity_is_quarantined("unresolved:foo::bar", None) is True
        assert entity_is_quarantined("resolved:foo", None) is False
        assert entity_is_quarantined("e1", {"bsg.noise": True}) is True


def _entity_table(rows: list[dict]) -> pa.Table:
    return pa.table(
        {
            "entity_id": pa.array([r["entity_id"] for r in rows], type=pa.large_utf8()),
            "name": pa.array([r.get("name", "") for r in rows], type=pa.large_utf8()),
            "metadata_json": pa.array(
                [r.get("metadata_json") for r in rows], type=pa.utf8()
            ),
        }
    )


class TestQuarantinedEntityIds:
    def test_finds_flagged_entities(self):
        table = _entity_table(
            [
                {"entity_id": "e1", "metadata_json": '{"bsg.noise": true}'},
                {"entity_id": "e2", "metadata_json": '{"bsg.quarantined": true}'},
                {"entity_id": "e3", "metadata_json": None},
                {"entity_id": "e4", "metadata_json": '{"bsg.category": "SOURCE"}'},
            ]
        )
        assert _quarantined_entity_ids(table) == {"e1", "e2"}

    def test_false_flag_not_quarantined(self):
        table = _entity_table(
            [{"entity_id": "e1", "metadata_json": '{"bsg.noise": false}'}]
        )
        assert _quarantined_entity_ids(table) == set()

    def test_missing_column_returns_empty(self):
        table = pa.table({"entity_id": pa.array(["e1"], type=pa.large_utf8())})
        assert _quarantined_entity_ids(table) == set()

    def test_empty_table_returns_empty(self):
        table = _entity_table([])
        assert _quarantined_entity_ids(table) == set()


class TestWriterPersistsQuarantineMetadata:
    def _writer(self, tmp_path: Path) -> BathoBundleWriter:
        return BathoBundleWriter(bundle_dir=tmp_path, run_id=1)

    def _write(self, w: BathoBundleWriter, entities: list[dict]) -> None:
        w.write_file_artifact(
            file_id=1,
            agent={"entities": entities},
            storage={"entities": []},
            rels=[],
            content_hash="h",
        )

    def test_flagged_entity_keeps_metadata(self, tmp_path: Path):
        w = self._writer(tmp_path)
        self._write(w, [{"id": "e1", "name": "foo", "metadata": {"bsg.noise": True}}])
        meta = w._agent_buf["metadata_json"]
        assert len(meta) == 1
        assert '"bsg.noise": true' in meta[0]

    def test_unflagged_entity_metadata_dropped(self, tmp_path: Path):
        """Extraction metadata outside the projection (bsg.* +
        decorators/docstring/invocation_snippet, CFG-03) stays null to bound
        artifact size."""
        w = self._writer(tmp_path)
        self._write(w, [{"id": "e1", "name": "foo", "metadata": {"some_internal": 1}}])
        assert w._agent_buf["metadata_json"] == [None]

    def test_bsg_projection_persists_enrichment(self, tmp_path: Path):
        """bsg.* keys persist (T08 durability); matcher keys persist too
        (CFG-03); other non-bsg keys are projected out."""
        w = self._writer(tmp_path)
        self._write(w, [{"id": "e1", "name": "foo", "metadata": {
            "bsg.category": "SOURCE",
            "bsg.rules": ["r1"],
            "decorators": ["x"],       # matcher key — persisted (CFG-03)
            "tree_sitter_node": "n",   # dropped by projection
        }}])
        import json as _json
        meta = _json.loads(w._agent_buf["metadata_json"][0])
        assert meta == {
            "bsg.category": "SOURCE",
            "bsg.rules": ["r1"],
            "decorators": ["x"],
        }

    def test_unresolved_stub_keeps_metadata(self, tmp_path: Path):
        w = self._writer(tmp_path)
        self._write(w, [{"id": "unresolved:x::y", "name": "stub", "metadata": {"caller_scope": "s"}}])
        assert w._agent_buf["metadata_json"][0] is not None


class _SimpleEntity:
    def __init__(self, eid: str, file: str, metadata: dict | None = None):
        self.id = eid
        self.file = file
        self.name = eid
        self.metadata = metadata


class _SimpleRel:
    def __init__(self, source_id: str, target_id: str):
        self.source_id = source_id
        self.target_id = target_id
        self.type = RelationshipType.CALLS


class TestCommunityExclusion:
    def test_flagged_entity_excluded_from_communities(self):
        graph = MagicMock()
        graph.entities = {
            "a1": _SimpleEntity("a1", "a.py"),
            "a2": _SimpleEntity("a2", "a.py"),
            "a3": _SimpleEntity("a3", "a.py"),
            "noise1": _SimpleEntity("noise1", "vendor/lock.py", {"bsg.noise": True}),
        }
        graph.relationships = [
            _SimpleRel("a1", "a2"),
            _SimpleRel("a2", "a3"),
            _SimpleRel("a3", "noise1"),
        ]
        graph._rels_by_endpoint = {}
        for rel in graph.relationships:
            graph._rels_by_endpoint.setdefault(rel.source_id, []).append(rel)
            graph._rels_by_endpoint.setdefault(rel.target_id, []).append(rel)
        graph.degree_by_endpoint = lambda eid: len(graph._rels_by_endpoint.get(eid, []))

        communities = detect_communities(graph, {"enabled": True})
        all_members = {eid for c in communities for eid in c.member_entity_ids}
        assert "noise1" not in all_members
        assert {"a1", "a2", "a3"} <= all_members
