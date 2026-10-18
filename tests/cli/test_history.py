"""Tests for the `batho history` CLI subcommand."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from batho.cli.history import cmd_history
from batho.orchestrator.build import run_build, BuildOptions
from batho.orchestrator.patch import run_patch, PatchOptions


def _ns(root: Path, **over) -> argparse.Namespace:
    base = dict(root=root, run=None, entity=None, file=None, last=10, since=None, json=False)
    base.update(over)
    return argparse.Namespace(**base)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Built repo with one patch applied (≥2 runs, ≥1 changelog row)."""
    (tmp_path / "a.py").write_text("def fa():\n    return 1\n", encoding="utf-8")
    assert run_build(BuildOptions(root=tmp_path, force_full=True)).success
    (tmp_path / "a.py").write_text("def fa():\n    return 2\n", encoding="utf-8")
    res = run_patch(PatchOptions(root=tmp_path))
    assert res.success and res.changes_applied >= 1
    return tmp_path


def test_history_lists_recent_runs(repo: Path, capsys):
    """Bare `batho history` lists runs newest-first with uuid/type/status."""
    assert cmd_history(_ns(repo)) == 0
    out = capsys.readouterr().out
    assert "patch_" in out and "build_" in out
    assert "showing" in out and "of" in out


def test_history_last_limits_list(repo: Path, capsys):
    """--last N caps the run list."""
    assert cmd_history(_ns(repo, last=1)) == 0
    out = capsys.readouterr().out
    assert "showing 1 of" in out
    # newest first → the single row is the patch run
    assert "patch_" in out and "build_" not in out


def test_history_list_json(repo: Path, capsys):
    assert cmd_history(_ns(repo, json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] >= 2
    assert payload["runs"][0]["run_uuid"].startswith("patch_")
    assert payload["runs"][0]["run_type"] == "patch"


def test_history_run_mode(repo: Path, capsys):
    """--run prints node changes for that run (unchanged diff semantics)."""
    from batho.modules.storage.arrow_bundle import get_bundle

    run_uuid = get_bundle(repo)._reader.get_latest_run_id()
    assert cmd_history(_ns(repo, run=run_uuid)) == 0
    out = capsys.readouterr().out
    assert f"Run: {run_uuid}" in out


def test_history_run_mode_not_found(repo: Path, capsys):
    assert cmd_history(_ns(repo, run="run-does-not-exist")) == 1
    assert "not found" in capsys.readouterr().err.lower()


def test_history_entity_respects_last(repo: Path, capsys):
    """--entity caps history at --last entries."""
    from batho.modules.storage.arrow_bundle import get_bundle

    db = get_bundle(repo)
    rows = db.get_run_file_changelog(db._reader.get_latest_run_id())
    assert rows
    entity_id = rows[0]["entity_id"]
    assert cmd_history(_ns(repo, entity=entity_id, last=1)) == 0
    out = capsys.readouterr().out
    # one transition line per history entry
    assert out.count("→") == 1


def test_history_file_mode(repo: Path, capsys):
    assert cmd_history(_ns(repo, file="a.py")) == 0
    out = capsys.readouterr().out
    assert "File: a.py" in out


def test_history_since_requires_entity(repo: Path, capsys):
    """--since without --entity is a usage error (unchanged from diff)."""
    assert cmd_history(_ns(repo, file="a.py", since="whatever")) == 1
    assert "--entity" in capsys.readouterr().err


def test_history_no_bundle(tmp_path: Path, capsys):
    assert cmd_history(_ns(tmp_path)) == 1
    assert "No artifact bundle" in capsys.readouterr().err


def test_diff_subcommand_removed():
    """Hard rename: `batho diff` is gone (argparse rejects unknown subcommand)."""
    from batho_cli import _build_parser

    with pytest.raises(SystemExit):
        _build_parser().parse_args(["diff", "--run", "x"])
