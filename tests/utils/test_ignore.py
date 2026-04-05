"""Tests for batho_core.utils.ignore module."""
from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from batho_core.utils.ignore import (
    DEFAULT_IGNORE_PATTERNS,
    WATCH_IGNORE_PATTERNS,
    is_ignored,
    load_ignore_spec,
    rglob_ignored_filtered,
    should_ignore_path,
    walk_ignored_filtered,
)


# ---------------------------------------------------------------------------
# DEFAULT_IGNORE_PATTERNS
# ---------------------------------------------------------------------------

class TestDefaultPatterns:

    def test_contains_venv(self):
        assert ".venv/" in DEFAULT_IGNORE_PATTERNS

    def test_contains_node_modules(self):
        assert "node_modules/" in DEFAULT_IGNORE_PATTERNS

    def test_contains_pycache(self):
        assert "__pycache__/" in DEFAULT_IGNORE_PATTERNS

    def test_contains_git(self):
        assert ".git/" in DEFAULT_IGNORE_PATTERNS

    def test_contains_ctn(self):
        assert ".ctn/" in DEFAULT_IGNORE_PATTERNS

    def test_watch_patterns_exist(self):
        assert len(WATCH_IGNORE_PATTERNS) > 0


# ---------------------------------------------------------------------------
# load_ignore_spec
# ---------------------------------------------------------------------------

