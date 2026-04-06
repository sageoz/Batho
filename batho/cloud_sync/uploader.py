"""High-level cloud sync orchestration for registry artifacts."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from batho.cloud_sync.client import SyncClient
from batho.cloud_sync.config import CloudSyncConfig
from batho.config import get_config_cached
from batho.context.storage import get_artifact_registry
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="cloud_sync_uploader")

ProgressCallback = Callable[[int, int, dict[str, Any]], None]


@dataclass
class SyncSummary:
    total: int = 0
    uploaded: int = 0
    failed: int = 0
    dry_run: bool = False
    duration_seconds: float = 0.0
    by_type: dict[str, dict[str, int]] = field(default_factory=dict)
    failures: list[dict[str, Any]] = field(default_factory=list)


class CloudSyncUploader:
    def __init__(
        self,
        config: CloudSyncConfig | dict[str, Any] | None = None,
        *,
        client: SyncClient | None = None,
    ):
        if config is None:
            cfg = get_config_cached().get("cloud_sync", {})
            config = cfg if isinstance(cfg, dict) else {}

        if isinstance(config, CloudSyncConfig):
            self.config = config
        else:
            self.config = CloudSyncConfig.model_validate(config)

        self.client = client or SyncClient(self.config)

    @staticmethod
    def _summarize_types(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
        summary: dict[str, dict[str, int]] = {}
        for row in rows:
            artifact_type = str(row.get("artifact_type") or "unknown")
            size_bytes = int(row.get("size_bytes") or 0)
            bucket = summary.setdefault(artifact_type, {"count": 0, "size_bytes": 0})
            bucket["count"] += 1
            bucket["size_bytes"] += max(0, size_bytes)
        return summary

    @staticmethod
    def _metadata_payload(row: dict[str, Any]) -> dict[str, Any]:
        metadata_json = row.get("metadata")
        metadata = metadata_json if isinstance(metadata_json, dict) else {}

        payload = {
            "artifact_id": str(row.get("artifact_id") or ""),
            "artifact_type": str(row.get("artifact_type") or "artifact_file"),
            "schema_version": str(row.get("schema_version") or ""),
            "logical_path": str(row.get("logical_path") or ""),
            "checksum": str(row.get("checksum") or ""),
            "size_bytes": int(row.get("size_bytes") or 0),
            "producer": str(row.get("producer") or "unknown"),
            "run_id": str(row.get("run_id") or ""),
            "retention_class": str(row.get("retention_class") or "default"),
            "metadata_json": metadata,
        }
        return payload

    def _project_id(self, ctn_dir: Path) -> str:
        configured = str(self.config.project_id or "").strip()
        if configured:
            return configured
        return ctn_dir.parent.name

    def _sync_rows(
        self,
        ctn_dir: Path,
        rows: list[dict[str, Any]],
        *,
        dry_run: bool,
        progress_callback: ProgressCallback | None,
    ) -> SyncSummary:
        summary = SyncSummary(
            total=len(rows),
            dry_run=dry_run,
            by_type=self._summarize_types(rows),
        )
        if dry_run or not rows:
            return summary

        registry = get_artifact_registry(ctn_dir)
        project_id = self._project_id(ctn_dir)
        start = time.perf_counter()

        for index, row in enumerate(rows, start=1):
            artifact_id = str(row.get("artifact_id") or "")
            artifact_path = Path(str(row.get("physical_path") or ""))
            retry_count = int(row.get("retry_count") or 0)

            if progress_callback:
                progress_callback(index, len(rows), {"artifact_id": artifact_id})

            if not artifact_path.exists():
                error_msg = f"artifact file missing: {artifact_path}"
                registry.mark_sync_failed(
                    artifact_id,
                    error=error_msg,
                    retry_count=retry_count + 1,
                )
                summary.failed += 1
                summary.failures.append({"artifact_id": artifact_id, "error": error_msg})
                continue

            metadata = self._metadata_payload(row)
            result = self.client.upload_artifact(
                artifact_path,
                metadata,
                project_id=project_id,
            )

            if result.success:
                cloud_content_id = str(result.cloud_content_id or "").strip() or artifact_id
                registry.mark_synced(artifact_id, cloud_content_id=cloud_content_id)
                summary.uploaded += 1
            else:
                message = str(result.error or "upload_failed")
                registry.mark_sync_failed(
                    artifact_id,
                    error=message,
                    retry_count=retry_count + 1,
                )
                summary.failed += 1
                summary.failures.append({"artifact_id": artifact_id, "error": message})

        summary.duration_seconds = time.perf_counter() - start
        return summary

    def sync_pending_artifacts(
        self,
        ctn_dir: Path,
        dry_run: bool = False,
        artifact_types: list[str] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> SyncSummary:
        registry = get_artifact_registry(ctn_dir)
        rows = registry.get_pending_artifacts(artifact_types=artifact_types)
        return self._sync_rows(
            ctn_dir,
            rows,
            dry_run=dry_run,
            progress_callback=progress_callback,
        )

    def get_sync_status(self, ctn_dir: Path) -> dict[str, Any]:
        registry = get_artifact_registry(ctn_dir)
        summary = registry.get_sync_summary()
        return {
            "project_id": self._project_id(ctn_dir),
            "pending": int(summary.get("pending", 0)),
            "synced": int(summary.get("synced", 0)),
            "failed": int(summary.get("failed", 0)),
            "conflict": int(summary.get("conflict", 0)),
            "local_only": int(summary.get("local_only", 0)),
            "total": int(summary.get("total", 0)),
        }

    def retry_failed(
        self,
        ctn_dir: Path,
        dry_run: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> SyncSummary:
        registry = get_artifact_registry(ctn_dir)
        rows = registry.get_failed_artifacts(max_retries=self.config.max_retries)
        return self._sync_rows(
            ctn_dir,
            rows,
            dry_run=dry_run,
            progress_callback=progress_callback,
        )
