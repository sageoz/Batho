"""Tests for batho load orchestrator — pack/unpack round-trip."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from batho.modules.storage.arrow_bundle import BathoBundle, resolve_bundle_dir
from batho.modules.storage.arrow_bundle.manager import BathoBundleManager
from batho.modules.storage.arrow_bundle.writer import write_simple_ipc
from batho.modules.storage.arrow_bundle.schemas import BUNDLE_SCHEMA_VERSION, RUNS_SCHEMA
from batho.orchestrator.load import LoadOptions, LoadResult, run_load


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_minimal_bundle(artifact_dir: Path) -> BathoBundleManager:
    """Create a one-run bundle and return its manager."""
    mgr = BathoBundleManager(artifact_dir)
    row = {
        "run_uuid": "build_001",
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "started_at": "2024-01-01T00:00:00Z",
        "completed_at": "2024-01-01T00:00:01Z",
        "status": "completed",
        "git_commit": None, "git_branch": None,
        "root_path": "/test/repo",
        "entity_count": 2, "rel_count": 1,
        "file_count": 1, "duration_ms": 200, "error_message": None,
    }
    tmp = artifact_dir / "runs.tmp.ipc"
    write_simple_ipc([row], RUNS_SCHEMA, tmp)
    mgr.commit_patch({"runs": tmp}, "build_001")
    return mgr


def _export_bundle(src_root: Path) -> Path:
    """Build a bundle under src_root and export a ZIP; return ZIP path."""
    artifact_dir = resolve_bundle_dir(src_root)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    mgr = _build_minimal_bundle(artifact_dir)
    zip_path = src_root / "export.batho"
    mgr.export_artifact(zip_path)
    return zip_path


# ---------------------------------------------------------------------------
# run_load success path
# ---------------------------------------------------------------------------

class TestRunLoadSuccess:
    def test_load_populates_bundle_dir(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        zip_path = _export_bundle(src)

        dst_root = tmp_path / "dst"
        dst_root.mkdir()

        result = run_load(LoadOptions(root=dst_root, artifact_path=zip_path))
        assert result.success, result.message
        assert (resolve_bundle_dir(dst_root) / "meta.json").exists()

    def test_load_result_has_correct_tables_count(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        zip_path = _export_bundle(src)

        dst_root = tmp_path / "dst"
        dst_root.mkdir()

        result = run_load(LoadOptions(root=dst_root, artifact_path=zip_path))
        assert result.success
        assert result.tables_loaded >= 1

    def test_load_result_has_generation(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        zip_path = _export_bundle(src)

        dst_root = tmp_path / "dst"
        dst_root.mkdir()

        result = run_load(LoadOptions(root=dst_root, artifact_path=zip_path))
        assert result.generation >= 1

    def test_loaded_bundle_is_readable(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        zip_path = _export_bundle(src)

        dst_root = tmp_path / "dst"
        dst_root.mkdir()

        run_load(LoadOptions(root=dst_root, artifact_path=zip_path))

        db = BathoBundle(dst_root)
        runs = db._reader.get_all_runs()
        assert len(runs) == 1
        assert runs[0]["run_uuid"] == "build_001"

    def test_load_then_export_roundtrip(self, tmp_path):
        """Export → load into dst → export again → load into dst2 → still readable."""
        src = tmp_path / "src"
        src.mkdir()
        zip1 = _export_bundle(src)

        dst1 = tmp_path / "dst1"
        dst1.mkdir()
        run_load(LoadOptions(root=dst1, artifact_path=zip1))

        artifact_dir1 = resolve_bundle_dir(dst1)
        mgr1 = BathoBundleManager(artifact_dir1)
        zip2 = tmp_path / "export2.batho"
        mgr1.export_artifact(zip2)

        dst2 = tmp_path / "dst2"
        dst2.mkdir()
        result2 = run_load(LoadOptions(root=dst2, artifact_path=zip2))
        assert result2.success

        db2 = BathoBundle(dst2)
        assert len(db2._reader.get_all_runs()) == 1


# ---------------------------------------------------------------------------
# run_load error paths
# ---------------------------------------------------------------------------

class TestRunLoadErrors:
    def test_missing_root_fails(self, tmp_path):
        result = run_load(LoadOptions(
            root=tmp_path / "nonexistent",
            artifact_path=tmp_path / "any.batho",
        ))
        assert not result.success
        assert "does not exist" in result.message

    def test_missing_artifact_fails(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        result = run_load(LoadOptions(
            root=root,
            artifact_path=tmp_path / "missing.batho",
        ))
        assert not result.success
        assert "not found" in result.message

    def test_existing_bundle_without_force_fails(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        zip_path = _export_bundle(src)

        dst_root = tmp_path / "dst"
        dst_root.mkdir()
        run_load(LoadOptions(root=dst_root, artifact_path=zip_path))

        result = run_load(LoadOptions(root=dst_root, artifact_path=zip_path))
        assert not result.success
        assert "already exists" in result.message

    def test_force_overwrites_existing_bundle(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        zip_path = _export_bundle(src)

        dst_root = tmp_path / "dst"
        dst_root.mkdir()
        run_load(LoadOptions(root=dst_root, artifact_path=zip_path))

        result = run_load(LoadOptions(root=dst_root, artifact_path=zip_path, force=True))
        assert result.success

    def test_bad_zip_schema_version_fails(self, tmp_path):
        import zipfile, json
        src = tmp_path / "src"
        src.mkdir()
        zip_path = _export_bundle(src)

        bad_zip = tmp_path / "bad.batho"
        shutil.copy(zip_path, bad_zip)
        # Rebuild the ZIP replacing manifest.json to avoid duplicate-name warnings
        tmp_zip = bad_zip.with_suffix(".tmp.batho")
        with zipfile.ZipFile(bad_zip, "r") as src_zf, zipfile.ZipFile(tmp_zip, "w") as dst_zf:
            manifest = json.loads(src_zf.read("manifest.json"))
            manifest["schema_version"] = "batho-bundle.v999"
            for item in src_zf.infolist():
                if item.filename != "manifest.json":
                    dst_zf.writestr(item, src_zf.read(item.filename))
            dst_zf.writestr("manifest.json", json.dumps(manifest))
        shutil.move(str(tmp_zip), str(bad_zip))

        dst_root = tmp_path / "dst"
        dst_root.mkdir()
        result = run_load(LoadOptions(root=dst_root, artifact_path=bad_zip))
        assert not result.success
        assert "schema" in result.message.lower() or "mismatch" in result.message.lower()
