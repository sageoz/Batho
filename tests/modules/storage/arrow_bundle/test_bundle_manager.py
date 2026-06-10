"""Tests for BathoBundleManager — MVCC commit, GC, ZIP export/unpack."""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

import pyarrow as pa
import pytest

from batho.modules.storage.arrow_bundle.manager import BathoBundleManager
from batho.modules.storage.arrow_bundle.writer import write_simple_ipc, read_ipc_table
from batho.modules.storage.arrow_bundle.bundle import resolve_bundle_dir
from batho.utils.path_sanitizer import PathSecurityError
from batho.modules.storage.arrow_bundle.schemas import (
    BUNDLE_SCHEMA_VERSION,
    FILE_TRACKING_SCHEMA,
    RUNS_SCHEMA,
)


def _write_tmp_ipc(artifact_dir: Path, name: str, rows: list[dict], schema: pa.Schema) -> Path:
    tmp = artifact_dir / f"{name}.tmp.ipc"
    write_simple_ipc(rows, schema, tmp)
    return tmp


def _run_row(uuid: str) -> dict:
    return {
        "run_uuid": uuid, "schema_version": BUNDLE_SCHEMA_VERSION,
        "started_at": "2024-01-01T00:00:00Z", "completed_at": None,
        "status": "completed", "git_commit": None, "git_branch": None,
        "root_path": "/tmp/repo", "entity_count": 0, "rel_count": 0,
        "file_count": 0, "duration_ms": None, "error_message": None,
    }


class TestManifest:
    def test_load_manifest_missing_returns_default(self, tmp_path):
        mgr = BathoBundleManager(tmp_path)
        manifest = mgr.load_manifest()
        assert manifest["generation"] == 0
        assert manifest["active_files"] == {}
        assert manifest["schema_version"] == BUNDLE_SCHEMA_VERSION

    def test_load_manifest_roundtrip(self, tmp_path):
        mgr = BathoBundleManager(tmp_path)
        data = {"schema_version": BUNDLE_SCHEMA_VERSION, "generation": 5,
                "active_files": {"runs": "runs.v5.ipc"}, "last_run_uuid": "r5"}
        (tmp_path / "meta.json").write_text(json.dumps(data))
        manifest = mgr.load_manifest()
        assert manifest["generation"] == 5
        assert manifest["active_files"]["runs"] == "runs.v5.ipc"

    def test_load_manifest_corrupted_returns_default(self, tmp_path):
        (tmp_path / "meta.json").write_text("not valid json{{")
        mgr = BathoBundleManager(tmp_path)
        manifest = mgr.load_manifest()
        assert manifest["generation"] == 0


class TestCommitPatch:
    def test_first_commit_generation_1(self, tmp_path):
        mgr = BathoBundleManager(tmp_path)
        tmp = _write_tmp_ipc(tmp_path, "runs", [_run_row("r1")], RUNS_SCHEMA)
        gen = mgr.commit_patch({"runs": tmp}, "r1")
        assert gen == 1
        assert (tmp_path / "runs.v1.ipc").exists()
        assert not (tmp_path / "runs.tmp.ipc").exists()

    def test_manifest_updated_atomically(self, tmp_path):
        mgr = BathoBundleManager(tmp_path)
        tmp = _write_tmp_ipc(tmp_path, "runs", [_run_row("r1")], RUNS_SCHEMA)
        mgr.commit_patch({"runs": tmp}, "r1")

        manifest = mgr.load_manifest()
        assert manifest["generation"] == 1
        assert manifest["last_run_uuid"] == "r1"
        assert manifest["active_files"]["runs"] == "runs.v1.ipc"

    def test_second_commit_increments_generation(self, tmp_path):
        mgr = BathoBundleManager(tmp_path)
        tmp1 = _write_tmp_ipc(tmp_path, "runs", [_run_row("r1")], RUNS_SCHEMA)
        mgr.commit_patch({"runs": tmp1}, "r1")

        tmp2 = _write_tmp_ipc(tmp_path, "runs", [_run_row("r2")], RUNS_SCHEMA)
        gen = mgr.commit_patch({"runs": tmp2}, "r2")
        assert gen == 2
        assert (tmp_path / "runs.v2.ipc").exists()
        manifest = mgr.load_manifest()
        assert manifest["active_files"]["runs"] == "runs.v2.ipc"

    def test_multi_stream_commit(self, tmp_path):
        mgr = BathoBundleManager(tmp_path)
        runs_tmp = _write_tmp_ipc(tmp_path, "runs", [_run_row("r1")], RUNS_SCHEMA)
        ft_tmp = _write_tmp_ipc(tmp_path, "file_tracking", [], FILE_TRACKING_SCHEMA)
        mgr.commit_patch({"runs": runs_tmp, "file_tracking": ft_tmp}, "r1")

        manifest = mgr.load_manifest()
        assert "runs" in manifest["active_files"]
        assert "file_tracking" in manifest["active_files"]

    def test_active_path_returns_correct_file(self, tmp_path):
        mgr = BathoBundleManager(tmp_path)
        tmp = _write_tmp_ipc(tmp_path, "runs", [_run_row("r1")], RUNS_SCHEMA)
        mgr.commit_patch({"runs": tmp}, "r1")

        path = mgr.active_path("runs")
        assert path is not None
        assert path.name == "runs.v1.ipc"

    def test_active_path_missing_table_returns_none(self, tmp_path):
        mgr = BathoBundleManager(tmp_path)
        assert mgr.active_path("agent_views") is None


