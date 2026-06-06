"""Compaction: flush in-memory row buffers → sorted Arrow IPC File format.

Two-phase design:
  Phase 1 (bulk-insert): rows accumulate in memory buffers.
  Phase 2 (compact):     buffers → RecordBatch → sort → write plain IPC File
                         to final .ipc files (mmap-readable, zero-copy).

IPC File format is chosen for at-rest compacted files because:
  - Supports random access and memory-mapping (zero-copy reads)
  - No decompression overhead on every read
  - OS pages in only touched columns/rows

The _stream/ staging files (written during bulk-insert phase) still use
IPC Stream + zstd since they are append-friendly and transient (deleted
after compact()).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.ipc as ipc
import zstandard as zstd

from .schemas import (
    DANGLING_SCHEMA,
    ENTITIES_SCHEMA,
    ENTITY_DICT_SCHEMA,
    RELATIONSHIPS_SCHEMA,
)


# ---------------------------------------------------------------------------
# Plain IPC File helpers (at-rest compacted files: bsg/current/*.ipc)
# ---------------------------------------------------------------------------

def write_ipc(table: pa.Table, path: Path) -> None:
    """Write a PyArrow Table to a plain Arrow IPC File (mmap-readable)."""
    tmp = path.with_suffix(".ipc.tmp")
    with ipc.new_file(tmp, table.schema) as writer:
        writer.write_table(table)
    tmp.replace(path)


def read_ipc(path: Path) -> pa.Table:
    """Read a plain Arrow IPC File via memory-map (zero-copy)."""
    with pa.memory_map(str(path), "r") as mmap:
        with ipc.open_file(mmap) as reader:
            return reader.read_all()


def read_ipc_columns(path: Path, columns: list[str]) -> pa.Table:
    """Read specific columns from a plain Arrow IPC File via memory-map."""
    with pa.memory_map(str(path), "r") as mmap:
        with ipc.open_file(mmap) as reader:
            return reader.read_all().select(columns)


# ---------------------------------------------------------------------------
# IPC Stream + zstd helpers (transient _stream/ staging files only)
# ---------------------------------------------------------------------------

def _write_stream_zst(table: pa.Table, path: Path) -> None:
    """Write a PyArrow Table to a zstd-compressed IPC Stream (for _stream/ staging)."""
    buf = io.BytesIO()
    with ipc.new_stream(buf, table.schema) as writer:
        writer.write_table(table)
    cctx = zstd.ZstdCompressor(level=3)
    compressed = cctx.compress(buf.getvalue())
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(compressed)
    tmp.replace(path)


def _read_stream_zst(path: Path) -> pa.Table:
    """Read a zstd-compressed IPC Stream file (for _stream/ staging)."""
    dctx = zstd.ZstdDecompressor()
    raw = dctx.decompress(path.read_bytes())
    return ipc.open_stream(io.BytesIO(raw)).read_all()


# ---------------------------------------------------------------------------
# Compact functions — produce plain .ipc files
# ---------------------------------------------------------------------------

def compact_entity_dict(rows: list[tuple[int, str]], path: Path) -> None:
    """Compact entity_dict rows → entity_dict.ipc (plain IPC File)."""
    if not rows:
        tbl = pa.table({"id": pa.array([], type=pa.int64()), "val": pa.array([], type=pa.large_utf8())})
    else:
        ids, vals = zip(*rows)
        tbl = pa.table(
            {
                "id": pa.array(ids, type=pa.int64()),
                "val": pa.array(vals, type=pa.large_utf8()),
            }
        )
    write_ipc(tbl, path)


def compact_entities(rows: list[tuple[Any, ...]], path: Path) -> None:
    """Compact entities rows → entities.ipc, sorted by (entity_name, entity_type)."""
    if not rows:
        arrays = {
            "entity_key": pa.array([], type=pa.int64()),
            "run_id": pa.array([], type=pa.int32()),
            "entity_name": pa.array([], type=pa.dictionary(pa.int32(), pa.utf8())),
            "entity_type": pa.array([], type=pa.dictionary(pa.int16(), pa.utf8())),
            "fqn": pa.array([], type=pa.large_utf8()),
            "file_path": pa.array([], type=pa.dictionary(pa.int32(), pa.utf8())),
            "line_number": pa.array([], type=pa.int32()),
            "signature": pa.array([], type=pa.large_utf8()),
            "is_exported": pa.array([], type=pa.bool_()),
        }
        tbl = pa.table(arrays, schema=ENTITIES_SCHEMA)
    else:
        (
            entity_keys, run_ids, entity_names, entity_types,
            fqns, file_paths, line_numbers, signatures, is_exporteds,
        ) = zip(*rows)
        tbl = pa.table(
            {
                "entity_key": pa.array(entity_keys, type=pa.int64()),
                "run_id": pa.array(run_ids, type=pa.int32()),
                "entity_name": pa.array(entity_names, type=pa.dictionary(pa.int32(), pa.utf8())),
                "entity_type": pa.array(entity_types, type=pa.dictionary(pa.int16(), pa.utf8())),
                "fqn": pa.array(fqns, type=pa.large_utf8()),
                "file_path": pa.array(file_paths, type=pa.dictionary(pa.int32(), pa.utf8())),
                "line_number": pa.array(line_numbers, type=pa.int32()),
                "signature": pa.array(signatures, type=pa.large_utf8()),
                "is_exported": pa.array(is_exporteds, type=pa.bool_()),
            },
            schema=ENTITIES_SCHEMA,
        )
        import pyarrow.compute as pc
        sort_tbl = pa.table({
            "entity_name": tbl.column("entity_name").cast(pa.utf8()),
            "entity_type": tbl.column("entity_type").cast(pa.utf8()),
        })
        sort_indices = pc.sort_indices(
            sort_tbl, sort_keys=[("entity_name", "ascending"), ("entity_type", "ascending")]
        )
        tbl = tbl.take(sort_indices)
    write_ipc(tbl, path)


def compact_relationships(rows: list[tuple[Any, ...]], path: Path) -> None:
    """Compact relationships rows → relationships.ipc (plain IPC File)."""
    if not rows:
        arrays = {
            "source_key": pa.array([], type=pa.int64()),
            "target_key": pa.array([], type=pa.int64()),
            "relation_type": pa.array([], type=pa.dictionary(pa.int16(), pa.utf8())),
            "run_id": pa.array([], type=pa.int32()),
            "metadata_json": pa.array([], type=pa.utf8()),
        }
        tbl = pa.table(arrays, schema=RELATIONSHIPS_SCHEMA)
    else:
        source_keys, target_keys, relation_types, run_ids, metadata_jsons = zip(*rows)
        tbl = pa.table(
            {
                "source_key": pa.array(source_keys, type=pa.int64()),
                "target_key": pa.array(target_keys, type=pa.int64()),
                "relation_type": pa.array(relation_types, type=pa.dictionary(pa.int16(), pa.utf8())),
                "run_id": pa.array(run_ids, type=pa.int32()),
                "metadata_json": pa.array(metadata_jsons, type=pa.utf8()),
            },
            schema=RELATIONSHIPS_SCHEMA,
        )
    write_ipc(tbl, path)


def compact_dangling(rows: list[tuple[Any, ...]], path: Path) -> None:
    """Compact dangling_references rows → dangling.ipc (plain IPC File)."""
    if not rows:
        arrays = {
            "source_key": pa.array([], type=pa.int64()),
            "unresolved_target_name": pa.array([], type=pa.dictionary(pa.int32(), pa.utf8())),
            "relation_type": pa.array([], type=pa.dictionary(pa.int16(), pa.utf8())),
            "run_id": pa.array([], type=pa.int32()),
        }
        tbl = pa.table(arrays, schema=DANGLING_SCHEMA)
    else:
        source_keys, target_names, relation_types, run_ids = zip(*rows)
        tbl = pa.table(
            {
                "source_key": pa.array(source_keys, type=pa.int64()),
                "unresolved_target_name": pa.array(target_names, type=pa.dictionary(pa.int32(), pa.utf8())),
                "relation_type": pa.array(relation_types, type=pa.dictionary(pa.int16(), pa.utf8())),
                "run_id": pa.array(run_ids, type=pa.int32()),
            },
            schema=DANGLING_SCHEMA,
        )
    write_ipc(tbl, path)


def write_empty_dangling(path: Path) -> None:
    """Write an empty dangling table (after resolution is complete)."""
    compact_dangling([], path)
