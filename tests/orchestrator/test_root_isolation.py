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

from batho.core.config import set_active_root, get_active_root, get_config_cached
from batho.orchestrator.build import BuildOptions, run_build
from batho.orchestrator.patch import PatchOptions, run_patch
from batho.orchestrator.export import ExportOptions, run_export
from batho.modules.storage.arrow_bundle import get_bundle, resolve_bundle_dir
from batho.cli.diff import cmd_diff
from batho.cli.fix import cmd_fix


@pytest.fixture(autouse=True)
def clean_caches():
    from batho.core.config.loader import _active_root, _get_config_cached_for_root
    _active_root.set(None)
    _get_config_cached_for_root.cache_clear()
    yield
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
    """Verify that build artifacts are created in the project root, not the current working directory.

    Scenario:
        A build is triggered while the current working directory is a subdirectory of the project.
        The artifact bundle must still be placed under the project's root, not under the CWD.

    Execution Flow:
        1. Create a subdirectory "other" inside the temp project.
        2. Change the working directory to "other" using monkeypatch.
        3. Run `run_build` with the project root as the target.
        4. Assert the build succeeds and the bundle meta.json exists under the project root.
        5. Assert the bundle was NOT created under "other".

    Expectations:
        - Build output is anchored to the specified root directory, unaffected by the process CWD.
    """
    other_dir = temp_project / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)

    options = BuildOptions(root=temp_project, force_full=True, verbose=False)
    res = run_build(options)
    assert res.success

    bundle_dir = resolve_bundle_dir(temp_project)
    assert (bundle_dir / "meta.json").exists()

    # Assert artifact bundle was not created under other_dir
    assert not (other_dir / ".batho" / "artifact").exists()


def test_patch_uses_root_not_cwd(temp_project, monkeypatch):
    """Verify that patch operations target the project root, not the current working directory.

    Scenario:
        After a successful build, the CWD is changed to a subdirectory, and a file in the project is modified.
        The patch must still detect and apply changes to the project's root.

    Execution Flow:
        1. Run a full build on the temp project.
        2. Create and chdir into a subdirectory "other".
        3. Modify the project's main.py file.
        4. Run `run_patch` targeting the project root.
        5. Assert the patch succeeds and at least one change is applied.

    Expectations:
        - Patch detects changes in the root project regardless of the current working directory.
    """
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
    """Verify that export writes the artifact to the project root by default, not the CWD.

    Scenario:
        After building, the CWD is changed to a subdirectory, and export is run without an explicit output path.
        The artifact must be placed in the project root.

    Execution Flow:
        1. Run a full build on the temp project.
        2. Create and chdir into a subdirectory "other".
        3. Run `run_export` with output=None.
        4. Assert the export succeeds and the artifact exists under the project root.
        5. Assert the artifact does NOT exist under "other".

    Expectations:
        - Default export output is anchored to the project root directory.
    """
    options = BuildOptions(root=temp_project, force_full=True, verbose=False)
    build_res = run_build(options)
    assert build_res.success

    other_dir = temp_project / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)
    
    export_options = ExportOptions(root=temp_project, output=None)
    export_res = run_export(export_options)
    assert export_res.success
    
    root_name = temp_project.resolve().name
    sanitized = __import__("re").sub(r"[^a-z0-9_-]", "-", root_name.lower()).strip("-")
    expected_export = temp_project / f"artifact_{sanitized}.batho"
    assert expected_export.exists()
    assert not (other_dir / f"artifact_{sanitized}.batho").exists()


def test_export_explicit_output_honoured(temp_project, monkeypatch):
    """Verify that an explicit output path overrides the default root-based output.

    Scenario:
        After building, export is run with a custom output file path in a different directory.
        The artifact must be written exactly to the specified path.

    Execution Flow:
        1. Run a full build on the temp project.
        2. Create and chdir into a subdirectory "other".
        3. Run `run_export` with a custom output path inside "other".
        4. Assert the export succeeds, the custom file exists, and no artifact was written to the project root.

    Expectations:
        - Explicit output path is honored over the default root-based naming.
    """
    options = BuildOptions(root=temp_project, force_full=True, verbose=False)
    build_res = run_build(options)
    assert build_res.success

    other_dir = temp_project / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)
    
    custom_output = other_dir / "custom.batho"
    export_options = ExportOptions(root=temp_project, output=custom_output)
    export_res = run_export(export_options)
    assert export_res.success
    assert custom_output.exists()
    assert not (temp_project / "custom.batho").exists()