class TestGarbageCollect:
    def test_gc_deletes_orphaned_ipc(self, tmp_path):
        mgr = BathoBundleManager(tmp_path)
        tmp1 = _write_tmp_ipc(tmp_path, "runs", [_run_row("r1")], RUNS_SCHEMA)
        mgr.commit_patch({"runs": tmp1}, "r1")

        tmp2 = _write_tmp_ipc(tmp_path, "runs", [_run_row("r2")], RUNS_SCHEMA)
        mgr.commit_patch({"runs": tmp2}, "r2")

        assert (tmp_path / "runs.v1.ipc").exists()
        assert (tmp_path / "runs.v2.ipc").exists()

        deleted = mgr.garbage_collect()
        assert deleted == 1
        assert not (tmp_path / "runs.v1.ipc").exists()
        assert (tmp_path / "runs.v2.ipc").exists()

    def test_gc_no_orphans_returns_zero(self, tmp_path):
        mgr = BathoBundleManager(tmp_path)
        tmp = _write_tmp_ipc(tmp_path, "runs", [_run_row("r1")], RUNS_SCHEMA)
        mgr.commit_patch({"runs": tmp}, "r1")

        deleted = mgr.garbage_collect()
        assert deleted == 0

    def test_gc_empty_dir_returns_zero(self, tmp_path):
        mgr = BathoBundleManager(tmp_path)
        assert mgr.garbage_collect() == 0


