"""Tests for BathoBundleWriter — flush, sort-by-file_id, generation increment."""

from __future__ import annotations

import tempfile
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pytest

from batho.modules.storage.arrow_bundle.writer import BathoBundleWriter, write_simple_ipc, read_ipc_table
from batho.modules.storage.arrow_bundle.schemas import FILE_TRACKING_SCHEMA, RUNS_SCHEMA
from batho.modules.storage.arrow_bundle.bundle import BathoBundle
from batho.modules.storage.arrow_bundle.reader import BathoBundleReader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent_entity(file_id: int, entity_id: str) -> dict:
    return {
        "file_id": file_id,
        "entity_id": entity_id,
        "name": "func",
        "entity_type": "function",
        "start_line": 1,
        "end_line": 10,
        "signature": None,
        "content_hash": "abc",
        "is_exported": False,
        "fqn": None,
    }


# ---------------------------------------------------------------------------
# write_simple_ipc / read_ipc_table
# ---------------------------------------------------------------------------

class TestWriteReadIpc:
    def test_roundtrip_nonempty(self, tmp_path):
        """Verify that write_simple_ipc and read_ipc_table roundtrip a non-empty schema correctly."""
        rows = [
            {"file_id": 1, "file_path": "a.py", "content_hash": "h1",
             "mtime_ns": 0, "inode": None, "size": 10, "is_indexed": True,
             "last_run_uuid": "r1", "updated_at": "2024-01-01T00:00:00", "encoding": "utf-8"},
        ]
        path = tmp_path / "test.ipc"
        write_simple_ipc(rows, FILE_TRACKING_SCHEMA, path)

        table = read_ipc_table(path)
        assert table.num_rows == 1
        assert table.schema == FILE_TRACKING_SCHEMA
        assert table.column("file_path").to_pylist() == ["a.py"]

    def test_roundtrip_empty(self, tmp_path):
        """Verify that writing and reading an empty list produces an empty table with the correct schema."""
        path = tmp_path / "empty.ipc"
        write_simple_ipc([], FILE_TRACKING_SCHEMA, path)
        table = read_ipc_table(path)
        assert table.num_rows == 0
        assert table.schema == FILE_TRACKING_SCHEMA

    def test_read_ipc_none_path(self):
        """Verify that passing None to read_ipc_table returns an empty table."""
        table = read_ipc_table(None)
        assert table.num_rows == 0

    def test_read_ipc_missing_file(self, tmp_path):
        """Verify that reading a non-existent IPC file returns an empty table."""
        table = read_ipc_table(tmp_path / "nonexistent.ipc")
        assert table.num_rows == 0

    def test_read_ipc_zero_byte_file(self, tmp_path):
        """Verify that reading a zero-byte IPC file returns an empty table."""
        p = tmp_path / "zero.ipc"
        p.write_bytes(b"")
        table = read_ipc_table(p)
        assert table.num_rows == 0

    def test_multiple_rows_preserved(self, tmp_path):
        """Verify that multiple rows are preserved correctly through an IPC roundtrip."""
        rows = [
            {"file_id": i, "file_path": f"f{i}.py", "content_hash": f"h{i}",
             "mtime_ns": i, "inode": None, "size": i * 10, "is_indexed": False,
             "last_run_uuid": None, "updated_at": "2024-01-01T00:00:00", "encoding": "utf-8"}
            for i in range(5)
        ]
        path = tmp_path / "multi.ipc"
        write_simple_ipc(rows, FILE_TRACKING_SCHEMA, path)
        table = read_ipc_table(path)
        assert table.num_rows == 5
        assert sorted(table.column("file_id").to_pylist()) == list(range(5))


# ---------------------------------------------------------------------------
# BathoBundleWriter
# ---------------------------------------------------------------------------