def test_config_loaded_from_root_batho_yaml(temp_project, monkeypatch):
    """Verify that configuration is loaded from the project's batho.yaml, not the CWD.

    Scenario:
        A custom batho.yaml exists in the project root, and the CWD is changed elsewhere.
        Config must still resolve from the project root.

    Execution Flow:
        1. Write a custom batho.yaml with a unique max_file_size_kb value to the project root.
        2. Create and chdir into a subdirectory "other".
        3. Call `set_active_root(temp_project)`.
        4. Fetch config via `get_config_cached()`.
        5. Assert the loaded config reflects the custom value from the project root.

    Expectations:
        - Config file resolution is anchored to the active root, not the process CWD.
    """
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
    """Verify that two separate projects in the same parent directory have independent artifacts.

    Scenario:
        Two projects (proj_a, proj_b) exist as sibling directories under the same parent.
        Each is built independently, and their artifact bundles must not overlap or share run IDs.

    Execution Flow:
        1. Create two sibling project directories with distinct main.py files.
        2. Run a full build on each project.
        3. Assert both builds succeed and each has its own meta.json.
        4. Query the latest run ID from each project's bundle.
        5. Assert the run IDs are different.

    Expectations:
        - Each project maintains an isolated artifact bundle with unique run identifiers.
    """
    proj_a = temp_project / "proj_a"
    proj_b = temp_project / "proj_b"
    proj_a.mkdir()
    proj_b.mkdir()

    (proj_a / "main.py").write_text("def a(): pass\n")
    (proj_b / "main.py").write_text("def b(): pass\n")

    res_a = run_build(BuildOptions(root=proj_a, force_full=True, verbose=False))
    assert res_a.success

    res_b = run_build(BuildOptions(root=proj_b, force_full=True, verbose=False))
    assert res_b.success

    assert (resolve_bundle_dir(proj_a) / "meta.json").exists()
    assert (resolve_bundle_dir(proj_b) / "meta.json").exists()

    db_a = get_bundle(proj_a)
    db_b = get_bundle(proj_b)

    assert db_a.get_latest_run_id() is not None
    assert db_b.get_latest_run_id() is not None
    assert db_a.get_latest_run_id() != db_b.get_latest_run_id()


def test_set_active_root_clears_cache(temp_project):
    """Verify that calling set_active_root clears the config cache for the new root.

    Scenario:
        Two projects have different batho.yaml configs. Switching the active root must
        reload the configuration rather than returning a stale cached value.

    Execution Flow:
        1. Create two projects with batho.yaml files containing different max_file_size_kb values.
        2. Set active root to proj_a and fetch cached config.
        3. Assert the value matches proj_a's config.
        4. Set active root to proj_b and fetch cached config.
        5. Assert the value matches proj_b's config.

    Expectations:
        - Config cache is invalidated and reloaded when the active root changes.
    """
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
    """Verify that build works correctly when the root path is a symlink.

    Scenario:
        The project root is accessed through a symbolic link. The build must resolve the symlink
        and place artifacts in the real directory, while the active root tracks the resolved path.

    Execution Flow:
        1. Create a real project directory with a main.py file.
        2. Create a symbolic link pointing to the real directory.
        3. Change CWD to a different directory.
        4. Run build using the symlink path as the root.
        5. Assert artifacts exist in the real directory and the active root is the resolved real path.

    Expectations:
        - Symlink roots are transparently resolved to their real paths for artifact placement.
    """
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

    assert (resolve_bundle_dir(real_proj) / "meta.json").exists()
    assert get_active_root() == real_proj


def test_root_with_trailing_slash(temp_project):
    """Verify that a root path with a trailing slash is handled correctly.

    Scenario:
        The root path is provided with a trailing slash, which should not cause path resolution
        errors or duplicate separators in artifact paths.

    Execution Flow:
        1. Construct a Path from the temp project string with an appended "/".
        2. Run build with this path as the root.
        3. Assert the build succeeds and the bundle meta.json exists.

    Expectations:
        - Trailing slashes in the root path are normalized without affecting artifact placement.
    """
    path_str = str(temp_project) + "/"
    path_with_slash = Path(path_str)

    options = BuildOptions(root=path_with_slash, force_full=True, verbose=False)
    res = run_build(options)
    assert res.success

    assert (resolve_bundle_dir(temp_project) / "meta.json").exists()