class TestLoadIgnoreSpec:

    def test_returns_spec(self, tmp_path: Path):
        spec = load_ignore_spec(tmp_path)
        assert spec is not None

    def test_loads_gitignore(self, tmp_path: Path):
        (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")
        spec = load_ignore_spec(tmp_path)
        # .log files should be ignored
        assert is_ignored(tmp_path / "error.log", tmp_path, spec)

    def test_loads_bathoignore(self, tmp_path: Path):
        (tmp_path / ".bathoignore").write_text("custom_dir/\n")
        spec = load_ignore_spec(tmp_path)
        assert is_ignored(tmp_path / "custom_dir" / "file.py", tmp_path, spec)

    def test_extra_patterns(self, tmp_path: Path):
        spec = load_ignore_spec(tmp_path, extra_patterns=["extra_dir/"])
        assert is_ignored(tmp_path / "extra_dir" / "foo.py", tmp_path, spec)

    def test_custom_ignore_files(self, tmp_path: Path):
        (tmp_path / ".myignore").write_text("secret/\n")
        spec = load_ignore_spec(tmp_path, ignore_files=[".myignore"])
        assert is_ignored(tmp_path / "secret" / "key.pem", tmp_path, spec)

    def test_custom_bathoignore_path_and_read_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        custom = tmp_path / "custom.ignore"
        custom.write_text("cache/\n", encoding="utf-8")
        spec = load_ignore_spec(tmp_path, bathoignore_path="custom.ignore")
        assert is_ignored(tmp_path / "cache" / "x.py", tmp_path, spec)

        original = Path.read_text

        def _raise_once(self: Path, *args, **kwargs):
            if self.name == ".gitignore":
                raise OSError("boom")
            return original(self, *args, **kwargs)

        (tmp_path / ".gitignore").write_text("broken/\n", encoding="utf-8")
        monkeypatch.setattr(Path, "read_text", _raise_once)
        spec2 = load_ignore_spec(tmp_path)
        assert spec2 is not None

    def test_pathspec_import_fallback_to_list(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        original_import = builtins.__import__

        def _import(name, *args, **kwargs):
            if name == "pathspec":
                raise ImportError("forced")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _import)
        spec = load_ignore_spec(tmp_path, extra_patterns=["logs/"])
        assert isinstance(spec, list)
        assert any("logs/" == p for p in spec)


# ---------------------------------------------------------------------------
# is_ignored
# ---------------------------------------------------------------------------

class TestIsIgnored:

    def test_venv_ignored(self, tmp_path: Path):
        spec = load_ignore_spec(tmp_path)
        assert is_ignored(tmp_path / ".venv" / "lib" / "site.py", tmp_path, spec)

    def test_node_modules_ignored(self, tmp_path: Path):
        spec = load_ignore_spec(tmp_path)
        assert is_ignored(tmp_path / "node_modules" / "react" / "index.js", tmp_path, spec)

    def test_source_file_not_ignored(self, tmp_path: Path):
        spec = load_ignore_spec(tmp_path)
        assert not is_ignored(tmp_path / "src" / "main.py", tmp_path, spec)

    def test_pycache_ignored(self, tmp_path: Path):
        spec = load_ignore_spec(tmp_path)
        assert is_ignored(tmp_path / "__pycache__" / "mod.pyc", tmp_path, spec)

    def test_relative_path(self, tmp_path: Path):
        spec = load_ignore_spec(tmp_path)
        # Already-relative path
        assert is_ignored(Path("__pycache__/foo.pyc"), tmp_path, spec)

    def test_absolute_outside_root_returns_false(self, tmp_path: Path):
        spec = load_ignore_spec(tmp_path)
        outside = Path("/tmp/outside.py")
        assert is_ignored(outside, tmp_path, spec) is False

    def test_fnmatch_fallback_paths(self, tmp_path: Path):
        spec = ["build/", "*.tmp", "src/*.py"]
        assert is_ignored(tmp_path / "build" / "x.o", tmp_path, spec)
        assert is_ignored(tmp_path / "a.tmp", tmp_path, spec)
        assert is_ignored(tmp_path / "src" / "m.py", tmp_path, spec)


# ---------------------------------------------------------------------------
# should_ignore_path
# ---------------------------------------------------------------------------

class TestShouldIgnorePath:

    def test_hidden_files_ignored(self, tmp_path: Path):
        spec = load_ignore_spec(tmp_path)
        assert should_ignore_path(
            tmp_path / ".hidden" / "file.py", tmp_path, spec, include_hidden=True
        )

    def test_hidden_files_not_ignored(self, tmp_path: Path):
        spec = load_ignore_spec(tmp_path)
        # When include_hidden=False, hidden-check is skipped but spec still applies
        result = should_ignore_path(
            tmp_path / "src" / "main.py", tmp_path, spec, include_hidden=False
        )
        assert not result

    def test_loads_spec_if_none(self, tmp_path: Path):
        """When spec=None, should_ignore_path loads it automatically."""
        result = should_ignore_path(
            tmp_path / ".venv" / "lib.py", tmp_path, spec=None
        )
        assert result  # .venv is in defaults


# ---------------------------------------------------------------------------
# walk_ignored_filtered & rglob_ignored_filtered
# ---------------------------------------------------------------------------

class TestWalkFiltered:

    def test_walk_skips_venv(self, tmp_path: Path):
        (tmp_path / ".venv" / "lib").mkdir(parents=True)
        (tmp_path / ".venv" / "lib" / "pkg.py").write_text("x = 1")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hi')")

        found_files = []
        for dirpath, _, filenames in walk_ignored_filtered(tmp_path):
            for f in filenames:
                found_files.append((dirpath / f).relative_to(tmp_path).as_posix())

        assert "src/main.py" in found_files
        assert not any(".venv" in f for f in found_files)

    def test_rglob_filters(self, tmp_path: Path):
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "m.pyc").write_bytes(b"")
        (tmp_path / "app.py").write_text("def f(): pass")

        results = list(rglob_ignored_filtered(tmp_path, "*.py"))
        names = [p.name for p in results]
        assert "app.py" in names
        assert "m.pyc" not in names

    def test_walk_and_rglob_with_explicit_spec(self, tmp_path: Path):
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "keep.txt").write_text("ok", encoding="utf-8")
        (tmp_path / "data" / "drop.log").write_text("x", encoding="utf-8")

        spec = ["*.log"]
        walked = []
        for dirpath, _, files in walk_ignored_filtered(tmp_path, spec=spec, skip_hidden=False):
            for f in files:
                walked.append((dirpath / f).name)

        assert "keep.txt" in walked
        assert "drop.log" not in walked

        matches = list(rglob_ignored_filtered(tmp_path, "*.txt", spec=spec, skip_hidden=False))
        assert len(matches) == 1
        assert matches[0].name == "keep.txt"
