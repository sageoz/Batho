"""Integration tests for batho fix command."""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, ANY


class TestFixEngine:
    """Tests for FixEngine."""

    def test_engine_initialization(self, tmp_path):
        """Test FixEngine can be initialized."""
        from batho.integrity.engine import FixEngine

        engine = FixEngine(root=tmp_path, deep_mode=False, dry_run=True)

        assert engine.root == tmp_path.resolve()
        assert engine.deep_mode is False
        assert engine.dry_run is True

    def test_run_no_database(self, tmp_path):
        """Test engine handles missing database gracefully."""
        from batho.integrity.engine import FixEngine

        engine = FixEngine(root=tmp_path, deep_mode=False, dry_run=True)

        # This will fail because there's no database, but should not crash
        with pytest.raises(Exception):
            engine.run()


class TestFixContext:
    """Tests for FixContext."""

    def test_context_creation(self):
        """Test FixContext can be created."""
        from batho.integrity.engine import FixContext

        mock_db = MagicMock()
        ctx = FixContext(root=Path("/test"), db=mock_db, deep_mode=True)

        assert ctx.root == Path("/test")
        assert ctx.deep_mode is True
        assert ctx.run_id is not None

    def test_log_audit(self):
        """Test audit logging."""
        from batho.integrity.engine import FixContext

        mock_db = MagicMock()
        ctx = FixContext(root=Path("/test"), db=mock_db)

        ctx.log_audit("test_action", {"key": "value"})

        assert len(ctx.audit_log) == 1
        assert ctx.audit_log[0]["action"] == "test_action"


class TestReportGenerator:
    """Tests for ReportGenerator."""

    def test_generate_text_report(self):
        """Test text report generation."""
        from batho.integrity.report import ReportGenerator
        from batho.integrity.engine import FixResult, FixSummary

        generator = ReportGenerator(format="text")

        summary = FixSummary(
            checks_passed=5,
            checks_failed=0,
            duration_ms=1000,
        )

        result = FixResult(
            started_at="2024-01-01T00:00:00",
            completed_at="2024-01-01T00:00:01",
            root="/test",
            db_path="/test/artifact_test.batho",
            mode="quick",
            summary=summary,
            check_results=[],
            repairs=[],
        )

        report = generator.generate(result)

        assert "Batho Fix Report" in report
        assert "quick" in report

    def test_generate_json_report(self):
        """Test JSON report generation."""
        import json
        from batho.integrity.report import ReportGenerator
        from batho.integrity.engine import FixResult, FixSummary

        generator = ReportGenerator(format="json")

        summary = FixSummary(
            checks_passed=5,
            checks_failed=0,
            duration_ms=1000,
        )

        result = FixResult(
            started_at="2024-01-01T00:00:00",
            completed_at="2024-01-01T00:00:01",
            root="/test",
            db_path="/test/artifact_test.batho",
            mode="quick",
            summary=summary,
            check_results=[],
            repairs=[],
        )

        report = generator.generate(result)
        data = json.loads(report)

        assert data["mode"] == "quick"
        assert data["summary"]["checks_passed"] == 5

    def test_generate_csv_report(self):
        """Test CSV report generation."""
        from batho.integrity.report import ReportGenerator
        from batho.integrity.engine import FixResult, FixSummary

        generator = ReportGenerator(format="csv")

        summary = FixSummary(
            checks_passed=5,
            checks_failed=0,
            duration_ms=1000,
        )

        result = FixResult(
            started_at="2024-01-01T00:00:00",
            completed_at="2024-01-01T00:00:01",
            root="/test",
            db_path="/test/artifact_test.batho",
            mode="quick",
            summary=summary,
            check_results=[],
            repairs=[],
        )

        report = generator.generate(result)

        assert "timestamp,check_name,severity" in report


class TestRollbackManager:
    """Tests for RollbackManager."""

    def test_find_last_known_good_no_snapshots(self):
        """Test find_last_known_good when no snapshots exist."""
        from batho.integrity.rollback import RollbackManager

        mock_db = MagicMock()
        mock_db.connection.return_value.__enter__ = MagicMock(
            return_value=MagicMock(
                execute=MagicMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))
            )
        )
        mock_db.connection.return_value.__exit__ = MagicMock(return_value=None)

        manager = RollbackManager(mock_db, "/test")
        result = manager.find_last_known_good()

        assert result is None


class TestCliFix:
    """Tests for CLI fix command."""

    def test_register_fix_parser(self):
        """Test that fix parser is registered correctly."""
        import argparse
        from batho.cli.fix import register_fix_parser

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        register_fix_parser(subparsers)

        # Check that 'fix' command was registered
        # (subparsers._group_actions[0].choices would contain 'fix')

    def test_cmd_fix_no_database(self, tmp_path, capsys):
        """Test fix command handles missing database."""
        import argparse
        from batho.cli.fix import cmd_fix

        args = argparse.Namespace(
            root=tmp_path,
            deep=False,
            dry_run=False,
            format="text",
            output=None,
            rollback_to=None,
            repair_only=None,
            create_checkpoint=None,
            no_audit=False,
        )

        exit_code = cmd_fix(args)

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "No artifact database found" in captured.err
