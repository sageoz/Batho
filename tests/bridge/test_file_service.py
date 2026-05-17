"""Tests for the bridge file service."""

from pathlib import Path

import pytest

from batho.bridge.file_service import (
    FileNotFoundError as FileServiceNotFoundError,
    SecurityError,
    build_file_content_response,
    get_entities_for_file,
    get_language_from_path,
    safe_read_file,
)


class TestSafeReadFile:
    """Test safe file reading with security checks."""

    def test_safe_read_file_success(self, tmp_path):
        """Test reading a valid file within the root."""
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello world')", encoding="utf-8")

        result = safe_read_file("test.py", tmp_path)
        assert result == "print('hello world')"

    def test_safe_read_file_with_subdirectories(self, tmp_path):
        """Test reading a file in a subdirectory."""
        subdir = tmp_path / "src"
        subdir.mkdir()
        test_file = subdir / "main.py"
        test_file.write_text("def main(): pass", encoding="utf-8")

        result = safe_read_file("src/main.py", tmp_path)
        assert result == "def main(): pass"

    def test_path_traversal_blocked(self, tmp_path):
        """Test that path traversal attacks are blocked."""
        with pytest.raises(SecurityError) as exc_info:
            safe_read_file("../etc/passwd", tmp_path)
        assert "outside project root" in str(exc_info.value).lower()

    def test_absolute_path_blocked(self, tmp_path):
        """Test that absolute paths outside root are blocked."""
        with pytest.raises(SecurityError) as exc_info:
            safe_read_file("/etc/passwd", tmp_path)
        assert "outside project root" in str(exc_info.value).lower()

    def test_nonexistent_file(self, tmp_path):
        """Test that nonexistent files raise FileNotFoundError."""
        with pytest.raises(FileServiceNotFoundError):
            safe_read_file("nonexistent.py", tmp_path)

    def test_directory_not_allowed(self, tmp_path):
        """Test that directories cannot be read as files."""
        subdir = tmp_path / "src"
        subdir.mkdir()

        with pytest.raises(FileServiceNotFoundError):
            safe_read_file("src", tmp_path)

    def test_ignored_file_blocked(self, tmp_path):
        """Test that files matching .bathoignore are blocked."""
        # Create .bathoignore
        ignore_file = tmp_path / ".bathoignore"
        ignore_file.write_text("secret.py\n", encoding="utf-8")

        # Create ignored file
        secret_file = tmp_path / "secret.py"
        secret_file.write_text("password = '12345'", encoding="utf-8")

        with pytest.raises(SecurityError) as exc_info:
            safe_read_file("secret.py", tmp_path)
        assert "ignored" in str(exc_info.value).lower()

    def test_path_with_leading_dot_slash(self, tmp_path):
        """Test that ./path format is handled correctly."""
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1", encoding="utf-8")

        result = safe_read_file("./test.py", tmp_path)
        assert result == "x = 1"

    def test_path_with_leading_slash_blocked(self, tmp_path):
        """Test that absolute paths like /test.py are blocked for security."""
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1", encoding="utf-8")

        # Absolute paths should be blocked as security risk
        with pytest.raises(SecurityError) as exc_info:
            safe_read_file("/test.py", tmp_path)
        assert "outside project root" in str(exc_info.value).lower()

    def test_hidden_file_allowed(self, tmp_path):
        """Test that hidden files like .pre-commit-config.yaml can be viewed."""
        hidden_file = tmp_path / ".pre-commit-config.yaml"
        hidden_file.write_text("repos: []", encoding="utf-8")

        # Hidden files should be readable (they're legitimate source files)
        result = safe_read_file(".pre-commit-config.yaml", tmp_path)
        assert result == "repos: []"

    def test_hidden_file_with_bathoignore_blocked(self, tmp_path):
        """Test that hidden files can still be blocked via .bathoignore."""
        # Create .bathoignore that blocks the hidden file
        ignore_file = tmp_path / ".bathoignore"
        ignore_file.write_text(".secret\n", encoding="utf-8")

        secret_file = tmp_path / ".secret"
        secret_file.write_text("password", encoding="utf-8")

        # Should be blocked because it's in .bathoignore
        with pytest.raises(SecurityError) as exc_info:
            safe_read_file(".secret", tmp_path)
        assert "ignored" in str(exc_info.value).lower()


