"""BsgScratchStore — Apache Arrow IPC persistent scratch store.

Replaces the four SQLite scratch tables:
  entity_dict, query_entities, query_relationships, dangling_references

Directory layout:
  <batho_dir>/bsg/current/          ← single shared store (build + patch update in-place)
    entity_dict.ipc                 # plain Arrow IPC File, memory-mappable
    entities.ipc                    # plain Arrow IPC File, memory-mappable
    relationships.ipc               # plain Arrow IPC File, memory-mappable
    dangling.ipc                    # plain Arrow IPC File, memory-mappable
    meta.json
    _stream/                        # staging during bulk-insert; removed after compact()
      entities_stream.ipc.zst       # IPC Stream + zstd (transient, append-friendly)
      relationships_stream.ipc.zst
      dangling_stream.ipc.zst

  <batho_dir>/bsg/<patch_uuid>/     ← per-patch delta sidecar (changed-file rows only)
    entities.ipc
    relationships.ipc
    meta.json
"""

from __future__ import annotations

import json
import re
import shutil
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow as pa

from batho.utils.logging import get_logger

from .compaction import (
    compact_dangling,
    compact_entities,
    compact_entity_dict,
    compact_relationships,
    read_ipc,
    read_ipc_columns,
    write_ipc,
    write_empty_dangling,
    _read_stream_zst,
    _write_stream_zst,
)
from .schemas import (
    DANGLING_SCHEMA,
    ENTITIES_SCHEMA,
    RELATIONSHIPS_SCHEMA,
    SCHEMA_VERSION,
)


# ---------------------------------------------------------------------------
# Row-tuple → pa.Table helpers (used by _stream/ spill path)
# ---------------------------------------------------------------------------

def _rows_to_entities_table(rows: list[tuple]) -> pa.Table:
    if not rows:
        return pa.table({
            "entity_key": pa.array([], type=pa.int64()),
            "run_id": pa.array([], type=pa.int32()),
            "entity_name": pa.array([], type=pa.dictionary(pa.int32(), pa.utf8())),
            "entity_type": pa.array([], type=pa.dictionary(pa.int16(), pa.utf8())),
            "fqn": pa.array([], type=pa.large_utf8()),
            "file_path": pa.array([], type=pa.dictionary(pa.int32(), pa.utf8())),
            "line_number": pa.array([], type=pa.int32()),
            "signature": pa.array([], type=pa.large_utf8()),
            "is_exported": pa.array([], type=pa.bool_()),
        }, schema=ENTITIES_SCHEMA)
    eks, rids, ens, ets, fqns, fps, lns, sigs, exps = zip(*rows)
    return pa.table({
        "entity_key": pa.array(eks, type=pa.int64()),
        "run_id": pa.array(rids, type=pa.int32()),
        "entity_name": pa.array(ens, type=pa.dictionary(pa.int32(), pa.utf8())),
        "entity_type": pa.array(ets, type=pa.dictionary(pa.int16(), pa.utf8())),
        "fqn": pa.array(fqns, type=pa.large_utf8()),
        "file_path": pa.array(fps, type=pa.dictionary(pa.int32(), pa.utf8())),
        "line_number": pa.array(lns, type=pa.int32()),
        "signature": pa.array(sigs, type=pa.large_utf8()),
        "is_exported": pa.array(exps, type=pa.bool_()),
    }, schema=ENTITIES_SCHEMA)


def _rows_to_relationships_table(rows: list[tuple]) -> pa.Table:
    if not rows:
        return pa.table({
            "source_key": pa.array([], type=pa.int64()),
            "target_key": pa.array([], type=pa.int64()),
            "relation_type": pa.array([], type=pa.dictionary(pa.int16(), pa.utf8())),
            "run_id": pa.array([], type=pa.int32()),
            "metadata_json": pa.array([], type=pa.utf8()),
        }, schema=RELATIONSHIPS_SCHEMA)
    sks, tks, rts, rids, mjs = zip(*rows)
    return pa.table({
        "source_key": pa.array(sks, type=pa.int64()),
        "target_key": pa.array(tks, type=pa.int64()),
        "relation_type": pa.array(rts, type=pa.dictionary(pa.int16(), pa.utf8())),
        "run_id": pa.array(rids, type=pa.int32()),
        "metadata_json": pa.array(mjs, type=pa.utf8()),
    }, schema=RELATIONSHIPS_SCHEMA)


