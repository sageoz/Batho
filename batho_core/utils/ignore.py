"""
backend/utils/ignore.py — Centralized ignore pattern utility for batho.

Provides unified ignore pattern handling across the entire codebase.
Combines default exclusions with .gitignore and .bathoignore files.

Usage:
    from backend.utils.ignore import load_ignore_spec, is_ignored, DEFAULT_IGNORE_PATTERNS

    spec = load_ignore_spec(root_path)
    if is_ignored(file_path, root_path, spec):
        continue
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from batho_core.utils.logging import get_logger

logger = get_logger(__name__)
# ---------------------------------------------------------------------------
# Default ignore patterns — applied even if ignore files don't exist
# ---------------------------------------------------------------------------

DEFAULT_IGNORE_PATTERNS: list[str] = [
    # Virtual environments
    ".venv/",
    "venv/",
    "env/",
    ".env/",
    "virtualenv/",
    # Node.js dependencies
    "node_modules/",
    "bower_components/",
    # Python cache
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".pytest_cache/",
    ".mypy_cache/",
    ".tox/",
    # Version control
    ".git/",
    ".svn/",
    ".hg/",
    # Build artifacts
    "build/",
    "dist/",
    "*.egg-info/",
    ".eggs/",
    "target/",  # Rust, Java
    "out/",  # TypeScript, etc.
    # IDE and tool directories
    ".idea/",
    ".vscode/",
    ".vs/",
    "*.swp",
    "*.swo",
    "*~",
    # OS files
    ".DS_Store",
    "Thumbs.db",
    # Lock files (usually very large)
    "uv.lock",
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
    "Cargo.lock",
    "Gemfile.lock",
    # Misc
    ".next/",  # Next.js build
    ".nuxt/",  # Nuxt.js build
    ".output/",
    "coverage/",
    "htmlcov/",
    ".coverage",
    ".sass-cache/",
    ".parcel-cache/",
    # Batho's own directories
    ".ctn/",
    ".batho/",
    ".aider/",
    ".roo/",
    ".cline/",
    ".kilo/",
    # (not source-of-truth code)
    "*.mod.c",  # Kernel module metadata — auto-generated
    "*.mod.h",
    ".config",  # Kconfig output — binary-ish
    "vmlinux.symvers",  # Linker symbol table
    "*.order",  # Build order files
    "*.a",  # Static libs
    "*.ko",  # Compiled modules
    "scripts/kconfig/*",  # Kconfig parser — not user code
    "Documentation/**/*.rst",  # Optional: skip docs for code-only graph
    "tools/testing/**",  # Optional: skip kernel selftests
    "arch/*/boot/compressed/",  # Compressed boot stubs

]

# Patterns that should always be ignored for file watching
WATCH_IGNORE_PATTERNS: list[str] = [
    "**/.git/**",
    "**/node_modules/**",
    "**/.venv/**",
    "**/venv/**",
    "**/__pycache__/**",
    "**/.ctn/**",
    "**/.batho/**",
    "**/dist/**",
    "**/build/**",
    "**/*.log",
    "**/.pytest_cache/**",
    "**/.mypy_cache/**",
    "**/.tox/**",
    "**/.next/**",
    "**/.nuxt/**",
    "**/.output/**",
    "**/.idea/**",
    "**/.vscode/**",
    "**/.vs/**",
    "**/*.swp",
    "**/*.swo",
    "**/*~",
    "**/.DS_Store",
    "**/Thumbs.db",
    "**/target/**",
    "**/out/**",
    "**/.aider/**",
    "**/.roo/**",
    "**/.cline/**",
    "**/.kilo/**",
    "**/testdata/**",
    "**/test_data/**",
    "**/fixtures/**",
    "**/mock_data/**",
]

# Agent-related patterns that should be ignored
AGENT_IGNORE_PATTERNS: list[str] = [
    "**/.aider.chat.history.md",
    "**/.aider.input.history",
    "**/.roo/**/*.md",
    "**/.cline/**/*.md",
    "**/.kilo/**/*.md",
    "**/.kilo/**/*.log",
]


# ---------------------------------------------------------------------------
# Ignore spec loading
# ---------------------------------------------------------------------------


def load_ignore_spec(
    root: Path,
    extra_patterns: list[str] | None = None,
    ignore_files: list[str] | None = None,
    bathoignore_path: str | None = None,
) -> Any:
    """
    Load combined ignore patterns using pathspec.

    Always includes default exclusions for common directories like .venv,
    node_modules, __pycache__, etc. to prevent indexing dependencies.

    If .bathoignore exists at repo root, merges its patterns with global patterns.
    If .bathoignore does NOT exist, uses only global patterns.

    Args:
        root: The workspace root path.
        extra_patterns: Additional patterns to include.
        ignore_files: List of ignore file names to load (relative to root).
                      Defaults to [".gitignore", ".bathoignore"].
        bathoignore_path: Optional custom path to .bathoignore file.

    Returns:
        A pathspec PathSpec object, or a list of patterns as fallback.
    """
    patterns: list[str] = list(DEFAULT_IGNORE_PATTERNS)

    if extra_patterns:
        patterns.extend(extra_patterns)

    # Default ignore files to check
    if ignore_files is None:
        ignore_files = [".gitignore", ".bathoignore"]

    # If custom bathoignore path is provided, use it instead of default
    if bathoignore_path:
        ignore_files = [bathoignore_path]

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
):
    """
    Yield (dirpath, dirnames, filenames) tuples like os.walk(),
    but with ignored directories removed from dirnames to prevent traversal.

    Args:
        root: The root directory to walk.
        spec: Optional pre-loaded ignore spec.
        skip_hidden: If True, also skip hidden directories.

    Yields:
        Tuples of (current_path, dirnames, filenames) with ignored dirs filtered.
    """
    if spec is None:
        spec = load_ignore_spec(root)

    for current_path, dirnames, filenames in root.walk():
        # Filter out ignored directories to prevent descending into them
        dirnames[:] = [
            d
            for d in dirnames
            if not should_ignore_path(current_path / d, root, spec, include_hidden=skip_hidden)
        ]

        # Filter out ignored files
        filtered_files = [
            f
            for f in filenames
            if not should_ignore_path(current_path / f, root, spec, include_hidden=skip_hidden)
        ]

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
