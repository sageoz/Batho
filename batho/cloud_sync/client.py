"""HTTP client for Batho cloud sync endpoints."""

from __future__ import annotations

import json
import mimetypes
import socket
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from batho.cloud_sync.config import CloudSyncConfig
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="cloud_sync_client")

ProgressCallback = Callable[[str, dict[str, Any]], None]


@dataclass
class SyncResult:
    artifact_id: str
    success: bool
    status_code: int | None = None
    cloud_content_id: str | None = None
    synced_at: str | None = None
    error: str | None = None
    retry_count: int = 0
    duration_seconds: float = 0.0
    response_json: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchResult:
    total: int
    uploaded: int
    failed: int
    results: list[SyncResult] = field(default_factory=list)
    duration_seconds: float = 0.0


class SyncClient:
    def __init__(self, config: CloudSyncConfig):
        self.config = config
        self.endpoint = config.endpoint.strip().rstrip("/")

    def _build_url(self, path: str) -> str:
        return f"{self.endpoint}/{path.lstrip('/')}"

    def _base_headers(self, *, project_id: str | None = None) -> dict[str, str]:
        api_key = self.config.resolved_api_key()
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if self.config.organization_id:
            headers["X-Organization-Id"] = self.config.organization_id

        resolved_project = (project_id or self.config.project_id or "").strip()
        if resolved_project:
            headers["X-Project-Id"] = resolved_project
        return headers

    def _multipart_payload(
        self,
        artifact_path: Path,
        metadata: dict[str, Any],
    ) -> tuple[bytes, str]:
        boundary = f"----batho-sync-{uuid.uuid4().hex}"
        newline = b"\r\n"
        mime_type = (
            mimetypes.guess_type(str(artifact_path))[0] or "application/octet-stream"
        )

        metadata_payload = json.dumps(metadata, ensure_ascii=True).encode("utf-8")
        file_payload = artifact_path.read_bytes()

        parts: list[bytes] = [
            f"--{boundary}".encode("ascii"),
            (
                f'Content-Disposition: form-data; name="file"; '
                f'filename="{artifact_path.name}"'
            ).encode("utf-8"),
            f"Content-Type: {mime_type}".encode("ascii"),
            b"",
            file_payload,
            f"--{boundary}".encode("ascii"),
            b'Content-Disposition: form-data; name="metadata"',
            b"Content-Type: application/json",
            b"",
            metadata_payload,
            f"--{boundary}--".encode("ascii"),
            b"",
        ]
        return newline.join(parts), boundary

    @staticmethod
    def _parse_json(payload: bytes) -> dict[str, Any]:
        if not payload:
            return {}
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _should_retry_status(status_code: int) -> bool:
        return status_code == 429 or status_code >= 500

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        payload: bytes | None = None,
        timeout_seconds: int | None = None,
    ) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            url=url, data=payload, headers=headers, method=method
        )
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else self.config.timeout_seconds
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                return int(getattr(response, "status", 200)), self._parse_json(body)
        except urllib.error.HTTPError as exc:
            body = exc.read() if exc.fp is not None else b""
            payload_json = self._parse_json(body)
            raise RuntimeError(
                json.dumps({"status": int(exc.code), "payload": payload_json})
            ) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise ConnectionError(str(exc)) from exc

    def upload_artifact(
        self,
        artifact_path: Path | str,
        metadata: dict[str, Any],
        *,
        progress_callback: ProgressCallback | None = None,
        project_id: str | None = None,
    ) -> SyncResult:
        path = Path(artifact_path)
        artifact_id = str(metadata.get("artifact_id") or path.name)

        if not self.endpoint:
            return SyncResult(
                artifact_id=artifact_id,
                success=False,
                error="cloud sync endpoint is not configured",
            )

        if not self.config.resolved_api_key():
            return SyncResult(
                artifact_id=artifact_id,
                success=False,
                error="cloud sync api_key is not configured",
            )

        if not path.exists() or not path.is_file():
            return SyncResult(
                artifact_id=artifact_id,
                success=False,
                error=f"artifact does not exist: {path}",
            )

        start = time.perf_counter()
        retries = max(0, int(self.config.max_retries))
        upload_url = self._build_url("artifacts/upload")

        for attempt in range(retries + 1):
            body, boundary = self._multipart_payload(path, metadata)
            headers = self._base_headers(project_id=project_id)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

            try:
                status_code, response_json = self._request(
                    "POST",
                    upload_url,
                    headers=headers,
                    payload=body,
                    timeout_seconds=self.config.timeout_seconds,
                )
            except ConnectionError as exc:
                if attempt < retries:
                    delay = min(30.0, float(2**attempt))
                    if progress_callback:
                        progress_callback(
                            "retry",
                            {
                                "artifact_id": artifact_id,
                                "attempt": attempt + 1,
                                "delay_seconds": delay,
                                "error": str(exc),
                            },
                        )
                    time.sleep(delay)
                    continue
                duration = time.perf_counter() - start
                return SyncResult(
                    artifact_id=artifact_id,
                    success=False,
                    error=str(exc),
                    retry_count=attempt,
                    duration_seconds=duration,
                )
            except RuntimeError as exc:
                details: dict[str, Any]
                try:
                    details = json.loads(str(exc))
                except json.JSONDecodeError:
                    details = {"status": None, "payload": {}, "error": str(exc)}
                status_code = details.get("status")
                payload = (
                    details.get("payload")
                    if isinstance(details.get("payload"), dict)
                    else {}
                )
                retriable = (
                    self._should_retry_status(int(status_code))
                    if isinstance(status_code, int)
                    else False
                )
                if retriable and attempt < retries:
                    delay = min(30.0, float(2**attempt))
                    if progress_callback:
                        progress_callback(
                            "retry",
                            {
                                "artifact_id": artifact_id,
                                "attempt": attempt + 1,
                                "delay_seconds": delay,
                                "status_code": status_code,
                                "error": payload.get("error") or "http_error",
                            },
                        )
                    time.sleep(delay)
                    continue

                duration = time.perf_counter() - start
                return SyncResult(
                    artifact_id=artifact_id,
                    success=False,
                    status_code=(
                        int(status_code) if isinstance(status_code, int) else None
                    ),
                    error=str(payload.get("error") or "upload_failed"),
                    retry_count=attempt,
                    duration_seconds=duration,
                    response_json=payload,
                )

            duration = time.perf_counter() - start
            cloud_content_id = str(response_json.get("cloud_content_id") or "") or None
            synced_at = str(response_json.get("synced_at") or "") or None
            result = SyncResult(
                artifact_id=artifact_id,
                success=200 <= status_code < 300,
                status_code=status_code,
                cloud_content_id=cloud_content_id,
                synced_at=synced_at,
                retry_count=attempt,
                duration_seconds=duration,
                response_json=response_json,
            )
            if progress_callback:
                progress_callback(
                    "uploaded",
                    {
                        "artifact_id": artifact_id,
                        "status_code": status_code,
                        "duration_seconds": duration,
                    },
                )
            return result

        duration = time.perf_counter() - start
        return SyncResult(
            artifact_id=artifact_id,
            success=False,
            error="upload retries exhausted",
            retry_count=retries,
            duration_seconds=duration,
        )

    def upload_batch(
        self,
        artifacts: list[dict[str, Any]],
        *,
        progress_callback: ProgressCallback | None = None,
        project_id: str | None = None,
    ) -> BatchResult:
        batch_start = time.perf_counter()
        results: list[SyncResult] = []

        for item in artifacts:
            artifact_path = Path(str(item.get("artifact_path") or ""))
            metadata = item.get("metadata")
            metadata_dict = metadata if isinstance(metadata, dict) else {}
            result = self.upload_artifact(
                artifact_path,
                metadata_dict,
                progress_callback=progress_callback,
                project_id=project_id,
            )
            results.append(result)

        uploaded = sum(1 for row in results if row.success)
        failed = len(results) - uploaded
        return BatchResult(
            total=len(results),
            uploaded=uploaded,
            failed=failed,
            results=results,
            duration_seconds=time.perf_counter() - batch_start,
        )

    def check_health(self) -> bool:
        if not self.endpoint:
            return False

        url = self._build_url("health")
        headers = self._base_headers()
        try:
            status_code, _ = self._request("GET", url, headers=headers)
        except (RuntimeError, ConnectionError):
            return False
        return 200 <= status_code < 300

    def get_presigned_url(self, artifact_id: str) -> str | None:
        if not self.endpoint or not artifact_id:
            return None

        encoded_id = quote(artifact_id, safe="")
        url = self._build_url(f"artifacts/{encoded_id}/presigned-url")
        headers = self._base_headers()
        try:
            status_code, payload = self._request("GET", url, headers=headers)
        except (RuntimeError, ConnectionError):
            return None

        if not (200 <= status_code < 300):
            return None

        value = payload.get("url") or payload.get("presigned_url")
        if not isinstance(value, str):
            return None
        return value or None
