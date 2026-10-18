"""
batho/utils/ignore.py — Centralized ignore pattern utility for batho.

Provides unified ignore pattern handling across the entire codebase.
Loads default patterns from default-ignore-patterns.yaml with .gitignore files.

Usage:
    from batho.utils.ignore import load_ignore_spec, is_ignored

    spec = load_ignore_spec(root_path)
    if is_ignored(file_path, root_path, spec):
        continue
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from batho.utils.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Default patterns file
# ---------------------------------------------------------------------------

DEFAULT_PATTERNS_FILE = "default-ignore-patterns.yaml"


def get_default_patterns_path() -> Path:
    """Get the path to the default ignore patterns YAML file."""
    return Path(__file__).parent.parent / "core" / "config" / DEFAULT_PATTERNS_FILE


def load_default_patterns_from_yaml(
    patterns_file: Path | None = None,
) -> list[str]:
    """
    Load default patterns from YAML file. Returns empty list if file unavailable.

    Args:
        patterns_file: Optional path to custom patterns YAML file.
                       If None, uses built-in default-ignore-patterns.yaml.

    Returns:
        List of default ignore patterns, or empty list if file not found.
    """
    if patterns_file is None:
        patterns_file = get_default_patterns_path()

    if not patterns_file.exists():
        logger.debug(
            "default_patterns_file_not_found",
            path=str(patterns_file),
        )
        return []

    try:
        import yaml  # type: ignore[import-untyped]

        with open(patterns_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data and isinstance(data, dict):
            patterns = data.get("patterns", [])
            if isinstance(patterns, list):
                logger.debug(
                    "default_patterns_loaded_from_yaml",
                    path=str(patterns_file),
                    count=len(patterns),
                )
                return patterns
    except Exception as e:
        logger.warning(
            "failed_to_load_default_patterns_yaml",
            path=str(patterns_file),
            error=str(e),
        )

    return []


# ---------------------------------------------------------------------------
# Ignore spec loading
# ---------------------------------------------------------------------------


def load_ignore_spec(
    root: Path,
    extra_patterns: list[str] | None = None,
    ignore_files: list[str] | None = None,
    default_patterns_file: Path | str | None = None,
    use_defaults: bool = True,
) -> Any:
    """
    Load combined ignore patterns using pathspec.

    Includes default exclusions for common directories like .venv,
    node_modules, __pycache__, etc. to prevent indexing dependencies,
    unless ``use_defaults`` is False (opt-out via indexer.ignore_defaults).

    Only loads .gitignore patterns (no backward compatibility for .bathoignore).

    Args:
        root: The workspace root path.
        extra_patterns: Additional patterns to include.
        ignore_files: List of ignore file names to load (relative to root).
                      Defaults to [".gitignore"].
        default_patterns_file: Optional path (str or Path) to custom default patterns YAML.
                               If None, uses built-in defaults.
        use_defaults: If False, skip built-in default patterns (user patterns and
                      .gitignore still apply).

    Returns:
        A pathspec PathSpec object, or a list of patterns as fallback.
    """
    patterns_file_path: Path | None = None
    if default_patterns_file:
        patterns_file_path = Path(default_patterns_file) if isinstance(default_patterns_file, str) else default_patterns_file

    patterns: list[str] = []
    if use_defaults:
        patterns.extend(load_default_patterns_from_yaml(patterns_file_path))

    if extra_patterns:
        patterns.extend(extra_patterns)

    # Default ignore files to check - only .gitignore (no .bathoignore support)
    if ignore_files is None:
        ignore_files = [".gitignore"]

    for ignore_file_name in ignore_files:
        ignore_file = root / ignore_file_name
        if ignore_file.exists():
            try:
                text = ignore_file.read_text(encoding="utf-8", errors="ignore")
                for line in text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line)
                logger.debug(
                    "ignore_file_loaded",
                    ignore_file=str(ignore_file),
                    patterns_added=len(text.splitlines()),
                )
            except OSError as read_exc:
                logger.debug(
                    "ignore_file_read_failed",
                    ignore_file=str(ignore_file),
                    error=str(read_exc),
                )
                pass  # Continue without this ignore file

    try:
        import pathspec  # type: ignore[import-untyped]

        return pathspec.PathSpec.from_lines("gitignore", patterns)
    except ImportError:
        # Fallback: store raw patterns for fnmatch
        return patterns


def is_ignored(file_path: Path, root: Path, spec: Any) -> bool:
    """
    Return True if file_path matches the ignore spec.

    Args:
        file_path: The path to check (can be absolute or relative).
        root: The workspace root path.
        spec: The ignore spec from load_ignore_spec() (pathspec or list).

    Returns:
        True if the file should be ignored, False otherwise.
    """
    try:
        rel = file_path.relative_to(root).as_posix()
    except ValueError:
        # If file_path is not relative to root, check if it's already relative
        if not file_path.is_absolute():
            rel = file_path.as_posix()
        else:
            return False

    # pathspec PathSpec
    if hasattr(spec, "match_file"):
        return spec.match_file(rel)

    # fnmatch fallback
    import fnmatch

    parts = Path(rel).parts
    for pattern in spec:
        normalized = pattern.rstrip("/")
        # Check if any path part matches
        for part in parts:
            if fnmatch.fnmatch(part, normalized):
                return True
        # Check full relative path
        if fnmatch.fnmatch(rel, pattern):
            return True
        # Check with trailing slash for directories
        if fnmatch.fnmatch(rel + "/", pattern):
            return True
    return False


def should_ignore_path(
    path: Path,
    root: Path,
    spec: Any | None = None,
    include_hidden: bool = True,
) -> bool:
    """
    Convenience function to check if a path should be ignored.

    Loads the ignore spec automatically if not provided.
    Optionally skips hidden files (starting with ".").

    Args:
        path: The path to check.
        root: The workspace root path.
        spec: Optional pre-loaded ignore spec.
        include_hidden: If True, also ignores hidden files/directories.

    Returns:
        True if the path should be ignored.
    """
    if include_hidden:
        # Check if any part of the path is hidden
        rel_parts = []
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            rel_parts = path.parts if not path.is_absolute() else []

        for part in rel_parts:
            if part.startswith(".") and part not in (".", ".."):
                return True

    if spec is None:
        spec = load_ignore_spec(root)

    return is_ignored(path, root, spec)


# ---------------------------------------------------------------------------
# Iterator helpers
# ---------------------------------------------------------------------------


def walk_ignored_filtered(
    root: Path,
    spec: Any | None = None,
    skip_hidden: bool = True,
    skipped_paths: list[Path] | None = None,
):
    """
    Yield (dirpath, dirnames, filenames) tuples like os.walk(),
    but with ignored directories removed from dirnames to prevent traversal.

    Args:
        root: The root directory to walk.
        spec: Optional pre-loaded ignore spec.
        skip_hidden: If True, also skip hidden directories.
        skipped_paths: Optional list that receives every skipped (ignored)
            path — files and directories — so callers can report what the
            ignore spec filtered out.

    Yields:
        Tuples of (current_path, dirnames, filenames) with ignored dirs filtered.
    """
    if spec is None:
        spec = load_ignore_spec(root)

    import os
    for dirpath_str, dirnames, filenames in os.walk(str(root)):
        current_path = Path(dirpath_str)
        # Filter out ignored directories to prevent descending into them
        kept_dirs = []
        for d in dirnames:
            dpath = current_path / d
            if should_ignore_path(dpath, root, spec, include_hidden=skip_hidden):
                if skipped_paths is not None:
                    skipped_paths.append(dpath)
            else:
                kept_dirs.append(d)
        dirnames[:] = kept_dirs

        # Filter out ignored files
        filtered_files = []
        for f in filenames:
            fpath = current_path / f
            if should_ignore_path(fpath, root, spec, include_hidden=skip_hidden):
                if skipped_paths is not None:
                    skipped_paths.append(fpath)
            else:
                filtered_files.append(f)

        yield current_path, dirnames, filtered_files


def rglob_ignored_filtered(
    root: Path,
    pattern: str,
    spec: Any | None = None,
    skip_hidden: bool = True,
):
    """
    Yield paths matching pattern like Path.rglob(), but filter out ignored paths.

    Args:
        root: The root directory to search.
        pattern: The glob pattern to match.
        spec: Optional pre-loaded ignore spec.
        skip_hidden: If True, also skip hidden files.

    Yields:
        Path objects that match the pattern and are not ignored.
    """
    if spec is None:
        spec = load_ignore_spec(root)

    for path in root.rglob(pattern):
        if not should_ignore_path(path, root, spec, include_hidden=skip_hidden):
            yield path
