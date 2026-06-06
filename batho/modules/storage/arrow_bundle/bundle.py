"""BathoBundle — Arrow Bundle façade replacing BathoDatabase.

Public API mirrors BathoDatabase exactly so callers in build.py, patch.py,
export.py, gc.py, diff.py, fix.py, and unified_cache.py need only update
their import paths and the constructor call.

Storage layout:
  <repo_root>/.batho/artifact/   — working copy (plain IPC files)
  <repo_root>/.batho/bsg/        — BSG graph index (Arrow, unchanged)
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.ipc as ipc

from batho.utils.logging import get_logger
from .schemas import (
    BUNDLE_SCHEMA_VERSION,
    RUNS_SCHEMA,
    FILE_TRACKING_SCHEMA,
    FILE_CHANGELOG_SCHEMA,
    RUN_ARTIFACTS_SCHEMA,
)
from .manager import BathoBundleManager
from .reader import BathoBundleReader
from .writer import BathoBundleWriter, write_simple_ipc, read_ipc_table
from .helpers import (
    _accumulate_scratch_rows,
    _expand_graph_payload,
    _expand_relationship,
    _minify_graph_payload,
    _minify_relationship,
)

LOGGER = get_logger(__name__, component="arrow_bundle")

_BUNDLE_CACHE: dict[str, "BathoBundle"] = {}
_BUNDLE_CACHE_LOCK = threading.RLock()


def artifact_dirname(root: Path) -> str:
    dirname = root.resolve().name
    sanitized = re.sub(r"[^a-z0-9_-]", "-", dirname.lower())
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    if not sanitized or sanitized == "default":
        path_hash = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:8]
        sanitized = f"default-{path_hash}"
    return sanitized


def resolve_bundle_dir(root: Path | str) -> Path:
    """Return the artifact dir for repo root, from config or the default .batho/artifact/."""
    root_path = Path(root).resolve()
    try:
        from batho.core.config.loader import _get_config_cached_for_root
        cfg = _get_config_cached_for_root(root_path)
        artifact_dir = cfg.get("paths", {}).get("artifact_dir")
        if artifact_dir:
            p = Path(artifact_dir)
            if not p.is_absolute():
                p = root_path / p
            return p.resolve()
    except Exception:
        pass
    return root_path / ".batho" / "artifact"


def get_bundle(repo_root: Path | str) -> "BathoBundle":
    """Get or create a cached BathoBundle for a repository (replaces get_database)."""
    root = Path(repo_root).resolve()
    key = str(root)
    with _BUNDLE_CACHE_LOCK:
        existing = _BUNDLE_CACHE.get(key)
        if existing is not None and not existing._closed:
            return existing
        bundle = BathoBundle(root)
        _BUNDLE_CACHE[key] = bundle
        return bundle


class BathoBundle:
    """Arrow Bundle storage engine — drop-in replacement for BathoDatabase.

    Persists all Batho artifact data as plain Arrow IPC files in
    .batho/artifact/ with generation-MVCC for concurrent safety.
    """

    def __init__(self, repo_root: Path | str) -> None:
        self._repo_root = Path(repo_root).resolve()
        self._artifact_dir = resolve_bundle_dir(self._repo_root)
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        self._manager = BathoBundleManager(self._artifact_dir)
        self._reader = BathoBundleReader(self._artifact_dir)
        self._lock = threading.RLock()
        self._closed = False

        self._run_rows: list[dict[str, Any]] = []
        self._file_tracking_rows: list[dict[str, Any]] = []
        self._changelog_rows: list[dict[str, Any]] = []
        self._run_artifact_rows: list[dict[str, Any]] = []

        self._next_file_id: int = self._compute_next_file_id()
        self._file_id_cache: dict[str, int] = self._load_file_id_cache()

        self._writer: BathoBundleWriter | None = None
        self._current_run_internal_id: int = 0

    @property
    def repo_root(self) -> Path:
        return self._repo_root

    @property
    def artifact_dir(self) -> Path:
        return self._artifact_dir

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_next_file_id(self) -> int:
        p = self._active_or_empty("file_tracking")
        if p is None:
            return 1
        table = read_ipc_table(p)
        if table.num_rows == 0 or "file_id" not in table.schema.names:
            return 1
        return int(table.column("file_id").to_pylist()[-1]) + 1

    def _load_file_id_cache(self) -> dict[str, int]:
        p = self._active_or_empty("file_tracking")
        if p is None:
            return {}
        table = read_ipc_table(p)
        if table.num_rows == 0 or "file_path" not in table.schema.names:
            return {}
        paths = table.column("file_path").to_pylist()
        ids = table.column("file_id").to_pylist()
        return dict(zip(paths, ids))

    def _active_or_empty(self, name: str) -> Path | None:
        return self._manager.active_path(name)

    def _get_or_create_file_id(self, file_path: str) -> int:
        with self._lock:
            if file_path in self._file_id_cache:
                return self._file_id_cache[file_path]
            fid = self._next_file_id
            self._next_file_id += 1
            self._file_id_cache[file_path] = fid
            return fid

    def _flush_runs(self, run_uuid: str) -> None:
        if not self._run_rows:
            return
        existing_table = read_ipc_table(self._active_or_empty("runs"))
        if existing_table.num_rows > 0:
            existing_rows = existing_table.to_pylist()
            merged = {r["run_uuid"]: r for r in existing_rows}
            for r in self._run_rows:
                merged[r["run_uuid"]] = r
            all_rows = list(merged.values())
        else:
            all_rows = list(self._run_rows)

        tmp = self._artifact_dir / "runs.tmp.ipc"
        write_simple_ipc(all_rows, RUNS_SCHEMA, tmp)
        self._manager.commit_patch({"runs": tmp}, run_uuid)
        self._run_rows = []
        self._reader.invalidate("runs")

    def _flush_file_tracking(self, run_uuid: str) -> None:
        existing_table = read_ipc_table(self._active_or_empty("file_tracking"))
        existing_rows = existing_table.to_pylist() if existing_table.num_rows > 0 else []
        merged: dict[str, dict] = {r["file_path"]: r for r in existing_rows}

        # Apply explicit tracking rows first
        for r in self._file_tracking_rows:
            merged[r["file_path"]] = r

        # Auto-seed minimal entries for any file_id assigned but not yet tracked
        now = datetime.now(timezone.utc).isoformat()
        for file_path, file_id in self._file_id_cache.items():
            if file_path not in merged:
                merged[file_path] = {
                    "file_id": file_id,
                    "file_path": file_path,
                    "content_hash": "",
                    "mtime_ns": None,
                    "inode": None,
                    "size": 0,
                    "is_indexed": True,
                    "last_run_uuid": run_uuid,
                    "updated_at": now,
                    "encoding": None,
                }

        if not merged:
            return

        all_rows = list(merged.values())
        tmp = self._artifact_dir / "file_tracking.tmp.ipc"
        write_simple_ipc(all_rows, FILE_TRACKING_SCHEMA, tmp)
        self._manager.commit_patch({"file_tracking": tmp}, run_uuid)
        self._file_tracking_rows = []
        self._reader.invalidate("file_tracking")

    def _flush_changelog(self, run_uuid: str) -> None:
        if not self._changelog_rows:
            return
        existing_table = read_ipc_table(self._active_or_empty("file_changelog"))
        all_rows = (existing_table.to_pylist() if existing_table.num_rows > 0 else []) + self._changelog_rows
        tmp = self._artifact_dir / "file_changelog.tmp.ipc"
        write_simple_ipc(all_rows, FILE_CHANGELOG_SCHEMA, tmp)
        self._manager.commit_patch({"file_changelog": tmp}, run_uuid)
        self._changelog_rows = []
        self._reader.invalidate("file_changelog")

    def _flush_run_artifacts(self, run_uuid: str) -> None:
        if not self._run_artifact_rows:
            return
        existing_table = read_ipc_table(self._active_or_empty("run_artifacts"))
        if existing_table.num_rows > 0:
            existing_rows = existing_table.to_pylist()
            merged = {r["run_uuid"]: r for r in existing_rows}
            for r in self._run_artifact_rows:
                merged[r["run_uuid"]] = r
            all_rows = list(merged.values())
        else:
            all_rows = list(self._run_artifact_rows)
        tmp = self._artifact_dir / "run_artifacts.tmp.ipc"
        write_simple_ipc(all_rows, RUN_ARTIFACTS_SCHEMA, tmp)
        self._manager.commit_patch({"run_artifacts": tmp}, run_uuid)
        self._run_artifact_rows = []
        self._reader.invalidate("run_artifacts")

    # ------------------------------------------------------------------
    # Index Runs
    # ------------------------------------------------------------------

    def create_run(
        self,
        run_uuid: str,
        *,
        schema_version: str = "",
        root_path: str = "",
        git_commit: str | None = None,
        git_branch: str | None = None,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "run_uuid": run_uuid,
            "schema_version": schema_version or BUNDLE_SCHEMA_VERSION,
            "started_at": now,
            "completed_at": None,
            "status": "running",
            "git_commit": git_commit,
            "git_branch": git_branch,
            "root_path": root_path or str(self._repo_root),
            "entity_count": 0,
            "rel_count": 0,
            "file_count": 0,
            "duration_ms": None,
            "error_message": None,
        }
        with self._lock:
            self._run_rows.append(row)
            internal_id = len(self._run_rows)
            self._current_run_internal_id = internal_id

        self._writer = BathoBundleWriter(self._artifact_dir, internal_id)
        return internal_id

    def get_run_internal_id(self, run_uuid: str) -> int | None:
        return self._reader.get_run_internal_id(run_uuid)

    def complete_run(
        self,
        run_uuid: str,
        *,
        entity_count: int = 0,
        rel_count: int = 0,
        file_count: int = 0,
        duration_ms: int | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            for row in self._run_rows:
                if row["run_uuid"] == run_uuid:
                    row["status"] = "completed"
                    row["completed_at"] = now
                    row["entity_count"] = entity_count
                    row["rel_count"] = rel_count
                    row["file_count"] = file_count
                    row["duration_ms"] = duration_ms
                    break

            streams: dict[str, Path] = {}
            if self._writer is not None:
                streams = self._writer.finalize()
                self._writer = None

            self._flush_file_tracking(run_uuid)
            if streams:
                for name, path in streams.items():
                    p = path
                    streams[name] = p
                self._manager.commit_patch(streams, run_uuid)
                for name in streams:
                    self._reader.invalidate(name)

            self._flush_runs(run_uuid)
            self._flush_changelog(run_uuid)
            self._flush_run_artifacts(run_uuid)

    def fail_run(self, run_uuid: str, *, error_message: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            for row in self._run_rows:
                if row["run_uuid"] == run_uuid:
                    row["status"] = "failed"
                    row["completed_at"] = now
                    row["error_message"] = error_message
                    break
            self._flush_runs(run_uuid)

    def get_latest_run_id(self) -> str | None:
        return self._reader.get_latest_run_id()

    def get_run(self, run_uuid: str) -> dict[str, Any] | None:
        return self._reader.get_run(run_uuid)

    def delete_run(self, run_uuid: str) -> None:
        table = read_ipc_table(self._active_or_empty("runs"))
        if table.num_rows == 0:
            return
        import pyarrow.compute as pc
        mask = pc.invert(pc.equal(table.column("run_uuid"), run_uuid))
        filtered = table.filter(mask)
        tmp = self._artifact_dir / "runs.tmp.ipc"
        with ipc.new_file(str(tmp), RUNS_SCHEMA) as w:
            for batch in filtered.to_batches():
                w.write_batch(batch)
        self._manager.commit_patch({"runs": tmp}, run_uuid)
        self._reader.invalidate("runs")

    def get_entity_count(self, run_uuid: str) -> int:
        run = self.get_run(run_uuid)
        return run["entity_count"] if run else 0

    def get_relationship_count(self, run_uuid: str) -> int:
        run = self.get_run(run_uuid)
        return run["rel_count"] if run else 0

    # ------------------------------------------------------------------
    # File Artifacts
    # ------------------------------------------------------------------

    def insert_file_artifacts_batch(
        self,
        run_internal_id: int,
        batch_items: list[dict[str, Any]],
        store: Any = None,
        delta_store: Any = None,
        entity_ids_global: set[str] | None = None,
    ) -> None:
        if not batch_items:
            return

        if entity_ids_global is not None:
            entity_ids_in_batch: set[str] = entity_ids_global
        else:
            entity_ids_in_batch = set()
            for item in batch_items:
                avd = item.get("agent_view_data") or {}
                for e in avd.get("entities", []):
                    eid = e.get("id")
                    if eid:
                        entity_ids_in_batch.add(eid)

        if self._writer is None:
            self._writer = BathoBundleWriter(self._artifact_dir, run_internal_id)

        for item in batch_items:
            file_path = item["file_path"]
            content_hash = item.get("content_hash", "")
            agent_view = item.get("agent_view_data") or {}
            storage_view = item.get("storage_delta_data") or {}
            rels = item.get("relationships_data") or []
            file_id = self._get_or_create_file_id(file_path)

            self._writer.write_file_artifact(
                file_id=file_id,
                agent=agent_view,
                storage=storage_view,
                rels=rels,
                content_hash=content_hash,
            )

            if store is not None:
                _accumulate_scratch_rows(
                    store=store,
                    run_internal_id=run_internal_id,
                    file_path=file_path,
                    agent_view_data=agent_view,
                    relationships_data=rels,
                    entity_ids_in_batch=entity_ids_in_batch,
                    delta_store=delta_store,
                )

    def get_file_artifacts(
        self,
        run_internal_id: int,
        include_storage: bool = False,
        include_relationships: bool = True,
    ) -> list[dict[str, Any]]:
        """Retrieve all file artifacts for a run as expanded dicts."""
        tracking_table = read_ipc_table(self._active_or_empty("file_tracking"))
        if tracking_table.num_rows == 0:
            return []

        tracking_rows = tracking_table.to_pylist()

        results = []
        for tr in tracking_rows:
            file_id = tr["file_id"]
            file_path = tr["file_path"]
            content_hash = tr.get("content_hash", "")

            agent_rows = self._reader._slice_for_file("agent_views", file_id)
            rels_rows: list[dict] = []
            if include_relationships:
                rels_rows = self._reader._slice_for_file("rels_views", file_id)

            entities: list[dict] = []
            for row in agent_rows:
                ent: dict[str, Any] = {
                    "id": row.get("entity_id"),
                    "name": row.get("name"),
                    "type": row.get("entity_type"),
                    "entity_type": row.get("entity_type"),
                    "start_line": row.get("start_line"),
                    "end_line": row.get("end_line"),
                    "signature": row.get("signature"),
                    "content_hash": row.get("content_hash"),
                    "is_exported": row.get("is_exported", False),
                    "fqn": row.get("fqn"),
                }
                if include_storage:
                    storage_rows = self._reader._slice_for_file("storage_views", file_id)
                    storage_by_id = {r.get("entity_id"): r for r in storage_rows}
                    sr = storage_by_id.get(ent["id"])
                    if sr:
                        ent["raw_content"] = sr.get("raw_content")
                        ent["raw_bytes"] = sr.get("raw_bytes")
                        ent["leading_whitespace"] = sr.get("leading_ws")
                        ent["trailing_whitespace"] = sr.get("trailing_ws")
                        ent["ast_node_type"] = sr.get("ast_node_type")
                        ent["parent_id"] = sr.get("parent_id")
                        ent["start_byte"] = sr.get("start_byte")
                        ent["end_byte"] = sr.get("end_byte")
                        ent["syntax_glue"] = {
                            "leading_whitespace": sr.get("leading_ws") or "",
                            "trailing_whitespace": sr.get("trailing_ws") or "",
                        }
                entities.append(ent)

            rels_expanded: list[dict] = []
            for rr in rels_rows:
                rel: dict[str, Any] = {
                    "source_id": rr.get("source_id"),
                    "target_id": rr.get("target_id"),
                    "type": rr.get("relation_type"),
                    "relationship_type": rr.get("relation_type"),
                }
                meta_json = rr.get("metadata_json")
                if meta_json:
                    try:
                        import json as _json
                        rel["metadata"] = _json.loads(meta_json)
                    except Exception:
                        pass
                rels_expanded.append(rel)

            results.append({
                "file_path": file_path,
                "content_hash": content_hash,
                "graph": {
                    "entities": entities,
                    "relationships": rels_expanded,
                },
            })

        return results

    def get_agent_entities_for_file(
        self,
        run_internal_id: int,
        file_path: str,
    ) -> list[dict[str, Any]]:
        file_id = self._file_id_cache.get(file_path)
        if file_id is None:
            file_id = self._reader.file_id_for_path(file_path)
        if file_id is None:
            return []

        agent_rows = self._reader._slice_for_file("agent_views", file_id)
        return [
            {
                "id": r.get("entity_id"),
                "name": r.get("name"),
                "type": r.get("entity_type"),
                "entity_type": r.get("entity_type"),
                "start_line": r.get("start_line"),
                "end_line": r.get("end_line"),
                "signature": r.get("signature"),
                "is_exported": r.get("is_exported", False),
                "fqn": r.get("fqn"),
            }
            for r in agent_rows
        ]

    # ------------------------------------------------------------------
    # File Tracking
    # ------------------------------------------------------------------

    def upsert_file_tracking(self, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            for r in records:
                file_path = r["file_path"]
                file_id = self._get_or_create_file_id(file_path)
                mtime_ns = r.get("mtime_ns")
                if mtime_ns is None:
                    mtime = r.get("mtime")
                    if mtime is not None:
                        try:
                            mtime_ns = int(float(mtime) * 1e9)
                        except (TypeError, ValueError):
                            mtime_ns = None
                self._file_tracking_rows.append({
                    "file_id": file_id,
                    "file_path": file_path,
                    "content_hash": r.get("content_hash", ""),
                    "mtime_ns": mtime_ns,
                    "inode": r.get("inode"),
                    "size": int(r.get("size", 0)),
                    "is_indexed": bool(r.get("is_indexed", False)),
                    "last_run_uuid": r.get("last_run_id"),
                    "updated_at": now,
                    "encoding": r.get("encoding", "utf-8"),
                })
        return len(records)

    def get_file_tracking(self, file_path: str) -> dict[str, Any] | None:
        return self._reader.get_file_tracking(file_path)

    def get_all_file_tracking(self) -> dict[str, dict[str, Any]]:
        return self._reader.get_all_file_tracking()

    def get_all_file_hashes(self) -> dict[str, str]:
        return self._reader.get_all_file_hashes()

    def get_unindexed_files_with_details(self) -> list[dict[str, Any]]:
        return self._reader.get_unindexed_files_with_details()

    def delete_file_tracking(self, file_path: str) -> None:
        table = read_ipc_table(self._active_or_empty("file_tracking"))
        if table.num_rows == 0:
            return
        import pyarrow.compute as pc
        mask = pc.invert(pc.equal(table.column("file_path"), file_path))
        filtered = table.filter(mask)
        tmp = self._artifact_dir / "file_tracking.tmp.ipc"
        with ipc.new_file(str(tmp), FILE_TRACKING_SCHEMA) as w:
            for batch in filtered.to_batches():
                w.write_batch(batch)
        self._manager.commit_patch({"file_tracking": tmp}, "delete_tracking")
        self._file_id_cache.pop(file_path, None)
        self._reader.invalidate("file_tracking")

    def delete_file_tracking_batch(self, file_paths: list[str]) -> int:
        if not file_paths:
            return 0
        path_set = set(file_paths)
        table = read_ipc_table(self._active_or_empty("file_tracking"))
        if table.num_rows == 0:
            return 0
        import pyarrow.compute as pc
        existing = table.column("file_path").to_pylist()
        mask = pa.array([p not in path_set for p in existing])
        filtered = table.filter(mask)
        removed = table.num_rows - filtered.num_rows
        tmp = self._artifact_dir / "file_tracking.tmp.ipc"
        with ipc.new_file(str(tmp), FILE_TRACKING_SCHEMA) as w:
            for batch in filtered.to_batches():
                w.write_batch(batch)
        self._manager.commit_patch({"file_tracking": tmp}, "delete_tracking_batch")
        for fp in file_paths:
            self._file_id_cache.pop(fp, None)
        self._reader.invalidate("file_tracking")
        return removed

    # ------------------------------------------------------------------
    # File Changelog
    # ------------------------------------------------------------------

    def record_file_changelog(
        self,
        run_id: int,
        base_run_id: int,
        diffs: list[Any],
    ) -> None:
        if not diffs:
            return
        run_uuid = ""
        base_run_uuid = ""
        for row in self._run_rows:
            if row.get("run_uuid"):
                run_uuid = row["run_uuid"]
            if base_run_id and row.get("run_uuid"):
                base_run_uuid = row["run_uuid"]

        now = datetime.now(timezone.utc).isoformat()
        def _gv(obj: Any, key: str, default: Any = "") -> Any:
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        def _normalize_changed_fields(val: Any) -> list[str]:
            if val is None:
                return []
            if isinstance(val, list):
                return [str(v) for v in val]
            if isinstance(val, dict):
                return list(val.keys())
            return []

        with self._lock:
            for d in diffs:
                file_path = _gv(d, "file_path", "") or ""
                file_id = self._get_or_create_file_id(file_path)
                self._changelog_rows.append({
                    "run_uuid": run_uuid or str(run_id),
                    "base_run_uuid": base_run_uuid or str(base_run_id) or None,
                    "file_id": file_id,
                    "entity_id": _gv(d, "entity_id", ""),
                    "entity_name": _gv(d, "entity_name", ""),
                    "entity_type": _gv(d, "entity_type", ""),
                    "change_kind": _gv(d, "change_kind", ""),
                    "changed_fields": _normalize_changed_fields(_gv(d, "changed_fields", [])),
                    "old_hash": _gv(d, "old_hash", None),
                    "new_hash": _gv(d, "new_hash", None),
                })

    def get_file_node_history(
        self,
        entity_id: str,
        *,
        limit: int = 50,
        since_completed_at: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._reader.get_file_node_history(entity_id)[:limit]

    def get_run_file_changelog(self, run_uuid: str) -> list[dict[str, Any]]:
        return self._reader.get_file_changelog_raw(since_run_uuid=run_uuid)

    def get_file_changelog_raw(
        self,
        rel_path: str,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._reader.get_file_changelog_raw(rel_path=rel_path, since_run_uuid=since)

    def prune_file_changelog(self, max_runs: int) -> None:
        self.garbage_collect()

    # ------------------------------------------------------------------
    # Run Artifacts
    # ------------------------------------------------------------------

    def finalize_run_artifacts(
        self,
        run_internal_id: int,
        artifacts: dict[str, Any],
        blob_config: dict | None = None,
    ) -> None:
        import json as _json

        def _to_json(key: str, val: Any) -> str | None:
            if blob_config is not None:
                cfg = blob_config.get("run_artifacts", {})
                if not cfg.get(key, True):
                    return None
            if val is None:
                return None
            try:
                return _json.dumps(val, ensure_ascii=True, default=str)
            except Exception:
                return None

        run_uuid = ""
        for row in self._run_rows:
            if row.get("run_uuid"):
                run_uuid = row["run_uuid"]
        if not run_uuid:
            run_uuid = self._reader.get_latest_run_id() or str(run_internal_id)

        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._run_artifact_rows.append({
                "run_uuid": run_uuid,
                "context_overview_json": _to_json("context_overview", artifacts.get("context_overview")),
                "telemetry_json": _to_json("telemetry_metrics", artifacts.get("telemetry_metrics")),
                "structural_json": _to_json("structural_metrics", artifacts.get("structural_metrics")),
                "security_audit_json": _to_json("security_audit", artifacts.get("security_audit")),
                "artifact_payload_json": _to_json("artifact_payload", artifacts.get("artifact_payload")),
                "delta_stats_json": _to_json("delta_stats", artifacts.get("delta_stats")),
                "created_at": now,
            })
            self._flush_run_artifacts(run_uuid)

    def get_run_artifacts(self, run_internal_id: int) -> dict[str, Any] | None:
        run_uuid = self._reader.get_latest_run_id()
        if run_uuid is None:
            return None

        import json as _json

        def _from_json(s: str | None) -> dict | None:
            if not s:
                return None
            try:
                return _json.loads(s)
            except Exception:
                return None

        row = self._reader.get_run_artifacts(run_uuid)
        if not row:
            return None
        return {
            "run_id": run_internal_id,
            "context_overview": _from_json(row.get("context_overview_json")),
            "telemetry_metrics": _from_json(row.get("telemetry_json")),
            "structural_metrics": _from_json(row.get("structural_json")),
            "security_audit": _from_json(row.get("security_audit_json")),
            "artifact_payload": _from_json(row.get("artifact_payload_json")),
            "delta_stats": _from_json(row.get("delta_stats_json")),
            "created_at": row.get("created_at"),
        }

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_entities(
        self,
        run_uuid: str,
        query: str,
        *,
        kinds: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        import pyarrow.compute as pc

        table = read_ipc_table(self._active_or_empty("agent_views"))
        if table.num_rows == 0:
            return []

        if "." in query:
            mask = pc.equal(table.column("fqn"), query)
        else:
            exact = pc.equal(table.column("name"), query)
            prefix = pc.starts_with(table.column("name"), query)
            mask = pc.or_(exact, prefix)

        if kinds:
            type_masks = [pc.equal(table.column("entity_type"), k) for k in kinds]
            kind_mask = type_masks[0]
            for m in type_masks[1:]:
                kind_mask = pc.or_(kind_mask, m)
            mask = pc.and_(mask, kind_mask)

        result_table = table.filter(mask).slice(0, limit)
        return result_table.to_pylist()

    # ------------------------------------------------------------------
    # GC / maintenance
    # ------------------------------------------------------------------

    def garbage_collect(self) -> int:
        return self._manager.garbage_collect()

    def vacuum(self) -> None:
        self.garbage_collect()

    def get_stats(self) -> dict[str, Any]:
        manifest = self._manager.load_manifest()
        active = self._manager.all_active_paths()
        stats: dict[str, Any] = {
            "schema_version": manifest.get("schema_version"),
            "generation": manifest.get("generation", 0),
            "last_run_uuid": manifest.get("last_run_uuid"),
            "tables": {},
        }
        for name, path in active.items():
            try:
                size = path.stat().st_size
                table = read_ipc_table(path)
                stats["tables"][name] = {"size_bytes": size, "rows": table.num_rows}
            except Exception:
                stats["tables"][name] = {"size_bytes": 0, "rows": 0}
        return stats

    # ------------------------------------------------------------------
    # Export / Load helpers
    # ------------------------------------------------------------------

    def export_artifact(self, output_zip_path: Path) -> None:
        self._manager.export_artifact(output_zip_path)

    @property
    def artifact_dir(self) -> Path:
        return self._artifact_dir

    @property
    def repo_root(self) -> Path:
        return self._repo_root

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        with _BUNDLE_CACHE_LOCK:
            self._closed = True
            key = str(self._repo_root)
            _BUNDLE_CACHE.pop(key, None)

    def __repr__(self) -> str:
        return f"BathoBundle(root={self._repo_root!s})"
