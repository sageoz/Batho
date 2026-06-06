"""Tests for batho export --pack (transport ZIP production)."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from batho.modules.storage.arrow_bundle.bundle import BathoBundle
from batho.orchestrator.export import ExportOptions, run_export


def _bootstrap(tmp_path: Path) -> str:
    """Minimal bundle with one completed run so pack has active files."""
    db = BathoBundle(tmp_path)
    run_uuid = "build_pack_test_0001"
    db.create_run(run_uuid, root_path=str(tmp_path))
    db.complete_run(run_uuid, entity_count=2, rel_count=1, file_count=1, duration_ms=50)
    db.close()
    return run_uuid


class TestExportPack:
    def test_pack_produces_zip(self, tmp_path):
        _bootstrap(tmp_path)
        out = tmp_path / "out.batho"
        opts = ExportOptions(root=tmp_path, pack=True, output=out)
        result = run_export(opts)

        assert result.success, result.errors
        assert result.output_path == out
        assert out.exists()
        assert zipfile.is_zipfile(out)

    def test_pack_zip_contains_manifest_and_ipc(self, tmp_path):
        _bootstrap(tmp_path)
        out = tmp_path / "out.batho"
        result = run_export(ExportOptions(root=tmp_path, pack=True, output=out))

        assert result.success
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert "manifest.json" in names
        ipc_members = [n for n in names if n.endswith(".ipc.zst")]
        assert len(ipc_members) >= 1

    def test_pack_manifest_schema_version(self, tmp_path):
        _bootstrap(tmp_path)
        out = tmp_path / "out.batho"
        run_export(ExportOptions(root=tmp_path, pack=True, output=out))

        import json
        with zipfile.ZipFile(out) as zf:
            manifest = json.loads(zf.read("manifest.json"))
        assert manifest["schema_version"] == "batho-bundle.v1"
        assert manifest["generation"] >= 1

    def test_pack_ipc_members_are_zstd_compressed(self, tmp_path):
        _bootstrap(tmp_path)
        out = tmp_path / "out.batho"
        run_export(ExportOptions(root=tmp_path, pack=True, output=out))

        import zstandard as zstd
        dctx = zstd.ZstdDecompressor()
        with zipfile.ZipFile(out) as zf:
            for name in zf.namelist():
                if not name.endswith(".ipc.zst"):
                    continue
                raw = zf.read(name)
                decompressed = dctx.decompress(raw)
                assert len(decompressed) >= 8, f"{name} decompressed to nothing"

    def test_pack_default_output_path(self, tmp_path):
        _bootstrap(tmp_path)
        opts = ExportOptions(root=tmp_path, pack=True)
        result = run_export(opts)

        assert result.success
        assert result.output_path is not None
        assert result.output_path.suffix == ".batho"
        assert result.output_path.exists()

    def test_pack_no_bundle_returns_error(self, tmp_path):
        opts = ExportOptions(root=tmp_path, pack=True)
        result = run_export(opts)

        assert not result.success
        assert any("No artifact bundle" in e for e in result.errors)

    def test_pack_roundtrip_with_load(self, tmp_path):
        """Pack then load should restore all IPC tables to a fresh directory."""
        _bootstrap(tmp_path)
        out = tmp_path / "out.batho"
        run_export(ExportOptions(root=tmp_path, pack=True, output=out))

        dest = tmp_path / "restored"
        dest.mkdir()
        from batho.modules.storage.arrow_bundle.manager import BathoBundleManager
        mgr = BathoBundleManager(dest)
        manifest = mgr.unpack_artifact(out)

        assert manifest["schema_version"] == "batho-bundle.v1"
        active = manifest.get("active_files", {})
        assert "runs" in active
        ipc_files = list(dest.glob("*.ipc"))
        assert len(ipc_files) >= 1