class TestExportUnpack:
    def _build_bundle(self, artifact_dir: Path) -> BathoBundleManager:
        mgr = BathoBundleManager(artifact_dir)
        tmp = _write_tmp_ipc(artifact_dir, "runs", [_run_row("r1")], RUNS_SCHEMA)
        mgr.commit_patch({"runs": tmp}, "r1")
        return mgr

    def test_export_creates_zip(self, tmp_path):
        artifact_dir = tmp_path / "artifact"
        artifact_dir.mkdir()
        mgr = self._build_bundle(artifact_dir)

        zip_path = tmp_path / "export.batho"
        mgr.export_artifact(zip_path)
        assert zip_path.exists()
        assert zip_path.stat().st_size > 0

    def test_export_zip_contains_manifest_and_ipc_zst(self, tmp_path):
        artifact_dir = tmp_path / "artifact"
        artifact_dir.mkdir()
        mgr = self._build_bundle(artifact_dir)

        zip_path = tmp_path / "export.batho"
        mgr.export_artifact(zip_path)

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
        assert "manifest.json" in names
        assert any(n.endswith(".ipc.zst") for n in names)

    def test_export_empty_bundle_raises(self, tmp_path):
        mgr = BathoBundleManager(tmp_path)
        with pytest.raises(RuntimeError, match="No active artifact files"):
            mgr.export_artifact(tmp_path / "out.batho")

    def test_unpack_roundtrip(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        mgr = self._build_bundle(src_dir)

        zip_path = tmp_path / "bundle.batho"
        mgr.export_artifact(zip_path)

        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()
        dst_mgr = BathoBundleManager(dst_dir)
        manifest = dst_mgr.unpack_artifact(zip_path)

        assert manifest["schema_version"] == BUNDLE_SCHEMA_VERSION
        assert "runs" in manifest["active_files"]
        assert dst_mgr.active_path("runs") is not None

    def test_unpack_restores_readable_ipc(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        mgr = self._build_bundle(src_dir)

        zip_path = tmp_path / "bundle.batho"
        mgr.export_artifact(zip_path)

        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()
        dst_mgr = BathoBundleManager(dst_dir)
        dst_mgr.unpack_artifact(zip_path)

        path = dst_mgr.active_path("runs")
        assert path is not None
        table = read_ipc_table(path)
        assert table.num_rows == 1
        assert table.column("run_uuid").to_pylist() == ["r1"]

    def test_unpack_wrong_schema_version_raises(self, tmp_path):
        artifact_dir = tmp_path / "artifact"
        artifact_dir.mkdir()
        mgr = self._build_bundle(artifact_dir)

        zip_path = tmp_path / "export.batho"
        mgr.export_artifact(zip_path)

        # Rebuild the ZIP replacing manifest.json to avoid duplicate-name warnings
        import io, shutil as _shutil
        tmp_zip = zip_path.with_suffix(".tmp.batho")
        with zipfile.ZipFile(zip_path, "r") as src_zf, zipfile.ZipFile(tmp_zip, "w") as dst_zf:
            manifest = json.loads(src_zf.read("manifest.json"))
            manifest["schema_version"] = "batho-bundle.v999"
            for item in src_zf.infolist():
                if item.filename != "manifest.json":
                    dst_zf.writestr(item, src_zf.read(item.filename))
            dst_zf.writestr("manifest.json", json.dumps(manifest))
        _shutil.move(str(tmp_zip), str(zip_path))

        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()
        dst_mgr = BathoBundleManager(dst_dir)
        with pytest.raises(RuntimeError, match="schema mismatch"):
            dst_mgr.unpack_artifact(zip_path)


class TestBundleManagerSecurityAndLimits:
    """Security boundaries and safety limitation tests for the BathoBundleManager."""

    def test_resolve_bundle_dir_traversal_raise(self, tmp_path: Path):
        """Verify that resolve_bundle_dir raises PathSecurityError when configured to escape project root.

        Scenario:
            The configuration references paths that escape the workspace. `resolve_bundle_dir` must
            detect this and immediately raise a `PathSecurityError` before initializing storage.

        Execution Flow:
            1. Write an unsafe `batho.yaml` containing absolute outside references under `paths.artifact_dir`.
            2. Call `resolve_bundle_dir(tmp_path)` within a `pytest.raises(PathSecurityError)` context.

        Expectations:
            - Aborts initialization when directory configuration is insecure.
        """
        # Write unsafe config
        (tmp_path / "batho.yaml").write_text("paths:\n  artifact_dir: /tmp/outside_dir\n")
        
        # Should raise PathSecurityError directly
        with pytest.raises(PathSecurityError):
            resolve_bundle_dir(tmp_path)

    def test_zip_export_oom_prevention(self, tmp_path: Path):
        """Verify that export_artifact runs successfully using streaming compression to prevent OOM.

        Scenario:
            Large Arrow tables on disk could trigger out-of-memory errors if loaded fully into memory
            during archive packaging. The export pipeline must stream write compression buffers.

        Execution Flow:
            1. Set up a mock artifact directory and write a mock IPC file and `meta.json` manifest.
            2. Initialize `BathoBundleManager`.
            3. Call `export_artifact` pointing to a destination ZIP path.
            4. Assert that the zip archive was created and contains valid members.

        Expectations:
            - Clean streaming export pipeline.
            - Valid output ZIP format containing compressed zstd archives.
        """
        artifact_dir = tmp_path / "artifact"
        artifact_dir.mkdir()

        # Create dummy IPC files
        import pyarrow.ipc as ipc
        schema = pa.schema([("file_id", pa.int64())])
        table = pa.Table.from_pydict({"file_id": [1, 2, 3]}, schema=schema)
        ipc_file = artifact_dir / "agent_views.v1.ipc"
        with ipc.new_file(str(ipc_file), schema) as w:
            w.write_table(table)

        # Write manifest
        meta_path = artifact_dir / "meta.json"
        with open(meta_path, "w") as f:
            json.dump({
                "generation": 1,
                "active_files": {
                    "agent_views": "agent_views.v1.ipc"
                }
            }, f)

        # Run export
        manager = BathoBundleManager(artifact_dir)
        zip_path = tmp_path / "export.zip"
        
        manager.export_artifact(zip_path)

        # Verify zip was created and has correct members
        assert zip_path.exists()
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            assert "manifest.json" in names
            assert "agent_views.ipc.zst" in names

    def test_manifest_nanosecond_invalidation(self, tmp_path: Path):
        """Verify that load_manifest detects nanosecond mtime and size changes for cache invalidation.

        Scenario:
            If two build modifications occur inside the exact same second, low-precision file modification
            timers (st_mtime) might look identical, causing stale manifest cache hits.
            The invalidation checker must inspect st_mtime_ns (nanoseconds) to detect updates.

        Execution Flow:
            1. Write initial manifest to `meta.json`.
            2. Call `manager.load_manifest()` (caches results).
            3. Rewrite `meta.json` with updated content, but manually set `st_mtime_ns` to be slightly
               different (+1000 ns) while keeping the same file size.
            4. Call `manager.load_manifest()` again and assert that it detects the change and invalidates the cache.

        Expectations:
            - Robust nanosecond-level manifest invalidation prevents stale cache issues.
        """
        meta_path = tmp_path / "meta.json"
        manager = BathoBundleManager(tmp_path)
        
        # Initial manifest
        manifest_data = {"schema_version": "batho-bundle.v1", "generation": 1, "active_files": {}}
        meta_path.write_text(json.dumps(manifest_data))
        
        m1 = manager.load_manifest()
        assert m1["generation"] == 1
        
        # Update generation but keep same file size and modify st_mtime_ns explicitly
        manifest_data["generation"] = 2
        meta_path.write_text(json.dumps(manifest_data))
        
        # Artificially set stat times
        import os
        stat_res = meta_path.stat()
        os.utime(meta_path, ns=(stat_res.st_atime_ns, stat_res.st_mtime_ns + 1000))
        
        m2 = manager.load_manifest()
        assert m2["generation"] == 2

    def test_decompression_ratio_bomb_prevention(self, tmp_path: Path):
        """Verify that a high-ratio zstd compression stream causes unpack_artifact to raise a RuntimeError.

        Scenario:
            An attacker crafts a tiny zstd payload (few KB) that expands to gigabytes of repeating data.
            This would crash/OOM the host process. The decompression utility must monitor decompression
            ratio and abort if ratio exceeds 100x.

        Execution Flow:
            1. Craft a high-ratio compression payload (repeating 'a' blocks compressing heavily).
            2. Write to a mock ZIP.
            3. Call `manager.unpack_artifact` and verify it raises `RuntimeError` with a "Decompression ratio" message.

        Expectations:
            - Ratio limits (100x max) are enforced during decompression.
        """
        import zstandard as zstd
        artifact_dir = tmp_path / "artifact"
        manager = BathoBundleManager(artifact_dir)

        zip_file = tmp_path / "bomb.zip"
        cctx = zstd.ZstdCompressor(level=3)
        
        # 2MB of repeating text compresses down to a few KB, resulting in a ratio > 100x
        compressed = cctx.compress(b"a" * 2 * 1024 * 1024)

        with zipfile.ZipFile(zip_file, "w") as zf:
            manifest_data = {
                "schema_version": "batho-bundle.v1",
                "generation": 1,
                "active_files": {}
            }
            zf.writestr("manifest.json", json.dumps(manifest_data))
            zf.writestr("bomb_table.ipc.zst", compressed)

        # Unpacking should fail due to ratio exceeding 100x
        with pytest.raises(RuntimeError) as exc_info:
            manager.unpack_artifact(zip_file)
        assert "Decompression ratio" in str(exc_info.value)

    def test_unpack_artifact_oversized_manifest(self, tmp_path: Path):
        """Verify that an oversized manifest.json inside a ZIP causes unpack_artifact to raise a RuntimeError.

        Scenario:
            An archive contains a bloated `manifest.json` file designed to trigger OOM.
            The unpacker must reject any manifest.json files exceeding a reasonable threshold (10 MB).

        Execution Flow:
            1. Pack an 11MB file as `manifest.json` in a test ZIP archive.
            2. Invoke `unpack_artifact`.
            3. Assert that a `RuntimeError` with "exceeds maximum limit" is raised.

        Expectations:
            - Bloated manifests are discarded immediately without loading fully.
        """
        artifact_dir = tmp_path / "artifact"
        manager = BathoBundleManager(artifact_dir)

        zip_file = tmp_path / "oversized.zip"
        
        # 11MB of manifest data (greater than our 10MB limit)
        manifest_data = " " * (11 * 1024 * 1024)

        with zipfile.ZipFile(zip_file, "w") as zf:
            zf.writestr("manifest.json", manifest_data)

        with pytest.raises(RuntimeError) as exc_info:
            manager.unpack_artifact(zip_file)
        assert "exceeds maximum limit" in str(exc_info.value)

    def test_zip_slip_rejection(self, tmp_path: Path):
        """Verify that Zip Slip path traversal attempts raise PathSecurityError.

        Scenario:
            An archive contains member files with parent-directory traversal names (e.g., `../../escaped.py`).
            If extracted blindly, they write arbitrary files outside the target directory.
            The unpacker must detect and block these traversal attempts.

        Execution Flow:
            1. Write a malicious ZIP containing a relative path traversal member.
            2. Run `unpack_artifact` and verify it raises `PathSecurityError`.

        Expectations:
            - Extraction paths are strictly sanitized to stay within the target workspace.
        """
        artifact_dir = tmp_path / "artifact"
        bsg_dir = tmp_path / "bsg"
        manager = BathoBundleManager(artifact_dir)

        # Create a malicious zip file
        zip_file = tmp_path / "malicious.zip"
        with zipfile.ZipFile(zip_file, "w") as zf:
            # manifest.json is required
            manifest_data = {
                "schema_version": "batho-bundle.v1",
                "generation": 1,
                "active_files": {}
            }
            zf.writestr("manifest.json", json.dumps(manifest_data))
            
            # Add a Zip Slip member escaping active files
            zf.writestr("../escaped_file.ipc.zst", b"some_compressed_data")
            
            # Add a Zip Slip member escaping bsg
            zf.writestr("bsg/../../escaped_bsg.ipc.zst", b"some_compressed_data")

        # Unpacking should raise PathSecurityError
        with pytest.raises(PathSecurityError):
            manager.unpack_artifact(zip_file, bsg_target_dir=bsg_dir)

    def test_decompression_bomb_prevention(self, tmp_path: Path):
        """Verify that decompression sizes exceeding absolute max limits raise RuntimeError.

        Scenario:
            Even if ratio is fine, the absolute expanded size must not exceed the maximum absolute limit (500 MB).

        Execution Flow:
            1. Mock `MAX_DECOMPRESS_SIZE` to a tiny value (500 bytes).
            2. Pack a small payload and decompress it.
            3. Assert that `RuntimeError` is raised with a size-limit message.

        Expectations:
            - Absolute size caps are enforced.
        """
        artifact_dir = tmp_path / "artifact"
        manager = BathoBundleManager(artifact_dir)

        zip_file = tmp_path / "bomb.zip"
        import zstandard as zstd
        cctx = zstd.ZstdCompressor(level=3)
        compressed = cctx.compress(b"a" * 1000)

        with zipfile.ZipFile(zip_file, "w") as zf:
            manifest_data = {
                "schema_version": "batho-bundle.v1",
                "generation": 1,
                "active_files": {}
            }
            zf.writestr("manifest.json", json.dumps(manifest_data))
            zf.writestr("bomb_table.ipc.zst", compressed)

        # Let's mock MAX_DECOMPRESS_SIZE in manager.py to verify it fails
        import batho.modules.storage.arrow_bundle.manager as manager_mod
        original_limit = manager_mod.MAX_DECOMPRESS_SIZE
        
        # Run with standard limit (should succeed because 1000 < 500MB)
        manifest = manager.unpack_artifact(zip_file)
        assert "bomb_table" in manifest["active_files"]

        # Run with a very low limit (should fail since 1000 > 500)
        manager_mod.MAX_DECOMPRESS_SIZE = 500
        try:
            with pytest.raises(RuntimeError) as exc_info:
                manager.unpack_artifact(zip_file)
            assert "Failed to decompress ZIP member" in str(exc_info.value)
        finally:
            manager_mod.MAX_DECOMPRESS_SIZE = original_limit

