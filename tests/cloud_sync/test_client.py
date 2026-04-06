from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from batho.cloud_sync.client import SyncClient
from batho.cloud_sync.config import CloudSyncConfig


class _FakeResponse:
    def __init__(self, status: int, payload: dict[str, object] | None = None):
        self.status = status
        self._payload = json.dumps(payload or {}).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False


def _client_config() -> CloudSyncConfig:
    return CloudSyncConfig(
        enabled=True,
        endpoint="https://sync.example/v1",
        api_key="test_key",
        organization_id="org_1",
        project_id="proj_1",
        timeout_seconds=5,
        max_retries=2,
    )


def test_upload_artifact_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "graph.json"
    path.write_text('{"ok": true}', encoding="utf-8")

    def _urlopen(_request, timeout):
        _ = timeout
        return _FakeResponse(
            200,
            {
                "artifact_id": "a1",
                "cloud_content_id": "s3://bucket/key",
                "synced_at": "2026-04-06T12:00:00Z",
            },
        )

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)

    client = SyncClient(_client_config())
    result = client.upload_artifact(path, {"artifact_id": "a1"})

    assert result.success is True
    assert result.status_code == 200
    assert result.cloud_content_id == "s3://bucket/key"
    assert result.retry_count == 0


def test_upload_artifact_retries_on_503_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "graph.json"
    path.write_text('{"ok": true}', encoding="utf-8")

    calls = {"count": 0}

    def _urlopen(request, timeout):
        _ = timeout
        calls["count"] += 1
        if calls["count"] < 3:
            raise urllib.error.HTTPError(
                request.full_url,
                503,
                "Service Unavailable",
                hdrs=None,
                fp=io.BytesIO(b'{"error":"storage_unavailable"}'),
            )
        return _FakeResponse(200, {"artifact_id": "a2", "cloud_content_id": "s3://ok"})

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    client = SyncClient(_client_config())
    result = client.upload_artifact(path, {"artifact_id": "a2"})

    assert result.success is True
    assert calls["count"] == 3
    assert result.retry_count == 2


def test_upload_artifact_does_not_retry_non_retriable_http(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "graph.json"
    path.write_text('{"ok": true}', encoding="utf-8")

    calls = {"count": 0}

    def _urlopen(request, timeout):
        _ = timeout
        calls["count"] += 1
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"invalid_api_key"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)

    client = SyncClient(_client_config())
    result = client.upload_artifact(path, {"artifact_id": "a3"})

    assert result.success is False
    assert result.status_code == 401
    assert result.error == "invalid_api_key"
    assert calls["count"] == 1


def test_check_health_false_on_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _urlopen(_request, timeout):
        _ = timeout
        raise urllib.error.URLError("down")

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)

    client = SyncClient(_client_config())
    assert client.check_health() is False


def test_get_presigned_url_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def _urlopen(_request, timeout):
        _ = timeout
        return _FakeResponse(200, {"url": "https://storage.example/signed"})

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)

    client = SyncClient(_client_config())
    assert client.get_presigned_url("artifact-1") == "https://storage.example/signed"
