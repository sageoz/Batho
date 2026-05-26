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