class TestBathoBundleWriter:
    def test_init_creates_dir(self, tmp_path):
        """Verify that BathoBundleWriter initialization creates the artifact directory."""
        bundle_dir = tmp_path / "artifact"
        writer = BathoBundleWriter(bundle_dir, run_id=1)
        assert bundle_dir.exists()

    def test_write_single_agent_entity(self, tmp_path):
        """Verify that writing a single agent entity buffers it correctly."""
        writer = BathoBundleWriter(tmp_path, run_id=1)
        writer.write_file_artifact(
            file_id=1,
            agent={"entities": [{"id": "e1", "name": "foo", "type": "function",
                                  "start_line": 1, "is_exported": True}]},
            storage={"entities": []},
            rels=[],
            content_hash="abc123",
        )
        assert len(writer._agent_buf["entity_id"]) == 1
        assert writer._agent_buf["entity_id"][0] == "e1"

    def test_write_multiple_files_accumulates(self, tmp_path):
        """Verify that writing artifacts for multiple files accumulates them in the internal buffer."""
        writer = BathoBundleWriter(tmp_path, run_id=1)
        for fid in range(3):
            writer.write_file_artifact(
                file_id=fid,
                agent={"entities": [{"id": f"e{fid}", "name": "fn", "type": "function",
                                      "start_line": 1, "is_exported": False}]},
                storage={"entities": []},
                rels=[],
                content_hash=f"h{fid}",
            )
        assert len(writer._agent_buf["file_id"]) == 3

    def test_finalize_writes_tmp_ipc_files(self, tmp_path):
        """Verify that finalize writes non-empty streams to temporary IPC files on disk."""
        writer = BathoBundleWriter(tmp_path, run_id=1)
        writer.write_file_artifact(
            file_id=2,
            agent={"entities": [{"id": "e2", "name": "bar", "type": "class",
                                  "start_line": 5, "is_exported": False}]},
            storage={"entities": []},
            rels=[{"source_id": "e2", "target_id": "e3", "relation_type": "calls"}],
            content_hash="deadbeef",
        )
        streams = writer.finalize()
        assert "agent_views" in streams
        assert streams["agent_views"].exists()
        assert streams["agent_views"].stat().st_size > 0

    def test_finalize_empty_produces_no_streams(self, tmp_path):
        """Verify that finalizing an empty writer produces no output streams."""
        writer = BathoBundleWriter(tmp_path, run_id=1)
        streams = writer.finalize()
        assert streams == {}

    def test_rels_written_correctly(self, tmp_path):
        """Verify that relationship data is written correctly to the rels_views stream."""
        writer = BathoBundleWriter(tmp_path, run_id=1)
        writer.write_file_artifact(
            file_id=10,
            agent={"entities": []},
            storage={"entities": []},
            rels=[
                {"source_id": "s1", "target_id": "t1", "type": "imports"},
                {"source_id": "s2", "target_id": "t2", "type": "calls"},
            ],
            content_hash="relshash",
        )
        streams = writer.finalize()
        assert "rels_views" in streams
        table = read_ipc_table(streams["rels_views"])
        assert table.num_rows == 2
        assert set(table.column("relation_type").to_pylist()) == {"imports", "calls"}