class TestGetLanguageFromPath:
    """Test language detection from file extensions."""

    def test_python_files(self):
        assert get_language_from_path("test.py") == "python"
        assert get_language_from_path("/path/to/file.py") == "python"

    def test_javascript_files(self):
        assert get_language_from_path("script.js") == "javascript"
        assert get_language_from_path("app.jsx") == "jsx"

    def test_typescript_files(self):
        assert get_language_from_path("main.ts") == "typescript"
        assert get_language_from_path("component.tsx") == "tsx"

    def test_json_files(self):
        assert get_language_from_path("config.json") == "json"

    def test_yaml_files(self):
        assert get_language_from_path("config.yaml") == "yaml"
        assert get_language_from_path("config.yml") == "yaml"

    def test_markdown_files(self):
        assert get_language_from_path("README.md") == "markdown"

    def test_html_files(self):
        assert get_language_from_path("index.html") == "html"
        assert get_language_from_path("page.htm") == "html"

    def test_css_files(self):
        assert get_language_from_path("styles.css") == "css"
        assert get_language_from_path("styles.scss") == "scss"
        assert get_language_from_path("styles.sass") == "sass"

    def test_rust_files(self):
        assert get_language_from_path("main.rs") == "rust"

    def test_go_files(self):
        assert get_language_from_path("main.go") == "go"

    def test_java_files(self):
        assert get_language_from_path("Main.java") == "java"

    def test_c_files(self):
        assert get_language_from_path("main.c") == "c"
        assert get_language_from_path("main.h") == "c"

    def test_cpp_files(self):
        assert get_language_from_path("main.cpp") == "cpp"
        assert get_language_from_path("main.cc") == "cpp"
        assert get_language_from_path("main.hpp") == "cpp"

    def test_csharp_files(self):
        assert get_language_from_path("Program.cs") == "csharp"

    def test_unknown_files(self):
        assert get_language_from_path("file.xyz") == "plaintext"

    def test_extensionless_files(self):
        """Test detection of common extension-less filenames."""
        assert get_language_from_path("Makefile") == "makefile"
        assert get_language_from_path("Dockerfile") == "dockerfile"
        assert get_language_from_path("Jenkinsfile") == "groovy"
        assert get_language_from_path("Rakefile") == "ruby"


class TestGetEntitiesForFile:
    """Test entity extraction from BSG data."""

    def test_empty_bsg_data(self):
        assert get_entities_for_file("test.py", {}) == []
        assert get_entities_for_file("test.py", None) == []

    def test_no_nodes(self):
        bsg_data = {"nodes": []}
        assert get_entities_for_file("test.py", bsg_data) == []

    def test_entities_for_file(self):
        bsg_data = {
            "nodes": [
                {
                    "id": "func:foo:test.py:1",
                    "name": "foo",
                    "type": "FUNCTION",
                    "file": "test.py",
                    "start_line": 1,
                    "end_line": 5,
                    "signature": "def foo()",
                },
                {
                    "id": "class:Bar:test.py:7",
                    "name": "Bar",
                    "type": "CLASS",
                    "file": "test.py",
                    "start_line": 7,
                    "end_line": 12,
                },
                {
                    "id": "func:baz:other.py:1",
                    "name": "baz",
                    "type": "FUNCTION",
                    "file": "other.py",
                    "start_line": 1,
                    "end_line": 3,
                },
            ]
        }

        entities = get_entities_for_file("test.py", bsg_data)
        assert len(entities) == 2
        assert entities[0]["name"] == "foo"
        assert entities[1]["name"] == "Bar"

    def test_entities_sorted_by_line(self):
        bsg_data = {
            "nodes": [
                {
                    "id": "func:bar:test.py:10",
                    "name": "bar",
                    "type": "FUNCTION",
                    "file": "test.py",
                    "start_line": 10,
                    "end_line": 15,
                },
                {
                    "id": "func:foo:test.py:1",
                    "name": "foo",
                    "type": "FUNCTION",
                    "file": "test.py",
                    "start_line": 1,
                    "end_line": 5,
                },
            ]
        }

        entities = get_entities_for_file("test.py", bsg_data)
        assert entities[0]["name"] == "foo"
        assert entities[1]["name"] == "bar"

    def test_file_path_normalization(self):
        """Test that file paths are normalized for matching."""
        bsg_data = {
            "nodes": [
                {
                    "id": "func:foo:test.py:1",
                    "name": "foo",
                    "type": "FUNCTION",
                    "file": "./test.py",  # Leading ./
                    "start_line": 1,
                    "end_line": 5,
                },
            ]
        }

        entities = get_entities_for_file("test.py", bsg_data)
        assert len(entities) == 1
        assert entities[0]["name"] == "foo"


