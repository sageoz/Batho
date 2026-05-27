"""
batho/context/bsg_map/relativizer.py — Path relativization with caching.
"""

from __future__ import annotations

from pathlib import Path


class PathRelativizer:
    """
    Cached path relativization helper.

    Computes root_path.resolve() once at initialization and maintains
    a persistent cache across calls. Eliminates redundant syscalls when
    relativizing many paths during BSG build/patch operations.
    """

    def __init__(self, root: str | None = None) -> None:
        if root:
            self._root_path = Path(root).resolve()
        else:
            self._root_path = Path.cwd().resolve()
        self._cache: dict[str, str] = {}

    def __call__(self, p: str) -> str:
        """Convert absolute path *p* to a path relative to root_path."""
        cached = self._cache.get(p)
        if cached is not None:
            return cached
        try:
            # We use resolve() to ensure we're comparing canonical paths
            rel = Path(p).resolve().relative_to(self._root_path).as_posix()
        except ValueError:
            # Fallback for paths outside the root
            rel = Path(p).as_posix()
        self._cache[p] = rel
        return rel

    def root_path(self) -> Path:
        """Return the resolved root path."""
        return self._root_path
