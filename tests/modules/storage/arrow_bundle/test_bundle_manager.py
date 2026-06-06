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
