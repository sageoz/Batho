"""Regression test for build/patch hash consistency bug.

This test verifies that `batho patch` reports 0 changes immediately after
`batho build` completes, ensuring hash computation is consistent between
the two operations.

Bug fixed: Previously, build.py used simple SHA256 for all files, while
patch.py used content-aware hashing that returned `size_mtime` format
for binary files instead of SHA256. This caused binary files to always
appear "modified" even when unchanged.
"""

import os
import tempfile
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def test_repo_with_mixed_files():
    """Create a test repo with text, binary, and special files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)

        # Create text files
        (root / "main.py").write_text(
            "def main():\n    print('hello')\n\nif __name__ == '__main__':\n    main()\n"
        )
        (root / "utils.py").write_text(
            "def helper():\n    return 42\n"
        )
        (root / "README.md").write_text("# Test Project\n\nA test project.\n")

        # Create a binary file (PNG header)
        (root / "image.png").write_bytes(
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        )

        # Create another binary file (simulated .woff2)
        (root / "font.woff2").write_bytes(
            b"wOF2" + os.urandom(50)
        )

        # Create a zip file
        zip_path = root / "archive.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("test.txt", "hello world")

        # Create empty file
        (root / "empty.txt").write_text("")

        # Create subdirectory with files
        subdir = root / "subdir"
        subdir.mkdir()
        (subdir / "nested.py").write_text("def nested(): pass\n")

        yield root


def test_build_then_patch_reports_no_changes(test_repo_with_mixed_files):
    """Verify patch reports 0 changes immediately after build."""
    from batho.orchestrator.build import BuildOptions, run_build
    from batho.orchestrator.patch import PatchOptions, run_patch
    from batho.modules.storage.arrow_bundle import resolve_bundle_dir
    import shutil

    root = test_repo_with_mixed_files

    # Clean up any existing bundle
    bundle_dir = resolve_bundle_dir(root)
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir, ignore_errors=True)

    # Run build
    build_options = BuildOptions(root=root, force_full=True, verbose=False)
    build_result = run_build(build_options)

    assert build_result.success, f"Build failed: {build_result.warnings}"
    assert (bundle_dir / "meta.json").exists(), "Bundle should exist after build"

    # Immediately run patch - should report no changes
    patch_options = PatchOptions(root=root, verbose=False)
    patch_result = run_patch(patch_options)

    assert patch_result.success, f"Patch failed: {patch_result.warnings}"

    # The key assertion: patch should detect 0 changes
    # The result should either have a "no changes" warning or 0 changes_applied
    has_no_changes_warning = any(
        "No changes detected" in w for w in patch_result.warnings
    )

    assert has_no_changes_warning or patch_result.changes_applied == 0, (
        f"Patch detected changes immediately after build!\n"
        f"  Changes applied: {patch_result.changes_applied}\n"
        f"  Added: {patch_result.added}, Modified: {patch_result.modified}, Deleted: {patch_result.deleted}\n"
        f"  Warnings: {patch_result.warnings}\n"
        f"\n"
        f"This indicates a hash mismatch between build and patch operations.\n"
        f"Check that both use the same hash function (compute_file_hash from batho.utils.hash)."
    )


def test_build_then_patch_hash_scan_mode(test_repo_with_mixed_files):
    """Verify patch with hash scan mode works correctly after build."""
    from batho.orchestrator.build import BuildOptions, run_build
    from batho.orchestrator.patch import PatchOptions, run_patch
    from batho.modules.storage.arrow_bundle import resolve_bundle_dir
    import shutil

    root = test_repo_with_mixed_files

    # Clean up
    bundle_dir = resolve_bundle_dir(root)
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir, ignore_errors=True)

    # Run build
    build_options = BuildOptions(root=root, force_full=True, verbose=False)
    build_result = run_build(build_options)
    assert build_result.success

    # Run patch with explicit mode that forces hash scan
    # Note: In a non-git repo, this falls back to hash scan
    patch_options = PatchOptions(root=root, verbose=False)
    patch_result = run_patch(patch_options)

    assert patch_result.success

    # Should report no changes
    has_no_changes_warning = any(
        "No changes detected" in w for w in patch_result.warnings
    )
    assert has_no_changes_warning or patch_result.changes_applied == 0


def test_binary_file_hash_consistency():
    """Verify binary files get consistent SHA256 hashes from both functions."""
    import tempfile
    from batho.utils.hash import compute_file_hash

    # Create a binary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 1000)
        temp_path = Path(f.name)

    try:
        # Compute hash using the standardized function
        hash1 = compute_file_hash(temp_path)

        # Compute expected SHA256
        import hashlib
        expected_hash = hashlib.sha256(temp_path.read_bytes()).hexdigest()

        assert hash1 == expected_hash, (
            f"Binary file hash mismatch!\n"
            f"  compute_file_hash: {hash1}\n"
            f"  expected SHA256: {expected_hash}\n"
            f"Binary files should use SHA256, not size_mtime format."
        )

        # Ensure it doesn't return size_mtime format
        assert "_" not in hash1 or "T" not in hash1, (
            f"Hash appears to be in size_mtime format: {hash1}\n"
            f"Binary files should use SHA256, not size_mtime format."
        )
    finally:
        temp_path.unlink()


def test_text_file_hash_consistency():
    """Verify text files get consistent SHA256 hashes."""
    import tempfile
    from batho.utils.hash import compute_file_hash

    # Create a text file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".txt") as f:
        f.write("Hello, World!\nThis is a test.\n")
        temp_path = Path(f.name)

    try:
        # Compute hash using the standardized function
        hash1 = compute_file_hash(temp_path)

        # Compute expected SHA256
        import hashlib
        expected_hash = hashlib.sha256(temp_path.read_bytes()).hexdigest()

        assert hash1 == expected_hash, (
            f"Text file hash mismatch!\n"
            f"  compute_file_hash: {hash1}\n"
            f"  expected SHA256: {expected_hash}"
        )
    finally:
        temp_path.unlink()


def test_build_git_metadata_and_file_tracking_run_id(test_repo_with_mixed_files):
    """Verify that build correctly records run metadata and populates file_tracking."""
    import subprocess
    import shutil
    from batho.orchestrator.build import BuildOptions, run_build
    from batho.modules.storage.arrow_bundle import resolve_bundle_dir, get_bundle
    from batho.modules.graph.incremental import is_git_repo

    root = test_repo_with_mixed_files

    # Try initializing git repo in the test directory to test git metadata collection
    is_git = False
    try:
        subprocess.run(["git", "init"], cwd=str(root), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(root), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(root), check=True, capture_output=True)
        subprocess.run(["git", "add", "main.py"], cwd=str(root), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(root), check=True, capture_output=True)
        is_git = is_git_repo(root)
    except Exception:
        pass

    # Clean up any existing bundle
    bundle_dir = resolve_bundle_dir(root)
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir, ignore_errors=True)

    # Run build
    build_options = BuildOptions(root=root, force_full=True, verbose=False)
    build_result = run_build(build_options)

    assert build_result.success, f"Build failed: {build_result.warnings}"
    assert (resolve_bundle_dir(root) / "meta.json").exists(), "Bundle should exist after build"

    # Query via BathoBundle reader
    db = get_bundle(root)

    run_row = db._reader.get_run(build_result.run_id)
    assert run_row is not None, f"No run found with uuid {build_result.run_id}"

    if is_git:
        assert run_row.get("git_commit") is not None, "git_commit should not be null when inside a git repo"
        assert run_row.get("git_branch") is not None, "git_branch should not be null when inside a git repo"
    else:
        assert run_row.get("git_commit") is None, "git_commit should be null when not in a git repo"
        assert run_row.get("git_branch") is None, "git_branch should be null when not in a git repo"

    # Check file_tracking
    tracking_records = db.get_all_file_tracking()
    assert len(tracking_records) > 0, "file_tracking should have records populated after build"
    for file_path, record in tracking_records.items():
        assert record["last_run_uuid"] == build_result.run_id, (
            f"file {file_path} has last_run_uuid {record['last_run_uuid']}, expected {build_result.run_id}"
        )

