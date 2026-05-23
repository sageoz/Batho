"""Unit and integration tests for the `batho patch` `--mode` feature."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from batho import PatchMode
from batho.context import PatchMode as ContextPatchMode
from batho.context.incremental import get_changed_files_by_mode, GitDiffEntry


class TestPatchModeAPI:
    """Verify that PatchMode is exposed correctly in public APIs."""

    def test_public_imports(self):
        """Test PatchMode is accessible from public exports."""
        assert PatchMode is not None
        assert ContextPatchMode is not None
        assert PatchMode == ContextPatchMode
        assert PatchMode.AUTO.value == "auto"
        assert PatchMode.COMMIT.value == "commit"
        assert PatchMode.STAGED.value == "staged"
        assert PatchMode.MODIFIED.value == "modified"


class TestGetChangedFilesByMode:
    """Tests for get_changed_files_by_mode change detection."""

    @patch("batho.context.incremental.is_git_repo")
    def test_non_git_repo(self, mock_is_git):
        """Verify that get_changed_files_by_mode returns None if not a git repo."""
        mock_is_git.return_value = False
        res = get_changed_files_by_mode(PatchMode.AUTO, Path("/dummy"))
        assert res is None

    @patch("batho.context.incremental.is_git_repo")
    @patch("batho.context.incremental._run_git")
    def test_commit_mode(self, mock_run_git, mock_is_git):
        """Verify COMMIT mode runs correct git diff command."""
        mock_is_git.return_value = True
        
        # Mock git output
        mock_completed = MagicMock()
        mock_completed.stdout = "M\tfile1.py\nA\tfile2.py\n"
        mock_run_git.return_value = mock_completed

        # Test with base_commit
        res = get_changed_files_by_mode(PatchMode.COMMIT, Path("/dummy"), base_commit="abc1234")
        assert res is not None
        assert len(res) == 2
        assert res[0].path == "file1.py"
        assert res[0].status == "M"
        assert res[1].path == "file2.py"
        assert res[1].status == "A"

        mock_run_git.assert_called_once_with(
            Path("/dummy").resolve(),
            ["diff", "--name-status", "-M", "--diff-filter=ACDMRT", "abc1234..HEAD"]
        )

        # Test without base_commit
        assert get_changed_files_by_mode(PatchMode.COMMIT, Path("/dummy"), base_commit=None) is None

    @patch("batho.context.incremental.is_git_repo")
    @patch("batho.context.incremental._run_git")
    def test_staged_mode(self, mock_run_git, mock_is_git):
        """Verify STAGED mode runs git diff --cached."""
        mock_is_git.return_value = True
        mock_completed = MagicMock()
        mock_completed.stdout = "A\tstaged_file.py\n"
        mock_run_git.return_value = mock_completed

        res = get_changed_files_by_mode(PatchMode.STAGED, Path("/dummy"))
        assert res is not None
        assert len(res) == 1
        assert res[0].path == "staged_file.py"
        assert res[0].status == "A"

        mock_run_git.assert_called_once_with(
            Path("/dummy").resolve(),
            ["diff", "--cached", "--name-status", "-M", "--diff-filter=ACDMRT"]
        )

    @patch("batho.context.incremental.is_git_repo")
    @patch("batho.context.incremental._run_git")
    def test_modified_mode(self, mock_run_git, mock_is_git):
        """Verify MODIFIED mode runs git diff without --cached."""
        mock_is_git.return_value = True
        mock_completed = MagicMock()
        mock_completed.stdout = "M\tmodified_file.py\n"
        mock_run_git.return_value = mock_completed

        res = get_changed_files_by_mode(PatchMode.MODIFIED, Path("/dummy"))
        assert res is not None
        assert len(res) == 1
        assert res[0].path == "modified_file.py"
        assert res[0].status == "M"

        mock_run_git.assert_called_once_with(
            Path("/dummy").resolve(),
            ["diff", "--name-status", "-M", "--diff-filter=ACDMRT"]
        )

    @patch("batho.context.incremental.is_git_repo")
    @patch("batho.context.incremental.get_changed_files_by_mode")
    def test_auto_mode_merging(self, mock_get_by_mode, mock_is_git):
        """Verify AUTO mode merges staged and modified files with staged taking precedence."""
        mock_is_git.return_value = True

        def side_effect(mode, repo_root, base_commit=None):
            if mode == PatchMode.STAGED:
                return [
                    GitDiffEntry(status="A", path="staged_only.py"),
                    GitDiffEntry(status="M", path="both.py"),
                ]
            elif mode == PatchMode.MODIFIED:
                return [
                    GitDiffEntry(status="M", path="modified_only.py"),
                    GitDiffEntry(status="D", path="both.py"),  # Override this with staged "M"
                ]
            return None

        mock_get_by_mode.side_effect = side_effect

        res = get_changed_files_by_mode(PatchMode.AUTO, Path("/dummy"))
        assert res is not None
        
        # We expect staged_only.py, modified_only.py, and both.py (with staged status: "M")
        paths = {r.path: r.status for r in res}
        assert len(paths) == 3
        assert paths["staged_only.py"] == "A"
        assert paths["modified_only.py"] == "M"
        assert paths["both.py"] == "M"  # staged took precedence over modified "D"


class TestCliPatchModes:
    """Verify that CLI subcommand registers and parses --mode argument correctly."""

    def test_register_patch_parser(self):
        """Test --mode argument registration in the parser."""
        from batho.cli.patch import register_patch_parser

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_patch_parser(subparsers)

        # Parse command arguments
        parsed = parser.parse_args(["patch", "--mode", "staged", "--max-file-size-kb", "200"])
        assert parsed.mode == "staged"
        assert parsed.max_file_size_kb == 200

        # Check default value
        parsed_default = parser.parse_args(["patch"])
        assert parsed_default.mode == "auto"

        # Check choices validation
        with pytest.raises(SystemExit):
            parser.parse_args(["patch", "--mode", "invalid_mode"])


class TestOrchestratorPatchIntegration:
    """Test orchestrator integration with PatchOptions mode."""

    @patch("batho.storage.engine.get_database")
    @patch("batho.orchestrator.patch.load_snapshot")
    @patch("batho.orchestrator.patch.get_changed_file_status_since")
    @patch("batho.orchestrator.patch.get_changed_files_by_mode")
    def test_run_patch_with_commit_mode(
        self, mock_get_by_mode, mock_get_since, mock_load_snapshot, mock_db, tmp_path
    ):
        """Verify COMMIT mode uses get_changed_file_status_since."""
        from batho.orchestrator.patch import run_patch, PatchOptions
        from batho.storage.engine import artifact_filename

        # Create a dummy database file so exists() check passes
        db_file = tmp_path / artifact_filename(tmp_path)
        db_file.touch()

        # Setup mock db and snapshot loading to return dummy baseline
        mock_db_instance = mock_db.return_value
        mock_db_instance.list_snapshots.return_value = [{"snapshot_id": "snap_123", "created_at": "2026-05-23T12:00:00Z"}]
        mock_load_snapshot.return_value = {"graph": {"entities": {}, "relationships": []}}

        mock_get_since.return_value = None  # Mock no changes to early exit clean
        
        options = PatchOptions(root=tmp_path, mode=PatchMode.COMMIT)
        
        # Run patch
        run_patch(options)

        mock_get_since.assert_called_once()
        mock_get_by_mode.assert_not_called()

    @patch("batho.storage.engine.get_database")
    @patch("batho.orchestrator.patch.load_snapshot")
    @patch("batho.orchestrator.patch.get_changed_file_status_since")
    @patch("batho.orchestrator.patch.get_changed_files_by_mode")
    def test_run_patch_with_auto_mode(
        self, mock_get_by_mode, mock_get_since, mock_load_snapshot, mock_db, tmp_path
    ):
        """Verify non-COMMIT modes (like AUTO) use get_changed_files_by_mode."""
        from batho.orchestrator.patch import run_patch, PatchOptions
        from batho.storage.engine import artifact_filename

        # Create a dummy database file so exists() check passes
        db_file = tmp_path / artifact_filename(tmp_path)
        db_file.touch()

        # Setup mock db and snapshot loading
        mock_db_instance = mock_db.return_value
        mock_db_instance.list_snapshots.return_value = [{"snapshot_id": "snap_123", "created_at": "2026-05-23T12:00:00Z"}]
        mock_load_snapshot.return_value = {"graph": {"entities": {}, "relationships": []}}

        mock_get_by_mode.return_value = None  # Mock no changes to early exit clean

        options = PatchOptions(root=tmp_path, mode=PatchMode.AUTO)
        run_patch(options)

        mock_get_since.assert_not_called()
        mock_get_by_mode.assert_called_once_with(PatchMode.AUTO, tmp_path.resolve())
