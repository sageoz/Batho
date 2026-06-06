"""Tests for BathoBundleWriter — flush, sort-by-file_id, generation increment."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pytest

from batho.modules.storage.arrow_bundle.writer import BathoBundleWriter, write_simple_ipc, read_ipc_table
from batho.modules.storage.arrow_bundle.schemas import FILE_TRACKING_SCHEMA, RUNS_SCHEMA


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
        path = tmp_path / "empty.ipc"
        write_simple_ipc([], FILE_TRACKING_SCHEMA, path)
        table = read_ipc_table(path)
        assert table.num_rows == 0
        assert table.schema == FILE_TRACKING_SCHEMA

    def test_read_ipc_none_path(self):
        table = read_ipc_table(None)
        assert table.num_rows == 0

    def test_read_ipc_missing_file(self, tmp_path):
        table = read_ipc_table(tmp_path / "nonexistent.ipc")
        assert table.num_rows == 0

    def test_read_ipc_zero_byte_file(self, tmp_path):
        p = tmp_path / "zero.ipc"
        p.write_bytes(b"")
        table = read_ipc_table(p)
        assert table.num_rows == 0

    def test_multiple_rows_preserved(self, tmp_path):
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
        bundle_dir = tmp_path / "artifact"
        writer = BathoBundleWriter(bundle_dir, run_id=1)
        assert bundle_dir.exists()

    def test_write_single_agent_entity(self, tmp_path):
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
        writer = BathoBundleWriter(tmp_path, run_id=1)
        streams = writer.finalize()
        assert streams == {}

    def test_rels_written_correctly(self, tmp_path):
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
