import os
import sys
import shutil
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import contextvars

from batho.config import set_active_root, get_active_root, get_config_cached
from batho.orchestrator.build import BuildOptions, run_build
from batho.orchestrator.patch import PatchOptions, run_patch
from batho.orchestrator.export import ExportOptions, run_export
from batho.storage.engine import get_database, artifact_filename, close_all_databases
from batho.cli.diff import cmd_diff
from batho.cli.fix import cmd_fix
from batho.cli._utils import find_workspace_with_db


@pytest.fixture(autouse=True)
def clean_caches():
    close_all_databases()
    from batho.config import _active_root, _get_config_cached_for_root
    _active_root.set(None)
    _get_config_cached_for_root.cache_clear()
    yield
    close_all_databases()
    _active_root.set(None)
    _get_config_cached_for_root.cache_clear()


@pytest.fixture
def temp_project():
    """Create a temporary directory structure for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        # Create a simple python file to index
        (root / "main.py").write_text("def hello():\n    print('world')\n")
        yield root


# --- Core Correctness Tests ---

def test_build_artifact_in_root_not_cwd(temp_project, monkeypatch):
    other_dir = temp_project / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)
    
    options = BuildOptions(root=temp_project, force_full=True, verbose=False)
    res = run_build(options)
    assert res.success
    
    expected_db = temp_project / artifact_filename(temp_project)
    assert expected_db.exists()
    
    # Assert nothing was created in other_dir
    assert not list(other_dir.glob("artifact_*.batho"))


def test_patch_uses_root_not_cwd(temp_project, monkeypatch):
    options = BuildOptions(root=temp_project, force_full=True, verbose=False)
    build_res = run_build(options)
    assert build_res.success
    
    other_dir = temp_project / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)
    
    # Modify a file in the project
    (temp_project / "main.py").write_text("def hello():\n    print('world')\n# modified\n")
    
    patch_options = PatchOptions(root=temp_project, verbose=False)
    patch_res = run_patch(patch_options)
    assert patch_res.success
    assert patch_res.changes_applied > 0


def test_export_output_defaults_to_root(temp_project, monkeypatch):
    options = BuildOptions(root=temp_project, force_full=True, verbose=False)
    build_res = run_build(options)
    assert build_res.success
    
    other_dir = temp_project / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)
    
    export_options = ExportOptions(root=temp_project, output=None)
    export_res = run_export(export_options)
    assert export_res.success
    
    expected_export = temp_project / "batho_export.json"
    assert expected_export.exists()
    assert not (other_dir / "batho_export.json").exists()


def test_export_explicit_output_honoured(temp_project, monkeypatch):
    options = BuildOptions(root=temp_project, force_full=True, verbose=False)
    build_res = run_build(options)
    assert build_res.success
    
    other_dir = temp_project / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)
    
    custom_output = other_dir / "custom.json"
    export_options = ExportOptions(root=temp_project, output=custom_output)
    export_res = run_export(export_options)
    assert export_res.success
    assert custom_output.exists()
    assert not (temp_project / "batho_export.json").exists()


def test_config_loaded_from_root_batho_yaml(temp_project, monkeypatch):
    # Write custom batho.yaml to temp_project
    (temp_project / "batho.yaml").write_text("indexer:\n  max_file_size_kb: 9999\n")
    
    other_dir = temp_project / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)
    
    # We must call set_active_root since that's what orchestrator does
    set_active_root(temp_project)
    cfg = get_config_cached()
    assert cfg["indexer"]["max_file_size_kb"] == 9999


def test_two_projects_independent_artifacts(temp_project):
    proj_a = temp_project / "proj_a"
    proj_b = temp_project / "proj_b"
    proj_a.mkdir()
    proj_b.mkdir()
    
    (proj_a / "main.py").write_text("def a(): pass\n")
    (proj_b / "main.py").write_text("def b(): pass\n")
    
    # Build A
    options_a = BuildOptions(root=proj_a, force_full=True, verbose=False)
    res_a = run_build(options_a)
    assert res_a.success
    
    # Build B
    options_b = BuildOptions(root=proj_b, force_full=True, verbose=False)
    res_b = run_build(options_b)
    assert res_b.success
    
    db_a = proj_a / artifact_filename(proj_a)
    db_b = proj_b / artifact_filename(proj_b)
    
    assert db_a.exists()
    assert db_b.exists()
    
    db_instance_a = get_database(proj_a)
    db_instance_b = get_database(proj_b)
    
    assert db_instance_a.get_latest_run_id() is not None
    assert db_instance_b.get_latest_run_id() is not None
    assert db_instance_a.get_latest_run_id() != db_instance_b.get_latest_run_id()


def test_set_active_root_clears_cache(temp_project):
    proj_a = temp_project / "proj_a"
    proj_b = temp_project / "proj_b"
    proj_a.mkdir()
    proj_b.mkdir()
    
    (proj_a / "batho.yaml").write_text("indexer:\n  max_file_size_kb: 1111\n")
    (proj_b / "batho.yaml").write_text("indexer:\n  max_file_size_kb: 2222\n")
    
    set_active_root(proj_a)
    cfg_a = get_config_cached()
    assert cfg_a["indexer"]["max_file_size_kb"] == 1111
    
    set_active_root(proj_b)
    cfg_b = get_config_cached()
    assert cfg_b["indexer"]["max_file_size_kb"] == 2222


# --- Edge Case Tests ---

def test_root_with_symlink(temp_project, monkeypatch):
    real_proj = temp_project / "real"
    real_proj.mkdir()
    (real_proj / "main.py").write_text("def hello(): pass\n")
    
    link_proj = temp_project / "link"
    os.symlink(real_proj, link_proj)
    
    other_dir = temp_project / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)
    
    options = BuildOptions(root=link_proj, force_full=True, verbose=False)
    res = run_build(options)
    assert res.success
    
    expected_db = real_proj / artifact_filename(real_proj)
    assert expected_db.exists()
    assert get_active_root() == real_proj


def test_root_with_trailing_slash(temp_project):
    path_str = str(temp_project) + "/"
    path_with_slash = Path(path_str)
    
    options = BuildOptions(root=path_with_slash, force_full=True, verbose=False)
    res = run_build(options)
    assert res.success
    
    expected_db = temp_project / artifact_filename(temp_project)
    assert expected_db.exists()


def test_root_nonexistent_raises_clean_error():
    nonexistent = Path("/nonexistent/path/here")
    options = BuildOptions(root=nonexistent, force_full=True, verbose=False)
    res = run_build(options)
    assert not res.success
    assert any("not exist" in w.lower() or "no such" in w.lower() for w in res.warnings)


def test_root_is_file_not_dir(temp_project):
    some_file = temp_project / "main.py"
    options = BuildOptions(root=some_file, force_full=True, verbose=False)
    res = run_build(options)
    assert not res.success
    assert any("not a directory" in w.lower() or "directory" in w.lower() for w in res.warnings)


def test_concurrent_builds_different_roots_no_config_bleed(temp_project):
    proj_a = temp_project / "proj_a"
    proj_b = temp_project / "proj_b"
    proj_a.mkdir()
    proj_b.mkdir()
    
    (proj_a / "batho.yaml").write_text("indexer:\n  max_file_size_kb: 1111\n")
    (proj_b / "batho.yaml").write_text("indexer:\n  max_file_size_kb: 2222\n")
    
    results = {}
    
    def worker_a():
        set_active_root(proj_a)
        time.sleep(0.05)
        results["a"] = get_config_cached()["indexer"]["max_file_size_kb"]
        
    def worker_b():
        set_active_root(proj_b)
        time.sleep(0.05)
        results["b"] = get_config_cached()["indexer"]["max_file_size_kb"]
        
    thread_a = threading.Thread(target=worker_a)
    thread_b = threading.Thread(target=worker_b)
    
    thread_a.start()
    thread_b.start()
    
    thread_a.join()
    thread_b.join()
    
    assert results["a"] == 1111
    assert results["b"] == 2222


def test_patch_on_nonexistent_artifact_clean_error(temp_project):
    options = PatchOptions(root=temp_project, verbose=False)
    res = run_patch(options)
    assert not res.success
    assert any("no artifact database found" in w.lower() or "database not found" in w.lower() for w in res.warnings)


def test_diff_from_different_cwd(temp_project, monkeypatch, capsys):
    options = BuildOptions(root=temp_project, force_full=True, verbose=False)
    build_res = run_build(options)
    assert build_res.success
    
    other_dir = temp_project / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)
    
    import argparse
    args = argparse.Namespace(
        root=temp_project,
        run="non-existent-run-uuid-123",
        entity=None,
        file=None,
        since=None,
        json=True
    )
    
    ret = cmd_diff(args)
    captured = capsys.readouterr()
    assert ret == 1
    assert "not found" in captured.err.lower()


def test_fix_from_different_cwd(temp_project, monkeypatch, capsys):
    options = BuildOptions(root=temp_project, force_full=True, verbose=False)
    build_res = run_build(options)
    assert build_res.success
    
    other_dir = temp_project / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)
    
    import argparse
    args = argparse.Namespace(
        root=temp_project,
        deep=False,
        dry_run=True,
        format="json",
        output=None,
        rollback_to=None,
        repair_only=None,
        create_checkpoint=None,
        no_audit=True
    )
    
    ret = cmd_fix(args)
    assert ret == 0


def test_no_legacy_batho_subdir_fallback(temp_project):
    legacy_dir = temp_project / ".batho"
    legacy_dir.mkdir()
    
    db_name = artifact_filename(temp_project)
    legacy_db = legacy_dir / db_name
    legacy_db.touch()
    
    res = find_workspace_with_db(temp_project)
    assert res is None


def test_artifact_filename_based_on_dirname():
    path_a = Path("/tmp/my-project")
    path_b = Path("/tmp/other-path/my-project")
    
    name_a = artifact_filename(path_a)
    name_b = artifact_filename(path_b)
    
    assert name_a == "artifact_my-project.batho"
    assert name_b == "artifact_my-project.batho"
