"""Tests for git-aware incremental helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from batho_core.context.incremental import (
    GitDiffEntry,
    _parse_name_status_output,
    extract_snapshot_commit,
    get_changed_file_status_since,
    get_changed_files_since,
    parse_snapshot_commit,
)


class TestSnapshotCommitParsing:
    def test_parse_snapshot_commit_new_format(self):
        commit = parse_snapshot_commit(
            "batho_repo_0123456789abcdef0123456789abcdef_20260404T120000000000Z"
        )
        assert commit == "0123456789abcdef0123456789abcdef"

    def test_parse_snapshot_commit_legacy_format_returns_none(self):
        assert parse_snapshot_commit("batho_1234abcd_20260404T120000Z") is None

    def test_extract_snapshot_commit_from_payload_metadata(self):
        snapshot_payload = {
            "git_metadata": {"commit_sha": "abcdef1234567890abcdef1234567890abcdef12"}
        }
        commit = extract_snapshot_commit("batho_legacy_20260404T120000Z", snapshot_payload)
        assert commit == "abcdef1234567890abcdef1234567890abcdef12"


class TestParseNameStatusOutput:
    def test_parse_name_status_handles_rename_as_delete_plus_add(self):
        output = "R100\told/path.py\tnew/path.py\n"
        entries = _parse_name_status_output(output)
        assert GitDiffEntry(status="D", path="old/path.py") in entries
        assert GitDiffEntry(status="A", path="new/path.py") in entries

    def test_parse_name_status_filters_unknown_status(self):
        output = "X\tunknown.txt\nM\tsrc/a.py\n"
        entries = _parse_name_status_output(output)
        assert GitDiffEntry(status="M", path="src/a.py") in entries
        assert all(entry.path != "unknown.txt" for entry in entries)


class TestChangedFilesSince:
    def test_get_changed_file_status_since_returns_none_when_not_git(self, monkeypatch):
        monkeypatch.setattr("batho_core.context.incremental.is_git_repo", lambda _: False)
        result = get_changed_file_status_since("batho_x_y_z", Path("."), {})
        assert result is None

    def test_get_changed_file_status_since_returns_entries(self, monkeypatch):
        monkeypatch.setattr("batho_core.context.incremental.is_git_repo", lambda _: True)
        monkeypatch.setattr(
            "batho_core.context.incremental.extract_snapshot_commit",
            lambda *_args, **_kwargs: "abc1234",
        )
        monkeypatch.setattr(
            "batho_core.context.incremental._run_git",
            lambda *_args, **_kwargs: SimpleNamespace(stdout="M\tsrc/a.py\nA\tsrc/b.py\n"),
        )

        entries = get_changed_file_status_since("snap", Path("."), {})
        assert entries is not None
        assert GitDiffEntry(status="M", path="src/a.py") in entries
        assert GitDiffEntry(status="A", path="src/b.py") in entries

    def test_get_changed_files_since_returns_unique_paths(self, monkeypatch):
        monkeypatch.setattr(
            "batho_core.context.incremental.get_changed_file_status_since",
            lambda *_args, **_kwargs: [
                GitDiffEntry(status="M", path="src/a.py"),
                GitDiffEntry(status="A", path="src/a.py"),
                GitDiffEntry(status="D", path="src/c.py"),
            ],
        )

        paths = get_changed_files_since("snap", Path("."), {})
        assert paths == ["src/a.py", "src/c.py"]