class TestBundleWriterAndOffsets:
    """Concurrency and offset indexing validation for the BathoBundleWriter."""

    def test_bundle_writer_concurrency(self, tmp_path: Path):
        """Verify that concurrent runs get separate writer instances to prevent cross-run contamination.

        Scenario:
            Multiple indexing jobs might spawn concurrently. The main `BathoBundle` must provision
            independent writer instances per active run ID, mapped locally, preventing one run's flushes
            from bleeding into another's.

        Execution Flow:
            1. Initialize `BathoBundle` on `tmp_path`.
            2. Call `create_run("run-1")` and `create_run("run-2")`.
            3. Assert that both run IDs are unique and not equal.
            4. Verify that each run's writer in the bundle's `_writers` mapping are completely distinct objects.
            5. Verify that each writer contains the correct corresponding `run_id`.
            6. Clean up by closing the bundle.

        Expectations:
            - Independent writer instances per concurrent run.
            - Absolute separation of write streams.
        """
        bundle = BathoBundle(tmp_path)
        
        # Simulate concurrent run creation
        run_id_1 = bundle.create_run("run-1")
        run_id_2 = bundle.create_run("run-2")

        # Assert they have distinct writer instances in the writers map
        assert run_id_1 != run_id_2
        assert bundle._writers[run_id_1] is not bundle._writers[run_id_2]
        assert bundle._writers[run_id_1].run_id == run_id_1
        assert bundle._writers[run_id_2].run_id == run_id_2

        # Clean up
        bundle.close()

    def test_multi_flush_offset_index_correctness(self, tmp_path: Path):
        """Verify that multi-batch flushes are correctly sorted and indexed on load, avoiding corruption.

        Scenario:
            A long build or patch job flushes intermediate buffers to disk multiple times.
            When those files are read back by the index reader, the internal offset mappings
            and chunk sizes must be calculated correctly, avoiding out-of-bounds array slicing.

        Execution Flow:
            1. Set up artifact dir and initialize `BathoBundleWriter`.
            2. Write Batch 1 (file_id=3) and trigger locked buffer flush.
            3. Write Batch 2 (file_id=1) and trigger locked buffer flush.
            4. Write Batch 3 (file_id=2) and finalize the writer.
            5. Write a mock `meta.json` manifest.
            6. Initialize `BathoBundleReader` and retrieve file artifacts by ID for 1, 2, and 3.
            7. Assert that each retrieved file artifact matches the expected source data exactly.

        Expectations:
            - Independent batches written via multiple flushes are stitched together cleanly.
            - Readers slice Arrow RecordBatches exactly according to the multi-flush index offsets.
        """
        artifact_dir = tmp_path / "artifact"
        artifact_dir.mkdir()
        
        # 1. Write multiple batches simulating separate flushes
        writer = BathoBundleWriter(artifact_dir, run_id=1)
        
        # Batch 1: file_id = 3
        writer.write_file_artifact(
            file_id=3,
            agent={"entities": [{"id": "ent3", "name": "func3", "type": "function", "start_line": 1}]},
            storage={"entities": []},
            rels=[],
            content_hash="hash3"
        )
        writer._flush_buffers_locked()

        # Batch 2: file_id = 1
        writer.write_file_artifact(
            file_id=1,
            agent={"entities": [{"id": "ent1", "name": "func1", "type": "function", "start_line": 1}]},
            storage={"entities": []},
            rels=[],
            content_hash="hash1"
        )
        writer._flush_buffers_locked()

        # Batch 3: file_id = 2
        writer.write_file_artifact(
            file_id=2,
            agent={"entities": [{"id": "ent2", "name": "func2", "type": "function", "start_line": 1}]},
            storage={"entities": []},
            rels=[],
            content_hash="hash2"
        )
        writer.finalize()

        # Update meta.json manifest
        meta_path = artifact_dir / "meta.json"
        with open(meta_path, "w") as f:
            json.dump({
                "generation": 1,
                "active_files": {
                    "agent_views": "agent_views.tmp.ipc"
                }
            }, f)

        # 2. Read back using BathoBundleReader
        reader = BathoBundleReader(artifact_dir)
        
        # Retrieve artifacts by id - should look up slices correctly
        res1 = reader.get_file_artifacts_by_id(1)
        res2 = reader.get_file_artifacts_by_id(2)
        res3 = reader.get_file_artifacts_by_id(3)

        assert len(res1["agent_view"]) == 1
        assert res1["agent_view"][0]["entity_id"] == "ent1"

        assert len(res2["agent_view"]) == 1
        assert res2["agent_view"][0]["entity_id"] == "ent2"

        assert len(res3["agent_view"]) == 1
        assert res3["agent_view"][0]["entity_id"] == "ent3"

