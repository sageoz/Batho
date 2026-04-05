"""Tests for batho.utils.path_sanitizer."""

from __future__ import annotations

from pathlib import Path

import pytest

from batho.utils.path_sanitizer import (
    PathSecurityError,
    is_safe_filename,
    safe_join,
    sanitize_diff_path,
    sanitize_path,
    validate_path_list,
)


class TestSanitizePath:

    def test_relative_path_with_base(self, tmp_path: Path):
        out = sanitize_path("src/main.py", tmp_path)
        assert out == (tmp_path / "src/main.py").resolve()

    def test_absolute_path_disallowed(self, tmp_path: Path):
        with pytest.raises(PathSecurityError):
            sanitize_path(tmp_path / "abs.py", tmp_path, allow_absolute=False)

    def test_path_traversal_rejected(self, tmp_path: Path):
        with pytest.raises(PathSecurityError):
            sanitize_path("../outside.txt", tmp_path)


class TestSafeJoin:

    def test_safe_join_success(self, tmp_path: Path):
        out = safe_join(tmp_path, "a", "b", "c.txt")
        assert out == (tmp_path / "a" / "b" / "c.txt").resolve()

    def test_safe_join_rejects_traversal(self, tmp_path: Path):
        with pytest.raises(PathSecurityError):
            safe_join(tmp_path, "..", "etc", "passwd")


class TestSanitizeDiffPath:

    def test_strips_git_prefix(self, tmp_path: Path):
        out = sanitize_diff_path("b/src/app.py", tmp_path)
        assert out == (tmp_path / "src" / "app.py").resolve()

    def test_rejects_dev_null(self, tmp_path: Path):
        with pytest.raises(PathSecurityError):
            sanitize_diff_path("/dev/null", tmp_path)

    def test_rejects_absolute_and_dangerous_patterns(self, tmp_path: Path):
        with pytest.raises(PathSecurityError):
            sanitize_diff_path("/etc/passwd", tmp_path)
        with pytest.raises(PathSecurityError):
            sanitize_diff_path("b/src//app.py", tmp_path)
        with pytest.raises(PathSecurityError):
            sanitize_diff_path("b/~/.bashrc", tmp_path)


class TestFilenameSafety:

    def test_safe_filename(self):
        assert is_safe_filename("main.py") is True

    @pytest.mark.parametrize(
        "name",
        [
            "bad/thing.py",
            "bad\\thing.py",
            "..",
            "CON",
            "NUL",
            "x<y.py",
            "x?y.py",
            "null\0byte.py",
        ],
    )
    def test_unsafe_filename(self, name: str):
        assert is_safe_filename(name) is False


class TestValidatePathList:

    def test_validate_list_success(self, tmp_path: Path):
        out = validate_path_list(["a.py", "b/c.py"], tmp_path)
        assert len(out) == 2
        assert out[0] == (tmp_path / "a.py").resolve()

    def test_validate_list_raises_on_unsafe(self, tmp_path: Path):
        with pytest.raises(PathSecurityError):
            validate_path_list(["ok.py", "../bad.py"], tmp_path)
