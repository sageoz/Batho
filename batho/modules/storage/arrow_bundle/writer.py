"""Arrow Bundle Writer — consolidated columnar accumulation for file artifacts.

Accumulates rows into in-memory column buffers and flushes them as unified,
uncompressed IPC files (sorted by file_id) into a temp path.
BathoBundleManager performs the atomic generation-pointer commit.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc

from batho.utils.logging import get_logger
from .schemas import (
    AGENT_VIEWS_SCHEMA,
    STORAGE_VIEWS_SCHEMA,
    RELS_VIEWS_SCHEMA,
    FILE_TRACKING_SCHEMA,
    FILE_CHANGELOG_SCHEMA,
    RUN_ARTIFACTS_SCHEMA,
    RUNS_SCHEMA,
)

LOGGER = get_logger(__name__, component="arrow_bundle_writer")

FLUSH_THRESHOLD_ROWS = 50_000


class BathoBundleWriter:
    """Incremental writer for Batho Arrow bundles.

    Accumulates file artifacts into in-memory column buffers.
    On flush: rows are sorted by file_id and written to a temp .ipc file.
    Call finalize() to flush remaining rows; then commit via BathoBundleManager.
    """

    def __init__(self, bundle_dir: Path, run_id: int) -> None:
        self.bundle_dir = bundle_dir.resolve()
        self.bundle_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self._lock = threading.Lock()
        self._row_count = 0

        self._agent_buf: dict[str, list[Any]] = {n: [] for n in AGENT_VIEWS_SCHEMA.names}
        self._storage_buf: dict[str, list[Any]] = {n: [] for n in STORAGE_VIEWS_SCHEMA.names}
        self._rels_buf: dict[str, list[Any]] = {n: [] for n in RELS_VIEWS_SCHEMA.names}

        self._agent_path = bundle_dir / "agent_views.tmp.ipc"
        self._storage_path = bundle_dir / "storage_views.tmp.ipc"
        self._rels_path = bundle_dir / "rels_views.tmp.ipc"

        self._agent_writer: ipc.RecordBatchFileWriter | None = None
        self._storage_writer: ipc.RecordBatchFileWriter | None = None
        self._rels_writer: ipc.RecordBatchFileWriter | None = None

    def _get_or_open_writer(
        self,
        path: Path,
        schema: pa.Schema,
        attr: str,
    ) -> ipc.RecordBatchFileWriter:
        w = getattr(self, attr)
        if w is None:
            w = ipc.new_file(str(path), schema)
            setattr(self, attr, w)
        return w

    def write_file_artifact(
        self,
        file_id: int,
        agent: dict[str, Any],
        storage: dict[str, Any],
        rels: list[dict[str, Any]],
        content_hash: str,
    ) -> None:
        with self._lock:
            for ent in agent.get("entities", []):
                self._agent_buf["file_id"].append(file_id)
                self._agent_buf["entity_id"].append(str(ent.get("id", "")))
                self._agent_buf["name"].append(str(ent.get("name", "")))
                self._agent_buf["entity_type"].append(str(ent.get("type") or ent.get("entity_type", "")))
                self._agent_buf["start_line"].append(int(ent.get("start_line") or ent.get("line") or 0))
                self._agent_buf["end_line"].append(ent.get("end_line"))
                self._agent_buf["signature"].append(ent.get("signature"))
                self._agent_buf["content_hash"].append(content_hash)
                self._agent_buf["is_exported"].append(bool(ent.get("is_exported", False)))
                self._agent_buf["fqn"].append(ent.get("fqn"))

            for ent in storage.get("entities", []):
                glue = ent.get("syntax_glue") or {}
                self._storage_buf["file_id"].append(file_id)
                self._storage_buf["entity_id"].append(str(ent.get("id", "")))
                raw = ent.get("raw_content")
                self._storage_buf["raw_content"].append(raw if isinstance(raw, str) else None)
                rb = ent.get("raw_bytes")
                self._storage_buf["raw_bytes"].append(rb if isinstance(rb, (bytes, bytearray)) else None)
                self._storage_buf["leading_ws"].append(glue.get("leading_whitespace") or ent.get("leading_whitespace"))
                self._storage_buf["trailing_ws"].append(glue.get("trailing_whitespace") or ent.get("trailing_whitespace"))
                self._storage_buf["ast_node_type"].append(ent.get("ast_node_type"))
                self._storage_buf["parent_id"].append(ent.get("parent_id"))
                self._storage_buf["start_byte"].append(ent.get("start_byte"))
                self._storage_buf["end_byte"].append(ent.get("end_byte"))

            for rel in rels:
                self._rels_buf["file_id"].append(file_id)
                self._rels_buf["source_id"].append(str(rel.get("source_id", "")))
                self._rels_buf["target_id"].append(str(rel.get("target_id", "")))
                self._rels_buf["relation_type"].append(str(rel.get("relation_type") or rel.get("type") or rel.get("relationship_type", "")))
                meta = rel.get("metadata")
                import json as _json
                self._rels_buf["metadata_json"].append(_json.dumps(meta) if meta else None)

            self._row_count += len(agent.get("entities", [])) + len(rels)
            if self._row_count >= FLUSH_THRESHOLD_ROWS:
                self._flush_buffers_locked()

    def _flush_buffers_locked(self) -> None:
        if self._row_count == 0:
            return

        self._write_sorted_batch(
            self._agent_buf, AGENT_VIEWS_SCHEMA,
            self._agent_path, "_agent_writer",
        )
        self._write_sorted_batch(
            self._storage_buf, STORAGE_VIEWS_SCHEMA,
            self._storage_path, "_storage_writer",
        )
        self._write_sorted_batch(
            self._rels_buf, RELS_VIEWS_SCHEMA,
            self._rels_path, "_rels_writer",
        )

        self._agent_buf = {n: [] for n in AGENT_VIEWS_SCHEMA.names}
        self._storage_buf = {n: [] for n in STORAGE_VIEWS_SCHEMA.names}
        self._rels_buf = {n: [] for n in RELS_VIEWS_SCHEMA.names}
        self._row_count = 0

    def _write_sorted_batch(
        self,
        buf: dict[str, list[Any]],
        schema: pa.Schema,
        path: Path,
        writer_attr: str,
    ) -> None:
        if not buf.get("file_id"):
            return

        file_ids = np.array(buf["file_id"], dtype=np.int64)
        sort_order = np.argsort(file_ids, kind="stable")

        arrays = []
        for field in schema:
            raw = buf[field.name]
            sorted_raw = [raw[i] for i in sort_order]
            arrays.append(pa.array(sorted_raw, type=field.type))

        batch = pa.RecordBatch.from_arrays(arrays, schema=schema)
        w = self._get_or_open_writer(path, schema, writer_attr)
        w.write_batch(batch)

    def finalize(self) -> dict[str, Path]:
        """Flush remaining rows and close IPC writers. Returns temp file paths."""
        with self._lock:
            self._flush_buffers_locked()

        for attr in ("_agent_writer", "_storage_writer", "_rels_writer"):
            w = getattr(self, attr)
            if w is not None:
                try:
                    w.close()
                except Exception:
                    pass
                setattr(self, attr, None)

        streams: dict[str, Path] = {}
        for name, path in [
            ("agent_views", self._agent_path),
            ("storage_views", self._storage_path),
            ("rels_views", self._rels_path),
        ]:
            if path.exists():
                streams[name] = path

        LOGGER.info("arrow_bundle_writer_finalized", run_id=self.run_id)
        return streams


def write_simple_ipc(
    rows: list[dict[str, Any]],
    schema: pa.Schema,
    path: Path,
) -> None:
    """Write a list of row dicts as a single IPC file (for small tables)."""
    if not rows:
        arrays = [pa.array([], type=field.type) for field in schema]
    else:
        arrays = []
        for field in schema:
            col = [row.get(field.name) for row in rows]
            arrays.append(pa.array(col, type=field.type))

    batch = pa.record_batch(arrays, schema=schema)
    with ipc.new_file(str(path), schema) as writer:
        writer.write_batch(batch)


def read_ipc_table(path: "Path | None") -> pa.Table:
    """Read a plain (uncompressed) IPC file into a Table."""
    if path is None or not path.exists() or path.stat().st_size < 8:
        return pa.table({})
    try:
        mmap = pa.memory_map(str(path), "r")
        return ipc.open_file(mmap).read_all()
    except Exception:
        return pa.table({})
