"""Tests for CLI command functions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from batho import cmd_index, cmd_invalidate, cmd_patch, cmd_stats, cmd_webhook
from batho_core.context.bsg_map import BSGMap
from batho_core.context.codegraph import InMemoryGraph
from batho_core.context.schema import Entity, EntityType
from batho_core.time_machine import FileChangeTracker, create_snapshot


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

    def test_index_overview_includes_evolution_ledger_insights(
        self,
        simple_python_repo: Path,
    ):
        ctn_dir = simple_python_repo / ".ctn"
        ctn_dir.mkdir(exist_ok=True)
        (ctn_dir / "evolution_ledger.json").write_text(
            json.dumps(
                {
                    "schema_version": "evolution-ledger.v1",
                    "updated_at": "2026-04-04T00:00:00+00:00",
                    "entries": [
                        {
                            "entry_id": "abc123",
                            "timestamp": "2026-04-04T00:00:00+00:00",
                            "source": "cli.patch.snapshot",
                            "dont_rule": "Don't patch without a valid base snapshot; refresh index/snapshot state first.",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

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
            verbose=False,
            log_json=False,
        )
        result = cmd_index(args)
        assert result == 0

        index_payload = json.loads((ctn_dir / "index.json").read_text(encoding="utf-8"))
        current_id = str(index_payload.get("current_index_id"))
        overview_path = ctn_dir / current_id / "context" / "overview.md"
        overview = overview_path.read_text(encoding="utf-8")
        assert "Evolution Ledger Insights" in overview
        assert "Don't patch without a valid base snapshot" in overview


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

    def test_stats_pretty_prints_interception_matrix(
        self,
        simple_python_repo: Path,
        capsys,
    ):
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

        ctn_dir = simple_python_repo / ".ctn"
        interception_file = ctn_dir / "interception_stats.json"
        interception_file.write_text(
            json.dumps(
                {
                    "schema_version": "interception-stats.v1",
                    "plugins": {
                        "bsg_schema_migration_enforcer": {
                            "plugin_id": "bsg_schema_migration_enforcer",
                            "name": "Schema Migration Enforcer",
                            "interceptions": 12,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        capsys.readouterr()
        args = argparse.Namespace(root=str(simple_python_repo))
        result = cmd_stats(args)

        captured = capsys.readouterr().out
        assert result == 0
        assert "Interception Matrix" in captured
        assert "Schema Migration Enforcer: 12 Interceptions" in captured


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

    def test_valid_payload_with_root_processes_synchronously(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ):
        root = tmp_path / "repo"
        root.mkdir()

        source_file = root / "a.py"
        source_file.write_text("print('hello')\n", encoding="utf-8")

        ctn_dir = root / ".ctn"
        ctn_dir.mkdir()

        graph = InMemoryGraph()
        graph.add_entity(
            Entity(
                type=EntityType.FUNCTION,
                name="hello",
                file=str(source_file),
                start_line=1,
                end_line=1,
                metadata={"language": "python"},
            )
        )
        bsg_map = BSGMap.build(graph, root=str(root))
        snapshot_id = create_snapshot(ctn_dir, root, graph, bsg_map, label="base")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "batho_core.webhook.processor.incremental_patch",
            lambda _ctn, _snapshot, _changes: {
                "success": True,
                "new_snapshot_id": f"{snapshot_id}-next",
            },
        )

        payload = {
            "event": "push",
            "ref": "refs/heads/main",
            "after": "abc123",
            "repository": {"full_name": "u/r"},
            "commits": [{"modified": ["a.py"]}],
        }
        args = argparse.Namespace(
            root=str(root),
            payload=json.dumps(payload),
            headers=json.dumps({"X-GitHub-Event": "push"}),
        )

        result = cmd_webhook(args)
        assert result == 0

        lines = capsys.readouterr().out.strip().split("\n")
        json_start = None
        for i, line in enumerate(lines):
            if line.strip() == "{":
                json_start = i
                break
        assert json_start is not None
        data = json.loads("\n".join(lines[json_start:]))
        assert data["status"] == "processed"
        assert data.get("processing", {}).get("status") == "processed"


class TestCmdPatch:
    def test_snapshot_patch_failure_writes_evolution_ledger(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        root = tmp_path / "repo"
        root.mkdir()

        source_file = root / "a.py"
        source_file.write_text("print('hello')\n", encoding="utf-8")

        ctn_dir = root / ".ctn"
        ctn_dir.mkdir()

        graph = InMemoryGraph()
        graph.add_entity(
            Entity(
                type=EntityType.FUNCTION,
                name="hello",
                file="a.py",
                start_line=1,
                end_line=1,
                metadata={"language": "python"},
            )
        )
        bsg_map = BSGMap.build(graph, root=str(root))
        snapshot_id = create_snapshot(ctn_dir, root, graph, bsg_map, label="base")

        monkeypatch.setattr(
            "batho.incremental_patch",
            lambda _ctn, _snapshot, _changes: {
                "success": False,
                "error": "Base snapshot not found",
                "operation_id": "op-123",
            },
        )

        args = argparse.Namespace(
            root=str(root),
            base_snapshot=snapshot_id,
            force_index_patch=False,
            diff=None,
            scan=False,
            files=[str(source_file)],
            snapshot=False,
            dry_run=False,
            max_file_size_kb=500,
        )

        result = cmd_patch(args)

        ledger_path = ctn_dir / "evolution_ledger.json"
        assert result == 1
        assert ledger_path.exists()

        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
        assert payload.get("entries")
        latest = payload["entries"][-1]
        assert latest.get("source") == "cli.patch.snapshot"
        assert "snapshot" in str(latest.get("dont_rule", "")).lower()

    def test_index_patch_scan_summary_tracks_added_modified_deleted(
        self,
        tmp_path: Path,
        capsys,
    ):
        root = tmp_path / "repo"
        root.mkdir()

        original = root / "a.py"
        original.write_text("def alpha():\n    return 1\n", encoding="utf-8")

        idx_args = argparse.Namespace(
            root=str(root),
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
        assert cmd_index(idx_args) == 0

        tracker = FileChangeTracker(root)
        tracker.scan_for_changes(max_file_size_kb=500)
        tracker.save(root / ".ctn" / "file_hashes.json")

        original.unlink()
        added = root / "b.py"
        added.write_text("def beta():\n    return 2\n", encoding="utf-8")

        capsys.readouterr()
        patch_args = argparse.Namespace(
            root=str(root),
            base_snapshot=None,
            force_index_patch=True,
            diff=None,
            scan=True,
            files=[],
            snapshot=False,
            dry_run=False,
            max_file_size_kb=500,
        )
        result = cmd_patch(patch_args)
        assert result == 0

        lines = capsys.readouterr().out.strip().split("\n")
        json_start = None
        for i, line in enumerate(lines):
            if line.strip() == "{":
                json_start = i
                break
        assert json_start is not None
        payload = json.loads("\n".join(lines[json_start:]))
        summary = payload.get("summary", {})
        assert summary.get("added", 0) >= 1
        assert summary.get("deleted", 0) >= 1