def _rows_to_dangling_table(rows: list[tuple]) -> pa.Table:
    if not rows:
        return pa.table({
            "source_key": pa.array([], type=pa.int64()),
            "unresolved_target_name": pa.array([], type=pa.dictionary(pa.int32(), pa.utf8())),
            "relation_type": pa.array([], type=pa.dictionary(pa.int16(), pa.utf8())),
            "run_id": pa.array([], type=pa.int32()),
        }, schema=DANGLING_SCHEMA)
    sks, tns, rts, rids = zip(*rows)
    return pa.table({
        "source_key": pa.array(sks, type=pa.int64()),
        "unresolved_target_name": pa.array(tns, type=pa.dictionary(pa.int32(), pa.utf8())),
        "relation_type": pa.array(rts, type=pa.dictionary(pa.int16(), pa.utf8())),
        "run_id": pa.array(rids, type=pa.int32()),
    }, schema=DANGLING_SCHEMA)

LOGGER = get_logger(__name__, component="arrow_store")

FLUSH_THRESHOLD = 100_000
BSG_STORE_SCHEMA_VERSION = SCHEMA_VERSION

PSEUDO_TARGET_PREFIXES = (
    "external:",
    "file:",
    "anchor:",
    "unresolved:",
    "symbol:",
    "image:",
    "import:",
    "stylesheet:",
    "resource:",
    "variable:",
)


