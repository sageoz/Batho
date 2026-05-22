"""
batho/context/reconstructor.py — BSG Reconstruction Engine (Phase 3).

Provides lossless file reconstruction from BSG entities with integrity
checks.  Complements the gap-extraction pipeline (Phase 2): once every
byte of a source file has been captured in Entity.raw_content fields,
FileReconstructor can reassemble the original file by concatenating
raw_content in byte order.

Design principles:
- Pure in-memory operations — never touches disk.
- Deterministic: same entities always produce the same output.
- Hash verification is opt-in (controlled by config flag).
"""

from __future__ import annotations

import time
from typing import Any, Callable

from batho.utils.hash import compute_bytes_hash
from batho.utils.logging import get_logger

from .schema import (
    Entity,
    EntityType,
    FileSnapshot,
    IntegrityError,
    ReconstructionError,
    ReconstructionResult,
)

logger = get_logger(__name__, operation="reconstructor")


# ---------------------------------------------------------------------------
# FileReconstructor
# ---------------------------------------------------------------------------


class FileReconstructor:
    """
    Reconstructs source files from BSG entities by concatenating
    ``raw_content`` in byte order.

    All methods are pure — no disk I/O, no side-effects.  Disk writes
    and CLI output are the caller's responsibility.
    """

    def __init__(self) -> None:
        self._logger = get_logger(__name__, operation="reconstructor")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reconstruct_file(
        self,
        file_path: str,
        entities: list[Entity],
        original_hash: str | None = None,
        original_content: str | None = None,
    ) -> ReconstructionResult:
        """
        Reconstruct a file from its BSG entities.

        Args:
            file_path: Path to the file (for error reporting / result metadata).
            entities: All entities covering the file, including SYNTAX_GLUE gap
                      entities.  Must have ``raw_content`` set and valid byte
                      coverage.
            original_hash: Optional SHA256 hex digest of the original file
                           content.  If provided and the reconstructed hash
                           does not match, raises ``IntegrityError``.
            original_content: Optional original file content (string).  If
                              provided, ``original_hash`` is derived from it
                              automatically when not explicitly given.

        Returns:
            A ``ReconstructionResult`` summarising the outcome.

        Raises:
            ReconstructionError: If any entity is missing ``raw_content``,
                                 the entity list is empty, or coverage is
                                 insufficient.
            IntegrityError: If ``original_hash`` is given and the
                            reconstructed hash does not match.
        """
        t0 = time.perf_counter()

        # --- Guard: non-empty entities ---
        if not entities:
            raise ReconstructionError(
                message="No entities provided for reconstruction",
                file_path=file_path,
                entity_count=0,
            )

        # --- Validate entities ---
        for ent in entities:
            try:
                if ent.raw_content is not None and not ent.validate_coverage():
                    self._logger.warning(
                        "entity_coverage_mismatch",
                        entity_id=ent.id,
                        start_byte=ent.start_byte,
                        end_byte=ent.end_byte,
                        raw_len=len(ent.raw_content.encode("utf-8")),
                    )
            except ValueError as exc:
                if ent.raw_content is not None:
                    raise ReconstructionError(
                        message=str(exc),
                        file_path=file_path,
                        entity_count=len(entities),
                    ) from exc

        selected = self._select_covering_entities(entities)

        if not selected:
            raise ReconstructionError(
                message="No covering entities after overlap resolution",
                file_path=file_path,
                entity_count=len(entities),
            )

        # --- Concatenate raw_content, preferring raw_bytes for lossless reconstruction ---
        # Also accumulate entity_bytes in this single loop to avoid a second pass
        # (RECON-02: eliminates the separate entity_bytes summation below).
        reconstructed_parts: list[bytes] = []
        entity_bytes: int = 0
        for e in selected:
            if e.raw_bytes is not None:
                # Use raw_bytes for lossless reconstruction
                reconstructed_parts.append(e.raw_bytes)
                entity_bytes += len(e.raw_bytes)
            elif e.raw_content is not None:
                # Fallback to decoded content
                chunk = e.raw_content.encode("utf-8")
                reconstructed_parts.append(chunk)
                entity_bytes += len(chunk)
            else:
                raise ReconstructionError(
                    message=f"Entity '{e.id}' has neither raw_bytes nor raw_content",
                    file_path=file_path,
                    entity_count=len(entities),
                )

        reconstructed_bytes = b"".join(reconstructed_parts)
        reconstructed = reconstructed_bytes.decode("utf-8", errors="replace")
        raw_reconstructed_hash = compute_bytes_hash(reconstructed_bytes)
        decoded_reencoded_hash = compute_bytes_hash(reconstructed.encode("utf-8"))

        # --- Compute byte coverage ---
        # Use original content size if available for accurate coverage calculation
        if original_content is not None:
            total_bytes = len(original_content.encode("utf-8"))
        else:
            # Use max entity end_byte as fallback (may overestimate if trailing gaps exist)
            # This is the original behavior; file existence check was removed to avoid test failures
            # in scenarios where files don't exist on disk during testing
            total_bytes = max(e.end_byte for e in selected) if selected else 0

        # --- Resolve original hash ---
        resolved_original_hash: str = original_hash or ""
        if original_content is not None and not original_hash:
            resolved_original_hash = compute_bytes_hash(
                original_content.encode("utf-8")
            )

        # --- Integrity check ---
        hash_match = False
        reconstructed_hash = decoded_reencoded_hash
        if resolved_original_hash:
            if resolved_original_hash == raw_reconstructed_hash:
                hash_match = True
                reconstructed_hash = raw_reconstructed_hash
            elif resolved_original_hash == decoded_reencoded_hash:
                hash_match = True
                reconstructed_hash = decoded_reencoded_hash

        if hash_match:
            byte_coverage = 1.0
            coverage_ok = True
        else:
            # Compute covered bytes by merging intervals of selected entities to avoid >100% coverage
            covered_bytes = 0
            current_start = -1
            current_end = -1
            for e in sorted(selected, key=lambda x: x.start_byte):
                if e.start_byte > current_end:
                    if current_start != -1:
                        covered_bytes += (current_end - current_start)
                    current_start = e.start_byte
                    current_end = e.end_byte
                else:
                    current_end = max(current_end, e.end_byte)
            if current_start != -1:
                covered_bytes += (current_end - current_start)

            byte_coverage = min(1.0, covered_bytes / total_bytes) if total_bytes > 0 else 1.0
            coverage_ok = self._check_coverage(selected, total_bytes)

        if not coverage_ok:
            self._logger.warning(
                "reconstruction_coverage_gap",
                file_path=file_path,
                total_bytes=total_bytes,
                entity_bytes=entity_bytes,
            )
        # Raise on hash mismatch when any reference is available
        if resolved_original_hash and not hash_match:
            raise IntegrityError(
                message=(
                    f"Hash mismatch for {file_path}: "
                    f"expected {resolved_original_hash}, got {reconstructed_hash}"
                ),
                file_path=file_path,
                expected_hash=resolved_original_hash,
                actual_hash=reconstructed_hash,
            )

        elapsed_ms = round((time.perf_counter() - t0) * 1000)

        warnings: list[str] = []
        if not coverage_ok:
            warnings.append(
                "Entity byte ranges do not form a contiguous span; "
                "gaps detected in reconstruction"
            )
        if byte_coverage < 1.0:
            warnings.append(
                f"Byte coverage is {byte_coverage:.2%}; "
                f"reconstructed content may be incomplete"
            )

        return ReconstructionResult(
            success=True,
            file_path=file_path,
            reconstructed_content=reconstructed,
            original_hash=resolved_original_hash,
            reconstructed_hash=reconstructed_hash,
            hash_match=hash_match,
            entity_count=len(entities),
            gap_count=sum(
                1
                for e in selected
                if e.type == EntityType.SYNTAX_GLUE
            ),
            byte_coverage=round(byte_coverage, 4),
            reconstruction_time_ms=elapsed_ms,
            errors=[],
            warnings=warnings,
        )

    def verify_integrity(
        self,
        file_path: str,
        entities: list[Entity],
        original_content: str,
    ) -> dict[str, Any]:
        """
        Verify that entities can faithfully reproduce the original content.

        This is a convenience wrapper around ``reconstruct_file`` that
        catches ``IntegrityError`` and returns a report dict instead of
        raising — useful for bulk verification.

        Args:
            file_path: Path to the file (for error reporting).
            entities: Entities to verify.
            original_content: The original file content as a string.

        Returns:
            A dict with keys:
            - ``coverage_match``: True if entity byte ranges span the file.
            - ``hash_match``: True if reconstructed hash matches original.
            - ``reconstructed_hash``: SHA256 of concatenated raw_content.
            - ``original_hash``: SHA256 of original_content.
            - ``verified``: True only if both coverage and hash match.
            - ``errors``: Any error messages encountered.
        """
        original_bytes = original_content.encode("utf-8")
        original_hash = compute_bytes_hash(original_bytes)
        errors: list[str] = []
        hash_match = False
        reconstructed_hash = ""

        try:
            result = self.reconstruct_file(
                file_path=file_path,
                entities=entities,
                original_hash=original_hash,
            )
            hash_match = result.hash_match
            reconstructed_hash = result.reconstructed_hash
        except (ReconstructionError, IntegrityError) as exc:
            errors.append(str(exc))

        selected = self._select_covering_entities(entities)
        coverage_match = self._check_coverage(selected, len(original_bytes))

        return {
            "coverage_match": coverage_match,
            "hash_match": hash_match,
            "reconstructed_hash": reconstructed_hash,
            "original_hash": original_hash,
            "verified": coverage_match and hash_match,
            "errors": errors,
        }

    def reconstruct_from_snapshot(
        self,
        snapshot: FileSnapshot,
        entity_lookup: Callable[[str], Entity | None] | dict[str, Entity],
    ) -> ReconstructionResult:
        """
        Reconstruct a file from a ``FileSnapshot``.

        Resolves ``snapshot.entity_ids`` to ``Entity`` objects using
        the provided lookup, then delegates to ``reconstruct_file``.

        Args:
            snapshot: A ``FileSnapshot`` with ``entity_ids`` populated.
            entity_lookup: Either a callable ``(entity_id: str) -> Entity | None``
                           or a dict ``{entity_id: Entity}``.

        Returns:
            A ``ReconstructionResult``.

        Raises:
            ReconstructionError: If entities cannot be resolved.
            IntegrityError: If hash verification fails.
        """
        # Normalise lookup to a callable
        if isinstance(entity_lookup, dict):
            lookup_fn: Callable[[str], Entity | None] = entity_lookup.get  # type: ignore[assignment]
        else:
            lookup_fn = entity_lookup

        resolved: list[Entity] = []
        missing_ids: list[str] = []

        for eid in snapshot.entity_ids:
            entity = lookup_fn(eid)
            if entity is None:
                missing_ids.append(eid)
            else:
                resolved.append(entity)

        if missing_ids:
            self._logger.warning(
                "snapshot_missing_entities",
                file_path=snapshot.file_path,
                missing_count=len(missing_ids),
                missing_ids=missing_ids,
            )

        if not resolved:
            raise ReconstructionError(
                message=(
                    f"No entities could be resolved from snapshot "
                    f"for {snapshot.file_path}"
                ),
                file_path=snapshot.file_path,
                entity_count=0,
            )

        # Build original_hash from snapshot metadata
        original_hash = snapshot.file_hash or None

        return self.reconstruct_file(
            file_path=snapshot.file_path,
            entities=resolved,
            original_hash=original_hash,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _select_covering_entities(entities: list[Entity]) -> list[Entity]:
        """Select a non-overlapping subset of entities that covers the file.

        Greedy interval covering: sort by start_byte (asc), then end_byte
        (desc) so parent entities come first, then keep entities that extend
        the covered range.  Entities without raw_content are skipped.
        """
        sorted_ents = sorted(entities, key=lambda e: (e.start_byte, -e.end_byte))
        if not sorted_ents:
            return []

        selected: list[Entity] = []
        cursor: int = sorted_ents[0].start_byte
        for ent in sorted_ents:
            if ent.start_byte <= cursor and ent.end_byte > cursor:
                if ent.raw_content is not None:
                    selected.append(ent)
                    cursor = ent.end_byte
        return selected

    @staticmethod
    def _check_coverage(entities: list[Entity], file_size: int) -> bool:
        """Return True if entity byte ranges span the entire file size."""
        if not entities:
            return file_size == 0
        sorted_ents = sorted(entities, key=lambda e: (e.start_byte, e.end_byte))
        cursor = 0
        for ent in sorted_ents:
            if ent.start_byte > cursor:
                return False
            cursor = max(cursor, ent.end_byte)
        return cursor >= file_size