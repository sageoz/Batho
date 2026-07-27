"""Regression tests for path sanitization utilities."""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path

import pytest

from batho.utils.path_sanitizer import (
    PathSecurityError,
    is_safe_filename,
    safe_join,
    sanitize_diff_path,
    sanitize_path,
)


class TestSanitizePathTraversalVectors:
    """Parameterized regression coverage for H2 path traversal resistance."""

    _BASE = "/tmp/batho_test_base"

    @pytest.mark.parametrize(
        "unsafe_path",
        [
            "..%2f..%2f..%2fetc%2fpasswd",
            "....//....//etc/passwd",
            "..\\..\\..\\windows\\system32",
            "..%5c..%5c..%5cwindows",
            "/etc/passwd",
            "file:///etc/passwd",
            "..;/etc/passwd",
            "..%00/etc/passwd",
            "....//....//....//etc/shadow",
            "..%2e..%2e/etc/passwd",
            "..%252f..%252f/etc/passwd",
            # Full-width dot and slash traversal (U+FF0E, U+FF0F)
            unicodedata.normalize("NFKC", "．．／．．／etc／passwd"),
        ],
    )
    def test_sanitize_path_rejects_traversal(self, unsafe_path: str, tmp_path: Path) -> None:
        with pytest.raises(PathSecurityError):
            sanitize_path(unsafe_path, base_dir=tmp_path)

    @pytest.mark.parametrize(
        "unsafe_path",
        [
            "..%2f..%2f..%2fetc%2fpasswd",
            "....//....//etc/passwd",
            "..\\..\\..\\windows\\system32",
            "/etc/passwd",
            "file:///etc/passwd",
            "..%252f..%252f/etc/passwd",
        ],
    )
    def test_sanitize_diff_path_rejects_encoded_traversal(
        self, unsafe_path: str, tmp_path: Path
    ) -> None:
        with pytest.raises(PathSecurityError):
            sanitize_diff_path(unsafe_path, tmp_path)


class TestSanitizePathNullBytes:
    def test_null_byte_in_path_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(PathSecurityError):
            sanitize_path("..\0/etc/passwd", base_dir=tmp_path)

    def test_null_byte_component_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(PathSecurityError):
            safe_join(tmp_path, "foo\0bar")


class TestSanitizePathValidRelativePaths:
    def test_ordinary_nested_path_allowed(self, tmp_path: Path) -> None:
        result = sanitize_path("src/app.py", base_dir=tmp_path)
        assert result == (tmp_path / "src" / "app.py").resolve()

    def test_dotted_filename_allowed(self, tmp_path: Path) -> None:
        result = sanitize_path("a.b/file.txt", base_dir=tmp_path)
        assert result == (tmp_path / "a.b" / "file.txt").resolve()

    def test_unicode_filename_allowed(self, tmp_path: Path) -> None:
        result = sanitize_path("文档/ caf é.py", base_dir=tmp_path)
        assert result == (tmp_path / "文档" / " caf é.py").resolve()

    def test_filename_with_two_consecutive_dots_allowed(self, tmp_path: Path) -> None:
        result = sanitize_path("archive..tar.gz", base_dir=tmp_path)
        assert result == (tmp_path / "archive..tar.gz").resolve()


class TestSafeJoin:
    def test_safe_join_ordinary_components(self, tmp_path: Path) -> None:
        result = safe_join(tmp_path, "src", "app.py")
        assert result == (tmp_path / "src" / "app.py").resolve()

    @pytest.mark.parametrize(
        "unsafe_component",
        [
            "..%2f..%2fetc",
            "..\\windows",
            "/etc",
            "file:///etc",
        ],
    )
    def test_safe_join_rejects_unsafe_components(
        self, tmp_path: Path, unsafe_component: str
    ) -> None:
        with pytest.raises(PathSecurityError):
            safe_join(tmp_path, unsafe_component, "passwd")

    def test_safe_join_symlink_escape_detected(self, tmp_path: Path) -> None:
        # Place the target outside the temporary base so the symlink escapes.
        outside = tmp_path.parent / f"{tmp_path.name}_outside"
        outside.mkdir(parents=True, exist_ok=True)
        link = tmp_path / "link"
        try:
            link.symlink_to(outside)
        except OSError:  # Windows without developer mode may refuse symlinks
            pytest.skip("Cannot create symbolic link in this environment")
        try:
            with pytest.raises(PathSecurityError):
                safe_join(tmp_path, "link", "secret.txt")
        finally:
            outside.rmdir()


class TestIsSafeFilename:
    @pytest.mark.parametrize(
        "unsafe_filename",
        [
            "..%2fpasswd",
            "..\\windows",
            "file:///etc/passwd",
            "CON.txt",
            "PRN.txt",
            "AUX.txt",
            "COM1.txt",
            "LPT1.txt",
            "foo/bar",
            "foo\\bar",
            "file\0name",
            # Full-width slash
            unicodedata.normalize("NFKC", "etc／passwd"),
        ],
    )
    def test_is_safe_filename_rejects_unsafe(self, unsafe_filename: str) -> None:
        assert is_safe_filename(unsafe_filename) is False

    @pytest.mark.parametrize(
        "safe_filename",
        [
            "app.py",
            "archive..tar.gz",
            "café.py",
            "文档.py",
            "関数.py",
        ],
    )
    def test_is_safe_filename_accepts_safe(self, safe_filename: str) -> None:
        assert is_safe_filename(safe_filename) is True


class TestSanitizePathTypeValidation:
    def test_non_string_path_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(PathSecurityError):
            sanitize_path(123, base_dir=tmp_path)  # type: ignore[arg-type]

    def test_path_object_allowed(self, tmp_path: Path) -> None:
        result = sanitize_path(Path("src/app.py"), base_dir=tmp_path)
        assert result == (tmp_path / "src" / "app.py").resolve()
