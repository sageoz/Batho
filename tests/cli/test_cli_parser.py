"""Tests for CLI argument parsing (batho_cli.build_parser)."""
from __future__ import annotations

import pytest

from batho_cli import build_parser


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------

class TestBuildParser:

    @pytest.fixture
    def parser(self):
        return build_parser()

    def test_index_command(self, parser):
        args = parser.parse_args(["index", "--root", "/tmp/repo"])
        assert args.command == "index"
        assert args.root == "/tmp/repo"

    def test_index_with_extensions(self, parser):
        args = parser.parse_args(["index", "--root", "/tmp", "--extensions", ".py", ".ts"])
        assert args.extensions == [".py", ".ts"]

    def test_index_with_force(self, parser):
        args = parser.parse_args(["index", "--root", "/tmp", "--force"])
        assert args.force is True

    def test_index_defaults(self, parser):
        args = parser.parse_args(["index", "--root", "/tmp"])
        assert args.max_workers == 0
        assert args.max_file_size_kb is None
        assert args.force is False
        assert args.full is False
        assert args.base_snapshot is None
        assert args.metrics_output is None
        assert args.verbose is False

    def test_index_full_and_base_snapshot(self, parser):
        args = parser.parse_args(
            ["index", "--root", "/tmp", "--full", "--base-snapshot", "snap-123"]
        )
        assert args.full is True
        assert args.base_snapshot == "snap-123"

    def test_index_snapshot(self, parser):
        args = parser.parse_args(["index", "--root", "/tmp", "--snapshot", "--snapshot-label", "v1"])
        assert args.snapshot is True
        assert args.snapshot_label == "v1"

    def test_stats_command(self, parser):
        args = parser.parse_args(["stats", "--root", "/tmp/repo"])
        assert args.command == "stats"

    def test_snapshots_command(self, parser):
        args = parser.parse_args(["snapshots", "--root", "/tmp"])
        assert args.command == "snapshots"

    def test_patch_command(self, parser):
        args = parser.parse_args(["patch", "--root", "/tmp", "file1.py", "file2.py"])
        assert args.command == "patch"
        assert args.files == ["file1.py", "file2.py"]

    def test_patch_with_diff(self, parser):
        args = parser.parse_args(["patch", "--root", "/tmp", "--diff", "changes.diff"])
        assert args.diff == "changes.diff"

    def test_storage_backfill_command(self, parser):
        args = parser.parse_args(["storage", "backfill", "--root", "/tmp"])
        assert args.command == "storage"
        assert args.storage_command == "backfill"

    def test_storage_verify_command(self, parser):
        args = parser.parse_args(["storage", "verify", "--root", "/tmp", "--repair"])
        assert args.command == "storage"
        assert args.storage_command == "verify"
        assert args.repair is True

    def test_storage_cleanup_command(self, parser):
        args = parser.parse_args(["storage", "cleanup", "--root", "/tmp", "--apply"])
        assert args.command == "storage"
        assert args.storage_command == "cleanup"
        assert args.apply is True

    def test_query_command(self, parser):
        args = parser.parse_args([
            "query",
            "--root",
            "/tmp",
            "--entity-type",
            "function",
            "--limit",
            "10",
        ])
        assert args.command == "query"
        assert args.entity_type == "function"
        assert args.limit == 10

    def test_webhook_command(self, parser):
        args = parser.parse_args(["webhook", "--payload", '{"event":"push"}'])
        assert args.command == "webhook"
        assert args.payload == '{"event":"push"}'

    def test_hooks_list_command(self, parser):
        args = parser.parse_args(["hooks", "list", "--root", "/tmp/repo"])
        assert args.command == "hooks"
        assert args.hooks_command == "list"
        assert args.root == "/tmp/repo"

    def test_hooks_status_command(self, parser):
        args = parser.parse_args(["hooks", "status", "--hook", "pre-commit"])
        assert args.command == "hooks"
        assert args.hooks_command == "status"
        assert args.hook == "pre-commit"

    def test_hooks_install_all_command(self, parser):
        args = parser.parse_args(["hooks", "install", "--all", "--force", "--dry-run"])
        assert args.command == "hooks"
        assert args.hooks_command == "install"
        assert args.all is True
        assert args.force is True
        assert args.dry_run is True

    def test_hooks_remove_command(self, parser):
        args = parser.parse_args(["hooks", "remove", "--hook", "pre-push", "--dry-run"])
        assert args.command == "hooks"
        assert args.hooks_command == "remove"
        assert args.hook == "pre-push"
        assert args.dry_run is True

    def test_hooks_run_command(self, parser):
        args = parser.parse_args([
            "hooks",
            "run",
            "--hook",
            "enterprise-nightly",
            "--verbose",
            "--dry-run",
        ])
        assert args.command == "hooks"
        assert args.hooks_command == "run"
        assert args.hook == "enterprise-nightly"
        assert args.verbose is True
        assert args.dry_run is True

    def test_invalidate_command(self, parser):
        args = parser.parse_args(["invalidate", "--root", "/tmp"])
        assert args.command == "invalidate"

    def test_missing_command_raises(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_missing_required_root_raises(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args(["index"])
