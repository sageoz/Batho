"""Unit tests for integrity check modules."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


class TestDatabaseIntegrityCheck:
    """Tests for DatabaseIntegrityCheck."""

    def test_check_integrity_passed(self):
        """Test database integrity check passes when pragma returns ok."""
        from batho.integrity.checks.database import DatabaseIntegrityCheck

        check = DatabaseIntegrityCheck()

        # Mock context
        ctx = MagicMock()
        ctx.db.connection.return_value.__enter__ = MagicMock(
            return_value=MagicMock(
                execute=MagicMock(return_value=MagicMock(fetchone=MagicMock(return_value=("ok",))))
            )
        )
        ctx.db.connection.return_value.__exit__ = MagicMock(return_value=None)

        result = check._check_integrity(ctx)

        assert len(result) == 1
        assert result[0].severity.value == "info"

    def test_check_integrity_failed(self):
        """Test database integrity check fails when pragma returns error."""
        from batho.integrity.checks.database import DatabaseIntegrityCheck

        check = DatabaseIntegrityCheck()

        # Mock context
        ctx = MagicMock()
        ctx.db.connection.return_value.__enter__ = MagicMock(
            return_value=MagicMock(
                execute=MagicMock(return_value=MagicMock(fetchone=MagicMock(return_value=("corrupt",))))
            )
        )
        ctx.db.connection.return_value.__exit__ = MagicMock(return_value=None)

        result = check._check_integrity(ctx)

        assert len(result) == 1
        assert result[0].severity.value == "critical"

    def test_supports_quick_mode(self):
        """Test that database check supports quick mode."""
        from batho.integrity.checks.database import DatabaseIntegrityCheck

        check = DatabaseIntegrityCheck()
        assert check.supports_quick_mode() is True


class TestRegistryIntegrityCheck:
    """Tests for RegistryIntegrityCheck."""

    def test_check_index_ids_valid(self):
        """Test registry check passes when all index_ids are valid."""
        from batho.integrity.checks.registry import RegistryIntegrityCheck

        check = RegistryIntegrityCheck()

        # Mock context with valid run_id
        ctx = MagicMock()
        ctx.get_index_runs.return_value = [{"run_id": "run-123"}]

        artifacts = [{"run_id": "run-123", "artifact_id": "art-1"}]

        result = check._check_index_ids(ctx, artifacts)

        # Should have info finding
        assert any(f.severity.value == "info" for f in result)

    def test_check_duplicates_found(self):
        """Test registry check finds duplicate artifact IDs."""
        from batho.integrity.checks.registry import RegistryIntegrityCheck

        check = RegistryIntegrityCheck()

        ctx = MagicMock()

        artifacts = [
            {"artifact_id": "dup-1", "run_id": "run-1"},
            {"artifact_id": "dup-1", "run_id": "run-2"},  # Duplicate
        ]

        result = check._check_duplicates(ctx, artifacts)

        assert len(result) == 1
        assert result[0].severity.value == "error"


class TestBSGIntegrityCheck:
    """Tests for BSGIntegrityCheck."""

    def test_check_checksums_valid(self):
        """Test BSG checksum validation with valid checksums."""
        from batho.integrity.checks.bsg import BSGIntegrityCheck
        import hashlib

        check = BSGIntegrityCheck()

        ctx = MagicMock()
        ctx.dry_run = False

        bsg_json = '{"test": "data"}'
        checksum = hashlib.sha256(bsg_json.encode("utf-8")).hexdigest()

        entries = [
            {"run_id": "run-1", "file_path": "test.py", "view_type": "agent", "bsg_json": bsg_json, "checksum": checksum}
        ]

        result = check._check_checksums(ctx, entries)

        assert any(f.severity.value == "info" for f in result)

    def test_check_checksums_mismatch(self):
        """Test BSG checksum validation with mismatched checksums."""
        from batho.integrity.checks.bsg import BSGIntegrityCheck

        check = BSGIntegrityCheck()

        ctx = MagicMock()
        ctx.dry_run = True

        entries = [
            {"run_id": "run-1", "file_path": "test.py", "view_type": "agent", "bsg_json": '{"test": "data"}', "checksum": "invalid"}
        ]

        result = check._check_checksums(ctx, entries)

        assert any(f.severity.value == "error" for f in result)


class TestSnapshotIntegrityCheck:
    """Tests for SnapshotIntegrityCheck."""

    def test_check_chain_integrity_valid(self):
        """Test snapshot chain integrity with valid chain."""
        from batho.integrity.checks.snapshots import SnapshotIntegrityCheck

        check = SnapshotIntegrityCheck()

        ctx = MagicMock()
        ctx.deep_mode = False

        snapshots = [
            {"snapshot_id": "snap-1", "parent_id": None},
            {"snapshot_id": "snap-2", "parent_id": "snap-1"},
        ]

        result = check._check_chain_integrity(ctx, snapshots)

        assert any(f.severity.value == "info" for f in result)

    def test_check_chain_integrity_orphaned(self):
        """Test snapshot chain integrity with orphaned snapshots."""
        from batho.integrity.checks.snapshots import SnapshotIntegrityCheck

        check = SnapshotIntegrityCheck()

        ctx = MagicMock()
        ctx.dry_run = True
        ctx.db.connection.return_value.__enter__ = MagicMock(return_value=MagicMock())
        ctx.db.connection.return_value.__exit__ = MagicMock(return_value=None)

        snapshots = [
            {"snapshot_id": "snap-1", "parent_id": None},
            {"snapshot_id": "snap-2", "parent_id": "missing-parent"},  # Orphaned
        ]

        result = check._check_chain_integrity(ctx, snapshots)

        assert any(f.severity.value == "warning" and "orphaned" in f.message.lower() for f in result)


class TestCacheIntegrityCheck:
    """Tests for CacheIntegrityCheck."""

    def test_check_ast_cache_no_entries(self):
        """Test AST cache check when no entries exist."""
        from batho.integrity.checks.cache import CacheIntegrityCheck

        check = CacheIntegrityCheck()

        ctx = MagicMock()
        ctx.db.connection.return_value.__enter__ = MagicMock(
            return_value=MagicMock(
                execute=MagicMock(return_value=MagicMock(fetchone=MagicMock(return_value=(0,))))
            )
        )
        ctx.db.connection.return_value.__exit__ = MagicMock(return_value=None)

        result = check._check_ast_cache(ctx)

        assert any(f.severity.value == "info" and "No AST cache" in f.message for f in result)


class TestSeverity:
    """Tests for Severity enum."""

    def test_severity_order(self):
        """Test severity levels have expected values."""
        from batho.integrity.checks import Severity

        assert Severity.CRITICAL.value == "critical"
        assert Severity.ERROR.value == "error"
        assert Severity.WARNING.value == "warning"
        assert Severity.INFO.value == "info"


class TestCheckStatus:
    """Tests for CheckStatus enum."""

    def test_status_values(self):
        """Test check status values."""
        from batho.integrity.checks import CheckStatus

        assert CheckStatus.PASSED.value == "passed"
        assert CheckStatus.FAILED.value == "failed"
        assert CheckStatus.FIXED.value == "fixed"
        assert CheckStatus.SKIPPED.value == "skipped"
