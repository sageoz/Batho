"""Regression tests for stub-resolution persistence (T5, spec-required).

.specs/stub-resolution-persistence T5 "Tests" line requires: build a fixture
(qualified dep-member usage), assert artifact rels contain the resolved
target; plus a patch-path regression test.

Covers both halves of the persistence contract:
  - rels rows: unresolved:* targets rewritten to resolved ids with strategy
    confidence and merged metadata (was implemented, untested)
  - agent_views stub entity rows: stub_resolution_state /
    resolved_target_id / resolution_strategy / resolution_confidence
    persisted via metadata_json (issue 3c8a1f9e62d4)
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pytest

from batho.modules.storage.arrow_bundle.writer import BathoBundleWriter


def _read_ipc(path: Path) -> list[dict]:
    with pa.memory_map(str(path), "r") as src:
        return ipc.open_file(src).read_all().to_pylist()


# ---------------------------------------------------------------------------
# Writer-level unit test — the finalize-time rewrite op
# ---------------------------------------------------------------------------

class TestWriterStubRewrites:

    def _write_fixture(self, tmp_path: Path) -> dict[str, Path]:
        w = BathoBundleWriter(tmp_path, run_id=1)
        w.write_file_artifact(
            file_id=1,
            agent={"entities": [
                {
                    "id": "unresolved:main()::Field",
                    "name": "Field",
                    "type": "EXTERNAL_SYMBOL",
                    "start_line": 10,
                    "metadata": {
                        "caller_scope": "batho pip x 1.0.0 main.py",
                        "target_name": "Field",
                        "stub_resolution_state": "pending",
                    },
                },
                {
                    "id": "batho pip x 1.0.0 main.py/helper().",
                    "name": "helper",
                    "type": "FUNCTION",
                    "start_line": 3,
                },
            ]},
            storage={"entities": []},
            rels=[{
                "source_id": "batho pip x 1.0.0 main.py/helper().",
                "target_id": "unresolved:main()::Field",
                "relation_type": "CALLS",
                "metadata": {"ref_kind": "attribute"},
                "confidence": 1.0,
            }],
            content_hash="h1",
        )
        w.set_stub_rewrites(
            {
                "unresolved:main()::Field": (
                    "batho pip pydantic 2 pydantic/Field().",
                    0.75,
                    {"resolution_strategy": "sibling_module"},
                )
            },
            entity_meta={
                "unresolved:main()::Field": {
                    "stub_resolution_state": "resolved",
                    "resolved_target_id": "batho pip pydantic 2 pydantic/Field().",
                    "resolution_strategy": "sibling_module",
                    "resolution_confidence": 0.75,
                }
            },
        )
        return w.finalize()

    def test_rels_target_rewritten_with_confidence_and_meta(self, tmp_path):
        streams = self._write_fixture(tmp_path)
        (rel,) = _read_ipc(streams["rels_views"])
        assert rel["target_id"] == "batho pip pydantic 2 pydantic/Field()."
        assert rel["confidence"] == pytest.approx(0.75)
        meta = json.loads(rel["metadata_json"])
        # existing rel metadata preserved, strategy merged in
        assert meta["ref_kind"] == "attribute"
        assert meta["resolution_strategy"] == "sibling_module"

    def test_stub_entity_row_persists_resolution_state(self, tmp_path):
        """T5 acceptance: stub entities persist stub_resolution_state +
        resolved_target_id in agent_views metadata_json."""
        streams = self._write_fixture(tmp_path)
        ents = {e["entity_id"]: e for e in _read_ipc(streams["agent_views"])}
        stub = ents["unresolved:main()::Field"]
        meta = json.loads(stub["metadata_json"])
        assert meta["stub_resolution_state"] == "resolved"
        assert meta["resolved_target_id"] == "batho pip pydantic 2 pydantic/Field()."
        assert meta["resolution_strategy"] == "sibling_module"
        assert meta["resolution_confidence"] == 0.75
        # extraction-time stub metadata is preserved
        assert meta["target_name"] == "Field"
        assert meta["caller_scope"] == "batho pip x 1.0.0 main.py"

    def test_non_stub_entities_have_null_metadata(self, tmp_path):
        """metadata_json is bounded to stub rows — no per-entity bloat."""
        streams = self._write_fixture(tmp_path)
        ents = {e["entity_id"]: e for e in _read_ipc(streams["agent_views"])}
        assert ents["batho pip x 1.0.0 main.py/helper()."]["metadata_json"] is None

    def test_no_rewrites_means_no_rewrite_file(self, tmp_path):
        """Empty rewrite set: finalize leaves the tmp files untouched."""
        w = BathoBundleWriter(tmp_path, run_id=1)
        w.write_file_artifact(
            file_id=1,
            agent={"entities": [{
                "id": "batho pip x 1.0.0 a.py/f().",
                "name": "f", "type": "FUNCTION", "start_line": 1,
            }]},
            storage={"entities": []},
            rels=[{
                "source_id": "a", "target_id": "b",
                "relation_type": "CALLS", "confidence": 1.0,
            }],
            content_hash="h",
        )
        streams = w.finalize()
        (rel,) = _read_ipc(streams["rels_views"])
        assert rel["target_id"] == "b"
        assert rel["confidence"] == pytest.approx(1.0)

    def test_rewrite_spans_record_batches(self, tmp_path, monkeypatch):
        """Multi-batch rels file: a stub hit in a later batch is rewritten
        while earlier batches pass through untouched — the chunked rewrite
        must not assume a single batch (issue 5d576bd8ac92)."""
        import batho.modules.storage.arrow_bundle.writer as writer_mod
        monkeypatch.setattr(writer_mod, "FLUSH_THRESHOLD_ROWS", 1)

        w = BathoBundleWriter(tmp_path, run_id=1)
        for fid, target in ((1, "real-target"), (2, "unresolved:main()::Field")):
            w.write_file_artifact(
                file_id=fid,
                agent={"entities": []},
                storage={"entities": []},
                rels=[{
                    "source_id": f"src-{fid}", "target_id": target,
                    "relation_type": "CALLS", "confidence": 1.0,
                }],
                content_hash=f"h{fid}",
            )
        w.set_stub_rewrites({
            "unresolved:main()::Field": ("resolved:t", 0.5, {"k": "v"}),
        })
        streams = w.finalize()

        # Sanity: the fixture really produced a multi-batch file.
        with pa.memory_map(str(streams["rels_views"]), "r") as src:
            assert ipc.open_file(src).num_record_batches >= 2

        rels = _read_ipc(streams["rels_views"])
        assert len(rels) == 2
        by_source = {r["source_id"]: r for r in rels}
        assert by_source["src-1"]["target_id"] == "real-target"
        hit = by_source["src-2"]
        assert hit["target_id"] == "resolved:t"
        assert hit["confidence"] == pytest.approx(0.5)
        assert json.loads(hit["metadata_json"])["k"] == "v"


# ---------------------------------------------------------------------------
# Build/patch e2e — persisted artifact state (spec-required fixture tests)
# ---------------------------------------------------------------------------

def _fixture_project(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    # helper.py defines Field; main.py calls it cross-file inside a function
    # body (module-level calls emit no rels) -> stub resolves via the
    # registered flat symbol name.
    (root / "helper.py").write_text(
        "def Field():\n    return 1\n",
        encoding="utf-8",
    )
    (root / "main.py").write_text(
        "import helper\n\ndef main():\n    helper.Field()\n",
        encoding="utf-8",
    )


def _agent_stub_rows(reader) -> list[dict]:
    table = reader._get_table("agent_views")
    rows = table.to_pylist()
    return [r for r in rows if str(r["entity_id"]).startswith("unresolved:")]


@pytest.mark.timeout(120)
class TestBuildPersistsStubResolution:

    def test_rels_views_contains_resolved_target(self, tmp_path):
        from batho.orchestrator.build import run_build, BuildOptions

        root = tmp_path / "proj"
        _fixture_project(root)
        result = run_build(BuildOptions(root=root, force_full=True))
        assert result.success, f"build failed: {result.warnings}"

        from batho.mcp.tools import _get_reader
        reader = _get_reader(str(root))
        rels = reader._get_table("rels_views").to_pylist()
        resolved = [
            r for r in rels
            if str(r["target_id"]).endswith("helper/Field().")
        ]
        assert resolved, (
            "no rel row targets the resolved helper.Field entity — "
            "stub-resolution rewrite did not persist"
        )
        # The pre-resolution unresolved: target must be gone from the artifact.
        assert not [
            r for r in resolved if str(r["target_id"]).startswith("unresolved:")
        ]

    def test_stub_entity_rows_persist_state(self, tmp_path):
        from batho.orchestrator.build import run_build, BuildOptions

        root = tmp_path / "proj"
        _fixture_project(root)
        result = run_build(BuildOptions(root=root, force_full=True))
        assert result.success, f"build failed: {result.warnings}"

        from batho.mcp.tools import _get_reader
        reader = _get_reader(str(root))
        stub_rows = _agent_stub_rows(reader)
        resolved_rows = [
            r for r in stub_rows
            if r["metadata_json"]
            and json.loads(r["metadata_json"]).get("stub_resolution_state") == "resolved"
        ]
        assert resolved_rows, (
            "no stub entity row carries persisted stub_resolution_state=resolved"
        )
        meta = json.loads(resolved_rows[0]["metadata_json"])
        assert meta["resolved_target_id"].endswith("helper/Field().")
        assert meta["resolution_strategy"]
        assert meta["resolution_confidence"] > 0

    def test_patch_path_persists_stub_resolution(self, tmp_path):
        """Patch-path regression: the same persistence holds on incremental runs."""
        from batho.orchestrator.build import run_build, BuildOptions
        from batho.orchestrator.patch import run_patch, PatchOptions

        root = tmp_path / "proj"
        _fixture_project(root)
        result = run_build(BuildOptions(root=root, force_full=True))
        assert result.success, f"build failed: {result.warnings}"

        # Change main.py so the patch re-extracts it and re-resolves its stubs.
        (root / "main.py").write_text(
            "import helper\n\ndef main():\n    helper.Field()\n    return 1\n",
            encoding="utf-8",
        )
        patch_result = run_patch(PatchOptions(root=root))
        assert patch_result.success, f"patch failed"

        from batho.mcp.tools import _get_reader
        reader = _get_reader(str(root))
        rels = reader._get_table("rels_views").to_pylist()
        resolved = [
            r for r in rels
            if str(r["target_id"]).endswith("helper/Field().")
        ]
        assert resolved, "patch artifact lost the resolved stub target"

        stub_rows = _agent_stub_rows(reader)
        resolved_rows = [
            r for r in stub_rows
            if r["metadata_json"]
            and json.loads(r["metadata_json"]).get("stub_resolution_state") == "resolved"
        ]
        assert resolved_rows, "patch artifact lost persisted stub entity state"
