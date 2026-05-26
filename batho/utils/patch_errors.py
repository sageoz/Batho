"""
Patch operation error classes and audit trail functionality for Batho.

Provides specific exceptions for different types of patch failures and
structured logging mechanisms for operation tracking and audit trails.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from batho.config import SCHEMA_VERSIONS
from batho.utils.logging import get_logger

logger = get_logger(__name__, component="patch_errors")


def _is_audit_enabled() -> bool:
    """Check if audit logging is enabled via config (lazy evaluation)."""
    try:
        from batho.config import get_config_cached

        return get_config_cached().get("flags", {}).get("audit_log_enabled", True)
    except Exception:
        return True  # Default to enabled if config fails


class PatchValidationError(ValueError):
    """Raised when patch inputs fail validation."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


class PatchConsistencyError(RuntimeError):
    """Raised when graph consistency cannot be maintained after patch operations."""

    def __init__(self, message: str, inconsistencies: list[str] | None = None):
        super().__init__(message)
        self.inconsistencies = inconsistencies or []


class PatchSnapshotError(FileNotFoundError):
    """Raised when snapshot operations fail."""

    def __init__(self, message: str, snapshot_id: str | None = None):
        super().__init__(message)
        self.snapshot_id = snapshot_id


class PatchFileError(OSError):
    """Raised when file operations within patch processing fail."""

    def __init__(
        self, message: str, file_path: str | None = None, operation: str | None = None
    ):
        super().__init__(message)
        self.file_path = file_path
        self.operation = operation


class PatchTimeoutError(TimeoutError):
    """Raised when patch operations exceed configured timeouts."""

    def __init__(self, message: str, timeout_seconds: float | None = None):
        super().__init__(message)
        self.timeout_seconds = timeout_seconds


@dataclass
class PatchAuditLogEntry:
    """Audit log entry for patch operations."""

    operation_id: str
    operation_type: str  # 'incremental_patch', 'rollback', etc.
    start_time: datetime
    end_time: datetime | None = None
    success: bool | None = None
    base_snapshot_id: str | None = None
    new_snapshot_id: str | None = None
    change_count: int = 0
    error_message: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "success": self.success,
            "base_snapshot_id": self.base_snapshot_id,
            "new_snapshot_id": self.new_snapshot_id,
            "change_count": self.change_count,
            "error_message": self.error_message,
            "metadata": self.metadata or {},
        }

    def complete(
        self,
        success: bool,
        new_snapshot_id: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.end_time = datetime.now(timezone.utc)
        self.success = success
        self.new_snapshot_id = new_snapshot_id
        self.error_message = error_message
        if metadata:
            self.metadata = {**(self.metadata or {}), **metadata}


class PatchAuditLogger:
    """Audit logger for patch operations with persistent storage."""

    def __init__(self, log_file: Path | None = None):
        self.log_file = log_file
        self.entries: list[PatchAuditLogEntry] = []

    def start_operation(
        self,
        operation_id: str,
        operation_type: str,
        base_snapshot_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PatchAuditLogEntry:
        """Start tracking a patch operation."""
        entry = PatchAuditLogEntry(
            operation_id=operation_id,
            operation_type=operation_type,
            start_time=datetime.now(timezone.utc),
            base_snapshot_id=base_snapshot_id,
            metadata=metadata,
        )
        self.entries.append(entry)

        if _is_audit_enabled():
            logger.info(
                "patch_audit_operation_start",
                operation_id=operation_id,
                operation_type=operation_type,
                base_snapshot_id=base_snapshot_id,
            )

        return entry

    def complete_operation(
        self,
        operation_id: str,
        success: bool,
        new_snapshot_id: str | None = None,
        error_message: str | None = None,
        change_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Complete tracking of a patch operation."""
        for entry in reversed(self.entries):
            if entry.operation_id == operation_id and entry.end_time is None:
                entry.complete(success, new_snapshot_id, error_message, metadata)
                entry.change_count = change_count
                break

        if _is_audit_enabled():
            logger.info(
                "patch_audit_operation_complete",
                operation_id=operation_id,
                success=success,
                new_snapshot_id=new_snapshot_id,
                change_count=change_count,
                error_message=error_message,
            )

        self._write_audit_log()

    def _write_audit_log(self) -> None:
        """Persist audit entries to log file."""
        if not _is_audit_enabled() or not self.log_file:
            return

        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            audit_data = {
                "schema_version": SCHEMA_VERSIONS["config"],
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "entries": [
                    entry.to_dict() for entry in self.entries if entry.end_time
                ],
            }

            tmp_path = self.log_file.with_suffix(self.log_file.suffix + ".tmp")
            tmp_path.write_text(
                json.dumps(audit_data, indent=2, ensure_ascii=True), encoding="utf-8"
            )
            tmp_path.replace(self.log_file)
        except Exception as exc:
            logger.warning("failed_to_write_audit_log", error=str(exc))

    def get_operation_history(
        self,
        operation_type: str | None = None,
        base_snapshot_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Retrieve operation history with optional filtering."""
        filtered = []
        for entry in reversed(self.entries):
            if (
                entry.end_time
                and (operation_type is None or entry.operation_type == operation_type)
                and (
                    base_snapshot_id is None
                    or entry.base_snapshot_id == base_snapshot_id
                )
            ):
                filtered.append(entry.to_dict())
                if len(filtered) >= limit:
                    break
        return filtered


# Global audit logger instance - lazy initialization to avoid circular imports
_audit_logger_instance: PatchAuditLogger | None = None


def _get_audit_logger() -> PatchAuditLogger:
    """Get or create the global audit logger instance (lazy initialization)."""
    global _audit_logger_instance
    if _audit_logger_instance is None:
        _audit_logger_instance = PatchAuditLogger()
    return _audit_logger_instance


# Module-level __getattr__ for backward compatible lazy loading
def __getattr__(name: str) -> Any:
    """Lazy load audit_logger on first access."""
    if name == "audit_logger":
        return _get_audit_logger()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
