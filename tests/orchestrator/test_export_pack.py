"""Tests for batho export default pack behavior (transport ZIP production)."""
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


class TestExportDefaultPack:
    def test_default_produces_zip(self, tmp_path):
        """Verify that running default export produces a valid ZIP archive.

        Scenario:
            An export operation is invoked specifying a target ZIP output path on an existing bundle.

        Execution Flow:
            1. Bootstrap a minimal bundle with one completed run in the temp path.
            2. Define the output path pointing to `out.batho`.
            3. Run `run_export` with the configured ExportOptions.
            4. Verify the export is successful, the output file is created at the correct path, and it is a valid zipfile.

        Expectations:
            - The export returns a successful result with no errors.
            - The output file exists and is recognized as a valid zip file.
        """
        _bootstrap(tmp_path)
        out = tmp_path / "out.batho"
        opts = ExportOptions(root=tmp_path, output=out)
        result = run_export(opts)

        assert result.success, result.errors
        assert result.output_path == out
        assert out.exists()
        assert zipfile.is_zipfile(out)

    def test_default_zip_contains_manifest_and_ipc(self, tmp_path):
        """Verify that the exported ZIP archive contains the manifest and IPC files.

        Scenario:
            An export operation is run on an existing bundle, and the contents of the generated ZIP are inspected.

        Execution Flow:
            1. Bootstrap a minimal bundle.
            2. Run `run_export` to output `out.batho`.
            3. Open the output ZIP file and list its contents.
            4. Verify the ZIP includes "manifest.json" and at least one ".ipc.zst" member.

        Expectations:
            - The export is successful.
            - The export package contains both the bundle manifest and the compressed IPC database tables.
        """
        _bootstrap(tmp_path)
        out = tmp_path / "out.batho"
        result = run_export(ExportOptions(root=tmp_path, output=out))

        assert result.success
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert "manifest.json" in names
        ipc_members = [n for n in names if n.endswith(".ipc.zst")]
        assert len(ipc_members) >= 1

    def test_default_manifest_schema_version(self, tmp_path):
        """Verify that the manifest inside the export package contains the correct schema version.

        Scenario:
            An export is performed, and the metadata in manifest.json inside the ZIP is loaded and checked.

        Execution Flow:
            1. Bootstrap a minimal bundle.
            2. Run `run_export` to output `out.batho`.
            3. Open the ZIP file, read the "manifest.json" entry, and parse it as JSON.
            4. Verify that schema_version is "batho-bundle.v1" and the generation value is at least 1.

        Expectations:
            - The export manifest contains the expected schema version format and a positive generation number.
        """
        _bootstrap(tmp_path)
        out = tmp_path / "out.batho"
        run_export(ExportOptions(root=tmp_path, output=out))

        import json
        with zipfile.ZipFile(out) as zf:
            manifest = json.loads(zf.read("manifest.json"))
        assert manifest["schema_version"] == "batho-bundle.v1"
        assert manifest["generation"] >= 1

    def test_default_ipc_members_are_zstd_compressed(self, tmp_path):
        """Verify that IPC file members within the exported ZIP are zstd-compressed.

        Scenario:
            An export package is generated, and its internal IPC files are decompressed using Zstd.

        Execution Flow:
            1. Bootstrap a minimal bundle.
            2. Run `run_export` to output `out.batho`.
            3. For each file in the ZIP ending with ".ipc.zst", extract and decompress it using a ZstdDecompressor.
            4. Verify that the decompressed byte array contains valid data (length >= 8 bytes).

        Expectations:
            - All IPC tables inside the archive are compressed with ZStandard and can be successfully decompressed.
        """
        _bootstrap(tmp_path)
        out = tmp_path / "out.batho"
        run_export(ExportOptions(root=tmp_path, output=out))

        import zstandard as zstd
        dctx = zstd.ZstdDecompressor()
        with zipfile.ZipFile(out) as zf:
            for name in zf.namelist():
                if not name.endswith(".ipc.zst"):
                    continue
                raw = zf.read(name)
                decompressed = dctx.decompress(raw)
                assert len(decompressed) >= 8, f"{name} decompressed to nothing"

    def test_default_output_path(self, tmp_path):
        """Verify that export uses a default output path when none is explicitly specified.

        Scenario:
            An export is run on an existing bundle without providing an output file path in the ExportOptions.

        Execution Flow:
            1. Bootstrap a minimal bundle.
            2. Initialize ExportOptions with only the bundle root directory.
            3. Run `run_export` with these options.
            4. Check that the returned output path has a ".batho" suffix and actually exists on disk.

        Expectations:
            - The export successfully computes and creates the package at a default path.
        """
        _bootstrap(tmp_path)
        opts = ExportOptions(root=tmp_path)
        result = run_export(opts)

        assert result.success
        assert result.output_path is not None
        assert result.output_path.suffix == ".batho"
        assert result.output_path.exists()

    def test_default_no_bundle_returns_error(self, tmp_path):
        """Verify that exporting an empty or non-existent bundle root returns a failure error.

        Scenario:
            Export options are configured with a root directory that does not contain a Batho bundle.

        Execution Flow:
            1. Initialize ExportOptions pointing to an empty temporary directory.
            2. Run `run_export`.
            3. Assert that the operation failed and the errors contain the expected "No artifact bundle" message.

        Expectations:
            - The export result reports success as False.
            - An error message indicating the lack of an artifact bundle is returned.
        """
        opts = ExportOptions(root=tmp_path)
        result = run_export(opts)

        assert not result.success
        assert any("No artifact bundle" in e for e in result.errors)

    def test_default_roundtrip_with_load(self, tmp_path):
        """Pack then load should restore all IPC tables to a fresh directory.

        Scenario:
            An exported bundle ZIP package is unpacked/loaded into a fresh destination directory using the BathoBundleManager.

        Execution Flow:
            1. Bootstrap a minimal bundle in a temp path.
            2. Export the bundle to `out.batho`.
            3. Create a fresh destination directory "restored".
            4. Use `BathoBundleManager` on the destination directory to unpack the exported ZIP package.
            5. Assert the unpacked manifest's schema version matches.
            6. Verify that IPC tables (such as runs) are correctly restored as files on disk.

        Expectations:
            - Unpacking the export package successfully restores the manifest and active IPC table files.
            - Schema version is maintained in the restored manifest.
        """
        _bootstrap(tmp_path)
        out = tmp_path / "out.batho"
        run_export(ExportOptions(root=tmp_path, output=out))

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
