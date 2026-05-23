"""Artifact loader — resolves and loads JSON content from .batho artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from batho.bridge.constants import DEFAULT_PATH_PATTERNS, INDEX_SCOPED_TYPES
from batho.bridge.models import ArtifactRecord
from batho.bridge.registry_client import ArtifactRegistryBridge
from batho.utils.hash import compute_file_hash
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge")


class ArtifactNotFoundError(Exception):
    """Raised when an artifact cannot be resolved on disk."""

    def __init__(self, artifact_type: str, resolved_path: str) -> None:
        super().__init__(f"Artifact not found: {artifact_type} at {resolved_path}")
        self.artifact_type = artifact_type
        self.resolved_path = resolved_path


class ChecksumMismatchError(Exception):
    """Raised when the on-disk checksum does not match the registry."""

    def __init__(self, artifact_type: str, expected: str, actual: str) -> None:
        super().__init__(
            f"Checksum mismatch for {artifact_type}: expected {expected}, got {actual}"
        )
        self.artifact_type = artifact_type
        self.expected = expected
        self.actual = actual


class ArtifactParseError(Exception):
    """Raised when JSON parsing fails."""

    def __init__(self, artifact_type: str, path: str, message: str) -> None:
        super().__init__(f"Parse error in {artifact_type} ({path}): {message}")
        self.artifact_type = artifact_type
        self.path = path


@dataclass
class ArtifactContent:
    """Loaded artifact with metadata."""

    record: ArtifactRecord
    data: dict[str, Any]
    resolved_path: str
    checksum_verified: bool


class ArtifactLoader:
    """Resolves artifact paths and loads JSON content with fallbacks."""

    def __init__(self, ctn_dir: Path) -> None:
        self.ctn_dir = ctn_dir.resolve()
        self._bridge = ArtifactRegistryBridge(self.ctn_dir)

    def _resolve_index_id(self) -> str | None:
        """Return the current index_id from the latest completed run."""
        latest = self._bridge.get_latest_index()
        return latest.index_id if latest else None

    def _resolve_path(self, artifact_type: str, index_id: str | None = None) -> Path | None:
        """Resolve the filesystem path for an artifact type.

        Resolution order:
        1. Registry lookup by type (most recent active artifact).
        2. Default pattern using provided or current index_id.
        3. Latest index outputs map lookup.
        """
        # 1. Registry lookup
        candidates = self._bridge.get_artifacts_by_type(artifact_type, limit=1)
        if candidates:
            record = candidates[0]
            logical = self.ctn_dir / record.logical_path
            if logical.exists():
                return logical

        # 2. Default pattern
        pattern = DEFAULT_PATH_PATTERNS.get(artifact_type)
        if pattern:
            if artifact_type in INDEX_SCOPED_TYPES:
                idx = index_id or self._resolve_index_id()
                if idx:
                    resolved = self.ctn_dir / pattern.format(index_id=idx)
                    if resolved.exists():
                        return resolved
            else:
                resolved = self.ctn_dir / pattern
                if resolved.exists():
                    return resolved

        # 3. Latest index outputs map
        latest = self._bridge.get_latest_index()
        if latest and latest.outputs:
            output_key = _artifact_type_to_output_key(artifact_type)
            if output_key:
                rel_path = latest.outputs.get(output_key)
                if rel_path:
                    candidate = (self.ctn_dir.parent / rel_path).resolve()
                    if candidate.exists():
                        return candidate
                    # Try relative to ctn_dir itself
                    candidate2 = self.ctn_dir / rel_path
                    if candidate2.exists():
                        return candidate2

        return None

    def resolve_path(self, artifact_type: str, *, index_id: str | None = None) -> Path | None:
        """Public wrapper around internal artifact path resolution."""
        return self._resolve_path(artifact_type, index_id=index_id)

    def load_json(
        self,
        artifact_type: str,
        *,
        index_id: str | None = None,
        verify_checksum: bool = True,
    ) -> dict[str, Any]:
        """Load and return the JSON content for an artifact type.

        Raises:
            ArtifactNotFoundError: if no file can be resolved.
            ChecksumMismatchError: if checksum verification fails.
            ArtifactParseError: if JSON parsing fails.
        """
        path = self._resolve_path(artifact_type, index_id=index_id)
        if path is None or not path.exists():
            raise ArtifactNotFoundError(artifact_type, str(path) if path else "<unresolved>")

        # Checksum verification
        record: ArtifactRecord | None = None
        candidates = self._bridge.get_artifacts_by_type(artifact_type, limit=1)
        if candidates:
            record = candidates[0]

        checksum_verified = False
        if verify_checksum and record and record.checksum:
            actual = compute_file_hash(path) or ""
            if actual and actual != record.checksum:
                raise ChecksumMismatchError(artifact_type, record.checksum, actual)
            checksum_verified = actual == record.checksum

        # Load JSON
        try:
            raw = path.read_text(encoding="utf-8")
            data: dict[str, Any] = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactParseError(artifact_type, str(path), str(exc))

        if not isinstance(data, dict):
            raise ArtifactParseError(artifact_type, str(path), "top-level value is not an object")

        return data

    def load_artifact(self, record: ArtifactRecord, *, verify_checksum: bool = True) -> ArtifactContent:
        """Load a specific artifact by its registry record."""
        path = self.ctn_dir / record.logical_path
        if not path.exists():
            raise ArtifactNotFoundError(record.artifact_type, record.logical_path)

        checksum_verified = False
        if verify_checksum and record.checksum:
            actual = compute_file_hash(path) or ""
            if actual and actual != record.checksum:
                raise ChecksumMismatchError(record.artifact_type, record.checksum, actual)
            checksum_verified = actual == record.checksum

        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactParseError(record.artifact_type, str(path), str(exc))

        if not isinstance(data, dict):
            raise ArtifactParseError(record.artifact_type, str(path), "top-level value is not an object")

        return ArtifactContent(
            record=record,
            data=data,
            resolved_path=str(path),
            checksum_verified=checksum_verified,
        )


def _artifact_type_to_output_key(artifact_type: str) -> str | None:
    """Map artifact types to keys used in index outputs."""
    mapping = {
        "graph_json": "graph_json",
        "bsg_json": "bsg_json",
        "context_overview_json": "overview_json",
        "context_files_json": "files_json",
    }
    return mapping.get(artifact_type)


__all__ = [
    "ArtifactLoader",
    "ArtifactContent",
    "ArtifactNotFoundError",
    "ChecksumMismatchError",
    "ArtifactParseError",
]
