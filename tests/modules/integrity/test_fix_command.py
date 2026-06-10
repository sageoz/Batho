"""Integration tests for batho fix command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, ANY
import pytest

from batho.modules.integrity.engine import FixEngine, FixContext, FixResult, FixSummary
from batho.modules.integrity.report import ReportGenerator
from batho.modules.integrity.models import CheckReport, CheckStatus


class TestFixEngine:
    """Tests for FixEngine."""

    def test_engine_initialization(self, tmp_path):
        """Verify that FixEngine can be initialized with custom options.

        Scenario:
            FixEngine is instantiated with a temporary path, deep_mode=False, and dry_run=True.

        Execution Flow:
            1. Initialize FixEngine with the specified arguments.
            2. Assert that the root is correctly resolved to the temporary directory path.
            3. Assert that deep_mode is False.
            4. Assert that dry_run is True.

        Expectations:
            - The FixEngine is successfully constructed.
            - All initialization properties match the provided inputs.
        """
        engine = FixEngine(root=tmp_path, deep_mode=False, dry_run=True)

        assert engine.root == tmp_path.resolve()
        assert engine.deep_mode is False
        assert engine.dry_run is True

    def test_run_no_database(self, tmp_path):
        """Verify that running FixEngine fails when there is no database.

        Scenario:
            FixEngine runs in a temporary directory where no database exists.

        Execution Flow:
            1. Initialize FixEngine in dry_run mode.
            2. Call the run method inside a pytest.raises(Exception) context.
            3. Verify that an exception is raised due to the missing database.

        Expectations:
            - The run method raises an exception because the database is absent.
        """
        engine = FixEngine(root=tmp_path, deep_mode=False, dry_run=True)

        # This will fail because there's no database, but should not crash
        with pytest.raises(Exception):
            engine.run()


class TestFixContext:
    """Tests for FixContext."""

    def test_context_creation(self):
        """Verify that FixContext can be successfully created with a db and other settings.

        Scenario:
            FixContext is initialized with a path, a mocked database, and deep_mode set to True.

        Execution Flow:
            1. Create a MagicMock for the database.
            2. Instantiate FixContext with a mock root path, mock database, and deep_mode=True.
            3. Assert that root is set correctly.
            4. Assert that deep_mode is True.
            5. Assert that a run_id is generated (is not None).

        Expectations:
            - FixContext is initialized successfully.
            - Properties of the context are correct, including auto-generation of run_id.
        """
        mock_db = MagicMock()
        ctx = FixContext(root=Path("/test"), db=mock_db, deep_mode=True)

        assert ctx.root == Path("/test")
        assert ctx.deep_mode is True
        assert ctx.run_id is not None

    def test_log_audit(self):
        """Verify that log_audit adds actions and details to the audit log.

        Scenario:
            FixContext is initialized and an action is logged using the log_audit method.

        Execution Flow:
            1. Create a MagicMock for the database and initialize FixContext.
            2. Call log_audit with an action name "test_action" and details {"key": "value"}.
            3. Assert that the context's audit_log contains exactly one record.
            4. Assert that the record's action key is "test_action".

        Expectations:
            - The action is appended to the context's audit log.
            - The log entry correctly stores the action name.
        """
        mock_db = MagicMock()
        ctx = FixContext(root=Path("/test"), db=mock_db)

        ctx.log_audit("test_action", {"key": "value"})

        assert len(ctx.audit_log) == 1
        assert ctx.audit_log[0]["action"] == "test_action"


class TestReportGenerator:
    """Tests for ReportGenerator."""

    def test_generate_text_report(self):
        """Verify that ReportGenerator outputs a valid text report.

        Scenario:
            ReportGenerator is initialized with text format, and we generate a report from a FixResult.

        Execution Flow:
            1. Instantiate ReportGenerator with format="text".
            2. Construct a mock FixSummary and a FixResult.
            3. Call generator.generate with the FixResult.
            4. Assert that "Batho Fix Report" and "quick" are present in the output text.

        Expectations:
            - The report generator returns a text string representing the report.
            - The text includes correct header and metadata information.
        """
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
            bundle_dir="/test/.batho/artifact",
            mode="quick",
            summary=summary,
            check_results=[],
            repairs=[],
        )

        report = generator.generate(result)

        assert "Batho Fix Report" in report
        assert "quick" in report

    def test_generate_json_report(self):
        """Verify that ReportGenerator outputs a valid JSON report.

        Scenario:
            ReportGenerator is initialized with json format, and we generate a report from a FixResult.

        Execution Flow:
            1. Instantiate ReportGenerator with format="json".
            2. Construct a mock FixSummary and a FixResult.
            3. Call generator.generate with the FixResult.
            4. Parse the returned report string as JSON.
            5. Assert that "mode" is "quick" and "checks_passed" is 5.

        Expectations:
            - The output is a valid JSON string.
            - The parsed JSON structure contains the expected details of the FixResult.
        """
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
            bundle_dir="/test/.batho/artifact",
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
        """Verify that ReportGenerator outputs a valid CSV report.

        Scenario:
            ReportGenerator is initialized with csv format, and we generate a report from a FixResult.

        Execution Flow:
            1. Instantiate ReportGenerator with format="csv".
            2. Construct a mock FixSummary and a FixResult.
            3. Call generator.generate with the FixResult.
            4. Assert that the CSV headers "timestamp,check_name,severity" are present in the output.

        Expectations:
            - The output is a valid CSV string.
            - The CSV contains the appropriate header columns.
        """
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
            bundle_dir="/test/.batho/artifact",
            mode="quick",
            summary=summary,
            check_results=[],
            repairs=[],
        )

        report = generator.generate(result)

        assert "timestamp,check_name,severity" in report


class TestCliFix:
    """Tests for CLI fix command."""

    def test_register_fix_parser(self):
        """Verify that the register_fix_parser registers the fix subparsers.

        Scenario:
            An ArgumentParser instance is used to test registering the fix subcommand parser.

        Execution Flow:
            1. Initialize ArgumentParser and add subparsers.
            2. Call register_fix_parser with the subparsers.
            3. The subparser registration runs without raising exceptions.

        Expectations:
            - The fix subcommand and its arguments are successfully registered.
        """
        import argparse
        from batho.cli.fix import register_fix_parser

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        register_fix_parser(subparsers)

    def test_cmd_fix_no_database(self, tmp_path, capsys):
        """Verify that the cmd_fix command handles a missing database and exits with code 1.

        Scenario:
            The cmd_fix function is invoked with standard arguments in a directory lacking a database.

        Execution Flow:
            1. Create argparse.Namespace args with the path `tmp_path`.
            2. Call cmd_fix with these arguments.
            3. Assert that the returned exit code is 1.
            4. Read captured sys.stderr output.
            5. Assert that "No artifact bundle found" or similar error message is captured.

        Expectations:
            - The command exits gracefully with code 1.
            - An error message indicating the missing database/bundle is printed to standard error.
        """
        import argparse
        from batho.cli.fix import cmd_fix

        args = argparse.Namespace(
            root=tmp_path,
            deep=False,
            dry_run=False,
            target="all",
            phase=None,
            parallel=False,
            verbose=False,
            format="text",
            output=None,
        )

        exit_code = cmd_fix(args)

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "No artifact bundle found" in captured.err or "no artifact bundle" in captured.err.lower()
