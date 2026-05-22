"""Tests for CLI command functions."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from batho.config import get_config_cached
from batho.context.bsg_map import BSGMap
from batho.context.codegraph import InMemoryGraph
from batho.context.incremental import GitDiffEntry
from batho.context.schema import Entity, EntityType
from batho.time_machine import FileChangeTracker, create_snapshot
from batho_cli import (
    cmd_hooks_install,
    cmd_hooks_list,
    cmd_hooks_remove,
    cmd_hooks_run,
    cmd_hooks_status,
    cmd_index,
    cmd_invalidate,
    cmd_patch,
    cmd_query,
    cmd_stats,
    cmd_storage_backfill,
    cmd_storage_cleanup,
    cmd_storage_rebuild_indexes,
    cmd_storage_stats,
    cmd_storage_verify,
    cmd_verify,
    cmd_export,
    cmd_reconstruct,
)

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

    def test_index_persists_bsg_quality_warning_stats(self, simple_python_repo: Path):
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

        ctn_dir = simple_python_repo / ".ctn"
        index_payload = json.loads((ctn_dir / "index.json").read_text(encoding="utf-8"))
        current_id = str(index_payload.get("current_index_id"))
        entry = index_payload.get("indexes", {}).get(current_id, {})
        stats = entry.get("stats", {})
        bsg_payload = json.loads(
            (ctn_dir / current_id / "bsg.json").read_text(encoding="utf-8")
        )

        assert "bsg_quality_warnings" in stats
        assert stats["bsg_quality_warnings"] == len(
            bsg_payload.get("quality_warnings", [])
        )
        assert "bsg_quality_warning_samples" in stats

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

    def test_index_auto_incremental_reuses_snapshot_when_no_git_changes(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        root = tmp_path / "repo"
        root.mkdir()
        src = root / "a.py"
        src.write_text("def alpha():\n    return 1\n", encoding="utf-8")

        ctn_dir = root / ".ctn"
        ctn_dir.mkdir()

        graph = InMemoryGraph()
        graph.add_entity(
            Entity(
                type=EntityType.FUNCTION,
                name="alpha",
                file="a.py",
                start_line=1,
                end_line=2,
                metadata={"language": "python"},
            )
        )
        bsg_map = BSGMap.build(graph, root=str(root))
        snapshot_id = create_snapshot(ctn_dir, root, graph, bsg_map, label="base")

        monkeypatch.setattr(
            "batho.get_changed_file_status_since",
            lambda *_args, **_kwargs: [],
        )

        args = argparse.Namespace(
            root=str(root),
            extensions=None,
            max_workers=0,
            max_file_size_kb=None,
            force=False,
            full=False,
            base_snapshot=snapshot_id,
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
        entry = index_payload.get("indexes", {}).get(current_id, {})
        assert entry.get("stats", {}).get("incremental") is True
        assert entry.get("stats", {}).get("changes_applied") == 0

    def test_index_auto_incremental_applies_patch_for_git_changes(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        root = tmp_path / "repo"
        root.mkdir()
        src = root / "a.py"
        src.write_text("def alpha():\n    return 1\n", encoding="utf-8")

        ctn_dir = root / ".ctn"
        ctn_dir.mkdir()

        graph = InMemoryGraph()
        graph.add_entity(
            Entity(
                type=EntityType.FUNCTION,
                name="alpha",
                file="a.py",
                start_line=1,
                end_line=2,
                metadata={"language": "python"},
            )
        )
        bsg_map = BSGMap.build(graph, root=str(root))
        snapshot_id = create_snapshot(ctn_dir, root, graph, bsg_map, label="base")

        monkeypatch.setattr(
            "batho.get_changed_file_status_since",
            lambda *_args, **_kwargs: [GitDiffEntry(status="M", path="a.py")],
        )
        monkeypatch.setattr(
            "batho.incremental_patch",
            lambda *_args, **_kwargs: {
                "success": True,
                "new_snapshot_id": snapshot_id,
                "applied_changes": 1,
            },
        )

        args = argparse.Namespace(
            root=str(root),
            extensions=None,
            max_workers=0,
            max_file_size_kb=None,
            force=False,
            full=False,
            base_snapshot=snapshot_id,
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
        entry = index_payload.get("indexes", {}).get(current_id, {})
        assert entry.get("stats", {}).get("incremental") is True
        assert entry.get("stats", {}).get("changes_applied") == 1

    def test_index_streaming_serialization_mode(
        self, simple_python_repo: Path, monkeypatch
    ):
        monkeypatch.setenv("BATHO_BSG_SERIALIZATION_METHOD", "streaming")
        get_config_cached.cache_clear()

        args = argparse.Namespace(
            root=str(simple_python_repo),
            extensions=None,
            max_workers=0,
            max_file_size_kb=None,
            force=True,
            full=False,
            base_snapshot=None,
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

        ctn_dir = simple_python_repo / ".ctn"
        index_payload = json.loads((ctn_dir / "index.json").read_text(encoding="utf-8"))
        current_id = str(index_payload.get("current_index_id"))
        bsg_payload = json.loads(
            (ctn_dir / current_id / "bsg.json").read_text(encoding="utf-8")
        )
        assert "nodes" in bsg_payload
        assert "edges" in bsg_payload
        assert isinstance(bsg_payload.get("quality_warnings"), list)
        get_config_cached.cache_clear()

    def test_index_creates_context_json_files(self, simple_python_repo: Path):
        args = argparse.Namespace(
            root=str(simple_python_repo),
            extensions=None,
            max_workers=0,
            max_file_size_kb=None,
            force=True,
            full=False,
            base_snapshot=None,
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

        ctn_dir = simple_python_repo / ".ctn"
        index_payload = json.loads((ctn_dir / "index.json").read_text(encoding="utf-8"))
        current_id = str(index_payload.get("current_index_id"))

        overview_json_path = ctn_dir / current_id / "context" / "json" / "overview.json"
        files_json_path = ctn_dir / current_id / "context" / "json" / "files.json"

        assert overview_json_path.exists()
        assert files_json_path.exists()

        overview = json.loads(overview_json_path.read_text(encoding="utf-8"))
        assert overview["schema_version"] == "context-overview.v1"
        assert "summary" in overview
        assert "file_distribution" in overview

        files = json.loads(files_json_path.read_text(encoding="utf-8"))
        assert files["schema_version"] == "context-files.v1"
        assert "categories" in files
        assert "summary" in files

    def test_index_json_outputs_in_index_metadata(self, simple_python_repo: Path):
        args = argparse.Namespace(
            root=str(simple_python_repo),
            extensions=None,
            max_workers=0,
            max_file_size_kb=None,
            force=True,
            full=False,
            base_snapshot=None,
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

        ctn_dir = simple_python_repo / ".ctn"
        index_payload = json.loads((ctn_dir / "index.json").read_text(encoding="utf-8"))
        current_id = str(index_payload.get("current_index_id"))
        entry = index_payload.get("indexes", {}).get(current_id, {})
        outputs = entry.get("outputs", {})

        assert "overview_json" in outputs
        assert "files_json" in outputs
        assert outputs["overview_json"].endswith("context/json/overview.json")
        assert outputs["files_json"].endswith("context/json/files.json")

# ---------------------------------------------------------------------------
# cmd_stats
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
        metrics_dir = ctn_dir / "local" / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        interception_file = metrics_dir / "interception_stats.json"
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
        cache_dir = simple_python_repo / ".ctn" / "local" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "cache.db"
        cache_file.write_text("fake cache")

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

class TestCmdStorageAndQuery:
    def test_storage_backfill_and_verify_commands(
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
        assert cmd_index(idx_args) == 0

        capsys.readouterr()

        backfill_args = argparse.Namespace(root=str(simple_python_repo))
        backfill_result = cmd_storage_backfill(backfill_args)
        assert backfill_result == 0
        backfill_payload = json.loads(capsys.readouterr().out)
        assert backfill_payload.get("enabled") is True

        verify_args = argparse.Namespace(root=str(simple_python_repo), repair=False)
        verify_result = cmd_storage_verify(verify_args)
        assert verify_result == 0
        verify_payload = json.loads(capsys.readouterr().out)
        assert "missing_on_disk" in verify_payload
        assert "unregistered_on_disk" in verify_payload

    def test_storage_cleanup_command_dry_run(
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
        assert cmd_index(idx_args) == 0

        ctn_dir = simple_python_repo / ".ctn"
        registry_db = ctn_dir / "local" / "sync" / "artifact_registry.db"
        with sqlite3.connect(str(registry_db)) as conn:
            conn.execute(
                "UPDATE artifacts SET updated_at = '2000-01-01T00:00:00+00:00'"
            )
            conn.commit()

        capsys.readouterr()

        cleanup_args = argparse.Namespace(root=str(simple_python_repo), apply=False)
        cleanup_result = cmd_storage_cleanup(cleanup_args)
        assert cleanup_result == 0

        payload = json.loads(capsys.readouterr().out)
        assert payload.get("dry_run") is True
        assert "candidates" in payload

    def test_storage_stats_command(self, simple_python_repo: Path, capsys):
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
        assert cmd_index(idx_args) == 0

        capsys.readouterr()
        stats_args = argparse.Namespace(root=str(simple_python_repo), index_id=None)
        assert cmd_storage_stats(stats_args) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload.get("registry", {}).get("artifact_count", 0) >= 1
        assert "graph_cache" in payload

    def test_storage_rebuild_indexes_command(self, simple_python_repo: Path, capsys):
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
        assert cmd_index(idx_args) == 0

        capsys.readouterr()
        rebuild_args = argparse.Namespace(root=str(simple_python_repo), index_id=None)
        assert cmd_storage_rebuild_indexes(rebuild_args) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload.get("index_id")
        assert "entities_indexed" in payload
        assert "relationships_indexed" in payload

    def test_query_command_entity_type(self, simple_python_repo: Path, capsys):
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
        assert cmd_index(idx_args) == 0

        capsys.readouterr()

        query_args = argparse.Namespace(
            root=str(simple_python_repo),
            index_id=None,
            entity_type="function",
            file_path=None,
            relationship_type=None,
            limit=20,
            rebuild_index=False,
        )
        result = cmd_query(query_args)
        assert result == 0

        payload = json.loads(capsys.readouterr().out)
        assert payload.get("mode") == "entities_by_type"
        assert payload.get("index_id")
        assert isinstance(payload.get("rows"), list)


class TestCmdHooks:
    @staticmethod
    def _init_git_repo(root: Path) -> None:
        (root / ".git" / "hooks").mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _write_hooks_yaml(root: Path, content: str) -> None:
        cfg_path = root / ".batho" / "hooks.yaml"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(content, encoding="utf-8")

    def test_hooks_list_and_status(self, tmp_path: Path, capsys):
        root = tmp_path / "repo"
        root.mkdir()
        self._init_git_repo(root)
        self._write_hooks_yaml(
            root,
            (
                "version: hooks.v1\n"
                "hooks:\n"
                "  pre-commit:\n"
                "    enabled: true\n"
                "    stages:\n"
                "      - run: echo pre-commit\n"
                "  enterprise-nightly:\n"
                "    enabled: true\n"
                "    stages:\n"
                "      - run: echo nightly\n"
            ),
        )

        list_args = argparse.Namespace(root=str(root))
        assert cmd_hooks_list(list_args) == 0
        list_payload = json.loads(capsys.readouterr().out)
        assert "pre-commit" in list_payload.get("configured_hooks", [])
        assert "enterprise-nightly" in list_payload.get("configured_hooks", [])

        status_args = argparse.Namespace(root=str(root), hook="pre-commit")
        assert cmd_hooks_status(status_args) == 0
        status_payload = json.loads(capsys.readouterr().out)
        assert status_payload.get("hooks", [])[0].get("installed") is False

    def test_hooks_install_bootstrap_and_run_custom(self, tmp_path: Path, capsys):
        root = tmp_path / "repo"
        root.mkdir()
        self._init_git_repo(root)

        install_args = argparse.Namespace(
            root=str(root),
            hook=None,
            all=True,
            force=False,
            dry_run=False,
        )
        assert cmd_hooks_install(install_args) == 0
        payload = json.loads(capsys.readouterr().out)
        assert (root / ".batho" / "hooks.yaml").exists()
        assert "pre-commit" in payload.get("installed", [])
        assert any(
            "enterprise-nightly" in warning for warning in payload.get("warnings", [])
        )

        run_args = argparse.Namespace(
            root=str(root),
            hook="enterprise-nightly",
            dry_run=True,
            verbose=False,
        )
        assert cmd_hooks_run(run_args) == 0
        run_payload = json.loads(capsys.readouterr().out)
        assert run_payload.get("hook") == "enterprise-nightly"
        assert run_payload.get("success") is True

    def test_hooks_install_collision_and_force_remove(self, tmp_path: Path, capsys):
        root = tmp_path / "repo"
        root.mkdir()
        self._init_git_repo(root)
        self._write_hooks_yaml(
            root,
            (
                "version: hooks.v1\n"
                "hooks:\n"
                "  pre-commit:\n"
                "    enabled: true\n"
                "    stages:\n"
                "      - run: echo ok\n"
            ),
        )

        unmanaged = root / ".git" / "hooks" / "pre-commit"
        unmanaged.write_text("#!/usr/bin/env sh\necho unmanaged\n", encoding="utf-8")

        no_force_args = argparse.Namespace(
            root=str(root),
            hook=None,
            all=True,
            force=False,
            dry_run=False,
        )
        assert cmd_hooks_install(no_force_args) == 0
        no_force_payload = json.loads(capsys.readouterr().out)
        assert any(
            item.get("reason") == "unmanaged_collision"
            for item in no_force_payload.get("skipped", [])
        )

        force_args = argparse.Namespace(
            root=str(root),
            hook=None,
            all=True,
            force=True,
            dry_run=False,
        )
        assert cmd_hooks_install(force_args) == 0
        force_payload = json.loads(capsys.readouterr().out)
        assert "pre-commit" in force_payload.get("installed", [])
        assert "BATHO_MANAGED_HOOK" in unmanaged.read_text(encoding="utf-8")

        remove_args = argparse.Namespace(
            root=str(root),
            hook=None,
            all=True,
            dry_run=False,
        )
        assert cmd_hooks_remove(remove_args) == 0
        remove_payload = json.loads(capsys.readouterr().out)
        assert "pre-commit" in remove_payload.get("removed", [])
        assert not unmanaged.exists()


# ---------------------------------------------------------------------------
# cmd_reconstruct
# ---------------------------------------------------------------------------


class TestCmdReconstruct:

    def test_reconstruct_with_output(self, simple_python_repo: Path, capsys, tmp_path: Path):
        """Reconstruct with --output writes file."""
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
            base_snapshot=None,
            full=False,
            no_ast_cache=True,
            with_gaps=None,
            storage_view=None,
        )
        assert cmd_index(idx_args) == 0
        capsys.readouterr()

        # Find an indexed file
        target = "src/calculator.py"
        out_file = tmp_path / "reconstructed_calculator.py"

        rec_args = argparse.Namespace(
            root=str(simple_python_repo),
            file=target,
            verify=False,
            output=str(out_file),
        )
        result = cmd_reconstruct(rec_args)
        assert result == 0
        assert out_file.exists()
        assert out_file.read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# cmd_verify
# ---------------------------------------------------------------------------


class TestCmdVerify:

    def test_verify_no_file_flag(self, simple_python_repo: Path, capsys):
        """verify without --file or --all returns 1."""
        args = argparse.Namespace(
            root=str(simple_python_repo),
            file=None,
            all=False,
            report_json=None,
        )
        result = cmd_verify(args)
        # No index yet, errors out before --file/--all check
        assert result == 1

    def test_verify_file_success(self, simple_python_repo: Path, capsys):
        """verify --file on indexed repo returns 0 when snapshot exists."""
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
            base_snapshot=None,
            full=False,
            no_ast_cache=True,
            with_gaps=True,
            storage_view=None,
        )
        assert cmd_index(idx_args) == 0
        capsys.readouterr()

        # Note: full integrity verification requires FileSnapshots populated
        # via the storage view pipeline. This test validates the CLI path
        # succeeds for an indexed repo with raw_content available.
        verify_args = argparse.Namespace(
            root=str(simple_python_repo),
            file="src/calculator.py",
            all=False,
            report_json=None,
        )
        result = cmd_verify(verify_args)
        assert result == 0

    def test_verify_report_json(self, simple_python_repo: Path, capsys, tmp_path: Path):
        """verify --report-json writes structured report."""
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
            base_snapshot=None,
            full=False,
            no_ast_cache=True,
            with_gaps=True,
            storage_view=None,
        )
        assert cmd_index(idx_args) == 0
        capsys.readouterr()

        report_file = tmp_path / "verify_report.json"
        verify_args = argparse.Namespace(
            root=str(simple_python_repo),
            file="src/calculator.py",
            all=False,
            report_json=str(report_file),
        )
        result = cmd_verify(verify_args)
        assert result == 0
        assert report_file.exists()
        report = json.loads(report_file.read_text(encoding="utf-8"))
        assert "total" in report
        assert "passed" in report
        assert "results" in report


# ---------------------------------------------------------------------------
# cmd_export
# ---------------------------------------------------------------------------


class TestCmdExport:

    def test_export_without_bsg_flag(self, simple_python_repo: Path, capsys):
        """export without --bsg flag returns 1."""
        args = argparse.Namespace(
            root=str(simple_python_repo),
            bsg=False,
            file="src/calculator.py",
            output=None,
        )
        result = cmd_export(args)
        assert result == 1

    def test_export_bsg_file(self, simple_python_repo: Path, capsys, tmp_path: Path):
        """export --bsg --file reconstructs and writes output."""
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
            base_snapshot=None,
            full=False,
            no_ast_cache=True,
            with_gaps=None,
            storage_view=None,
        )
        assert cmd_index(idx_args) == 0
        capsys.readouterr()

        out_file = tmp_path / "exported_calculator.py"
        export_args = argparse.Namespace(
            root=str(simple_python_repo),
            bsg=True,
            file="src/calculator.py",
            output=str(out_file),
        )
        result = cmd_export(export_args)
        assert result == 0
        assert out_file.exists()
        assert out_file.read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# cmd_index — bidirectional flags
# ---------------------------------------------------------------------------


class TestCmdIndexBidirectional:

    def test_index_with_storage_view(self, simple_python_repo: Path, capsys):
        """index --storage-view produces bsg_storage_view.json."""
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
            base_snapshot=None,
            full=False,
            no_ast_cache=True,
            with_gaps=True,
            storage_view=True,
        )
        result = cmd_index(idx_args)
        assert result == 0
        capsys.readouterr()

        ctn_dir = simple_python_repo / ".ctn"
        metadata = json.loads((ctn_dir / "index.json").read_text(encoding="utf-8"))
        current_id = metadata.get("current_index_id")
        assert current_id

        sv_path = ctn_dir / current_id / "bsg_storage_view.json"
        assert sv_path.exists()
        sv_data = json.loads(sv_path.read_text(encoding="utf-8"))
        assert "view_type" in sv_data
        assert sv_data.get("view_type") == "storage"