class BsgScratchStore:
    """Arrow IPC + zstd scratch store for BSG build/patch runs.

    is_delta=False (default): writes to bsg/current/ — the single shared authoritative store.
    is_delta=True: writes to bsg/<run_uuid>/ — per-patch delta sidecar (changed rows only).
    """

    def __init__(
        self,
        run_uuid: str,
        batho_dir: Path,
        run_internal_id: int,
        *,
        is_delta: bool = False,
        _base_run_uuid: str = "",
        _changed_files: set[str] | None = None,
    ) -> None:
        self.run_uuid = run_uuid
        self.run_internal_id = run_internal_id
        self.is_delta = is_delta
        self._batho_dir = batho_dir.resolve()
        self._run_dir = (
            self._batho_dir / "bsg" / run_uuid
            if is_delta
            else self._batho_dir / "bsg" / "current"
        )
        self._stream_dir = self._run_dir / "_stream"
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._stream_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()

        # In-memory entity dict: val → id and id → val
        self._entity_dict: dict[str, int] = {}
        self._entity_val: dict[int, str] = {}
        self._next_entity_id: int = 1

        # Delta sidecar metadata
        self._base_run_uuid: str = _base_run_uuid
        self._changed_files: set[str] = _changed_files or set()

        # Row buffers
        self._entity_rows: list[tuple] = []
        self._rel_rows: list[tuple] = []
        self._dangling_rows: list[tuple] = []

        # Counters (accessible from orchestrator without reading Arrow)
        self.entity_count: int = 0
        self.rel_count: int = 0
        self.dangling_count: int = 0

        self._compacted = False

        # Write initial meta.json
        self._write_meta()

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    @property
    def entities_path(self) -> Path:
        return self._run_dir / "entities.ipc"

    @property
    def relationships_path(self) -> Path:
        return self._run_dir / "relationships.ipc"

    @property
    def dangling_path(self) -> Path:
        return self._run_dir / "dangling.ipc"

    @property
    def entity_dict_path(self) -> Path:
        return self._run_dir / "entity_dict.ipc"

    # ------------------------------------------------------------------
    # Entity dict (in-memory, no SQL)
    # ------------------------------------------------------------------

    def bulk_get_or_create_entity_keys(self, entity_ids: list[str]) -> dict[str, int]:
        """Batch-resolve entity ID strings to integer keys (creates if missing)."""
        with self._lock:
            result: dict[str, int] = {}
            for eid in entity_ids:
                if eid in self._entity_dict:
                    result[eid] = self._entity_dict[eid]
                else:
                    key = self._next_entity_id
                    self._next_entity_id += 1
                    self._entity_dict[eid] = key
                    self._entity_val[key] = eid
                    result[eid] = key
            return result

    def get_entity_val(self, key: int) -> str | None:
        """Reverse lookup: integer key → entity ID string."""
        return self._entity_val.get(key)

    # ------------------------------------------------------------------
    # Append rows (called from insert_file_artifacts_batch equivalent)
    # ------------------------------------------------------------------

    def append_entities(self, rows: list[tuple]) -> None:
        """Append entity rows: (entity_key, run_id, name, type, fqn, file_path, line, sig, is_exp)."""
        with self._lock:
            self._entity_rows.extend(rows)
            self.entity_count += len(rows)
            if len(self._entity_rows) >= FLUSH_THRESHOLD:
                self._flush_entities()

    def append_relationships(self, rows: list[tuple]) -> None:
        """Append relationship rows: (source_key, target_key, rel_type, run_id, metadata_json)."""
        with self._lock:
            self._rel_rows.extend(rows)
            self.rel_count += len(rows)
            if len(self._rel_rows) >= FLUSH_THRESHOLD:
                self._flush_relationships()

    def append_dangling(self, rows: list[tuple]) -> None:
        """Append dangling rows: (source_key, unresolved_target_name, rel_type, run_id)."""
        with self._lock:
            self._dangling_rows.extend(rows)
            self.dangling_count += len(rows)
            if len(self._dangling_rows) >= FLUSH_THRESHOLD:
                self._flush_dangling()

    # ------------------------------------------------------------------
    # Stream flush (intermediate — keeps memory bounded)
    # ------------------------------------------------------------------

    def _flush_entities(self) -> None:
        if not self._entity_rows:
            return
        self._stream_dir.mkdir(parents=True, exist_ok=True)
        path = self._stream_dir / "entities_stream.ipc.zst"
        existing = self._load_stream_rows_entities(path)
        all_rows = existing + self._entity_rows
        _write_stream_zst(_rows_to_entities_table(all_rows), path)
        self._entity_rows.clear()

    def _flush_relationships(self) -> None:
        if not self._rel_rows:
            return
        self._stream_dir.mkdir(parents=True, exist_ok=True)
        path = self._stream_dir / "relationships_stream.ipc.zst"
        existing = self._load_stream_rows_generic(path, 5)
        all_rows = existing + self._rel_rows
        _write_stream_zst(_rows_to_relationships_table(all_rows), path)
        self._rel_rows.clear()

    def _flush_dangling(self) -> None:
        if not self._dangling_rows:
            return
        self._stream_dir.mkdir(parents=True, exist_ok=True)
        path = self._stream_dir / "dangling_stream.ipc.zst"
        existing = self._load_stream_rows_dangling(path)
        all_rows = existing + self._dangling_rows
        _write_stream_zst(_rows_to_dangling_table(all_rows), path)
        self._dangling_rows.clear()

    def _load_stream_rows_entities(self, path: Path) -> list[tuple]:
        if not path.exists():
            return []
        try:
            tbl = _read_stream_zst(path)
            entity_key = tbl.column("entity_key").to_pylist()
            run_id = tbl.column("run_id").to_pylist()
            entity_name = tbl.column("entity_name").to_pylist()
            entity_type = tbl.column("entity_type").to_pylist()
            fqn = tbl.column("fqn").to_pylist()
            file_path = tbl.column("file_path").to_pylist()
            line_number = tbl.column("line_number").to_pylist()
            signature = tbl.column("signature").to_pylist()
            is_exported = tbl.column("is_exported").to_pylist()
            return [
                (ek, ri, en, et, fq, fp, ln, sg, bool(ie))
                for ek, ri, en, et, fq, fp, ln, sg, ie
                in zip(entity_key, run_id, entity_name, entity_type, fqn, file_path, line_number, signature, is_exported)
            ]
        except Exception:
            return []

    def _load_stream_rows_generic(self, path: Path, ncols: int) -> list[tuple]:
        if not path.exists():
            return []
        try:
            tbl = _read_stream_zst(path)
            cols = [tbl.column(c).to_pylist() for c in tbl.schema.names]
            return list(zip(*cols))
        except Exception:
            return []

    def _load_stream_rows_dangling(self, path: Path) -> list[tuple]:
        if not path.exists():
            return []
        try:
            tbl = _read_stream_zst(path)
            return [
                (
                    tbl.column("source_key")[i].as_py(),
                    tbl.column("unresolved_target_name")[i].as_py(),
                    tbl.column("relation_type")[i].as_py(),
                    tbl.column("run_id")[i].as_py(),
                )
                for i in range(len(tbl))
            ]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Compact (called at recreate_query_indexes() time)
    # ------------------------------------------------------------------

    def compact(self) -> None:
        """Flush all buffers → sorted plain IPC Files. Removes _stream/ staging."""
        with self._lock:
            # Merge in-memory buffers with any _stream/ spill files
            ent_stream_path = self._stream_dir / "entities_stream.ipc.zst"
            rel_stream_path = self._stream_dir / "relationships_stream.ipc.zst"
            dan_stream_path = self._stream_dir / "dangling_stream.ipc.zst"

            all_entity_rows = self._load_stream_rows_entities(ent_stream_path) + self._entity_rows
            all_rel_rows = self._load_stream_rows_generic(rel_stream_path, 5) + self._rel_rows
            all_dangling_rows = self._load_stream_rows_dangling(dan_stream_path) + self._dangling_rows

            # Deduplicate entities by (entity_key, run_id)
            seen_ent: set[tuple] = set()
            deduped_ent = []
            for row in all_entity_rows:
                key = (row[0], row[1])
                if key not in seen_ent:
                    seen_ent.add(key)
                    deduped_ent.append(row)

            # Deduplicate relationships by (source_key, target_key, relation_type, run_id)
            seen_rel: set[tuple] = set()
            deduped_rel = []
            for row in all_rel_rows:
                key = (row[0], row[1], row[2], row[3])
                if key not in seen_rel:
                    seen_rel.add(key)
                    deduped_rel.append(row)

            compact_entities(deduped_ent, self.entities_path)
            compact_relationships(deduped_rel, self.relationships_path)
            compact_dangling(all_dangling_rows, self.dangling_path)
            compact_entity_dict(list(self._entity_val.items()), self.entity_dict_path)

            # Update counters with deduped values
            self.entity_count = len(deduped_ent)
            self.rel_count = len(deduped_rel)

            # Clear in-memory buffers
            self._entity_rows.clear()
            self._rel_rows.clear()
            self._dangling_rows.clear()

            # Remove stream staging directory
            self._cleanup_stream_dir()
            self._compacted = True

        self._write_meta()
        LOGGER.info(
            "bsg_store_compacted",
            run_uuid=self.run_uuid,
            entities=self.entity_count,
            relationships=self.rel_count,
        )

    # ------------------------------------------------------------------
    # Phase H: resolve dangling references (pure Python, no SQL)
    # ------------------------------------------------------------------

    def resolve_dangling(self, db: Any) -> int:
        """Resolve dangling references using in-memory dict join + proximity scoring.

        Mirrors the logic of engine.resolve_dangling_references() but operates
        on Arrow files instead of SQLite tables.
        Returns the count of successfully resolved relationships.
        """
        if not self.dangling_path.exists():
            return 0

        try:
            dan_tbl = read_ipc(self.dangling_path)
        except Exception:
            return 0

        if len(dan_tbl) == 0:
            return 0

        if not self.entities_path.exists():
            return 0

        try:
            ent_tbl = read_ipc_columns(
                self.entities_path,
                ["entity_key", "entity_name", "file_path", "entity_type"],
            )
        except Exception:
            return 0

        # Build name → entity lookup (excluding UNRESOLVED)
        entities_by_name: dict[str, list[str]] = defaultdict(list)
        entities_by_id: dict[str, list[str]] = defaultdict(list)
        files_by_id: dict[str, str] = {}
        names_by_id: dict[str, str] = {}
        id_to_key: dict[str, int] = {}

        ent_keys = ent_tbl.column("entity_key").to_pylist()
        ent_names = ent_tbl.column("entity_name").to_pylist()
        ent_fps = ent_tbl.column("file_path").to_pylist()
        ent_types = ent_tbl.column("entity_type").to_pylist()

        for ekey, ename, efile, etype in zip(ent_keys, ent_names, ent_fps, ent_types):
            if etype and str(etype).upper() == "UNRESOLVED":
                continue
            eid = self._entity_val.get(ekey)
            if eid is None or not ename:
                continue
            id_to_key[eid] = ekey
            files_by_id[eid] = efile or ""
            names_by_id[eid] = ename
            entities_by_name[ename].append(eid)
            entities_by_id[eid].append(eid)
            if "." in ename:
                entities_by_name[ename.split(".")[-1]].append(eid)

        def lookup_candidates(ref_text: str) -> list[str]:
            normalized = ref_text.strip().strip(",;")
            normalized = re.sub(r"\s+as\s+\w+$", "", normalized).strip()
            if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'", "`"}:
                normalized = normalized[1:-1].strip()
            normalized = normalized.replace("::", ".").strip()
            if not normalized:
                return []
            ordered = [normalized]
            if "/" in normalized:
                tail = normalized.rsplit("/", 1)[-1]
                ordered.append(tail)
                if "." in tail:
                    ordered.append(tail.rsplit(".", 1)[0])
            if "." in normalized:
                ordered.append(normalized.rsplit(".", 1)[-1])
            if ":" in normalized and not normalized.startswith(("http://", "https://")):
                ordered.append(normalized.rsplit(":", 1)[-1])
            return ordered

        def shared_dir_depth(source: str, target: str) -> int:
            source_parts = Path(source).parts[:-1]
            target_parts = Path(target).parts[:-1]
            depth = 0
            for sp, tp in zip(source_parts, target_parts):
                if sp != tp:
                    break
                depth += 1
            return depth

        def choose_best(candidate_ids: list[str], source_file: str | None) -> str | None:
            if not candidate_ids:
                return None
            if len(candidate_ids) == 1:
                return candidate_ids[0]

            def score(entity_id: str) -> tuple[int, int, str]:
                target_file = files_by_id.get(entity_id, "")
                val_score = 0
                if source_file and target_file:
                    if source_file == target_file:
                        val_score += 1000
                    val_score += shared_dir_depth(source_file, target_file) * 10
                name_len = len(names_by_id.get(entity_id, ""))
                return (val_score, -name_len, entity_id)

            return max(candidate_ids, key=score)

        # Fetch source file for each dangling row
        src_keys_list = dan_tbl.column("source_key").to_pylist()
        tgt_names_list = dan_tbl.column("unresolved_target_name").to_pylist()
        rel_types_list = dan_tbl.column("relation_type").to_pylist()

        # Build source_key → file_path map from entities table
        src_key_to_file: dict[int, str] = {}
        for ekey, efile in zip(ent_keys, ent_fps):
            if ekey is not None and efile:
                src_key_to_file[ekey] = efile

        rels_to_insert: list[tuple] = []
        resolution_map: dict[str, list[dict]] = defaultdict(list)

        for src_key, ref_name, rel_type in zip(src_keys_list, tgt_names_list, rel_types_list):
            if not ref_name or not rel_type:
                continue
            src_file = src_key_to_file.get(src_key)

            target_ids = entities_by_id.get(ref_name)
            if not target_ids:
                for cand in lookup_candidates(ref_name):
                    target_ids = entities_by_name.get(cand)
                    if target_ids:
                        break

            target_id = choose_best(target_ids, src_file) if target_ids else None
            if target_id:
                tgt_key = id_to_key.get(target_id)
                if tgt_key is not None:
                    rels_to_insert.append((src_key, tgt_key, rel_type, self.run_internal_id, "{}"))
                    src_id = self._entity_val.get(src_key)
                    if src_id and src_file:
                        resolution_map[src_file].append(
                            {
                                "source_id": src_id,
                                "relation_type": rel_type,
                                "unresolved_target": ref_name,
                                "resolved_target": target_id,
                            }
                        )

        if rels_to_insert:
            # Deduplicate against existing relationships
            existing_rel_keys: set[tuple] = set()
            if self.relationships_path.exists():
                try:
                    existing_tbl = read_ipc_columns(
                        self.relationships_path,
                        ["source_key", "target_key", "relation_type", "run_id"],
                    )
                    for i in range(len(existing_tbl)):
                        existing_rel_keys.add((
                            existing_tbl.column("source_key")[i].as_py(),
                            existing_tbl.column("target_key")[i].as_py(),
                            existing_tbl.column("relation_type")[i].as_py(),
                            existing_tbl.column("run_id")[i].as_py(),
                        ))
                except Exception:
                    pass

            new_rels = [
                r for r in rels_to_insert
                if (r[0], r[1], r[2], r[3]) not in existing_rel_keys
            ]
            if new_rels:
                with self._lock:
                    self._rel_rows.extend(new_rels)
                    self.rel_count += len(new_rels)
                    self._flush_relationships()
                    # Re-compact relationships to merge resolved rels
                    self._recompact_relationships_only()

        # Patch bsg_rel_view blobs in SQLite file_artifacts
        if resolution_map and db is not None:
            self._patch_rel_blobs(db, resolution_map)

        # Overwrite dangling with empty table (resolution complete)
        write_empty_dangling(self.dangling_path)
        resolved_count = len(rels_to_insert)
        LOGGER.info("dangling_resolved", count=resolved_count, run_uuid=self.run_uuid)
        return resolved_count

    def _recompact_relationships_only(self) -> None:
        """Merge stream relationships with existing compacted file."""
        stream_path = self._stream_dir / "relationships_stream.ipc.zst"
        if stream_path.exists():
            stream_rows = self._load_stream_rows_generic(stream_path, 5)
        else:
            stream_rows = []

        existing_rows: list[tuple] = []
        if self.relationships_path.exists():
            try:
                tbl = read_ipc(self.relationships_path)
                cols = [tbl.column(c).to_pylist() for c in tbl.schema.names]
                existing_rows = list(zip(*cols)) if cols[0] else []
            except Exception:
                pass

        all_rows = existing_rows + stream_rows

        seen: set[tuple] = set()
        deduped = []
        for row in all_rows:
            key = (row[0], row[1], row[2], row[3])
            if key not in seen:
                seen.add(key)
                deduped.append(row)

        compact_relationships(deduped, self.relationships_path)
        if stream_path.exists():
            stream_path.unlink(missing_ok=True)

    def _patch_rel_blobs(self, db: Any, resolution_map: dict[str, list[dict]]) -> None:
        """Update bsg_rel_view blobs in SQLite file_artifacts for resolved targets."""
        import io
        import msgpack
        import zstandard as zstd

        cctx = zstd.ZstdCompressor(level=3)
        dctx = zstd.ZstdDecompressor()

        for file_path, resolutions in resolution_map.items():
            try:
                with db.connection(read_only=True) as conn:
                    row = conn.execute(
                        """SELECT bsg_rel_view FROM file_artifacts
                           WHERE run_id = ? AND file_id = (SELECT id FROM string_dict WHERE val = ?)""",
                        (self.run_internal_id, file_path),
                    ).fetchone()
                if not row or not row["bsg_rel_view"]:
                    continue

                rels_blob = row["bsg_rel_view"]
                rels_decompressed = dctx.decompress(rels_blob)
                rels_minified = msgpack.unpackb(rels_decompressed)

                updated = False
                for rel in rels_minified:
                    r_src = rel.get("s")
                    r_type = rel.get("rt")
                    r_tgt = rel.get("t")
                    for res in resolutions:
                        is_match = False
                        if r_src == res["source_id"] and r_type == res["relation_type"]:
                            if r_tgt == res["unresolved_target"]:
                                is_match = True
                            elif isinstance(r_tgt, str) and r_tgt.startswith("unresolved:"):
                                parts = r_tgt.split(":")
                                if len(parts) >= 2 and parts[1] == res["unresolved_target"]:
                                    is_match = True
                        if is_match:
                            rel["t"] = res["resolved_target"]
                            updated = True
                            break

                if updated:
                    new_blob = cctx.compress(msgpack.packb(rels_minified))
                    with db.transaction() as conn:
                        conn.execute(
                            """UPDATE file_artifacts SET bsg_rel_view = ?
                               WHERE run_id = ? AND file_id = (SELECT id FROM string_dict WHERE val = ?)""",
                            (new_blob, self.run_internal_id, file_path),
                        )
            except Exception as e:
                LOGGER.warning("failed_to_patch_rel_blob", file_path=file_path, error=str(e))

    # ------------------------------------------------------------------
    # Patch support: open current/ store filtered for changed files
    # ------------------------------------------------------------------

    @classmethod
    def open_for_patch(
        cls,
        batho_dir: Path,
        new_run_uuid: str,
        new_run_internal_id: int,
        changed_paths: set[str],
        db: Any,
    ) -> "tuple[BsgScratchStore, BsgScratchStore]":
        """Open the shared current/ store for a patch run.

        Returns (current_store, delta_store):
          - current_store: is_delta=False, backed by bsg/current/, pre-loaded from
            current/ data with rows for changed_paths filtered out. New rows for
            changed files will be appended then compacted back to current/.
          - delta_store: is_delta=True, backed by bsg/<new_run_uuid>/, accumulates
            only the changed-file rows for diff/audit purposes.
        """
        batho_dir = Path(batho_dir).resolve()
        current_dir = batho_dir / "bsg" / "current"

        current_store = cls(
            new_run_uuid,
            batho_dir,
            new_run_internal_id,
            is_delta=False,
        )
        delta_store = cls(
            new_run_uuid,
            batho_dir,
            new_run_internal_id,
            is_delta=True,
            _base_run_uuid="current",
            _changed_files=changed_paths,
        )

        if not current_dir.exists() or not (current_dir / "entity_dict.ipc").exists():
            LOGGER.warning(
                "bsg_current_dir_missing_or_empty",
                path=str(current_dir),
                note="starting with empty store for patch",
            )
            write_empty_dangling(current_store.dangling_path)
            current_store._write_meta()
            return current_store, delta_store

        # Load entity_dict from current/ into both stores (shared key space)
        ed_path = current_dir / "entity_dict.ipc"
        try:
            ed_tbl = read_ipc(ed_path)
            for i in range(len(ed_tbl)):
                eid = ed_tbl.column("id")[i].as_py()
                val = ed_tbl.column("val")[i].as_py()
                if eid is not None and val is not None:
                    current_store._entity_dict[val] = eid
                    current_store._entity_val[eid] = val
                    if eid >= current_store._next_entity_id:
                        current_store._next_entity_id = eid + 1
        except Exception as exc:
            LOGGER.warning("bsg_load_entity_dict_failed", error=str(exc))

        # Share the same entity dict with the delta store (same integer key space)
        delta_store._entity_dict = current_store._entity_dict
        delta_store._entity_val = current_store._entity_val
        delta_store._next_entity_id = current_store._next_entity_id

        # Load and filter entities (exclude changed files) into the in-memory buffer
        # so that compact() merges them with any new rows appended for changed files.
        ent_path = current_dir / "entities.ipc"
        kept_entity_keys: set[int] = set()
        if ent_path.exists():
            try:
                ent_tbl = read_ipc(ent_path)
                fp_col = ent_tbl.column("file_path").to_pylist()
                for i in range(len(ent_tbl)):
                    if fp_col[i] in changed_paths:
                        continue
                    row = (
                        ent_tbl.column("entity_key")[i].as_py(),
                        new_run_internal_id,
                        ent_tbl.column("entity_name")[i].as_py(),
                        ent_tbl.column("entity_type")[i].as_py(),
                        ent_tbl.column("fqn")[i].as_py(),
                        fp_col[i],
                        ent_tbl.column("line_number")[i].as_py(),
                        ent_tbl.column("signature")[i].as_py(),
                        bool(ent_tbl.column("is_exported")[i].as_py()),
                    )
                    current_store._entity_rows.append(row)
                    kept_entity_keys.add(row[0])
                current_store.entity_count = len(current_store._entity_rows)
            except Exception as exc:
                LOGGER.warning("bsg_load_base_entities_failed", error=str(exc))

        # Load and filter relationships into the in-memory buffer
        rel_path = current_dir / "relationships.ipc"
        if rel_path.exists():
            try:
                rel_tbl = read_ipc(rel_path)
                src_keys = rel_tbl.column("source_key").to_pylist()
                tgt_keys = rel_tbl.column("target_key").to_pylist()
                rel_types = rel_tbl.column("relation_type").to_pylist()
                meta_jsons = rel_tbl.column("metadata_json").to_pylist()

                for src_k, tgt_k, r_type, meta in zip(src_keys, tgt_keys, rel_types, meta_jsons):
                    if kept_entity_keys and (src_k not in kept_entity_keys):
                        continue
                    current_store._rel_rows.append((src_k, tgt_k, r_type, new_run_internal_id, meta or "{}"))
                current_store.rel_count = len(current_store._rel_rows)
            except Exception as exc:
                LOGGER.warning("bsg_load_base_relationships_failed", error=str(exc))

        # entity_dict: write to disk now so it's available for key lookups
        compact_entity_dict(list(current_store._entity_val.items()), current_store.entity_dict_path)

        current_store._write_meta()
        delta_store._write_meta()
        LOGGER.info(
            "bsg_store_opened_for_patch",
            new_run=new_run_uuid,
            unchanged_entities=current_store.entity_count,
            unchanged_rels=current_store.rel_count,
        )
        return current_store, delta_store

    # ------------------------------------------------------------------
    # Finalize & cleanup
    # ------------------------------------------------------------------

    def finalize(self) -> None:
        """Flush remaining buffers if compact() wasn't called, write final meta.json."""
        if not self._compacted:
            self.compact()
        else:
            self._write_meta()

    def cleanup_streams(self) -> None:
        """Remove the _stream/ staging directory only. Compacted files persist."""
        self._cleanup_stream_dir()

    def _cleanup_stream_dir(self) -> None:
        if self._stream_dir.exists():
            shutil.rmtree(self._stream_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_meta(self) -> None:
        meta: dict[str, Any] = {
            "run_uuid": self.run_uuid,
            "run_internal_id": self.run_internal_id,
            "schema_version": BSG_STORE_SCHEMA_VERSION,
            "entity_count": self.entity_count,
            "rel_count": self.rel_count,
            "dangling_count": self.dangling_count,
            "compacted": self._compacted,
            "is_delta": self.is_delta,
        }
        if self.is_delta:
            meta["base_run_uuid"] = self._base_run_uuid
            meta["changed_files"] = sorted(self._changed_files)
        meta_path = self._run_dir / "meta.json"
        tmp = meta_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        tmp.replace(meta_path)

    @classmethod
    def from_run_dir(cls, run_dir: Path, run_internal_id: int) -> "BsgScratchStore":
        """Reconstruct a BsgScratchStore from an existing directory (read operations).

        Accepts either bsg/current/ or bsg/<patch_uuid>/ as run_dir.
        """
        meta_path = run_dir / "meta.json"
        run_uuid = run_dir.name
        is_delta = run_dir.name != "current"
        base_run_uuid = ""
        changed_files: set[str] = set()
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                run_uuid = meta.get("run_uuid", run_uuid)
                run_internal_id = meta.get("run_internal_id", run_internal_id)
                is_delta = meta.get("is_delta", is_delta)
                base_run_uuid = meta.get("base_run_uuid", "")
                changed_files = set(meta.get("changed_files", []))
            except Exception:
                pass

        batho_dir = run_dir.parent.parent
        store = cls.__new__(cls)
        store.run_uuid = run_uuid
        store.run_internal_id = run_internal_id
        store.is_delta = is_delta
        store._batho_dir = batho_dir
        store._run_dir = run_dir
        store._stream_dir = run_dir / "_stream"
        store._base_run_uuid = base_run_uuid
        store._changed_files = changed_files
        store._lock = threading.Lock()
        store._entity_dict = {}
        store._entity_val = {}
        store._next_entity_id = 1
        store._entity_rows = []
        store._rel_rows = []
        store._dangling_rows = []
        store.entity_count = 0
        store.rel_count = 0
        store.dangling_count = 0
        store._compacted = True

        # Load entity dict into memory
        ed_path = run_dir / "entity_dict.ipc"
        if ed_path.exists():
            try:
                ed_tbl = read_ipc(ed_path)
                for i in range(len(ed_tbl)):
                    eid = ed_tbl.column("id")[i].as_py()
                    val = ed_tbl.column("val")[i].as_py()
                    if eid is not None and val is not None:
                        store._entity_dict[val] = eid
                        store._entity_val[eid] = val
                        if eid >= store._next_entity_id:
                            store._next_entity_id = eid + 1
            except Exception:
                pass

        return store
