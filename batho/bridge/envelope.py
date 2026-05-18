"""Shared JSON envelope helpers for MCP and REST responses."""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")

ERROR_CODES = {
    "workspace_not_found": "Workspace ID not found in registry",
    "workspace_not_ready": "Workspace is not in READY state",
    "workspace_degraded": "Workspace is in DEGRADED state, some operations may fail",
    "artifact_not_found": "Artifact not found",
    "artifact_checksum_mismatch": "Artifact checksum verification failed",
    "artifact_parse_error": "Failed to parse artifact content",
    "unknown_artifact_type": "Unknown artifact type",
    "invalid_argument": "Invalid argument provided",
    "internal_error": "Internal error occurred",
    "timeout": "Operation timed out",
}


def ok(
    data: Any,
    *,
    workspace_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a success envelope."""
    envelope: dict[str, Any] = {"ok": True, "data": data}
    if workspace_id:
        envelope["workspace_id"] = workspace_id
    if meta:
        envelope["meta"] = meta
    return envelope


def err(
    code: str,
    message: str,
    *,
    detail: Any = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Build an error envelope."""
    error: dict[str, Any] = {"code": code, "message": message}
    if detail is not None:
        error["detail"] = detail
    envelope: dict[str, Any] = {"ok": False, "error": error}
    if workspace_id:
        envelope["workspace_id"] = workspace_id
    return envelope


def to_json(payload: dict[str, Any]) -> str:
    """Serialize a payload to JSON string."""
    import json

    return json.dumps(payload, indent=2, default=str)


def tool_envelope(name: str) -> Callable[[Callable[..., T]], Callable[..., str]]:
    """Decorator that wraps a handler, times it, and converts exceptions to error envelopes."""

    def decorator(func: Callable[..., T]) -> Callable[..., str]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> str:
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration_ms = int((time.perf_counter() - start) * 1000)
                if isinstance(result, dict) and "ok" in result:
                    if "meta" not in result:
                        result["meta"] = {}
                    result["meta"]["duration_ms"] = duration_ms
                    return to_json(result)
                return to_json(ok(result, meta={"duration_ms": duration_ms}))
            except KeyError as exc:
                return to_json(err("workspace_not_found", str(exc)))
            except FileNotFoundError as exc:
                return to_json(err("artifact_not_found", str(exc)))
            except ValueError as exc:
                return to_json(err("invalid_argument", str(exc)))
            except TimeoutError as exc:
                return to_json(err("timeout", str(exc)))
            except Exception as exc:
                return to_json(err("internal_error", str(exc), detail=type(exc).__name__))

        return wrapper

    return decorator


__all__ = [
    "ERROR_CODES",
    "ok",
    "err",
    "to_json",
    "tool_envelope",
]
