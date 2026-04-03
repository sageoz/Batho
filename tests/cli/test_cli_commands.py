"""Tests for CLI command functions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from batho import cmd_index, cmd_invalidate, cmd_stats, cmd_webhook


# ---------------------------------------------------------------------------
# cmd_index
# ---------------------------------------------------------------------------

class TestCmdIndex:

    def test_index_simple_repo(self, simple_python_repo: Path, tmp_path: Path):
        args = argparse.Namespace(
            root=str(simple_python_repo),
            extensions=None,
            max_workers=0,
            max_file_size_kb=None,
            force=False,
            budget_tokens=0,
            output_json=None,
            output_md=None,
            metrics_output=None,
            snapshot=False,
            snapshot_label=None,
            verbose=False,
            log_json=False,
        )
        result = cmd_index(args)
        assert result == 0

        # Verify outputs were created
        ctn_dir = simple_python_repo / ".ctn"
        assert ctn_dir.exists()
        index_path = ctn_dir / "index.json"
        assert index_path.exists()

    def test_index_nonexistent_root(self):
        args = argparse.Namespace(
            root="/nonexistent/path",
            extensions=None,
            max_workers=0,
            max_file_size_kb=None,
            force=False,
            budget_tokens=0,
            output_json=None,
            output_md=None,
            metrics_output=None,
            snapshot=False,
            snapshot_label=None,
            verbose=False,
            log_json=False,
        )
        result = cmd_index(args)
        assert result == 1

    def test_index_with_force(self, simple_python_repo: Path):
        args = argparse.Namespace(
            root=str(simple_python_repo),
            extensions=None,
            max_workers=0,
            max_file_size_kb=None,
            force=True,
            budget_tokens=0,
            output_json=None,
            output_md=None,
            metrics_output=None,
            snapshot=False,
            snapshot_label=None,
            verbose=True,
            log_json=False,
        )
        result = cmd_index(args)
        assert result == 0

    def test_index_writes_metrics(self, simple_python_repo: Path, tmp_path: Path):
        metrics_path = tmp_path / "metrics.json"
        args = argparse.Namespace(
            root=str(simple_python_repo),
            extensions=None,
            max_workers=0,
            max_file_size_kb=None,
            force=True,
            budget_tokens=0,
            output_json=None,
            output_md=None,
            metrics_output=str(metrics_path),
            snapshot=False,
            snapshot_label=None,
            verbose=False,
            log_json=False,
        )
        result = cmd_index(args)
        assert result == 0
        assert metrics_path.exists()
        payload = json.loads(metrics_path.read_text())
        assert payload.get("index_id")
        assert payload.get("stats")


# ---------------------------------------------------------------------------
# cmd_stats
# ---------------------------------------------------------------------------

class TestCmdStats:

    def test_stats_after_index(self, simple_python_repo: Path, capsys):
        # First index
        idx_args = argparse.Namespace(
            root=str(simple_python_repo),
            extensions=None,
            max_workers=0,
            max_file_size_kb=None,
            force=True,
            budget_tokens=0,
            output_json=None,
            output_md=None,
            metrics_output=None,
            snapshot=False,
            snapshot_label=None,
            verbose=False,
            log_json=False,
        )
        cmd_index(idx_args)

        # Clear captured output from index
        capsys.readouterr()

        # Then stats
        args = argparse.Namespace(root=str(simple_python_repo))
        result = cmd_stats(args)
        assert result == 0

    def test_stats_no_index(self, tmp_path: Path, capsys):
        root = tmp_path / "empty_repo"
        root.mkdir()
        args = argparse.Namespace(root=str(root))
        result = cmd_stats(args)
        assert result == 0


# ---------------------------------------------------------------------------
# cmd_invalidate
# ---------------------------------------------------------------------------

class TestCmdInvalidate:

    def test_invalidate_clears_cache(self, simple_python_repo: Path, capsys):
        # Create a cache file
        ctn_dir = simple_python_repo / ".ctn"
        ctn_dir.mkdir(exist_ok=True)
        cache_file = ctn_dir / "file_cache.json"
        cache_file.write_text("{}")

        args = argparse.Namespace(root=str(simple_python_repo))
        result = cmd_invalidate(args)
        assert result == 0
        assert not cache_file.exists()

    def test_invalidate_already_clear(self, tmp_path: Path, capsys):
        root = tmp_path / "repo"
        root.mkdir()
        args = argparse.Namespace(root=str(root))
        result = cmd_invalidate(args)
        assert result == 0


# ---------------------------------------------------------------------------
# cmd_webhook
# ---------------------------------------------------------------------------

class TestCmdWebhook:

    def test_valid_payload(self, capsys):
        args = argparse.Namespace(
            payload=(
                '{"event":"push","ref":"refs/heads/main","after":"abc123",'
                '"repository":{"full_name":"u/r"},"commits":[]}'
            )
        )
        result = cmd_webhook(args)
        assert result == 0

        captured = capsys.readouterr()
        # cmd_webhook prints JSON via json.dumps with indent=2; extract the JSON block
        lines = captured.out.strip().split('\n')
        # Find start of JSON object
        json_start = None
        for i, line in enumerate(lines):
            if line.strip() == '{':
                json_start = i
                break
        if json_start is not None:
            json_text = '\n'.join(lines[json_start:])
            data = json.loads(json_text)
            assert data["event"] == "push"
            assert data["status"] == "parsed"

    def test_invalid_payload(self):
        args = argparse.Namespace(payload="not json{{{")
        result = cmd_webhook(args)
        assert result == 1