def test_root_nonexistent_raises_clean_error():
    """Verify that a non-existent root path produces a clean, descriptive error.

    Scenario:
        A build is invoked with a root directory that does not exist on the filesystem.
        The operation should fail gracefully with a meaningful warning message.

    Execution Flow:
        1. Define a path to a non-existent directory.
        2. Run build with this path as the root.
        3. Assert the build fails.
        4. Assert the warnings contain "not exist" or "no such".

    Expectations:
        - Missing root directories are detected early and reported with a clean error message.
    """
    nonexistent = Path("/nonexistent/path/here")
    options = BuildOptions(root=nonexistent, force_full=True, verbose=False)
    res = run_build(options)
    assert not res.success
    assert any("not exist" in w.lower() or "no such" in w.lower() for w in res.warnings)


def test_root_is_file_not_dir(temp_project):
    """Verify that passing a file path instead of a directory as root produces a clean error.

    Scenario:
        The root argument points to an existing file rather than a directory.
        The build must detect this and fail with an appropriate error message.

    Execution Flow:
        1. Use an existing file (main.py) as the root path.
        2. Run build with this file path as root.
        3. Assert the build fails.
        4. Assert the warnings contain "not a directory" or "directory".

    Expectations:
        - File paths provided as root are rejected with a descriptive error.
    """
    some_file = temp_project / "main.py"
    options = BuildOptions(root=some_file, force_full=True, verbose=False)
    res = run_build(options)
    assert not res.success
    assert any("not a directory" in w.lower() or "directory" in w.lower() for w in res.warnings)


def test_concurrent_builds_different_roots_no_config_bleed(temp_project):
    """Verify that concurrent builds on different roots do not leak config values between threads.

    Scenario:
        Two threads simultaneously set different active roots and read their respective configs.
        Each thread must see its own project's configuration without cross-contamination.

    Execution Flow:
        1. Create two projects with different batho.yaml values.
        2. Spawn two threads: worker_a sets root to proj_a, worker_b sets root to proj_b.
        3. Each thread reads its max_file_size_kb after a short sleep.
        4. Join both threads and assert each read the correct value.

    Expectations:
        - Per-thread active roots remain isolated; no config bleeding occurs between concurrent builds.
    """
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
    """Verify that patching a project with no existing artifact bundle produces a clean error.

    Scenario:
        A patch is run on a directory that has never been built, so no artifact bundle exists.
        The patch must fail gracefully with a meaningful message.

    Execution Flow:
        1. Run patch on the temp project without ever building it first.
        2. Assert the patch fails.
        3. Assert the warnings contain "no artifact" or "bundle".

    Expectations:
        - Missing bundles are detected and reported with a clean error before patching begins.
    """
    options = PatchOptions(root=temp_project, verbose=False)
    res = run_patch(options)
    assert not res.success
    assert any("no artifact" in w.lower() or "bundle" in w.lower() for w in res.warnings)


def test_diff_from_different_cwd(temp_project, monkeypatch, capsys):
    """Verify that the diff command works correctly when invoked from a different working directory.

    Scenario:
        After building, the CWD is changed to a subdirectory, and diff is run targeting the project root.
        The command must still operate on the project's artifact data.

    Execution Flow:
        1. Run a full build on the temp project.
        2. Create and chdir into a subdirectory "other".
        3. Invoke cmd_diff with the project root and a non-existent run UUID.
        4. Assert the command returns 1 and stderr contains "not found".

    Expectations:
        - CLI commands resolve the correct root artifact data regardless of the process CWD.
    """
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
    """Verify that the fix command works correctly when invoked from a different working directory.

    Scenario:
        After building, the CWD is changed to a subdirectory, and fix is run targeting the project root.
        The command must still operate on the project's artifact data.

    Execution Flow:
        1. Run a full build on the temp project.
        2. Create and chdir into a subdirectory "other".
        3. Invoke cmd_fix with the project root in dry-run mode.
        4. Assert the command returns 0 (success).

    Expectations:
        - CLI fix command resolves the correct root artifact data regardless of the process CWD.
    """
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




def test_bundle_dir_based_on_root():
    """Verify that the bundle directory path is derived correctly from the project root.

    Scenario:
        Two different root paths must each map to their own unique artifact subdirectory.

    Execution Flow:
        1. Define two distinct project paths.
        2. Resolve the bundle directory for each using resolve_bundle_dir.
        3. Assert each resolves to `.batho/artifact` under its respective root.

    Expectations:
        - Bundle directories are always located at `<root>/.batho/artifact`.
    """
    path_a = Path("/tmp/my-project")
    path_b = Path("/tmp/other-path/my-project")

    bundle_a = resolve_bundle_dir(path_a)
    bundle_b = resolve_bundle_dir(path_b)

    assert bundle_a == (path_a / ".batho" / "artifact").resolve()
    assert bundle_b == (path_b / ".batho" / "artifact").resolve()
