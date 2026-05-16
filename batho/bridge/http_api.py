"""REST HTTP API for the Batho bridge, mountable into the dashboard server."""

from __future__ import annotations

import http.server
import json
import urllib.parse
from pathlib import Path
from typing import Any

from batho.bridge.artifact_loader import (
    ArtifactLoader,
    ArtifactNotFoundError,
    ArtifactParseError,
    ChecksumMismatchError,
)
from batho.bridge.constants import DEFAULT_BRIDGE_HTTP_PORT, KNOWN_ARTIFACT_TYPES
from batho.bridge.models import BridgeErrorResponse, BridgeResponse
from batho.bridge.registry_client import ArtifactRegistryBridge
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge")


def _json_response(data: Any, status: int = 200) -> tuple[bytes, int, dict[str, str]]:
    body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }
    return body, status, headers


def _ok(data: Any, meta: dict[str, Any] | None = None) -> tuple[bytes, int, dict[str, str]]:
    return _json_response(BridgeResponse(data=data, meta=meta or {}).model_dump(exclude_none=True))


def _err(code: str, message: str, detail: Any = None, status: int = 400) -> tuple[bytes, int, dict[str, str]]:
    payload = BridgeErrorResponse(
        error={"code": code, "message": message, "detail": detail}
    ).model_dump(exclude_none=True)
    return _json_response(payload, status=status)


