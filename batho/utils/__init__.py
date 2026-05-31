"""
Utility helpers for Batho core (hashing, encoding, ignore rules, logging).
"""

from .cli_output import CLIOutput
from .encoding import normalize_to_utf8
from .hash import (
    compute_bytes_hash,
    compute_file_hash,
    compute_file_hash_cached,
    compute_string_hash,
)
from .ignore import is_ignored, load_ignore_spec
from .logging import (
    configure_logging,
    configure_logging_from_dict,
    get_log_level,
    get_logger,
)

__all__ = [
    "compute_bytes_hash",
    "compute_string_hash",
    "compute_file_hash",
    "compute_file_hash_cached",
    "normalize_to_utf8",
    "CLIOutput",
    "load_ignore_spec",
    "is_ignored",
    "get_logger",
    "get_log_level",
    "configure_logging",
    "configure_logging_from_dict",
]