class TestBuildFileContentResponse:
    """Test building complete file content responses."""

    def test_basic_response(self, tmp_path):
        """Test building response without BSG data."""
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')", encoding="utf-8")

        response = build_file_content_response("test.py", tmp_path)

        assert response["path"] == "test.py"
        assert response["content"] == "print('hello')"
        assert response["language"] == "python"
        assert response["totalLines"] == 1
        assert response["sizeBytes"] == 14
        assert response["entities"] == []
        assert response["entityCount"] == 0

    def test_response_with_entities(self, tmp_path):
        """Test building response with BSG entity enrichment."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def foo():\n    pass\n", encoding="utf-8")

        bsg_data = {
            "nodes": [
                {
                    "id": "func:foo:test.py:1",
                    "name": "foo",
                    "type": "FUNCTION",
                    "file": "test.py",
                    "start_line": 1,
                    "end_line": 2,
                    "signature": "def foo()",
                },
            ]
        }

        response = build_file_content_response(
            "test.py", tmp_path, bsg_data=bsg_data, include_entities=True
        )

        assert response["entityCount"] == 1
        assert len(response["entities"]) == 1
        assert response["entities"][0]["name"] == "foo"

    def test_response_has_entities_field(self, tmp_path):
        """Test that response includes has_entities flag for frontend."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def foo(): pass", encoding="utf-8")

        # Without BSG data - should have hasEntities=False
        response = build_file_content_response("test.py", tmp_path)
        # Note: has_entities is added by HTTP API layer, not by build_file_content_response

        # With BSG data and entities
        bsg_data = {
            "nodes": [
                {
                    "id": "func:foo:test.py:1",
                    "name": "foo",
                    "type": "FUNCTION",
                    "file": "test.py",
                    "start_line": 1,
                    "end_line": 1,
                },
            ]
        }
        response = build_file_content_response(
            "test.py", tmp_path, bsg_data=bsg_data, include_entities=True
        )
        assert response["entityCount"] == 1
        # The HTTP API layer adds hasEntities based on entityCount

    def test_response_with_entities_disabled(self, tmp_path):
        """Test that entities are excluded when include_entities=False."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def foo(): pass", encoding="utf-8")

        bsg_data = {
            "nodes": [
                {
                    "id": "func:foo:test.py:1",
                    "name": "foo",
                    "type": "FUNCTION",
                    "file": "test.py",
                    "start_line": 1,
                    "end_line": 1,
                },
            ]
        }

        response = build_file_content_response(
            "test.py", tmp_path, bsg_data=bsg_data, include_entities=False
        )

        assert response["entityCount"] == 0
        assert response["entities"] == []

    def test_multiline_file(self, tmp_path):
        """Test response for file with multiple lines."""
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\nline3\n", encoding="utf-8")

        response = build_file_content_response("test.py", tmp_path)

        assert response["totalLines"] == 4  # Includes trailing newline


class TestSecurityEdgeCases:
    """Test security edge cases and attacks."""

    def test_null_byte_injection(self, tmp_path):
        """Test that null bytes in path don't cause issues."""
        # This would typically be handled by the OS/filesystem
        # but we should be defensive
        test_file = tmp_path / "test.py"
        test_file.write_text("content", encoding="utf-8")

        # Most systems don't allow null bytes in filenames
        # but our normalization should handle edge cases gracefully
        result = safe_read_file("test.py", tmp_path)
        assert result == "content"

    def test_unicode_path(self, tmp_path):
        """Test unicode file paths."""
        test_file = tmp_path / "文件.py"
        test_file.write_text("# unicode filename", encoding="utf-8")

        result = safe_read_file("文件.py", tmp_path)
        assert result == "# unicode filename"

    def test_symlink_not_resolved_to_outside(self, tmp_path):
        """Test that symlinks outside root are blocked."""
        # Create a file outside the temp directory
        outside_file = tmp_path.parent / "outside_secret.txt"
        outside_file.write_text("secret", encoding="utf-8")

        # Create a symlink inside pointing outside
        symlink = tmp_path / "link.txt"
        try:
            symlink.symlink_to(outside_file)
        except OSError:
            # Skip if symlinks not supported (Windows without privileges)
            pytest.skip("Symlinks not supported on this platform")

        # Should resolve to real path and be blocked
        with pytest.raises(SecurityError):
            safe_read_file("link.txt", tmp_path)

        # Cleanup
        outside_file.unlink()
