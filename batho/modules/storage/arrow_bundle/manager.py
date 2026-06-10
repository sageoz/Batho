"""Arrow Bundle Manager — Generation-MVCC commit, GC, and ZIP export.

Writers commit new Arrow IPC generations atomically by:
  1. Writing to .tmp files
  2. Renaming to .v<N>.ipc
  3. Atomically swapping meta.json to point at new generation

Active readers continue to hold their mmap on the old generation.
Old generations are cleaned by garbage_collect() / batho gc orphans.

Transport ZIP (artifact_<dir>.batho) is produced by export_artifact(),
called exclusively from batho export.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.ipc as ipc
import zstandard as zstd

from batho.utils.logging import get_logger
from .schemas import BUNDLE_SCHEMA_VERSION, ALL_SCHEMAS

LOGGER = get_logger(__name__, component="arrow_bundle_manager")
MAX_DECOMPRESS_SIZE = 200 * 1024 * 1024  # 200 MB
MAX_DECOMPRESS_RATIO = 100


class BathoBundleManager:
    """Manages .batho/artifact/ working copy — MVCC generation rotation, GC, ZIP export."""

    def __init__(self, artifact_dir: Path) -> None:
        self.artifact_dir = artifact_dir.resolve()
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.artifact_dir / "meta.json"
        self._manifest_cache: dict[str, Any] | None = None
        self._manifest_mtime: int | None = None
        self._manifest_size: int | None = None
        self._manifest_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Manifest
    # ------------------------------------------------------------------

    def load_manifest(self) -> dict[str, Any]:
        with self._manifest_lock:
            if not self.manifest_path.exists():
                self._manifest_cache = None
                self._manifest_mtime = None
                self._manifest_size = None
                return {
                    "schema_version": BUNDLE_SCHEMA_VERSION,
                    "generation": 0,
                    "active_files": {},
                    "last_run_uuid": None,
                }
            try:
                stat_res = self.manifest_path.stat()
                mtime = stat_res.st_mtime_ns
                size = stat_res.st_size
                if (
                    self._manifest_cache is not None 
                    and self._manifest_mtime == mtime
                    and self._manifest_size == size
                ):
                    return self._manifest_cache

                manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                self._manifest_cache = manifest
                self._manifest_mtime = mtime
                self._manifest_size = size
                return manifest
            except (json.JSONDecodeError, OSError):
                self._manifest_cache = None
                self._manifest_mtime = None
                self._manifest_size = None
                return {
                    "schema_version": BUNDLE_SCHEMA_VERSION,
                    "generation": 0,
                    "active_files": {},
                    "last_run_uuid": None,
                }

    def _write_manifest_atomic(self, manifest: dict[str, Any]) -> None:
        import uuid
        tmp = self.manifest_path.with_suffix(f".tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
        tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(self.manifest_path))
        with self._manifest_lock:
            self._manifest_cache = None
            self._manifest_mtime = None
            self._manifest_size = None

    # ------------------------------------------------------------------
    # Commit
    # ------------------------------------------------------------------

    def commit_patch(
        self,
        new_streams: dict[str, Path],
        run_uuid: str,
        *,
        extra_meta: dict[str, Any] | None = None,
    ) -> int:
        """Atomically rotate to a new generation of artifact files.

        Args:
            new_streams: logical_name → .tmp.ipc path from BathoBundleWriter.finalize()
            run_uuid: the run being committed
            extra_meta: additional keys to merge into manifest

        Returns:
            new generation number
        """
        manifest = self.load_manifest()
        next_gen = manifest["generation"] + 1
        active_files = dict(manifest.get("active_files", {}))

        for logical_name, tmp_path in new_streams.items():
            stamped = self.artifact_dir / f"{logical_name}.v{next_gen}.ipc"
            shutil.move(str(tmp_path), str(stamped))
            active_files[logical_name] = stamped.name

        manifest["generation"] = next_gen
        manifest["active_files"] = active_files
        manifest["last_run_uuid"] = run_uuid
        manifest["schema_version"] = BUNDLE_SCHEMA_VERSION
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        if extra_meta:
            manifest.update(extra_meta)

        self._write_manifest_atomic(manifest)
        LOGGER.info("bundle_generation_committed", generation=next_gen, run_uuid=run_uuid)
        return next_gen

    def update_simple_table(self, logical_name: str, path: Path, run_uuid: str) -> None:
        """Commit a small side-table (runs, file_tracking, etc.) as a new generation."""
        self.commit_patch({logical_name: path}, run_uuid)

    # ------------------------------------------------------------------
    # Active file path lookup
    # ------------------------------------------------------------------

    def active_path(self, logical_name: str) -> Path | None:
        """Return the active .vN.ipc path for a logical table, or None."""
        manifest = self.load_manifest()
        fname = manifest.get("active_files", {}).get(logical_name)
        if not fname:
            return None
        p = self.artifact_dir / fname
        return p if p.exists() else None

    def all_active_paths(self) -> dict[str, Path]:
        manifest = self.load_manifest()
        result = {}
        for name, fname in manifest.get("active_files", {}).items():
            p = self.artifact_dir / fname
            if p.exists():
                result[name] = p
        return result

    # ------------------------------------------------------------------
    # Garbage collection
    # ------------------------------------------------------------------

    def garbage_collect(self) -> int:
        """Delete orphaned .vN.ipc files not referenced by active_files.

        Returns number of files deleted.
        """
        import re
        version_pattern = re.compile(r"\.v(\d+)\.ipc$")

        manifest = self.load_manifest()
        current_gen = manifest.get("generation", 0)
        active = set(manifest.get("active_files", {}).values())
        active.add("meta.json")
        cleaned = 0

        for p in self.artifact_dir.glob("*.ipc"):
            if p.name not in active:
                # Check version to prevent deleting files from a committing generation
                match = version_pattern.search(p.name)
                if match:
                    try:
                        file_gen = int(match.group(1))
                        if file_gen == current_gen + 1:
                            continue  # Skip files from the currently committing generation
                    except ValueError:
                        pass
                try:
                    p.unlink()
                    cleaned += 1
                except PermissionError:
                    pass

        LOGGER.info("bundle_gc_complete", deleted=cleaned)
        return cleaned

    # ------------------------------------------------------------------
    # ZIP export (transport artifact)
    # ------------------------------------------------------------------

    def export_artifact(self, output_zip_path: Path, bsg_current_dir: Path | None = None) -> None:
        """Pack active-generation files into a transport ZIP with zstd-compressed IPC members.

        Called exclusively by batho export. The ZIP contains:
          manifest.json       — bundle manifest
          <name>.ipc.zst      — zstd-compressed artifact IPC for each active table
          bsg/<name>.ipc.zst  — zstd-compressed bsg/current/ IPC files (if present)
        """
        manifest = self.load_manifest()
        active = self.all_active_paths()

        if not active:
            raise RuntimeError(
                "No active artifact files to export. Run batho build first."
            )

        output_zip_path.parent.mkdir(parents=True, exist_ok=True)
        cctx = zstd.ZstdCompressor(level=3)

        # Collect bsg/current/ plain .ipc files if directory exists
        bsg_files: dict[str, str] = {}
        bsg_ipc_paths: dict[str, Path] = {}
        if bsg_current_dir is not None and bsg_current_dir.is_dir():
            for ipc_file in sorted(bsg_current_dir.glob("*.ipc")):
                logical = ipc_file.stem  # e.g. 'entities'
                bsg_files[logical] = f"bsg/{logical}.ipc.zst"
                bsg_ipc_paths[logical] = ipc_file

        with zipfile.ZipFile(
            output_zip_path, "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=1,
        ) as zf:
            export_manifest = dict(manifest)
            export_manifest["active_files"] = {
                name: f"{name}.ipc.zst" for name in active
            }
            if bsg_files:
                export_manifest["bsg_files"] = bsg_files
            zf.writestr("manifest.json", json.dumps(export_manifest, indent=2))

            for logical_name, local_path in active.items():
                size = local_path.stat().st_size
                with local_path.open("rb") as f_in:
                    with zf.open(f"{logical_name}.ipc.zst", "w") as f_out:
                        cctx.copy_stream(f_in, f_out, size=size)

            for logical_name, ipc_path in bsg_ipc_paths.items():
                size = ipc_path.stat().st_size
                with ipc_path.open("rb") as f_in:
                    with zf.open(f"bsg/{logical_name}.ipc.zst", "w") as f_out:
                        cctx.copy_stream(f_in, f_out, size=size)

        LOGGER.info(
            "artifact_exported",
            dest=str(output_zip_path),
            tables=len(active),
            bsg_tables=len(bsg_ipc_paths),
        )

    # ------------------------------------------------------------------
    # ZIP unpack (batho load)
    # ------------------------------------------------------------------

    def unpack_artifact(self, zip_path: Path, bsg_target_dir: Path | None = None) -> dict[str, Any]:
        """Unpack a transport ZIP into artifact_dir as plain .ipc files.

        If bsg_target_dir is provided and the ZIP contains bsg/ members,
        they are decompressed as plain .ipc files into bsg_target_dir.

        Returns the manifest dict from the ZIP.
        """
        dctx = zstd.ZstdDecompressor()

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            if "manifest.json" not in names:
                raise RuntimeError(f"Invalid artifact: manifest.json missing in {zip_path}")

            manifest_info = zf.getinfo("manifest.json")
            MAX_MANIFEST_SIZE = 10 * 1024 * 1024  # 10 MB
            if manifest_info.file_size > MAX_MANIFEST_SIZE:
                raise RuntimeError(
                    f"manifest.json size {manifest_info.file_size} bytes exceeds maximum limit of {MAX_MANIFEST_SIZE} bytes"
                )
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            schema_ver = manifest.get("schema_version", "")
            if schema_ver != BUNDLE_SCHEMA_VERSION:
                raise RuntimeError(
                    f"Bundle schema mismatch: found {schema_ver!r}, "
                    f"expected {BUNDLE_SCHEMA_VERSION!r}. "
                    "Rebuild with: batho build --full"
                )

            generation = manifest.get("generation", 1)
            active_files: dict[str, str] = {}
            bsg_extracted: list[str] = []

            for member in names:
                if member == "manifest.json":
                    continue
                if not member.endswith(".ipc.zst"):
                    continue

                from batho.utils.path_sanitizer import is_safe_filename, safe_join, PathSecurityError

                if member.startswith("bsg/"):
                    logical = member[len("bsg/"):].replace(".ipc.zst", "")
                    if not is_safe_filename(logical):
                        raise PathSecurityError(f"Unsafe ZIP member path detected: {member}")
                else:
                    logical_name = member.replace(".ipc.zst", "")
                    if not is_safe_filename(logical_name):
                        raise PathSecurityError(f"Unsafe ZIP member path detected: {member}")

                compressed_size = zf.getinfo(member).compress_size
                try:
                    chunks = []
                    total_size = 0
                    with zf.open(member) as compressed_stream:
                        with dctx.stream_reader(compressed_stream) as reader:
                            while True:
                                chunk = reader.read(65536)
                                if not chunk:
                                    break
                                total_size += len(chunk)
                                if total_size > MAX_DECOMPRESS_SIZE:
                                    raise RuntimeError(
                                        f"Decompressed size exceeded maximum limit of {MAX_DECOMPRESS_SIZE} bytes"
                                    )
                                if total_size > 1024 * 1024:  # > 1 MB
                                    ratio = total_size / max(1, compressed_size)
                                    if ratio > MAX_DECOMPRESS_RATIO:
                                        raise RuntimeError(
                                            f"Decompression ratio {ratio:.1f}x exceeded safety threshold of {MAX_DECOMPRESS_RATIO}x"
                                        )
                                chunks.append(chunk)
                    raw_ipc = b"".join(chunks)
                except Exception as exc:
                    raise RuntimeError(f"Failed to decompress ZIP member {member}: {exc}") from exc

                if member.startswith("bsg/"):
                    # bsg/current/ plain .ipc files
                    if bsg_target_dir is not None:
                        bsg_target_dir.mkdir(parents=True, exist_ok=True)
                        dest = safe_join(bsg_target_dir, f"{logical}.ipc")
                        dest.write_bytes(raw_ipc)
                        bsg_extracted.append(logical)
                else:
                    stamped_name = f"{logical_name}.v{generation}.ipc"
                    dest = safe_join(self.artifact_dir, stamped_name)
                    dest.write_bytes(raw_ipc)
                    active_files[logical_name] = stamped_name

        new_manifest = dict(manifest)
        new_manifest["active_files"] = active_files
        self._write_manifest_atomic(new_manifest)

        LOGGER.info(
            "artifact_unpacked",
            source=str(zip_path),
            tables=len(active_files),
            bsg_tables=len(bsg_extracted),
            generation=generation,
        )
        return new_manifest
