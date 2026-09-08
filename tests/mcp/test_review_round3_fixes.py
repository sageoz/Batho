"""Tests for review round 3 fixes (MCP):

- 7670c3e8: graph_overview unresolved-dependency pattern counts stubs via the
  `unresolved:` ID prefix (stub_entity_count), not the dead UNRESOLVED type key
- 5f7b9d1e: T15 reclassification applied on the MCP raw-row read path
  (normalize_legacy_rel_rows)
- 7e9a1c3b: _resolve_stub name fallback prefers the module path that
  longest-prefix-matches the stub's FQN scope
"""

from __future__ import annotations

import json

import pyarrow as pa
import pytest

from batho.mcp.entity_resolution import (
    KIND_NAME,
    EndpointResolver,
)
from batho.mcp.graph_builder import format_summary, normalize_legacy_rel_rows


# ---------------------------------------------------------------------------
# 7670c3e8: graph_overview unresolved-dependency pattern
# ---------------------------------------------------------------------------


class TestOverviewStubPattern:
    """7670c3e8: the 'External dependencies significant' pattern must fire on
    contextual stubs (unresolved: prefix), which are EXTERNAL_SYMBOL typed."""

    @staticmethod
    def _stats(stub_count: int, total: int) -> dict:
        return {
            "total_entities": total,
            "total_relationships": 0,
            "total_files": 1,
            "entity_breakdown": {"EXTERNAL_SYMBOL": stub_count, "FUNCTION": total - stub_count},
            "stub_entity_count": stub_count,
            "files": [],
        }

    def test_pattern_fires_on_stub_count(self):
        stats = self._stats(stub_count=30, total=100)
        md = format_summary(stats)
        assert "External dependencies significant (30% unresolved)" in md

    def test_pattern_below_threshold_stays_silent(self):
        stats = self._stats(stub_count=10, total=100)
        md = format_summary(stats)
        assert "External dependencies significant" not in md

    def test_legacy_stats_fall_back_to_unresolved_type(self):
        """Old stats dicts without stub_entity_count use the UNRESOLVED key."""
        stats = {
            "total_entities": 100,
            "total_relationships": 0,
            "total_files": 1,
            "entity_breakdown": {"UNRESOLVED": 25, "FUNCTION": 75},
            "files": [],
        }
        md = format_summary(stats)
        assert "External dependencies significant (25% unresolved)" in md


# ---------------------------------------------------------------------------
# 5f7b9d1e: T15 reclassification on the raw-row read path
# ---------------------------------------------------------------------------


class TestNormalizeLegacyRelRows:
    """5f7b9d1e: legacy inverse types are re-classified with swapped endpoints."""

    def test_called_by_becomes_calls_with_swapped_endpoints(self):
        row = {
            "file_id": 1,
            "source_id": "ent-callee",
            "target_id": "ent-caller",
            "relation_type": "CALLED_BY",
            "metadata_json": json.dumps({"line": 5}),
            "roles": 0,
            "confidence": 1.0,
        }
        out = normalize_legacy_rel_rows([row])
        assert len(out) == 1
        norm = out[0]
        assert norm["relation_type"] == "CALLS"
        assert norm["source_id"] == "ent-caller"
        assert norm["target_id"] == "ent-callee"
        meta = json.loads(norm["metadata_json"])
        assert meta["reversed"] is True
        assert meta["line"] == 5

    def test_all_deprecated_types_mapped(self):
        for legacy, forward in [
            ("CALLED_BY", "CALLS"),
            ("IMPORTED_BY", "IMPORTS"),
            ("REFERENCED_IN", "READS"),
            ("CONTAINED_WITHIN", "CONTAINS"),
        ]:
            row = {
                "file_id": 1,
                "source_id": "a",
                "target_id": "b",
                "relation_type": legacy,
                "metadata_json": None,
            }
            (norm,) = normalize_legacy_rel_rows([row])
            assert norm["relation_type"] == forward
            assert (norm["source_id"], norm["target_id"]) == ("b", "a")
            assert json.loads(norm["metadata_json"])["reversed"] is True

    def test_forward_rows_untouched(self):
        row = {
            "file_id": 1,
            "source_id": "a",
            "target_id": "b",
            "relation_type": "CALLS",
            "metadata_json": None,
        }
        out = normalize_legacy_rel_rows([row])
        assert out[0] is row

    def test_invalid_metadata_json_tolerated(self):
        row = {
            "file_id": 1,
            "source_id": "a",
            "target_id": "b",
            "relation_type": "CALLED_BY",
            "metadata_json": "not-json{",
        }
        (norm,) = normalize_legacy_rel_rows([row])
        assert json.loads(norm["metadata_json"]) == {"reversed": True}


# ---------------------------------------------------------------------------
# 7e9a1c3b: _resolve_stub ambiguous name fallback
# ---------------------------------------------------------------------------


def _stub(caller_scope: str, fqn: str) -> str:
    return f"unresolved:batho npm docs-site 0.0.0 {caller_scope}:::{fqn}".replace(":::", "::")


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


class TestResolveStubAmbiguousName:
    """7e9a1c3b: same-named symbols in multiple files resolve by FQN-scope
    module-prefix match, deterministically."""

    @staticmethod
    def _resolver(files: dict[str, int]) -> EndpointResolver:
        agent_rows = [
            {"file_id": 1, "entity_id": "ent-main-main", "name": "main", "entity_type": "FUNCTION"},
            {"file_id": 2, "entity_id": "ent-pkg-helper", "name": "helper", "entity_type": "FUNCTION"},
            {"file_id": 3, "entity_id": "ent-other-helper", "name": "helper", "entity_type": "FUNCTION"},
        ]
        return EndpointResolver(_FakeReader(agent_rows, [], files))

    def test_prefers_module_matching_stub_scope(self):
        """Stub `pkg.helper` must resolve to pkg/helper.py, not other/helper.py."""
        resolver = self._resolver({
            "main.py": 1,
            "pkg/helper.py": 2,
            "other/helper.py": 3,
        })
        target = resolver.resolve(_stub("main().", "pkg.helper"))
        assert target.kind == KIND_NAME
        assert target.file_id == 2
        assert target.path == "pkg/helper.py"

    def test_deterministic_when_no_scope_matches(self):
        """No module matches the stub scope → deterministic first-defined wins."""
        resolver = self._resolver({
            "main.py": 1,
            "alpha/helper.py": 2,
            "beta/helper.py": 3,
        })
        target = resolver.resolve(_stub("main().", "totally.unknown.helper"))
        assert target.kind == KIND_NAME
        assert target.file_id == 2

    def test_deterministic_across_rebuilds(self):
        """Same inputs → same resolution (artifact order tie-break)."""
        files = {"main.py": 1, "alpha/helper.py": 2, "beta/helper.py": 3}
        t1 = self._resolver(files).resolve(_stub("main().", "zzz.helper"))
        t2 = self._resolver(files).resolve(_stub("main().", "zzz.helper"))
        assert t1.file_id == t2.file_id
