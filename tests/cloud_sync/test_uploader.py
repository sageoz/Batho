from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from batho.cloud_sync.client import SyncResult
from batho.cloud_sync.config import CloudSyncConfig
from batho.cloud_sync.uploader import CloudSyncUploader
from batho.context.storage import get_artifact_registry, register_artifact


class _FakeClient:
    def __init__(self, success_by_artifact_id: dict[str, bool] | None = None):
        self._success_by_artifact_id = success_by_artifact_id or {}
        self.project_ids: list[str | None] = []

    def upload_artifact(self, artifact_path, metadata, *, progress_callback=None, project_id=None):
        _ = artifact_path, progress_callback
        artifact_id = str(metadata.get("artifact_id") or "")
        self.project_ids.append(project_id)
        ok = self._success_by_artifact_id.get(artifact_id, True)
        if ok:
            return SyncResult(
                artifact_id=artifact_id,
                success=True,
                status_code=200,
                cloud_content_id=f"s3://bucket/{artifact_id}",
            )
        return SyncResult(
            artifact_id=artifact_id,
            success=False,
            status_code=503,
            error="storage_unavailable",
        )


def _register_sample_artifacts(ctn_dir: Path) -> None:
    graph_path = ctn_dir / "graph.json"
    metrics_path = ctn_dir / "metrics.json"
    graph_path.write_text('{"nodes": []}', encoding="utf-8")
    metrics_path.write_text('{"ok": true}', encoding="utf-8")

    assert register_artifact(ctn_dir, graph_path, "graph_json", schema_version="graph.v1")
    assert register_artifact(ctn_dir, metrics_path, "metrics_json", schema_version="metrics.v1")


def test_sync_pending_artifacts_dry_run(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()
    _register_sample_artifacts(ctn_dir)

    cfg = CloudSyncConfig(enabled=True, endpoint="https://sync.example/v1", api_key="key")
    uploader = CloudSyncUploader(cfg, client=_FakeClient())

    summary = uploader.sync_pending_artifacts(ctn_dir, dry_run=True)

    assert summary.total == 2
    assert summary.uploaded == 0
    assert summary.failed == 0
    assert summary.by_type["graph_json"]["count"] == 1
    assert summary.by_type["metrics_json"]["count"] == 1


def test_sync_pending_artifacts_marks_success_and_failure(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()
    _register_sample_artifacts(ctn_dir)

    registry = get_artifact_registry(ctn_dir)
    pending = registry.get_pending_artifacts()
    assert len(pending) == 2

    first_id = str(pending[0]["artifact_id"])
    second_id = str(pending[1]["artifact_id"])

    cfg = CloudSyncConfig(enabled=True, endpoint="https://sync.example/v1", api_key="key")
    fake_client = _FakeClient(success_by_artifact_id={first_id: True, second_id: False})
    uploader = CloudSyncUploader(cfg, client=fake_client)

    summary = uploader.sync_pending_artifacts(ctn_dir, dry_run=False)

    assert summary.total == 2
    assert summary.uploaded == 1
    assert summary.failed == 1

    status = uploader.get_sync_status(ctn_dir)
    assert status["synced"] == 1
    assert status["failed"] == 1

    failed_rows = registry.get_failed_artifacts(max_retries=3)
    assert len(failed_rows) == 1
    assert int(failed_rows[0]["retry_count"]) == 1


def test_retry_failed_retries_only_eligible_rows(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()
    _register_sample_artifacts(ctn_dir)

    registry = get_artifact_registry(ctn_dir)
    pending = registry.get_pending_artifacts()
    target_id = str(pending[0]["artifact_id"])
    assert registry.mark_sync_failed(target_id, "temporary", retry_count=1)

    cfg = CloudSyncConfig(
        enabled=True,
        endpoint="https://sync.example/v1",
        api_key="key",
        max_retries=3,
    )
    uploader = CloudSyncUploader(cfg, client=_FakeClient(success_by_artifact_id={target_id: True}))

    summary = uploader.retry_failed(ctn_dir)
    assert summary.total == 1
    assert summary.uploaded == 1
    assert summary.failed == 0

    status = uploader.get_sync_status(ctn_dir)
    assert status["failed"] == 0
    assert status["synced"] >= 1


def test_sync_uses_repo_name_as_project_id_fallback(tmp_path: Path) -> None:
    root = tmp_path / "sample-repo"
    ctn_dir = root / ".ctn"
    ctn_dir.mkdir(parents=True)
    _register_sample_artifacts(ctn_dir)

    registry = get_artifact_registry(ctn_dir)
    row = registry.get_pending_artifacts(limit=1)[0]
    artifact_id = str(row["artifact_id"])

    fake_client = _FakeClient(success_by_artifact_id={artifact_id: True})
    cfg = CloudSyncConfig(enabled=True, endpoint="https://sync.example/v1", api_key="key", project_id="")
    uploader = CloudSyncUploader(cfg, client=fake_client)

    summary = uploader.sync_pending_artifacts(ctn_dir)
    assert summary.uploaded >= 1
    assert fake_client.project_ids
    assert all(project_id == "sample-repo" for project_id in fake_client.project_ids)
