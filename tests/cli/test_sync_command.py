from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

import batho_cli as batho
from batho.context.storage import register_artifact
from batho_cli import cmd_sync


def _base_args(root: Path, **overrides):
    payload = {
        "root": str(root),
        "dry_run": False,
        "artifact_types": None,
        "status": False,
        "retry_failed": False,
        "verbose": False,
    }
    payload.update(overrides)
    return argparse.Namespace(**payload)


def test_cmd_sync_status_mode_outputs_counts(tmp_path: Path, capsys) -> None:
    root = tmp_path / "repo"
    ctn_dir = root / ".ctn"
    ctn_dir.mkdir(parents=True)

    metrics_dir = ctn_dir / "local" / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    artifact = metrics_dir / "metrics.json"
    artifact.write_text('{"ok": true}', encoding="utf-8")
    assert register_artifact(ctn_dir, artifact, "metrics_json", schema_version="metrics.v1")

    result = cmd_sync(_base_args(root, status=True))
    assert result == 0

    output = capsys.readouterr().out
    assert "Sync Status" in output
    assert "Pending" in output


def test_cmd_sync_requires_enabled_for_upload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    root = tmp_path / "repo"
    root.mkdir(parents=True)

    monkeypatch.setattr(
        batho,
        "reload_config",
        lambda: {
            "cloud_sync": {
                "enabled": False,
                "endpoint": "",
                "api_key": "",
                "organization_id": "",
                "project_id": "",
                "timeout_seconds": 300,
                "max_retries": 3,
                "batch_size": 10,
            }
        },
    )

    result = cmd_sync(_base_args(root, dry_run=False))
    assert result == 1
    assert "Cloud sync is disabled" in capsys.readouterr().err


def test_cmd_sync_dry_run_uses_uploader_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    root = tmp_path / "repo"
    root.mkdir(parents=True)

    monkeypatch.setattr(
        batho,
        "reload_config",
        lambda: {
            "cloud_sync": {
                "enabled": True,
                "endpoint": "https://sync.example/v1",
                "api_key": "abc",
                "organization_id": "",
                "project_id": "",
                "timeout_seconds": 300,
                "max_retries": 3,
                "batch_size": 10,
            }
        },
    )

    class _FakeUploader:
        def __init__(self, _cfg):
            pass

        @staticmethod
        def get_sync_status(_ctn_dir):
            return {
                "project_id": "repo",
                "pending": 0,
                "synced": 0,
                "failed": 0,
                "local_only": 0,
                "total": 0,
            }

        @staticmethod
        def sync_pending_artifacts(_ctn_dir, dry_run=False, artifact_types=None, progress_callback=None):
            _ = dry_run, artifact_types, progress_callback
            return SimpleNamespace(
                total=2,
                uploaded=0,
                failed=0,
                duration_seconds=0.0,
                by_type={"graph_json": {"count": 2, "size_bytes": 4096}},
                failures=[],
            )

        @staticmethod
        def retry_failed(_ctn_dir, dry_run=False, progress_callback=None):
            _ = dry_run, progress_callback
            return SimpleNamespace(
                total=0,
                uploaded=0,
                failed=0,
                duration_seconds=0.0,
                by_type={},
                failures=[],
            )

    monkeypatch.setattr("batho.cloud_sync.uploader.CloudSyncUploader", _FakeUploader)

    result = cmd_sync(_base_args(root, dry_run=True, artifact_types=["graph_json"]))
    assert result == 0
    out = capsys.readouterr().out
    assert "Found 2 artifacts to sync" in out
    assert "graph_json" in out


def test_cmd_sync_returns_nonzero_when_uploads_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir(parents=True)

    monkeypatch.setattr(
        batho,
        "reload_config",
        lambda: {
            "cloud_sync": {
                "enabled": True,
                "endpoint": "https://sync.example/v1",
                "api_key": "abc",
                "organization_id": "",
                "project_id": "",
                "timeout_seconds": 300,
                "max_retries": 3,
                "batch_size": 10,
            }
        },
    )

    class _FakeUploader:
        def __init__(self, _cfg):
            pass

        @staticmethod
        def get_sync_status(_ctn_dir):
            return {
                "project_id": "repo",
                "pending": 0,
                "synced": 0,
                "failed": 0,
                "local_only": 0,
                "total": 0,
            }

        @staticmethod
        def sync_pending_artifacts(_ctn_dir, dry_run=False, artifact_types=None, progress_callback=None):
            _ = dry_run, artifact_types, progress_callback
            return SimpleNamespace(
                total=1,
                uploaded=0,
                failed=1,
                duration_seconds=0.2,
                by_type={"graph_json": {"count": 1, "size_bytes": 1024}},
                failures=[{"artifact_id": "a1", "error": "storage_unavailable"}],
            )

        @staticmethod
        def retry_failed(_ctn_dir, dry_run=False, progress_callback=None):
            _ = dry_run, progress_callback
            return SimpleNamespace(
                total=1,
                uploaded=0,
                failed=1,
                duration_seconds=0.2,
                by_type={"graph_json": {"count": 1, "size_bytes": 1024}},
                failures=[{"artifact_id": "a1", "error": "storage_unavailable"}],
            )

    monkeypatch.setattr("batho.cloud_sync.uploader.CloudSyncUploader", _FakeUploader)

    result = cmd_sync(_base_args(root))
    assert result == 1
