"""Integrity verification and repair module for Batho.

This module provides the `batho fix` command implementation for verifying
and repairing artifact database corruption.
"""

from __future__ import annotations

from .engine import FixEngine, FixContext, FixResult
from .checks import (
    CheckResult,
    CheckStatus,
    Finding,
    IntegrityCheck,
    Severity,
)
from .report import FixReport
from .repair import RepairRecord

__all__ = [
    "FixEngine",
    "FixContext",
    "FixResult",
    "CheckResult",
    "CheckStatus",
    "Finding",
    "IntegrityCheck",
    "Severity",
    "FixReport",
    "RepairRecord",
]