class BridgeAPIHandler:
    """HTTP request handler for bridge REST endpoints.

    This is designed to be invoked from a ``DualRootHandler`` or standalone
    server.  It does *not* subclass ``BaseHTTPRequestHandler``; instead it
    exposes a ``dispatch(path, query)`` method that returns a response
    triple ``(body_bytes, status, headers)``.
    """

    def __init__(self, ctn_dir: Path) -> None:
        self.ctn_dir = ctn_dir.resolve()
        self._bridge = ArtifactRegistryBridge(self.ctn_dir)
        self._loader = ArtifactLoader(self.ctn_dir)

    def dispatch(self, path: str, query: dict[str, list[str]]) -> tuple[bytes, int, dict[str, str]]:
        """Dispatch a request to the appropriate handler."""
        # Strip leading /api/v1/bridge/
        prefix = "/api/v1/bridge/"
        if not path.startswith(prefix):
            return _err("invalid_path", f"Path must start with {prefix}", status=404)

        route = path[len(prefix):].strip("/")
        segments = [s for s in route.split("/") if s]

        if not segments:
            return _ok({"endpoints": [
                "GET /indexes",
                "GET /indexes/{index_id}",
                "GET /artifacts?type=&index_id=&limit=",
                "GET /artifacts/{artifact_type}?index_id=",
                "GET /artifacts/content?path=",
                "GET /stats",
            ]})

        if segments[0] == "indexes":
            return self._handle_indexes(segments, query)
        if segments[0] == "artifacts":
            return self._handle_artifacts(segments, query)
        if segments[0] == "stats":
            return self._handle_stats()

        return _err("unknown_endpoint", f"Unknown endpoint: {route}", status=404)

    def _handle_indexes(
        self, segments: list[str], query: dict[str, list[str]]
    ) -> tuple[bytes, int, dict[str, str]]:
        if len(segments) == 1:
            # GET /indexes
            entries = self._bridge.list_indexes()
            return _ok(
                [e.model_dump(exclude_none=True) for e in entries],
                meta={"count": len(entries)},
            )
        if len(segments) == 2:
            # GET /indexes/{index_id}
            index_id = segments[1]
            entries = self._bridge.list_indexes()
            for entry in entries:
                if entry.index_id == index_id:
                    return _ok(entry.model_dump(exclude_none=True))
            return _err("index_not_found", f"Index not found: {index_id}", status=404)
        return _err("invalid_path", "Invalid indexes path", status=404)

    def _handle_artifacts(
        self, segments: list[str], query: dict[str, list[str]]
    ) -> tuple[bytes, int, dict[str, str]]:
        if len(segments) == 1:
            # GET /artifacts?type=&index_id=&limit=
            artifact_type = _first(query.get("type"))
            limit_str = _first(query.get("limit"))
            limit = int(limit_str) if limit_str and limit_str.isdigit() else 50

            if artifact_type:
                if artifact_type not in KNOWN_ARTIFACT_TYPES:
                    return _err(
                        "unknown_artifact_type",
                        f"Unknown artifact type: {artifact_type}. Known: {sorted(KNOWN_ARTIFACT_TYPES)}",
                    )
                records = self._bridge.get_artifacts_by_type(artifact_type, limit=limit)
            else:
                # Return a summary of all types
                types = self._bridge.list_artifact_types()
                summary: dict[str, Any] = {}
                for t in types[:limit]:
                    summary[t] = len(self._bridge.get_artifacts_by_type(t, limit=1))
                return _ok(summary, meta={"types": len(types)})

            return _ok(
                [r.model_dump(exclude_none=True) for r in records],
                meta={"count": len(records), "artifact_type": artifact_type},
            )

        if len(segments) == 2:
            # GET /artifacts/{artifact_type}?index_id=
            artifact_type = segments[1]
            if artifact_type not in KNOWN_ARTIFACT_TYPES:
                return _err(
                    "unknown_artifact_type",
                    f"Unknown artifact type: {artifact_type}. Known: {sorted(KNOWN_ARTIFACT_TYPES)}",
                )

            index_id = _first(query.get("index_id"))
            try:
                data = self._loader.load_json(artifact_type, index_id=index_id)
            except ArtifactNotFoundError as exc:
                return _err("artifact_not_found", str(exc), status=404)
            except ChecksumMismatchError as exc:
                return _err("checksum_mismatch", str(exc), status=409)
            except ArtifactParseError as exc:
                return _err("parse_error", str(exc), status=500)

            return _ok(
                data,
                meta={"artifact_type": artifact_type, "index_id": index_id or "current"},
            )

        if len(segments) == 3 and segments[2] == "content":
            # GET /artifacts/{artifact_type}/content?path=
            logical_path = _first(query.get("path"))
            if not logical_path:
                return _err("missing_param", "Query parameter 'path' is required")

            record = self._bridge.get_artifact_by_logical_path(logical_path)
            if not record:
                return _err("artifact_not_found", f"No artifact at path: {logical_path}", status=404)

            try:
                content = self._loader.load_artifact(record)
            except (ArtifactNotFoundError, ChecksumMismatchError, ArtifactParseError) as exc:
                return _err(type(exc).__name__.replace("Error", "").lower(), str(exc), status=404)

            return _ok(
                content.data,
                meta={
                    "artifact_type": record.artifact_type,
                    "logical_path": record.logical_path,
                    "resolved_path": content.resolved_path,
                    "checksum_verified": content.checksum_verified,
                },
            )

        return _err("invalid_path", "Invalid artifacts path", status=404)

    def _handle_stats(self) -> tuple[bytes, int, dict[str, str]]:
        stats = self._bridge.stats()
        return _ok(stats.model_dump(exclude_none=True))


def _first(values: list[str] | None) -> str | None:
    if values:
        return values[0]
    return None


class BridgeHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    """Standalone HTTP request handler that serves bridge API endpoints."""

    ctn_dir: Path

    def __init__(self, *args, ctn_dir: Path | None = None, **kwargs):
        if ctn_dir is not None:
            self.ctn_dir = ctn_dir
        super().__init__(*args, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        handler = BridgeAPIHandler(self.ctn_dir)
        body, status, headers = handler.dispatch(parsed.path, query)
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        LOGGER.info("bridge_http_request", method=self.command, path=self.path, status=args[1] if len(args) > 1 else "-")


def create_bridge_server(ctn_dir: Path, host: str = "127.0.0.1", port: int = DEFAULT_BRIDGE_HTTP_PORT):
    """Create a standalone bridge HTTP server."""
    from functools import partial
    handler = partial(BridgeHTTPRequestHandler, ctn_dir=ctn_dir)
    return http.server.ThreadingHTTPServer((host, port), handler)


__all__ = [
    "BridgeAPIHandler",
    "BridgeHTTPRequestHandler",
    "create_bridge_server",
]
