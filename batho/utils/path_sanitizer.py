"""
Path sanitization utilities to prevent security issues.

Provides functions to safely handle file paths and prevent path traversal attacks.
"""

import os
import unicodedata
from pathlib import Path
from typing import Optional, Union
from urllib.parse import unquote, urlsplit

from batho.utils.logging import get_logger

logger = get_logger(__name__, component="path_sanitizer")


class PathSecurityError(Exception):
    """Raised when a path is determined to be unsafe."""

    pass  # Required for exception class definition


# Maximum percent-decode iterations to prevent nested encoding bypasses.
_MAX_PERCENT_DECODE_ROUNDS = 5


def _canonicalize_untrusted_path(
    value: Union[str, Path], allow_absolute: bool = False
) -> str:
    """Canonicalize an untrusted path string before Path construction.

    Performs defense-in-depth normalization and rejects common traversal
    vectors (percent encoding, Unicode homoglyphs, URI schemes, backslashes,
    absolute paths, null bytes, and parent-directory components). The returned
    value is a safe relative POSIX-style path string that may still contain
    benign dots and slashes.

    When ``allow_absolute`` is True, leading-slash absolute paths are permitted
    (used only for trusted, operator-supplied paths such as registry entries
    and the ``--root`` CLI flag). All other defenses still apply.

    Raises:
        PathSecurityError: If the input cannot be made safe.
    """
    if not isinstance(value, (str, Path)):
        raise PathSecurityError(f"Non-string path rejected: {type(value)!r}")

    text = str(value)

    if "\0" in text:
        raise PathSecurityError("Null byte in path")

    # Decode percent encoding in a bounded loop so %252f cannot bypass a single
    # unquote() call. Use latin-1 as an intermediate representation because
    # unquote() returns str in Py3, but repeated decoding should stabilize.
    decoded = text
    for _ in range(_MAX_PERCENT_DECODE_ROUNDS):
        new = unquote(decoded)
        if new == decoded:
            break
        decoded = new
    else:
        # If we never hit the break, encoding kept changing; treat as attack.
        raise PathSecurityError(f"Percent decoding did not stabilize: {text!r}")

    # Normalize Unicode so full-width dot/slash and lookalikes become canonical.
    try:
        decoded = unicodedata.normalize("NFKC", decoded)
    except Exception as exc:
        raise PathSecurityError(f"Unicode normalization failed: {exc}") from exc

    # Reject explicit URI schemes (e.g. file:///etc/passwd). urlsplit on a path
    # with no scheme returns an empty scheme.
    parsed = urlsplit(decoded)
    if parsed.scheme:
        raise PathSecurityError(f"URI scheme not allowed: {parsed.scheme}")

    # Convert backslashes to forward slashes for cross-platform validation.
    decoded = decoded.replace("\\", "/")

    # Reject null bytes that may have been introduced by percent-decoding (%00).
    if "\0" in decoded:
        raise PathSecurityError("Null byte in decoded path")

    # Reject absolute paths after canonicalization, unless explicitly allowed
    # for trusted operator-supplied paths (registry entries, --root CLI flag).
    if decoded.startswith("/") and not allow_absolute:
        raise PathSecurityError(f"Absolute path not allowed: {text!r}")
    # Windows drive-prefixed forms such as C: or C:/
    if len(decoded) >= 2 and decoded[1] == ":":
        raise PathSecurityError(f"Drive-prefixed path not allowed: {text!r}")
    # UNC paths such as //server/share
    if decoded.startswith("//"):
        raise PathSecurityError(f"UNC path not allowed: {text!r}")

    # Treat semicolons like path separators because some URL/web path parsers
    # interpret ; as a path-parameter delimiter, enabling traversal evasions
    # such as "..;/etc/passwd".
    decoded = decoded.replace(";", "/")

    # Collapse multiple consecutive slashes to a single slash so that
    # "....//....//etc/passwd" cannot hide traversal behind empty components.
    while "//" in decoded:
        decoded = decoded.replace("//", "/")

    # Reject .. components; do not reject benign filenames merely because they
    # contain two consecutive dots.
    parts = [p for p in decoded.split("/") if p]
    if any(p == ".." for p in parts):
        raise PathSecurityError(f"Path traversal component rejected: {text!r}")

    # Defense against double-dot evasion patterns such as "....//" or
    # "..%2e..%2e" which, after canonicalization, contain multiple consecutive
    # dots. Removing every ".." substring must not collapse a non-absolute path
    # into an absolute path or into a traversal that starts with "..". For
    # trusted absolute paths (allow_absolute=True) this check is skipped since
    # the leading slash is expected.
    stripped = decoded.replace("..", "")
    if not allow_absolute and stripped.startswith("/"):
        raise PathSecurityError(f"Double-dot traversal evasion rejected: {text!r}")

    return decoded


