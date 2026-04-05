"""
Utility helpers for Batho core (hashing, encoding, ignore rules, logging).
"""

from .encoding import normalize_to_utf8
from .hash import (
    compute_bytes_hash,
    compute_file_hash,
    compute_file_hash_cached,
    compute_string_hash,
    generate_entity_id,
    generate_relationship_id,
)
from .ignore import is_ignored, load_ignore_spec
from .logging import get_log_level, get_logger
from .patch_errors import (
    PatchValidationError,
    PatchConsistencyError,
    PatchSnapshotError,
    PatchFileError,
    PatchTimeoutError,
    PatchAuditLogger,
    audit_logger,
)

__all__ = [
    "compute_bytes_hash",
    "compute_string_hash",
    "compute_file_hash",
    "compute_file_hash_cached",
    "generate_entity_id",
    "generate_relationship_id",
    "normalize_to_utf8",
    "load_ignore_spec",
    "is_ignored",
    "get_logger",
    "get_log_level",
    "PatchValidationError",
    "PatchConsistencyError",
    "PatchSnapshotError",
    "PatchFileError",
    "PatchTimeoutError",
    "PatchAuditLogger",
    "audit_logger",
]
