"""Models and dataclasses for integrity verification and repairs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(Enum):
    """Severity levels for integrity issues."""

    CRITICAL = "critical"  # Data loss risk, immediate fix required
    ERROR = "error"  # Corruption detected, auto-fix attempted
    WARNING = "warning"  # Anomaly detected, may be transient
    INFO = "info"  # FYI, no action needed


class CheckStatus(Enum):
    """Status of an integrity check phase."""

    PASSED = "passed"
    FAILED = "failed"
    FIXED = "fixed"
    SKIPPED = "skipped"


@dataclass
class Issue:
    """Single integrity issue detected."""

    type: str                           # e.g., "corrupt_zstd_blob", "stuck_run"
    severity: Severity                  # CRITICAL, ERROR, WARNING, INFO
    table: str                          # Database table name
    identifier: dict[str, Any]          # Primary key values
    description: str
    repair_strategy: str | None = None


@dataclass
class RepairResult:
    """Result of a repair operation."""

    issue: Issue
    success: bool
    error: str | None = None
    rows_affected: int = 0


@dataclass
class CheckReport:
    """Report from a single checker."""

    phase: str                          # "db", "state", "blobs", "graph"
    status: CheckStatus
    issues: list[Issue] = field(default_factory=list)
    repairs: list[RepairResult] = field(default_factory=list)
    duration_ms: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