def sanitize_path(
    path: Union[str, Path],
    base_dir: Optional[Union[str, Path]] = None,
    allow_absolute: bool = False,
) -> Path:
    """
    Sanitize a file path to prevent security issues.

    Args:
        path: The path to sanitize
        base_dir: Base directory to resolve relative paths against
        allow_absolute: Whether to allow absolute paths

    Returns:
        Sanitized absolute Path object

    Raises:
        PathSecurityError: If the path is determined to be unsafe
    """
    # Canonicalize untrusted input before constructing a Path. For absolute-path
    # mode we still canonicalize to reject encodings/URI schemes/null bytes, then
    # check allow_absolute separately.
    canonical = _canonicalize_untrusted_path(path, allow_absolute=allow_absolute)
    path_obj = Path(canonical)

    # Convert to absolute path
    if base_dir:
        base_dir = Path(base_dir).resolve()
        if path_obj.is_absolute():
            if not allow_absolute:
                raise PathSecurityError(f"Absolute path not allowed: {path_obj}")
            final_path = path_obj.resolve()
        else:
            final_path = (base_dir / path_obj).resolve()
    else:
        final_path = path_obj.resolve()

    # Check for path traversal attempts
    if base_dir and not _is_path_safe(final_path, Path(base_dir).resolve()):
        raise PathSecurityError(f"Path traversal detected: {path} -> {final_path}")

    return final_path


def _is_path_safe(path: Path, base_dir: Path) -> bool:
    """
    Check if a path is safe (doesn't escape base directory).

    Args:
        path: The path to check
        base_dir: The base directory that should contain the path

    Returns:
        True if path is safe, False otherwise
    """
    try:
        path.relative_to(base_dir)
        return True
    except ValueError:
        return False


def safe_join(base_dir: Union[str, Path], *paths: Union[str, Path]) -> Path:
    """
    Safely join paths, preventing path traversal.

    Args:
        base_dir: Base directory
        *paths: Path components to join

    Returns:
        Safe joined path

    Raises:
        PathSecurityError: If the resulting path would escape base_dir
    """
    base = Path(base_dir).resolve()

    # Canonicalize each untrusted component before joining. This rejects percent
    # encoding, URI schemes, null bytes, Unicode lookalikes, backslash-based
    # traversal, and parent-directory components at the source.
    canonical_components = []
    for path_component in paths:
        canonical = _canonicalize_untrusted_path(path_component)
        # An absolute component from canonicalization should not happen because
        # leading slashes are rejected, but guard against any accidental leak.
        if Path(canonical).is_absolute():
            raise PathSecurityError(
                f"Absolute component not allowed in safe_join: {path_component!r}"
            )
        canonical_components.append(Path(canonical))

    # Join all path components
    result = base
    for path_component in canonical_components:
        result = result / path_component

    # Resolve to handle .. and .
    final_path = result.resolve()

    # Ensure we're still within base directory
    if not _is_path_safe(final_path, base):
        raise PathSecurityError(f"Path traversal in safe_join: {paths} -> {final_path}")

    return final_path


