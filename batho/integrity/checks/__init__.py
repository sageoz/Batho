"""Integrity check framework for batho fix command."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from ..engine import FixContext


class Severity(Enum):
    """Severity levels for integrity findings."""

    CRITICAL = "critical"  # Data loss risk, immediate fix required
    ERROR = "error"  # Corruption detected, auto-fix attempted
    WARNING = "warning"  # Anomaly detected, may be transient
    INFO = "info"  # FYI, no action needed


class CheckStatus(Enum):
    """Status of an integrity check."""

    PASSED = "passed"
    FAILED = "failed"
    FIXED = "fixed"
    SKIPPED = "skipped"


@dataclass
class Finding:
    """Single integrity check finding."""

    check_name: str
    severity: Severity
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    auto_fixed: bool = False
    fix_attempted: bool = False
    fix_error: str | None = None


@dataclass
class CheckResult:
    """Result of a single integrity check."""

    check_name: str
    status: CheckStatus
    duration_ms: int
    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class IntegrityCheck(Protocol):
    """Protocol for all integrity checks."""

    name: str
    description: str

    def run(self, ctx: "FixContext") -> CheckResult: ...

    def supports_quick_mode(self) -> bool: ...


# Import concrete check implementations for registration
from .database import DatabaseIntegrityCheck
from .index import IndexIntegrityCheck
from .bsg import BSGIntegrityCheck
from .views import ViewIntegrityCheck

__all__ = [
    "Severity",
    "CheckStatus",
    "Finding",
    "CheckResult",
    "IntegrityCheck",
    "DatabaseIntegrityCheck",
    "IndexIntegrityCheck",
    "BSGIntegrityCheck",
    "ViewIntegrityCheck",
]
