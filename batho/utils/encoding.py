"""
backend/utils/encoding.py — File encoding utilities.

Provides consistent encoding detection and handling for reading files
with multiple encoding fallbacks.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_ENCODING = "utf-8"
FALLBACK_ENCODINGS = ["utf-8", "ascii", "latin-1", "cp1252"]


def read_text_with_fallback(
    filepath: Path | str, encodings: list[str] | None = None, errors: str = "strict"
) -> str:
    """
    Read file text with encoding fallback.

    Attempts to decode the file using multiple encodings in order.
    Useful for reading files that may not be UTF-8 encoded.

    Args:
        filepath: Path to file
        encodings: List of encodings to try (default: FALLBACK_ENCODINGS)
        errors: Error handling strategy ('strict', 'replace', 'ignore')

    Returns:
        Decoded text content

    Raises:
        UnicodeDecodeError: If all encodings fail
        FileNotFoundError: If file does not exist

    Example:
        >>> from backend.utils.encoding import read_text_with_fallback
        >>> text = read_text_with_fallback("/path/to/file.txt")
        >>> text = read_text_with_fallback("/path/to/file.txt", errors="strict")
    """
    encodings = encodings or FALLBACK_ENCODINGS
    data_bytes = Path(filepath).read_bytes()

    last_exc: UnicodeDecodeError | None = None
    for encoding in encodings:
        try:
            decoded = data_bytes.decode(encoding, errors="strict")
            if errors == "strict":
                return decoded
            return data_bytes.decode(encoding, errors=errors)
        except UnicodeDecodeError as exc:
            last_exc = exc
            continue

    if last_exc is not None:
        raise last_exc
    raise UnicodeDecodeError("unknown", b"", 0, 0, f"Failed to decode {filepath} with encodings: {encodings}")


def decode_bytes_with_fallback(
    data: bytes, encodings: list[str] | None = None, errors: str = "replace"
) -> str:
    """
    Decode bytes with encoding fallback.

    Attempts to decode bytes using multiple encodings in order.
    Falls back to latin-1 which never fails (maps bytes 0-255 to Unicode).

    Args:
        data: Binary data to decode
        encodings: List of encodings to try (default: FALLBACK_ENCODINGS)
        errors: Error handling strategy ('strict', 'replace', 'ignore')

    Returns:
        Decoded text string

    Example:
        >>> from backend.utils.encoding import decode_bytes_with_fallback
        >>> text = decode_bytes_with_fallback(b"\xff\xfe")
    """
    encodings = encodings or FALLBACK_ENCODINGS

    for encoding in encodings:
        try:
            return data.decode(encoding, errors=errors)
        except UnicodeDecodeError:
            continue

    # Final fallback: latin-1 never fails (maps bytes 0-255 to Unicode)
    return data.decode("latin-1", errors=errors)


def normalize_to_utf8(data: bytes, errors: str = "replace") -> bytes:
    """
    Normalize bytes to valid UTF-8.

    Decodes bytes with fallback encodings, then re-encodes to UTF-8.
    Useful for normalizing data from various sources to a consistent encoding.

    Args:
        data: Binary data to normalize
        errors: Error handling strategy for re-encoding ('strict', 'replace', 'ignore')

    Returns:
        Valid UTF-8 encoded bytes

    Example:
        >>> from backend.utils.encoding import normalize_to_utf8
        >>> utf8_data = normalize_to_utf8(raw_bytes)
    """
    text = decode_bytes_with_fallback(data)
    return text.encode("utf-8", errors=errors)