def sanitize_diff_path(diff_path: str, base_dir: Union[str, Path]) -> Path:
    """
    Sanitize a path from a git diff output.

    Git diff paths can be malicious and include path traversal attempts.

    Args:
        diff_path: Path from git diff (e.g., "b/src/main.py" or "a/../../../etc/passwd")
        base_dir: Base directory to resolve against

    Returns:
        Sanitized absolute path

    Raises:
        PathSecurityError: If the path is determined to be unsafe
    """
    # Remove git diff prefixes
    clean_path = diff_path
    for prefix in ["b/", "a/"]:
        if clean_path.startswith(prefix):
            clean_path = clean_path[len(prefix) :]
            break

    # Skip /dev/null which represents deleted files
    if clean_path == "/dev/null" or clean_path == "dev/null":
        raise PathSecurityError("Cannot process /dev/null paths")

    # Reject absolute paths in diffs (they should always be relative)
    if clean_path.startswith("/"):
        raise PathSecurityError(f"Absolute path not allowed in diff: {diff_path}")

    # Check for other dangerous patterns
    dangerous_patterns = [
        "\0",  # Null bytes
    ]

    for pattern in dangerous_patterns:
        if pattern in clean_path:
            raise PathSecurityError(
                f"Dangerous pattern '{pattern}' in diff path: {diff_path}"
            )

    # Use proper path resolution instead of string-based detection
    try:
        resolved_path = sanitize_path(clean_path, base_dir, allow_absolute=False)
        return resolved_path
    except PathSecurityError:
        # Re-raise with more context
        raise PathSecurityError(f"Path traversal detected in diff path: {diff_path}")


def is_safe_filename(filename: str) -> bool:
    """
    Check if a filename is safe (no directory traversal, no null bytes, etc.).
    Decodes URL-encoded characters and normalizes Unicode to NFKC form to prevent bypasses.

    Args:
        filename: The filename to check

    Returns:
        True if filename is safe, False otherwise
    """
    # Reuse shared canonicalization for percent encoding, NFKC, null bytes,
    # traversal markers, URI schemes, and absolute paths.
    try:
        normalized = _canonicalize_untrusted_path(filename)
    except PathSecurityError:
        return False

    # _canonicalize_untrusted_path rejects null bytes, .. components, absolute
    # paths, and URI schemes, but it normalizes backslashes to forward slashes
    # so that path validation can use a single separator. A filename must not
    # contain any path separator.
    if "/" in normalized or "\\" in normalized:
        return False

    # Check for reserved names (Windows). Windows treats COM1.txt, LPT1.txt, etc.
    # as the device name itself; strip a leading extension before matching.
    reserved_names = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
    stem = normalized.split(".", 1)[0]
    if stem.upper() in reserved_names:
        return False

    # Check for dangerous characters
    dangerous_chars = set('<>:"|?*')
    if any(char in dangerous_chars for char in normalized):
        return False

    return True


def validate_path_list(
    paths: list[Union[str, Path]], base_dir: Union[str, Path]
) -> list[Path]:
    """
    Validate and sanitize a list of paths.

    Args:
        paths: List of paths to validate
        base_dir: Base directory for resolution

    Returns:
        List of sanitized paths

    Raises:
        PathSecurityError: If any path is unsafe
    """
    sanitized = []
    for path in paths:
        sanitized.append(sanitize_path(path, base_dir, allow_absolute=False))
    return sanitized


def is_filesystem_case_insensitive(dir_path: Path) -> bool:
    """
    Check if the filesystem at the given directory path is case-insensitive.
    """
    try:
        import tempfile
        dir_path_resolved = Path(dir_path).resolve()
        dir_path_resolved.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=str(dir_path_resolved), prefix="batho_case_test_") as f:
            p = Path(f.name)
            alt_p = Path(str(p).upper() if str(p).islower() else str(p).lower())
            return alt_p.exists()
    except Exception:
        import sys
        return sys.platform in ("win32", "darwin")
