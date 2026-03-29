"""
Path sanitization utilities to prevent security issues.

Provides functions to safely handle file paths and prevent path traversal attacks.
"""

import os
from pathlib import Path
from typing import Optional, Union
from batho_core.utils.logging import get_logger

logger = get_logger(__name__, component="path_sanitizer")


class PathSecurityError(Exception):
    """Raised when a path is determined to be unsafe."""
    pass


def sanitize_path(
    path: Union[str, Path], 
    base_dir: Optional[Union[str, Path]] = None,
    allow_absolute: bool = False
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
    path_obj = Path(path)
    
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
    
    # Join all path components
    result = base
    for path_component in paths:
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
            clean_path = clean_path[len(prefix):]
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
        "//",  # Double slashes (could indicate bypass attempts)
        "~",   # Home directory expansion
    ]
    
    for pattern in dangerous_patterns:
        if pattern in clean_path:
            raise PathSecurityError(f"Dangerous pattern '{pattern}' in diff path: {diff_path}")
    
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
    
    Args:
        filename: The filename to check
        
    Returns:
        True if filename is safe, False otherwise
    """
    # Check for null bytes
    if "\0" in filename:
        return False
    
    # Check for path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        return False
    
    # Check for reserved names (Windows)
    reserved_names = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
    }
    if filename.upper() in reserved_names:
        return False
    
    # Check for dangerous characters
    dangerous_chars = set("<>:\"|?*")
    if any(char in dangerous_chars for char in filename):
        return False
    
    return True


def validate_path_list(paths: list[Union[str, Path]], base_dir: Union[str, Path]) -> list[Path]:
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
