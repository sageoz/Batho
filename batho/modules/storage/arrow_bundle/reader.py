"""Arrow Bundle Reader — zero-copy memory-mapped reads with O(1) point lookup.

On first access to a logical table:
  1. Reads the active .vN.ipc path from meta.json
  2. Opens it via pa.memory_map (zero-copy)
  3. Builds a numpy offset index: dict[file_id → slice]

Subsequent get_file_artifacts(file_id) calls use the index for O(1) table.slice().
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc

from batho.utils.logging import get_logger
from .manager import BathoBundleManager

LOGGER = get_logger(__name__, component="arrow_bundle_reader")


class BathoBundleReader:
    """Memory-mapped, zero-copy reader for consolidated Arrow Bundle file artifacts."""

    def __init__(self, artifact_dir: Path) -> None:
        self.artifact_dir = artifact_dir.resolve()
        self._manager = BathoBundleManager(self.artifact_dir)
        self._tables: dict[str, pa.Table] = {}
        self._indices: dict[str, dict[int, slice]] = {}
        self._cached_paths: dict[str, Path | None] = {}
        self._lock = threading.RLock()

    def _get_table(self, logical_name: str) -> pa.Table:
        """Lazily memory-map the active IPC file for a logical table."""
        with self._lock:
            active_path = self._manager.active_path(logical_name)
            
            if logical_name in self._tables and self._cached_paths.get(logical_name) == active_path:
                return self._tables[logical_name]

            # Invalidate old cache
            self._tables.pop(logical_name, None)
            self._indices.pop(logical_name, None)
            self._cached_paths[logical_name] = active_path

            if active_path is None:
                return pa.table({})

            try:
                with pa.memory_map(str(active_path), "r") as mmap:
                    with ipc.open_file(mmap) as reader:
                        table = reader.read_all()

                # Ensure the table is globally sorted by file_id if present to support NP point lookup slices
                if "file_id" in table.schema.names and table.num_rows > 0:
                    import pyarrow.compute as pc
                    indices = pc.sort_indices(table, sort_keys=[("file_id", "ascending")])
                    table = table.take(indices)

                self._tables[logical_name] = table

                if "file_id" in table.schema.names:
                    self._indices[logical_name] = self._build_offset_index(table)

                return table
            except Exception as exc:
                LOGGER.error("bundle_reader_mmap_failed", table=logical_name, error=str(exc))
                return pa.table({})

    def _build_offset_index(self, table: pa.Table) -> dict[int, slice]:
        """Build dict[file_id → slice] using numpy for O(1) row lookup.

        Assumes rows are sorted by file_id (guaranteed by BathoBundleWriter).
        """
        if table.num_rows == 0:
            return {}

        file_ids = table.column("file_id").combine_chunks().to_numpy(zero_copy_only=False)
        unique_ids, start_indices = np.unique(file_ids, return_index=True)

        index: dict[int, slice] = {}
        n = len(unique_ids)
        for i in range(n):
            fid = int(unique_ids[i])
            start = int(start_indices[i])
            end = int(start_indices[i + 1]) if i + 1 < n else table.num_rows
            index[fid] = slice(start, end)

        return index

    def _slice_for_file(self, logical_name: str, file_id: int) -> list[dict[str, Any]]:
        with self._lock:
            table = self._get_table(logical_name)
            if table.num_rows == 0:
                return []
            row_slice = self._indices.get(logical_name, {}).get(file_id)
            if row_slice is None:
                return []
            sliced = table.slice(row_slice.start, row_slice.stop - row_slice.start)
            return sliced.to_pylist()

    # ------------------------------------------------------------------
    # File artifact reads
    # ------------------------------------------------------------------

    def get_file_artifacts_by_id(
        self,
        file_id: int,
        *,
        include_storage: bool = False,
    ) -> dict[str, Any]:
        """O(1) extraction of agent/rels (and optionally storage) for a single file."""
        result: dict[str, Any] = {
            "file_id": file_id,
            "agent_view": self._slice_for_file("agent_views", file_id),
            "rels_view": self._slice_for_file("rels_views", file_id),
        }
        if include_storage:
            result["storage_view"] = self._slice_for_file("storage_views", file_id)
        return result

    def get_all_file_ids(self) -> list[int]:
        """Return all known file_ids from file_tracking."""
        table = self._get_table("file_tracking")
        if table.num_rows == 0:
            return []
        return table.column("file_id").to_pylist()

    def get_all_file_hashes(self) -> dict[str, str]:
        """Return dict[file_path → content_hash] from file_tracking."""
        table = self._get_table("file_tracking")
        if table.num_rows == 0:
            return {}
        paths = table.column("file_path").to_pylist()
        hashes = table.column("content_hash").to_pylist()
        return dict(zip(paths, hashes))

    def get_all_file_tracking(self) -> dict[str, dict[str, Any]]:
        """Return dict[file_path → tracking_row] from file_tracking."""
        table = self._get_table("file_tracking")
        if table.num_rows == 0:
            return {}
        rows = table.to_pylist()
        return {row["file_path"]: row for row in rows}

    def get_file_tracking(self, file_path: str) -> dict[str, Any] | None:
        """Return single file_tracking row for a path."""
        file_path = str(file_path).replace("\\", "/")
        table = self._get_table("file_tracking")
        if table.num_rows == 0:
            return None
        import pyarrow.compute as pc
        mask = pc.equal(table.column("file_path"), file_path)
        sliced = table.filter(mask)
        if sliced.num_rows == 0:
            return None
        return sliced.to_pylist()[0]

    def get_unindexed_files_with_details(self) -> list[dict[str, Any]]:
        """Return file_tracking rows where is_indexed is False."""
        table = self._get_table("file_tracking")
        if table.num_rows == 0:
            return []
        import pyarrow.compute as pc
        mask = pc.equal(table.column("is_indexed"), False)
        return table.filter(mask).to_pylist()

    def file_id_for_path(self, file_path: str) -> int | None:
        """Look up file_id for a given path."""
        row = self.get_file_tracking(str(file_path).replace("\\", "/"))
        return row["file_id"] if row else None

    # ------------------------------------------------------------------
    # Run reads
    # ------------------------------------------------------------------

    def get_all_runs(self) -> list[dict[str, Any]]:
        table = self._get_table("runs")
        if table.num_rows == 0:
            return []
        return table.to_pylist()

    def get_run(self, run_uuid: str) -> dict[str, Any] | None:
        table = self._get_table("runs")
        if table.num_rows == 0:
            return None
        import pyarrow.compute as pc
        mask = pc.equal(table.column("run_uuid"), run_uuid)
        rows = table.filter(mask).to_pylist()
        return rows[0] if rows else None

    def get_latest_run_id(self) -> str | None:
        manifest = self._manager.load_manifest()
        return manifest.get("last_run_uuid")

    def get_run_internal_id(self, run_uuid: str) -> int | None:
        """Return 1-based row position as run_internal_id (Arrow has no autoincrement)."""
        table = self._get_table("runs")
        if table.num_rows == 0:
            return None
        uuids = table.column("run_uuid").to_pylist()
        try:
            return uuids.index(run_uuid) + 1
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Changelog reads
    # ------------------------------------------------------------------

    def get_file_changelog_raw(
        self,
        rel_path: str | None = None,
        since_run_uuid: str | None = None,
    ) -> list[dict[str, Any]]:
        if rel_path is not None:
            rel_path = str(rel_path).replace("\\", "/")
        table = self._get_table("file_changelog")
        if table.num_rows == 0:
            return []

        import pyarrow.compute as pc

        if rel_path is not None:
            file_id = self.file_id_for_path(rel_path)
            if file_id is None:
                return []
            mask = pc.equal(table.column("file_id"), file_id)
            table = table.filter(mask)

        if since_run_uuid is not None:
            mask2 = pc.equal(table.column("run_uuid"), since_run_uuid)
            table = table.filter(mask2)

        return table.to_pylist()

    def get_file_node_history(
        self,
        entity_id: str,
        *,
        since_run_uuid: str | None = None,
    ) -> list[dict[str, Any]]:
        table = self._get_table("file_changelog")
        if table.num_rows == 0:
            return []
        import pyarrow.compute as pc
        mask = pc.equal(table.column("entity_id"), entity_id)
        result = table.filter(mask)
        return result.to_pylist()

    # ------------------------------------------------------------------
    # Run artifacts reads
    # ------------------------------------------------------------------

    def get_run_artifacts(self, run_uuid: str) -> dict[str, Any] | None:
        table = self._get_table("run_artifacts")
        if table.num_rows == 0:
            return None
        import pyarrow.compute as pc
        mask = pc.equal(table.column("run_uuid"), run_uuid)
        rows = table.filter(mask).to_pylist()
        return rows[0] if rows else None

    # ------------------------------------------------------------------
    # Invalidation (after a new generation is committed)
    # ------------------------------------------------------------------

    def invalidate(self, logical_name: str | None = None) -> None:
        """Drop cached table so next access re-mmaps the new generation."""
        with self._lock:
            if logical_name is None:
                self._tables.clear()
                self._indices.clear()
                self._cached_paths.clear()
            else:
                self._tables.pop(logical_name, None)
                self._indices.pop(logical_name, None)
                self._cached_paths.pop(logical_name, None)
