"""Arrow-backed columnar graph storage (``ArrowGraph``).

A drop-in alternative to :class:`InMemoryGraph` that bounds peak RSS during
full builds by streaming extracted rows to Arrow IPC files and, after
post-processing, compacting them into memory-mapped IPC files with CSR/CSC
adjacency indexes.

Lifecycle (three phases):

1. **Stream (extraction/materialization).** ``add_entity`` / ``add_relationship``
   (and batch variants) append row dicts to small in-memory buffers that flush
   to ``entities.stream.arrow`` / ``rels.stream.arrow`` once row- or
   byte-thresholds are crossed. Only entity/relationship *id sets* are kept
   resident for dedup and ``__contains__``. The graph is write-only in this
   phase.
2. **Dicts (post-processing).** ``_load_stream_to_dicts()`` reads the streams
   back (last-wins dedup on entity id, mirroring ``InMemoryGraph`` overwrite
   semantics) into plain dicts plus secondary indexes. All read and mutation
   methods operate on these dicts. Any read/mutation called before an explicit
   load triggers it implicitly.
3. **Compact (consumption).** ``compact()`` writes unified IPC files
   (uncompressed, so they can be memory-mapped), opens them via
   :func:`pyarrow.memory_map`, builds CSR/CSC adjacency + secondary row
   indexes, and frees the Phase-2 dicts. The graph is read-only afterwards;
   mutations raise ``RuntimeError``.

``close()`` releases the mmap handles and removes the staging directory.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from collections import OrderedDict
from typing import Any, Iterator

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from batho.core.schemas import (
    Entity,
    EntityType,
    Relationship,
    RelationshipType,
    SymbolRole,
)
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="arrow_graph")


# ---------------------------------------------------------------------------
# Arrow schemas
# ---------------------------------------------------------------------------

ENTITY_ARROW_SCHEMA = pa.schema(
    [
        pa.field("entity_id", pa.large_utf8(), nullable=False),
        pa.field("name", pa.utf8(), nullable=False),
        # Stores EntityType.name (dictionary-encoded).
        pa.field("entity_type", pa.dictionary(pa.int8(), pa.utf8()), nullable=False),
        pa.field("file", pa.dictionary(pa.int32(), pa.large_utf8()), nullable=False),
        pa.field("start_line", pa.int32(), nullable=False),
        pa.field("end_line", pa.int32(), nullable=True),
        pa.field("start_byte", pa.int64(), nullable=True),
        pa.field("end_byte", pa.int64(), nullable=True),
        pa.field("parent_id", pa.large_utf8(), nullable=True),
        # signature, content_hash, children_order, ast_node_type, enclosing_*,
        # whitespace, is_documentation, metadata, plus any extra="allow" fields.
        pa.field("extras_json", pa.large_utf8(), nullable=True),
    ]
)

REL_ARROW_SCHEMA = pa.schema(
    [
        pa.field("rel_id", pa.large_utf8(), nullable=False),
        pa.field("source_id", pa.large_utf8(), nullable=False),
        pa.field("target_id", pa.large_utf8(), nullable=False),
        # Stores RelationshipType.name (dictionary-encoded).
        pa.field("rel_type", pa.dictionary(pa.int8(), pa.utf8()), nullable=False),
        # roles, confidence, reference/definition byte offsets, metadata.
        pa.field("extras_json", pa.large_utf8(), nullable=True),
    ]
)

# Filenames ArrowGraph creates in its staging directory (used for stale
# cleanup and safe close()).
_STAGING_FILENAMES = (
    "entities.stream.arrow",
    "rels.stream.arrow",
    "entities.arrow",
    "rels.arrow",
)

# Core (explicitly columned) entity fields; everything else lands in extras_json.
_ENTITY_CORE = {
    "entity_id",
    "name",
    "entity_type",
    "file",
    "start_line",
    "end_line",
    "start_byte",
    "end_byte",
    "parent_id",
    "extras_json",
}

# model_dump() keys that must not be duplicated into extras_json:
# - "id"/"id_override": identity is carried by the entity_id column; passing
#   id_override twice to model_construct would raise TypeError.
# - "type": carried by the entity_type column (enum .name).
# - "raw_content"/"raw_bytes": the graph never carries raw content (hollow
#   topology), so no Arrow columns exist for them.
_ENTITY_EXTRAS_EXCLUDE = _ENTITY_CORE | {"id", "id_override", "type", "raw_content", "raw_bytes"}

_REL_CORE = {"rel_id", "source_id", "target_id", "rel_type", "extras_json"}
_REL_EXTRAS_EXCLUDE = _REL_CORE | {"id", "type"}


# ---------------------------------------------------------------------------
# Row conversion helpers
# ---------------------------------------------------------------------------


def entity_to_row(ent: Entity) -> dict[str, Any]:
    """Convert an :class:`Entity` to an Arrow row dict (schema-aligned)."""
    dumped = ent.model_dump()  # includes metadata, signature, computed "id", etc.
    extras = {k: v for k, v in dumped.items() if k not in _ENTITY_EXTRAS_EXCLUDE}
    return {
        "entity_id": ent.id,
        "name": ent.name,
        "entity_type": ent.type.name,
        "file": ent.file,
        "start_line": ent.start_line,
        "end_line": ent.end_line,
        "start_byte": ent.start_byte,
        "end_byte": ent.end_byte,
        "parent_id": ent.parent_id,
        "extras_json": json.dumps(extras, default=str),
    }


def row_to_entity(row: dict[str, Any]) -> Entity:
    """Reconstruct an :class:`Entity` from an Arrow row dict (lossless)."""
    extras_json = row.get("extras_json")
    extras = json.loads(extras_json) if extras_json else {}
    return Entity.model_construct(
        id_override=row["entity_id"],
        name=row["name"],
        type=EntityType[row["entity_type"]],
        file=row["file"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        start_byte=row["start_byte"] or 0,
        end_byte=row["end_byte"] or 0,
        parent_id=row["parent_id"],
        raw_content=None,
        raw_bytes=None,
        **extras,
    )


def rel_to_row(rel: Relationship) -> dict[str, Any]:
    """Convert a :class:`Relationship` to an Arrow row dict (schema-aligned)."""
    dumped = rel.model_dump()
    extras = {k: v for k, v in dumped.items() if k not in _REL_EXTRAS_EXCLUDE}
    return {
        "rel_id": rel.id,
        "source_id": rel.source_id,
        "target_id": rel.target_id,
        "rel_type": rel.type.name,
        "extras_json": json.dumps(extras, default=str),
    }


def row_to_rel(row: dict[str, Any]) -> Relationship:
    """Reconstruct a :class:`Relationship` from an Arrow row dict (lossless)."""
    extras_json = row.get("extras_json")
    extras = json.loads(extras_json) if extras_json else {}
    roles = extras.get("roles")
    if roles is not None and not isinstance(roles, SymbolRole):
        extras["roles"] = SymbolRole(roles)
    return Relationship.model_construct(
        source_id=row["source_id"],
        target_id=row["target_id"],
        type=RelationshipType[row["rel_type"]],
        **extras,
    )


# ---------------------------------------------------------------------------
# RecordBatch / Table construction (explicit arrays; from_pylist cannot build
# dictionary<large_string> columns)
# ---------------------------------------------------------------------------


def _dict_array(values: list[str], target_type: pa.DataType) -> pa.Array:
    value_type = target_type.value_type
    encoded = pa.array(values, value_type).dictionary_encode()
    return pc.cast(encoded, target_type)


def _entity_arrays(rows: list[dict[str, Any]]) -> list[pa.Array]:
    return [
        pa.array([r["entity_id"] for r in rows], pa.large_utf8()),
        pa.array([r["name"] for r in rows], pa.utf8()),
        _dict_array(
            [r["entity_type"] for r in rows],
            ENTITY_ARROW_SCHEMA.field("entity_type").type,
        ),
        _dict_array(
            [r["file"] for r in rows], ENTITY_ARROW_SCHEMA.field("file").type
        ),
        pa.array([r["start_line"] for r in rows], pa.int32()),
        pa.array([r["end_line"] for r in rows], pa.int32()),
        pa.array([r["start_byte"] for r in rows], pa.int64()),
        pa.array([r["end_byte"] for r in rows], pa.int64()),
        pa.array([r["parent_id"] for r in rows], pa.large_utf8()),
        pa.array([r["extras_json"] for r in rows], pa.large_utf8()),
    ]


def _rel_arrays(rows: list[dict[str, Any]]) -> list[pa.Array]:
    return [
        pa.array([r["rel_id"] for r in rows], pa.large_utf8()),
        pa.array([r["source_id"] for r in rows], pa.large_utf8()),
        pa.array([r["target_id"] for r in rows], pa.large_utf8()),
        _dict_array([r["rel_type"] for r in rows], REL_ARROW_SCHEMA.field("rel_type").type),
        pa.array([r["extras_json"] for r in rows], pa.large_utf8()),
    ]


def _entity_batch(rows: list[dict[str, Any]]) -> pa.RecordBatch:
    return pa.RecordBatch.from_arrays(_entity_arrays(rows), schema=ENTITY_ARROW_SCHEMA)


def _rel_batch(rows: list[dict[str, Any]]) -> pa.RecordBatch:
    return pa.RecordBatch.from_arrays(_rel_arrays(rows), schema=REL_ARROW_SCHEMA)


def _estimate_row_bytes(row: dict[str, Any]) -> int:
    """Rough byte-size estimate of a row dict for flush-threshold accounting."""
    return sum(len(v) for v in row.values() if isinstance(v, str)) + 64


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class ArrowEntityView:
    """Dict-like view over an :class:`ArrowGraph`'s entities.

    Reconstructs ``Entity`` objects on read and decomposes them on write.
    Mirrors the ``dict[str, Entity]`` surface used by consumers:
    ``__getitem__`` / ``__setitem__`` / ``__contains__`` / ``__len__`` /
    ``keys`` / ``values`` / ``items`` / ``get`` / ``pop`` / iteration.
    """

    __slots__ = ("_graph",)

    def __init__(self, graph: "ArrowGraph") -> None:
        self._graph = graph

    def __getitem__(self, entity_id: str) -> Entity:
        entity = self._graph.get_entity(entity_id)
        if entity is None:
            raise KeyError(entity_id)
        return entity

    def __setitem__(self, entity_id: str, entity: Entity) -> None:
        self._graph.update_entity(entity_id, entity)

    def __contains__(self, entity_id: object) -> bool:
        return isinstance(entity_id, str) and entity_id in self._graph

    def __len__(self) -> int:
        return len(self._graph)

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def keys(self) -> list[str]:
        return self._graph.get_all_nodes()

    def values(self) -> Iterator[Entity]:
        yield from self._graph._iter_entities()

    def items(self) -> Iterator[tuple[str, Entity]]:
        graph = self._graph
        for eid, entity in zip(graph.get_all_nodes(), graph._iter_entities()):
            yield eid, entity

    def get(self, entity_id: str, default: Any = None) -> Any:
        entity = self._graph.get_entity(entity_id)
        return entity if entity is not None else default

    def pop(self, entity_id: str, *default: Any) -> Any:
        entity = self._graph.get_entity(entity_id)
        if entity is None:
            if default:
                return default[0]
            raise KeyError(entity_id)
        self._graph.remove_node(entity_id)
        return entity


class ArrowRelView:
    """List-like view over an :class:`ArrowGraph`'s relationships.

    Mirrors the ``list[Relationship]`` surface used by consumers:
    iteration, ``len()``, integer indexing, truthiness.
    """

    __slots__ = ("_graph",)

    def __init__(self, graph: "ArrowGraph") -> None:
        self._graph = graph

    def __iter__(self) -> Iterator[Relationship]:
        return self._graph._iter_relationships()

    def __len__(self) -> int:
        return self._graph._rel_count()

    def __getitem__(self, index: int) -> Relationship:
        graph = self._graph
        rels_len = len(self)
        if index < 0:
            index += rels_len
        if index < 0 or index >= rels_len:
            raise IndexError(index)
        # O(1): reconstruct the relationship at the given row index directly.
        graph._ensure_phase2()
        if graph._compacted:
            return graph._rel_at(index)
        return row_to_rel(graph._rel_dicts[index])


# ---------------------------------------------------------------------------
# ArrowGraph
# ---------------------------------------------------------------------------


class ArrowGraph:
    """Columnar, memory-mapped graph backend — drop-in for ``InMemoryGraph``.

    See module docstring for the three-phase lifecycle. Not thread-safe;
    ``build_graph`` post-processing runs on the main thread.
    """

    def __init__(
        self,
        staging_dir: str | Path,
        flush_rows: int = 5000,
        flush_bytes_mb: float = 1.0,
        recompact_delta_ratio: float = 0.10,
    ) -> None:
        self._staging_dir = Path(staging_dir)
        # Whether the staging dir already existed (controls safe cleanup in
        # close(): pre-existing dirs only have known artifacts removed).
        self._staging_preexisted = self._staging_dir.exists()
        if self._staging_preexisted:
            # Remove stale artifacts from a killed previous run (known files
            # only — foreign content is never touched).
            for name in _STAGING_FILENAMES:
                try:
                    (self._staging_dir / name).unlink(missing_ok=True)
                except OSError:
                    pass
        self._staging_dir.mkdir(parents=True, exist_ok=True)
        self._flush_rows = max(1, int(flush_rows))
        self._flush_bytes = max(1, int(flush_bytes_mb * 1024 * 1024))
        # Reserved for future delta-overlay re-compaction; stored but unused.
        self._recompact_delta_ratio = float(recompact_delta_ratio)

        # Phase 1: stream buffers + id sets (only persistent resident state)
        self._entity_buffer: list[dict[str, Any]] = []
        self._rel_buffer: list[dict[str, Any]] = []
        self._entity_buffer_bytes = 0
        self._rel_buffer_bytes = 0

        self._rel_ids: set[str] = set()
        self._entity_stream: Any = None  # pa.ipc stream writer
        self._rel_stream: Any = None
        self._entity_stream_path = self._staging_dir / "entities.stream.arrow"
        self._rel_stream_path = self._staging_dir / "rels.stream.arrow"

        # Phase 3 column caches (populated at compact) + entity read cache
        self._entity_columns: dict[str, Any] = {}
        self._rel_columns: dict[str, Any] = {}
        self._entity_cache: OrderedDict[str, Entity] = OrderedDict()

        # Phase 2: dicts + secondary indexes (authoritative once loaded)
        self._phase2_loaded = False
        self._entity_dicts: dict[str, dict[str, Any]] = {}
        self._rel_dicts: list[dict[str, Any]] = []
        self._by_file: dict[str, set[str]] = {}
        self._by_type: dict[EntityType, set[str]] = {}
        self._rels_by_endpoint: dict[str, list[int]] = {}
        self._rel_id_to_idx: dict[str, int] = {}

        # Phase 3: compacted mmap state
        self._compacted = False
        self._entity_mmap: Any = None
        self._rel_mmap: Any = None
        self._entity_table: pa.Table | None = None
        self._rel_table: pa.Table | None = None
        self._entity_row_map: dict[str, int] = {}
        self._row_entity_ids: list[str] = []
        self._csr_offsets: np.ndarray | None = None
        self._csr_indices: np.ndarray | None = None
        self._csc_offsets: np.ndarray | None = None
        self._csc_indices: np.ndarray | None = None
        # Endpoint id (not an entity row) -> rel rows, for rels whose endpoint
        # is not an entity in the graph (external: refs, legacy file paths).
        self._external_out: dict[str, list[int]] = {}
        self._external_in: dict[str, list[int]] = {}
        self._by_file_rows: dict[str, list[int]] = {}
        self._by_type_rows: dict[str, list[int]] = {}
        self._rel_count_compacted = 0

        self._closed = False
        self._entity_view = ArrowEntityView(self)
        self._rel_view = ArrowRelView(self)

    # ------------------------------------------------------------------
    # Writes (Phase 1: stream buffers; Phase 2: dicts)
    # ------------------------------------------------------------------

    def add_entity(self, entity: Entity) -> None:
        if self._compacted:
            raise RuntimeError(
                "ArrowGraph is compacted (read-only); additions are only "
                "allowed before compact()"
            )

        if self._phase2_active:
            self._put_entity_dict(entity.id, entity_to_row(entity))
            return
        self._entity_buffer.append(entity_to_row(entity))
        self._entity_buffer_bytes += _estimate_row_bytes(self._entity_buffer[-1])
        if (
            len(self._entity_buffer) >= self._flush_rows
            or self._entity_buffer_bytes >= self._flush_bytes
        ):
            self._flush_entity_buffer()

    def add_entities_batch(self, entities: list[Entity]) -> None:
        for entity in entities:
            self.add_entity(entity)

    def add_relationship(self, relationship: Relationship) -> None:
        if self._compacted:
            raise RuntimeError(
                "ArrowGraph is compacted (read-only); additions are only "
                "allowed before compact()"
            )
        if relationship.id in self._rel_ids:
            return
        self._rel_ids.add(relationship.id)
        if self._phase2_active:
            self._rel_dicts.append(rel_to_row(relationship))
            idx = len(self._rel_dicts) - 1
            self._rels_by_endpoint.setdefault(relationship.source_id, []).append(idx)
            self._rels_by_endpoint.setdefault(relationship.target_id, []).append(idx)
            self._rel_id_to_idx[relationship.id] = idx
            return
        self._rel_buffer.append(rel_to_row(relationship))
        self._rel_buffer_bytes += _estimate_row_bytes(self._rel_buffer[-1])
        if (
            len(self._rel_buffer) >= self._flush_rows
            or self._rel_buffer_bytes >= self._flush_bytes
        ):
            self._flush_rel_buffer()

    def add_relationships_batch(self, relationships: list[Relationship]) -> None:
        for relationship in relationships:
            self.add_relationship(relationship)

    # ------------------------------------------------------------------
    # Stream flushing
    # ------------------------------------------------------------------

    def _flush_entity_buffer(self) -> None:
        if not self._entity_buffer:
            return
        if self._entity_stream is None:
            self._entity_stream = pa.ipc.new_stream(
                str(self._entity_stream_path), ENTITY_ARROW_SCHEMA
            )
        self._entity_stream.write_batch(_entity_batch(self._entity_buffer))
        self._entity_buffer = []
        self._entity_buffer_bytes = 0

    def _flush_rel_buffer(self) -> None:
        if not self._rel_buffer:
            return
        if self._rel_stream is None:
            self._rel_stream = pa.ipc.new_stream(
                str(self._rel_stream_path), REL_ARROW_SCHEMA
            )
        self._rel_stream.write_batch(_rel_batch(self._rel_buffer))
        self._rel_buffer = []
        self._rel_buffer_bytes = 0

    def _close_streams(self) -> None:
        if self._entity_stream is not None:
            self._entity_stream.close()
            self._entity_stream = None
        if self._rel_stream is not None:
            self._rel_stream.close()
            self._rel_stream = None

    # ------------------------------------------------------------------
    # Phase transitions
    # ------------------------------------------------------------------

    @property
    def _phase2_active(self) -> bool:
        return self._phase2_loaded and not self._compacted

    def _load_stream_to_dicts(self) -> None:
        """Read the IPC streams back into Phase-2 dicts (idempotent).

        Flushes pending buffers first, then loads entities last-wins (mirroring
        ``InMemoryGraph`` overwrite semantics) and relationships in stream
        order, builds secondary indexes, and deletes the stream files.
        """
        if self._phase2_loaded or self._compacted:
            return
        self._flush_entity_buffer()
        self._flush_rel_buffer()
        self._close_streams()

        entity_dicts: dict[str, dict[str, Any]] = {}
        if self._entity_stream_path.exists():
            with pa.ipc.open_stream(str(self._entity_stream_path)) as reader:
                for batch in reader:
                    for row in batch.to_pylist():
                        entity_dicts[row["entity_id"]] = row  # last-wins

        rel_dicts: list[dict[str, Any]] = []
        if self._rel_stream_path.exists():
            with pa.ipc.open_stream(str(self._rel_stream_path)) as reader:
                for batch in reader:
                    rel_dicts.extend(batch.to_pylist())

        self._entity_dicts = entity_dicts
        self._rel_dicts = rel_dicts
        self._by_file = {}
        self._by_type = {}
        for eid, row in entity_dicts.items():
            self._by_file.setdefault(row["file"], set()).add(eid)
            self._by_type.setdefault(EntityType[row["entity_type"]], set()).add(eid)
        self._rebuild_rel_indexes()
        self._phase2_loaded = True

        for path in (self._entity_stream_path, self._rel_stream_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _ensure_phase2(self) -> None:
        if not self._phase2_loaded and not self._compacted:
            self._load_stream_to_dicts()

    def _rebuild_rel_indexes(self) -> None:
        by_endpoint: dict[str, list[int]] = {}
        id_to_idx: dict[str, int] = {}
        for idx, row in enumerate(self._rel_dicts):
            by_endpoint.setdefault(row["source_id"], []).append(idx)
            by_endpoint.setdefault(row["target_id"], []).append(idx)
            id_to_idx[row["rel_id"]] = idx
        self._rels_by_endpoint = by_endpoint
        self._rel_id_to_idx = id_to_idx

    def compact(self) -> None:
        """Compact Phase-2 dicts into memory-mapped IPC files (idempotent).

        Writes unified Arrow IPC files (uncompressed — required for mmap),
        opens them via :func:`pyarrow.memory_map`, builds CSR/CSC adjacency
        indexes plus secondary row indexes, and frees Phase-2 state.
        """
        if self._compacted or self._closed:
            return
        self._ensure_phase2()

        entity_rows = list(self._entity_dicts.values())
        entity_table = pa.Table.from_arrays(
            _entity_arrays(entity_rows), schema=ENTITY_ARROW_SCHEMA
        )
        rel_table = pa.Table.from_arrays(
            _rel_arrays(self._rel_dicts), schema=REL_ARROW_SCHEMA
        )

        entity_path = self._staging_dir / "entities.arrow"
        rel_path = self._staging_dir / "rels.arrow"
        options = pa.ipc.IpcWriteOptions(compression=None)  # required for mmap
        with pa.ipc.new_file(str(entity_path), ENTITY_ARROW_SCHEMA, options=options) as writer:
            writer.write_table(entity_table)
        with pa.ipc.new_file(str(rel_path), REL_ARROW_SCHEMA, options=options) as writer:
            writer.write_table(rel_table)

        self._entity_mmap = pa.memory_map(str(entity_path), "r")
        self._rel_mmap = pa.memory_map(str(rel_path), "r")
        self._entity_table = pa.ipc.open_file(self._entity_mmap).read_all().combine_chunks()
        self._rel_table = pa.ipc.open_file(self._rel_mmap).read_all().combine_chunks()

        # Preserve Phase-2 dict keys as entity identity (InMemoryGraph parity):
        # post-processing may evolve entities so their content-computed id
        # changes (e.g. semantic rules retag type/name), while relationships
        # extracted earlier still reference the original id. The dict key is
        # the stable identity; row order matches entity_rows above.
        self._row_entity_ids = list(self._entity_dicts.keys())
        self._entity_row_map = {eid: i for i, eid in enumerate(self._row_entity_ids)}
        self._build_adjacency_indexes()
        self._build_secondary_row_indexes()
        self._rel_count_compacted = self._rel_table.num_rows

        # Free Phase-2 state (authoritative copy now lives in the mmap'd files)
        self._entity_dicts = {}
        self._rel_dicts = []
        self._by_file = {}
        self._by_type = {}
        self._rels_by_endpoint = {}
        self._rel_id_to_idx = {}
        # Column handles cached for O(1) row decode (avoids per-call
        # table.column(name) lookups on the random-access hot path).
        self._entity_columns = {
            name: self._entity_table.column(name) for name in ENTITY_ARROW_SCHEMA.names
        }
        self._rel_columns = {
            name: self._rel_table.column(name) for name in REL_ARROW_SCHEMA.names
        }
        self._compacted = True

        LOGGER.info(
            "arrow_graph_compacted",
            entities=len(self._row_entity_ids),
            relationships=self._rel_count_compacted,
            staging_dir=str(self._staging_dir),
        )

    def _build_adjacency_indexes(self) -> None:
        """Build CSR (by source entity row) / CSC (by target entity row) indexes.

        ``indices`` store *relationship row indices* so one structure serves
        both ``neighbors()`` and ``get_rels_by_endpoint()``. Rels whose
        endpoint is not an entity row are kept in ``_external_out`` /
        ``_external_in`` keyed by the endpoint id.
        """
        assert self._rel_table is not None
        source_ids = self._rel_table.column("source_id").to_pylist()
        target_ids = self._rel_table.column("target_id").to_pylist()
        n_entities = len(self._row_entity_ids)
        n_rels = len(source_ids)
        row_map = self._entity_row_map

        src_rows = np.fromiter(
            (row_map.get(s, -1) for s in source_ids), dtype=np.int64, count=n_rels
        )
        tgt_rows = np.fromiter(
            (row_map.get(t, -1) for t in target_ids), dtype=np.int64, count=n_rels
        )
        rel_rows = np.arange(n_rels, dtype=np.int64)

        def _csr(entity_rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            valid = entity_rows >= 0
            keys = entity_rows[valid]
            rows = rel_rows[valid]
            order = np.argsort(keys, kind="stable")
            counts = np.bincount(keys, minlength=n_entities)
            offsets = np.zeros(n_entities + 1, dtype=np.int64)
            np.cumsum(counts, out=offsets[1:])
            return offsets, rows[order]

        self._csr_offsets, self._csr_indices = _csr(src_rows)
        self._csc_offsets, self._csc_indices = _csr(tgt_rows)

        external_out: dict[str, list[int]] = {}
        external_in: dict[str, list[int]] = {}
        for i in rel_rows[src_rows < 0]:
            external_out.setdefault(source_ids[i], []).append(int(i))
        for i in rel_rows[tgt_rows < 0]:
            external_in.setdefault(target_ids[i], []).append(int(i))
        self._external_out = external_out
        self._external_in = external_in

    def _build_secondary_row_indexes(self) -> None:
        assert self._entity_table is not None
        files = self._entity_table.column("file").to_pylist()
        types = self._entity_table.column("entity_type").to_pylist()
        by_file: dict[str, list[int]] = {}
        # Keyed by EntityType.name (string), unlike Phase-2 _by_type which is
        # keyed by EntityType enum. Lookups via entities_by_type() pass
        # entity_type.name to match.
        by_type: dict[str, list[int]] = {}
        for row, (file, etype) in enumerate(zip(files, types)):
            by_file.setdefault(file, []).append(row)
            by_type.setdefault(etype, []).append(row)
        self._by_file_rows = by_file
        self._by_type_rows = by_type

    # ------------------------------------------------------------------
    # Row reconstruction (Phase 3)
    # ------------------------------------------------------------------

    def _entity_at(self, row: int) -> Entity:
        cols = self._entity_columns
        return row_to_entity({name: col[row].as_py() for name, col in cols.items()})

    def _rel_at(self, row: int) -> Relationship:
        cols = self._rel_columns
        return row_to_rel({name: col[row].as_py() for name, col in cols.items()})

    def _csr_slice(self, offsets: np.ndarray, indices: np.ndarray, entity_row: int) -> list[int]:
        start = int(offsets[entity_row])
        end = int(offsets[entity_row + 1])
        return [int(i) for i in indices[start:end]]

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    @property
    def entities(self) -> ArrowEntityView:
        return self._entity_view

    @property
    def relationships(self) -> ArrowRelView:
        return self._rel_view

    def _iter_entities(self) -> Iterator[Entity]:
        """Iterate all entities, using chunked batch decode when compacted."""
        self._ensure_phase2()
        if self._compacted:
            assert self._entity_table is not None
            for batch in self._entity_table.to_batches():
                for row in batch.to_pylist():
                    yield row_to_entity(row)
        else:
            for row in self._entity_dicts.values():
                yield row_to_entity(row)

    def _iter_relationships(self) -> Iterator[Relationship]:
        self._ensure_phase2()
        if self._compacted:
            assert self._rel_table is not None
            # Chunked batch decode avoids materializing the entire table at
            # once, bounding peak RSS on very large graphs.
            for batch in self._rel_table.to_batches():
                for row in batch.to_pylist():
                    yield row_to_rel(row)
        else:
            for row in self._rel_dicts:
                yield row_to_rel(row)

    def _rel_count(self) -> int:
        self._ensure_phase2()
        if self._compacted:
            return self._rel_count_compacted
        return len(self._rel_dicts)

    def get_entity(self, entity_id: str) -> Entity | None:
        self._ensure_phase2()
        if self._compacted:
            cached = self._entity_cache.get(entity_id)
            if cached is not None:
                return cached
            row = self._entity_row_map.get(entity_id)
            if row is None:
                return None
            entity = self._entity_at(row)
            # Bounded LRU cache: repeated get_entity on the same ids is
            # common in BSGMap build / persistence (2x per relationship).
            # Evict the least-recently-used entry when the cap is reached,
            # avoiding full cache thrashing on workloads with >8192 entities.
            if len(self._entity_cache) >= 8192:
                self._entity_cache.popitem(last=False)
            self._entity_cache[entity_id] = entity
            return entity
        row_dict = self._entity_dicts.get(entity_id)
        return row_to_entity(row_dict) if row_dict is not None else None

    def neighbors(self, entity_id: str, direction: str = "out") -> list[str]:
        self._ensure_phase2()
        if not self._compacted:
            indices = self._rels_by_endpoint.get(entity_id, [])
            out: list[str] = []
            in_: list[str] = []
            for idx in dict.fromkeys(indices):
                row = self._rel_dicts[idx]
                if row["source_id"] == entity_id:
                    out.append(row["target_id"])
                if row["target_id"] == entity_id:
                    in_.append(row["source_id"])
        else:
            entity_row = self._entity_row_map.get(entity_id)
            out_rows: list[int] = []
            in_rows: list[int] = []
            if entity_row is not None:
                assert self._csr_offsets is not None and self._csr_indices is not None
                assert self._csc_offsets is not None and self._csc_indices is not None
                out_rows = self._csr_slice(self._csr_offsets, self._csr_indices, entity_row)
                in_rows = self._csr_slice(self._csc_offsets, self._csc_indices, entity_row)
            out_rows.extend(self._external_out.get(entity_id, []))
            in_rows.extend(self._external_in.get(entity_id, []))
            assert self._rel_table is not None
            target_col = self._rel_table.column("target_id")
            source_col = self._rel_table.column("source_id")
            out = (
                target_col.take(pa.array(out_rows, pa.int64())).to_pylist()
                if out_rows
                else []
            )
            in_ = (
                source_col.take(pa.array(in_rows, pa.int64())).to_pylist()
                if in_rows
                else []
            )
        if direction == "out":
            return out
        if direction == "in":
            return in_
        return list(dict.fromkeys(out + in_))

    def has_incoming_edges(self, entity_id: str) -> bool:
        return bool(self.neighbors(entity_id, "in"))

    def has_outgoing_edges(self, entity_id: str) -> bool:
        return bool(self.neighbors(entity_id, "out"))

    def entities_by_file(self, file_path: str) -> list[Entity]:
        self._ensure_phase2()
        if self._compacted:
            return [
                self._entity_at(row) for row in self._by_file_rows.get(file_path, [])
            ]
        return [
            row_to_entity(self._entity_dicts[eid])
            for eid in self._by_file.get(file_path, ())
            if eid in self._entity_dicts
        ]

    def entities_by_type(self, entity_type: EntityType) -> list[Entity]:
        self._ensure_phase2()
        if self._compacted:
            return [
                self._entity_at(row)
                for row in self._by_type_rows.get(entity_type.name, [])
            ]
        return [
            row_to_entity(self._entity_dicts[eid])
            for eid in self._by_type.get(entity_type, ())
            if eid in self._entity_dicts
        ]

    def get_rels_by_endpoint(self, entity_id: str) -> list[Relationship]:
        """Return all relationships where ``entity_id`` is source or target."""
        self._ensure_phase2()
        if not self._compacted:
            return [
                row_to_rel(self._rel_dicts[idx])
                for idx in self._rels_by_endpoint.get(entity_id, [])
            ]
        entity_row = self._entity_row_map.get(entity_id)
        rows: list[int] = []
        if entity_row is not None:
            assert self._csr_offsets is not None and self._csr_indices is not None
            assert self._csc_offsets is not None and self._csc_indices is not None
            rows.extend(self._csr_slice(self._csr_offsets, self._csr_indices, entity_row))
            rows.extend(self._csr_slice(self._csc_offsets, self._csc_indices, entity_row))
        rows.extend(self._external_out.get(entity_id, []))
        rows.extend(self._external_in.get(entity_id, []))
        # No dedup: CSR and CSC slices only intersect on self-loops, which
        # InMemoryGraph's endpoint index also returns twice (source+target).
        return [self._rel_at(row) for row in rows]

    def degree_by_endpoint(self, entity_id: str) -> int:
        """Count relationships touching ``entity_id`` without reconstructing them.

        Post-compact this reads CSR/CSC offset deltas directly (O(1)); the
        result matches ``len(get_rels_by_endpoint(entity_id))`` including
        double-counted self-loops.
        """
        self._ensure_phase2()
        if not self._compacted:
            return len(self._rels_by_endpoint.get(entity_id, ()))
        total = len(self._external_out.get(entity_id, ())) + len(
            self._external_in.get(entity_id, ())
        )
        entity_row = self._entity_row_map.get(entity_id)
        if entity_row is None:
            return total
        assert self._csr_offsets is not None and self._csc_offsets is not None
        return (
            int(self._csr_offsets[entity_row + 1] - self._csr_offsets[entity_row])
            + int(self._csc_offsets[entity_row + 1] - self._csc_offsets[entity_row])
            + total
        )

    def entity_ids_by_type(self, entity_type: EntityType) -> list[str]:
        """Return entity ids of a type without reconstructing entities."""
        self._ensure_phase2()
        if self._compacted:
            rows = self._by_type_rows.get(entity_type.name, [])
            return [self._row_entity_ids[i] for i in rows]
        return [
            eid
            for eid in self._by_type.get(entity_type, ())
            if eid in self._entity_dicts
        ]

    def get_all_nodes(self) -> list[str]:
        self._ensure_phase2()
        if self._compacted:
            return list(self._row_entity_ids)
        return list(self._entity_dicts.keys())

    def root_entities(self) -> list[Entity]:
        self._ensure_phase2()
        if self._compacted:
            assert self._entity_table is not None
            parent_col = self._entity_table.column("parent_id")
            null_mask = pc.is_null(parent_col).to_pylist()
            return [
                self._entity_at(row) for row, is_null in enumerate(null_mask) if is_null
            ]
        return [
            row_to_entity(row)
            for row in self._entity_dicts.values()
            if row["parent_id"] is None
        ]

    # ------------------------------------------------------------------
    # Mutations (Phase 2 only)
    # ------------------------------------------------------------------

    def _require_mutable(self) -> None:
        if self._compacted:
            raise RuntimeError(
                "ArrowGraph is compacted (read-only); mutations are only "
                "allowed before compact()"
            )
        self._ensure_phase2()

    def _put_entity_dict(self, entity_id: str, row: dict[str, Any]) -> None:
        old = self._entity_dicts.get(entity_id)
        if old is not None:
            if old["file"] != row["file"]:
                self._by_file.get(old["file"], set()).discard(entity_id)
            if old["entity_type"] != row["entity_type"]:
                self._by_type.get(EntityType[old["entity_type"]], set()).discard(entity_id)
        self._entity_dicts[entity_id] = row
        self._by_file.setdefault(row["file"], set()).add(entity_id)
        self._by_type.setdefault(EntityType[row["entity_type"]], set()).add(entity_id)


    def update_entity(self, entity_id: str, entity: Entity) -> None:
        """Insert or replace an entity, maintaining secondary indexes."""
        self._require_mutable()
        self._put_entity_dict(entity_id, entity_to_row(entity))

    def update_relationships(self, relationships: list[Relationship]) -> None:
        """Replace the full relationship list and rebuild endpoint indexes."""
        self._require_mutable()
        self._rel_dicts = [rel_to_row(rel) for rel in relationships]
        self._rel_ids = {rel.id for rel in relationships}
        self._rebuild_rel_indexes()

    def update_relationship(self, relationship: Relationship) -> None:
        """Replace a single relationship (matched by id)."""
        self._require_mutable()
        idx = self._rel_id_to_idx.get(relationship.id)
        if idx is None:
            self.add_relationship(relationship)
            return
        old = self._rel_dicts[idx]
        new_row = rel_to_row(relationship)
        self._rel_dicts[idx] = new_row
        for endpoint in (old["source_id"], old["target_id"]):
            lst = self._rels_by_endpoint.get(endpoint)
            if lst and idx in lst:
                lst.remove(idx)
        self._rels_by_endpoint.setdefault(new_row["source_id"], []).append(idx)
        self._rels_by_endpoint.setdefault(new_row["target_id"], []).append(idx)

    def _detach_relationship_rows(self, rel_idxs: set[int]) -> None:
        """Remove relationship rows by index and rebuild endpoint indexes."""
        if not rel_idxs:
            return
        for idx in rel_idxs:
            self._rel_ids.discard(self._rel_dicts[idx]["rel_id"])
        self._rel_dicts = [
            d for i, d in enumerate(self._rel_dicts) if i not in rel_idxs
        ]
        self._rebuild_rel_indexes()

    def remove_node(self, entity_id: str) -> bool:
        """Remove an entity and detach its relationships (mirrors InMemoryGraph)."""
        self._require_mutable()
        row = self._entity_dicts.pop(entity_id, None)
        if row is None:
            return False

        file_set = self._by_file.get(row["file"])
        if file_set is not None:
            file_set.discard(entity_id)
        type_set = self._by_type.get(EntityType[row["entity_type"]])
        if type_set is not None:
            type_set.discard(entity_id)

        rel_idxs = self._rels_by_endpoint.pop(entity_id, [])
        self._detach_relationship_rows(set(rel_idxs))
        return True

    def evict_file_graph(self, file_path: str) -> None:
        """Remove all entities (and attached relationships) for a file."""
        self._require_mutable()
        entity_ids = list(self._by_file.get(file_path, ()))
        if not entity_ids:
            return

        rel_idxs: set[int] = set()
        for eid in entity_ids:
            row = self._entity_dicts.pop(eid, None)
            if row is not None:
                type_set = self._by_type.get(EntityType[row["entity_type"]])
                if type_set is not None:
                    type_set.discard(eid)

            rel_idxs.update(self._rels_by_endpoint.pop(eid, ()))
        self._by_file.pop(file_path, None)
        self._detach_relationship_rows(rel_idxs)

    def enrich_from_storage_view(self, storage_view_data: dict[str, Any]) -> None:
        """Enrich entities from a storage-view payload (protocol parity).

        Applies the same field whitelist as InMemoryGraph (raw_content /
        raw_bytes, with hex decode for raw_bytes). Raw fields are not
        representable in the Arrow schema and are dropped at compact time
        (the graph never carries raw content).
        """
        if not storage_view_data:
            return
        self._require_mutable()
        for file_entry in storage_view_data.get("files", []):
            for entity_data in file_entry.get("entities", []):
                entity_id = entity_data.get("id")
                if entity_id and entity_id in self._entity_dicts:
                    entity = row_to_entity(self._entity_dicts[entity_id])
                    updates: dict[str, Any] = {}
                    if "raw_content" in entity_data:
                        updates["raw_content"] = entity_data["raw_content"]
                    if "raw_bytes" in entity_data:
                        raw_bytes_val = entity_data["raw_bytes"]
                        if isinstance(raw_bytes_val, str) and raw_bytes_val:
                            updates["raw_bytes"] = bytes.fromhex(raw_bytes_val)
                        elif raw_bytes_val:
                            updates["raw_bytes"] = raw_bytes_val
                    if updates:
                        self._put_entity_dict(
                            entity_id, entity_to_row(entity.model_copy(update=updates))
                        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Release mmap handles and remove the staging directory (idempotent)."""
        if self._closed:
            return
        self._closed = True
        self._close_streams()
        self._entity_table = None
        self._rel_table = None
        for mmap_file in (self._entity_mmap, self._rel_mmap):
            if mmap_file is not None:
                try:
                    mmap_file.close()
                except Exception:
                    pass
        self._entity_mmap = None
        self._rel_mmap = None
        self._entity_columns = {}
        self._rel_columns = {}
        self._entity_cache = OrderedDict()
        if self._staging_preexisted:
            # Only remove files this backend creates; never rmtree a directory
            # that existed before this instance (defense-in-depth against
            # deleting foreign content).
            for name in _STAGING_FILENAMES:
                try:
                    (self._staging_dir / name).unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                self._staging_dir.rmdir()  # only succeeds if left empty
            except OSError:
                pass
        else:
            shutil.rmtree(self._staging_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        self._ensure_phase2()
        if self._compacted:
            return len(self._row_entity_ids)
        return len(self._entity_dicts)

    def __contains__(self, entity_id: str) -> bool:
        self._ensure_phase2()
        if self._compacted:
            return entity_id in self._entity_row_map
        return entity_id in self._entity_dicts

    def __repr__(self) -> str:
        return (
            f"ArrowGraph(backend='arrow', entities={len(self)}, "
            f"relationships={self._rel_count()}, compacted={self._compacted})"
        )

    def stats(self) -> dict[str, Any]:
        """Get statistics about the graph (same keys as InMemoryGraph)."""
        self._ensure_phase2()
        if self._compacted:
            assert self._entity_table is not None and self._rel_table is not None
            entity_type_counts = pc.value_counts(
                self._entity_table.column("entity_type")
            ).to_pylist()
            entity_types = {
                EntityType[entry["values"]].value: entry["counts"]
                for entry in entity_type_counts
            }
            rel_type_counts = pc.value_counts(
                self._rel_table.column("rel_type")
            ).to_pylist()
            relationship_types = {
                RelationshipType[entry["values"]].value: entry["counts"]
                for entry in rel_type_counts
            }
            return {
                "entity_count": len(self._row_entity_ids),
                "relationship_count": self._rel_count_compacted,
                "file_count": len(self._by_file_rows),
                "entity_types": entity_types,
                "total_entities": len(self._row_entity_ids),
                "total_relationships": self._rel_count_compacted,
                "relationship_types": relationship_types,
                "files_indexed": len(self._by_file_rows),
                "indexes_valid": True,
            }
        entity_types: dict[int, int] = {}
        for etype, ids in self._by_type.items():
            count = sum(1 for eid in ids if eid in self._entity_dicts)
            if count:
                entity_types[etype.value] = count
        relationship_types: dict[int, int] = {}
        for row in self._rel_dicts:
            key = RelationshipType[row["rel_type"]].value
            relationship_types[key] = relationship_types.get(key, 0) + 1
        return {
            "entity_count": len(self._entity_dicts),
            "relationship_count": len(self._rel_dicts),
            "file_count": len(self._by_file),
            "entity_types": entity_types,
            "total_entities": len(self._entity_dicts),
            "total_relationships": len(self._rel_dicts),
            "relationship_types": relationship_types,
            "files_indexed": len(self._by_file),
            "indexes_valid": self._phase2_loaded,
        }

    def to_dict(self, *, view: str = "storage") -> dict[str, Any]:
        entities_by_id: dict[str, Any] = {}
        entities_list: list[Any] = []
        for eid, entity in self.entities.items():
            payload = entity.to_dict(view=view)
            entities_by_id[eid] = payload
            entities_list.append(payload)
        return {
            "entities": entities_list,
            "entities_by_id": entities_by_id,
            "relationships": [rel.to_dict() for rel in self.relationships],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], staging_dir: str | Path) -> "ArrowGraph":
        """Rebuild an ArrowGraph from a ``to_dict`` payload.

        Signature deviation from ``InMemoryGraph.from_dict``: requires a
        ``staging_dir`` for the Arrow staging area.
        """
        graph = cls(staging_dir=staging_dir)
        for e_data in data.get("entities_by_id", {}).values():
            graph.add_entity(Entity.from_dict(e_data))
        for r_data in data.get("relationships", []):
            graph.add_relationship(Relationship.from_dict(r_data))
        return graph
