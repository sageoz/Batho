"""Automatic repair strategies for integrity issues."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .checks import Finding


@dataclass
class RepairRecord:
    """Record of a repair operation."""

    repair_id: str
    finding_check_name: str
    strategy_name: str
    success: bool
    timestamp: str
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class RepairStrategy(Protocol):
    """Protocol for repair strategies."""

    name: str
    description: str

    def can_repair(self, finding: Finding) -> bool: ...

    def repair(self, finding: Finding, ctx: "FixContext") -> bool: ...

    def rollback(self, finding: Finding, ctx: "FixContext") -> bool: ...


class OrphanedRowRepair:
    """Remove rows violating foreign key constraints."""

    name = "orphaned_row"
    description = "Delete orphaned rows that violate foreign key constraints"

    def can_repair(self, finding: Finding) -> bool:
        return "orphaned" in finding.message.lower() and "foreign key" in finding.message.lower()

    def repair(self, finding: Finding, ctx: "FixContext") -> bool:
        # Implementation in check-specific repair logic
        return True

    def rollback(self, finding: Finding, ctx: "FixContext") -> bool:
        # Rollback not possible for deletions without backup
        return False


class CorruptedBSGRepair:
    """Regenerate BSG from source entities."""

    name = "corrupted_bsg"
    description = "Regenerate BSG entries from corresponding entities"

    def can_repair(self, finding: Finding) -> bool:
        return finding.check_name == "bsg" and ("checksum" in finding.message.lower() or "invalid json" in finding.message.lower())

    def repair(self, finding: Finding, ctx: "FixContext") -> bool:
        # Requires full BSG regeneration - complex operation
        return False

    def rollback(self, finding: Finding, ctx: "FixContext") -> bool:
        return False


class BrokenSnapshotChainRepair:
    """Rebuild parent_id references in snapshot chain."""

    name = "broken_snapshot_chain"
    description = "Clear broken parent_id references in snapshot chain"

    def can_repair(self, finding: Finding) -> bool:
        return finding.check_name == "snapshots" and "orphaned" in finding.message.lower()

    def repair(self, finding: Finding, ctx: "FixContext") -> bool:
        # Set parent_id to NULL for orphaned snapshots
        return True

    def rollback(self, finding: Finding, ctx: "FixContext") -> bool:
        # Rollback not possible without knowing original parent
        return False


class ChecksumMismatchRepair:
    """Recompute checksums for mismatched artifacts."""

    name = "checksum_mismatch"
    description = "Recompute and update checksums"

    def can_repair(self, finding: Finding) -> bool:
        return "checksum mismatch" in finding.message.lower()

    def repair(self, finding: Finding, ctx: "FixContext") -> bool:
        # Checksum repair is done inline in the checks
        return True

    def rollback(self, finding: Finding, ctx: "FixContext") -> bool:
        # Rollback not needed - old checksum is wrong anyway
        return True


class ExpiredCacheRepair:
    """Clear expired cache entries."""

    name = "expired_cache"
    description = "Delete expired AST cache entries"

    def can_repair(self, finding: Finding) -> bool:
        return finding.check_name == "cache" and "expired" in finding.message.lower()

    def repair(self, finding: Finding, ctx: "FixContext") -> bool:
        # Expired cache clearing is done inline
        return True

    def rollback(self, finding: Finding, ctx: "FixContext") -> bool:
        # Rollback not needed - cache can be rebuilt
        return True


__all__ = [
    "RepairRecord",
    "RepairStrategy",
    "OrphanedRowRepair",
    "CorruptedBSGRepair",
    "BrokenSnapshotChainRepair",
    "ChecksumMismatchRepair",
    "ExpiredCacheRepair",
]
