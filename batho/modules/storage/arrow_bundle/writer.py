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
import pyarrow.compute as pc
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
        # Stub-resolution rewrites applied to the run's rels tmp file at
        # finalize(): stub_id -> (resolved_target_id, confidence, metadata_merge).
        self._stub_rewrites: dict[str, tuple[str, float, dict[str, Any]]] = {}
        # Stub-entity metadata merges applied to the run's agent_views tmp
        # file at finalize(): stub_id -> {stub_resolution_state, ...} (T5).
        self._stub_entity_meta: dict[str, dict[str, Any]] = {}

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
            import json as _json
            for ent in agent.get("entities", []):
                ent_id = str(ent.get("id", ""))
                self._agent_buf["file_id"].append(file_id)
                self._agent_buf["entity_id"].append(ent_id)
                self._agent_buf["name"].append(str(ent.get("name", "")))
                self._agent_buf["entity_type"].append(str(ent.get("type") or ent.get("entity_type", "")))
                self._agent_buf["start_line"].append(int(ent.get("start_line") or ent.get("line") or 0))
                self._agent_buf["end_line"].append(ent.get("end_line"))
                self._agent_buf["signature"].append(ent.get("signature"))
                self._agent_buf["content_hash"].append(content_hash)
                self._agent_buf["is_exported"].append(bool(ent.get("is_exported", False)))
                self._agent_buf["fqn"].append(ent.get("fqn"))
                # Stub rows keep their extraction-time metadata (pending
                # state, caller_scope, target_name) for later merge; all
                # other entities stay null to bound artifact size.
                ent_meta = ent.get("metadata") if ent_id.startswith("unresolved:") else None
                try:
                    self._agent_buf["metadata_json"].append(
                        _json.dumps(ent_meta, default=str) if ent_meta else None
                    )
                except (TypeError, ValueError):
                    self._agent_buf["metadata_json"].append(None)

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
                self._rels_buf["roles"].append(int(rel.get("roles") or 0))
                _conf = rel.get("confidence")
                self._rels_buf["confidence"].append(float(_conf) if _conf is not None else 1.0)

            self._row_count += len(agent.get("entities", [])) + len(rels)
            if self._row_count >= FLUSH_THRESHOLD_ROWS:
                self._flush_buffers_locked()

    def write_rels_only(
        self,
        file_id: int,
        rels: list[dict[str, Any]],
    ) -> None:
        """Write relationships for a file without agent/storage entities.

        Used during post-graph rels rewrite to persist synthesized
        relationships (e.g., CONTAINS from Rust impl blocks / Go receivers).
        """
        with self._lock:
            for rel in rels:
                self._rels_buf["file_id"].append(file_id)
                self._rels_buf["source_id"].append(str(rel.get("source_id", "")))
                self._rels_buf["target_id"].append(str(rel.get("target_id", "")))
                self._rels_buf["relation_type"].append(
                    str(rel.get("relation_type") or rel.get("type") or rel.get("relationship_type", ""))
                )
                meta = rel.get("metadata")
                import json as _json
                self._rels_buf["metadata_json"].append(_json.dumps(meta) if meta else None)
                self._rels_buf["roles"].append(int(rel.get("roles") or 0))
                _conf = rel.get("confidence")
                self._rels_buf["confidence"].append(float(_conf) if _conf is not None else 1.0)

            self._row_count += len(rels)
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
        sort_indices = pa.array(np.argsort(file_ids, kind="stable"), type=pa.int64())

        arrays = []
        for field in schema:
            col = pa.array(buf[field.name], type=field.type)
            arrays.append(pc.take(col, sort_indices))

        batch = pa.RecordBatch.from_arrays(arrays, schema=schema)
        w = self._get_or_open_writer(path, schema, writer_attr)
        w.write_batch(batch)

    def set_stub_rewrites(
        self,
        mapping: dict[str, tuple[str, float, dict[str, Any]]],
        entity_meta: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Attach stub-resolution rewrites applied at finalize().

        The stored worker rels carry pre-resolution "unresolved:" targets.
        Each entry maps a stub entity id to (resolved_target_id, confidence,
        metadata_merge); rows whose target_id matches a stub id are rewritten
        in place. Rows are never added or dropped (coverage invariant).

        ``entity_meta`` (stub_id -> metadata merge dict) additionally updates
        the stub *entity* rows in agent_views — persisting
        stub_resolution_state / resolved_target_id / resolution_strategy /
        resolution_confidence (T5 acceptance).
        """
        self._stub_rewrites = dict(mapping or {})
        self._stub_entity_meta = dict(entity_meta or {})

    def _apply_stub_rewrites(self) -> None:
        """Rewrite resolved stub targets in the run's rels tmp file."""
        if not self._stub_rewrites or not self._rels_path.exists():
            return
        import json as _json

        stub_ids = pa.array(list(self._stub_rewrites.keys()))
        with pa.memory_map(str(self._rels_path), "r") as src:
            reader = ipc.open_file(src)
            # Pass 1 — mask-scan only: a zero-hit run (common) creates no tmp
            # file and copies nothing.
            hit_batches = set()
            for i in range(reader.num_record_batches):
                mask = pc.is_in(
                    reader.get_batch(i).column("target_id"), value_set=stub_ids
                )
                if pc.sum(mask).as_py():
                    hit_batches.add(i)
            if not hit_batches:
                return

            # Pass 2 — stream batches: no-hit batches pass through unmodified,
            # only hit batches materialize Python objects. RSS at finalize
            # stays bounded by one batch instead of the whole rels table.
            tmp_out = self._rels_path.with_name(self._rels_path.name + ".rewrite")
            rewritten = 0
            try:
                with ipc.new_file(str(tmp_out), reader.schema) as w:
                    for i in range(reader.num_record_batches):
                        batch = reader.get_batch(i)
                        if i not in hit_batches:
                            w.write_batch(batch)
                            continue
                        cols = batch.to_pydict()
                        tids = cols["target_id"]
                        for j, tid in enumerate(tids):
                            hit = self._stub_rewrites.get(tid)
                            if hit is None:
                                continue
                            resolved_id, confidence, meta = hit
                            tids[j] = resolved_id
                            cols["confidence"][j] = confidence
                            if meta:
                                existing = (
                                    _json.loads(cols["metadata_json"][j])
                                    if cols["metadata_json"][j]
                                    else {}
                                )
                                existing.update(meta)
                                cols["metadata_json"][j] = _json.dumps(existing)
                            rewritten += 1
                        w.write_batch(
                            pa.RecordBatch.from_pydict(cols, schema=batch.schema)
                        )
            except Exception:
                tmp_out.unlink(missing_ok=True)
                raise
        tmp_out.replace(self._rels_path)
        LOGGER.info("stub_targets_rewritten", rewritten=rewritten, run_id=self.run_id)

    def _apply_stub_entity_meta(self) -> None:
        """Merge stub-resolution state into the run's agent_views tmp file.

        Updates stub *entity* rows (entity_id in ``_stub_entity_meta``):
        persisted ``metadata_json`` gains stub_resolution_state /
        resolved_target_id / resolution_strategy / resolution_confidence so
        artifact consumers can distinguish resolved / pruned / unresolved
        stubs — the T5 entity-row half of the persistence contract.
        """
        if not self._stub_entity_meta or not self._agent_path.exists():
            return
        import json as _json

        stub_ids = pa.array(list(self._stub_entity_meta.keys()))
        # Same two-pass contract as _apply_stub_rewrites: mask-scan first so a
        # zero-hit run creates no tmp file; then stream, materializing only
        # batches containing a stub entity_id.
        with pa.memory_map(str(self._agent_path), "r") as src:
            reader = ipc.open_file(src)
            if "metadata_json" not in reader.schema.names:
                return
            hit_batches = set()
            for i in range(reader.num_record_batches):
                mask = pc.is_in(
                    reader.get_batch(i).column("entity_id"), value_set=stub_ids
                )
                if pc.sum(mask).as_py():
                    hit_batches.add(i)
            if not hit_batches:
                return

            tmp_out = self._agent_path.with_name(self._agent_path.name + ".rewrite")
            rewritten = 0
            try:
                with ipc.new_file(str(tmp_out), reader.schema) as w:
                    for i in range(reader.num_record_batches):
                        batch = reader.get_batch(i)
                        if i not in hit_batches:
                            w.write_batch(batch)
                            continue
                        cols = batch.to_pydict()
                        eids = cols["entity_id"]
                        metas = cols["metadata_json"]
                        for j, eid in enumerate(eids):
                            hit = self._stub_entity_meta.get(eid)
                            if hit is None:
                                continue
                            existing = _json.loads(metas[j]) if metas[j] else {}
                            existing.update(hit)
                            metas[j] = _json.dumps(existing)
                            rewritten += 1
                        w.write_batch(
                            pa.RecordBatch.from_pydict(cols, schema=batch.schema)
                        )
            except Exception:
                tmp_out.unlink(missing_ok=True)
                raise
        tmp_out.replace(self._agent_path)
        LOGGER.info("stub_entities_rewritten", rewritten=rewritten, run_id=self.run_id)

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

        # Persist stub-resolution rewrites into the run's rels table before
        # the streams are committed (must run after the IPC writer is closed).
        if self._stub_rewrites:
            try:
                self._apply_stub_rewrites()
            except Exception as exc:
                LOGGER.warning("stub_rewrite_failed", error=str(exc), run_id=self.run_id)
        # Same for stub *entity* rows in agent_views (resolution state).
        if self._stub_entity_meta:
            try:
                self._apply_stub_entity_meta()
            except Exception as exc:
                LOGGER.warning("stub_entity_rewrite_failed", error=str(exc), run_id=self.run_id)

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
        with pa.memory_map(str(path), "r") as mmap:
            with ipc.open_file(mmap) as reader:
                return reader.read_all()
    except Exception:
        return pa.table({})
