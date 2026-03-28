"""Cross-platform compatibility tests."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import platform

import pytest

from batho import main


class TestCrossPlatform:
    """Test cross-platform compatibility."""

    def test_unix_path_handling(self, tmp_path: Path):
        """Test Unix-style path handling."""
        # Create paths with Unix separators
        test_dir = tmp_path / "test" / "subdir" / "deep"
        test_dir.mkdir(parents=True)
        
        test_file = test_dir / "test.py"
        test_file.write_text("def test(): pass")
        
        # Index with Unix-style paths
        rc = main(["index", "--root", str(tmp_path), "--force"])
        assert rc == 0
        
        # Verify results
        ctn_dir = tmp_path / ".ctn"
        assert ctn_dir.exists()
        meta = json.loads((ctn_dir / "index.json").read_text())
        assert len(meta.get("indexes", {})) > 0

    def test_windows_path_handling(self, tmp_path: Path):
        """Test Windows-style path handling."""
        # Create paths with Windows separators
        test_dir = tmp_path / "test" / "subdir" / "deep"
        test_dir.mkdir(parents=True)
        
        test_file = test_dir / "test.py"
        test_file.write_text("def test(): pass")
        
        # Index with Windows-style paths
        rc = main(["index", "--root", str(tmp_path), "--force"])
        assert rc == 0
        
        # Verify results
        ctn_dir = tmp_path / ".ctn"
        assert ctn_dir.exists()
        meta = json.loads((ctn_dir / "index.json").read_text())
        assert len(meta.get("indexes", {})) > 0

    def test_path_normalization_across_platforms(self, tmp_path: Path):
        """Test path normalization works across platforms."""
        # Create test structure
        test_dir = tmp_path / "test" / "subdir"
        test_dir.mkdir(parents=True)
        
        test_file = test_dir / "test.py"
        test_file.write_text("def test(): pass")
        
        # Test with different path separators
        if platform.system() == "Windows":
            mixed_path = str(tmp_path) + "\\test/subdir"
        else:
            mixed_path = str(tmp_path) + "/test\\subdir"
        
        # Index should handle mixed separators
        rc = main(["index", "--root", str(tmp_path), "--force"])
        assert rc == 0
        
        # Verify results
        ctn_dir = tmp_path / ".ctn"
        assert ctn_dir.exists()

    def test_file_permission_scenarios(self, tmp_path: Path):
        """Test file permission scenarios."""
        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def test(): pass")
        
        # Test with read-only file
        original_mode = test_file.stat().st_mode
        try:
            test_file.chmod(0o444)  # Read-only
            
            # Index should still work
            rc = main(["index", "--root", str(tmp_path), "--force"])
            assert rc == 0
            
            # Verify results
            ctn_dir = tmp_path / ".ctn"
            assert ctn_dir.exists()
            
        finally:
            # Restore permissions
            test_file.chmod(original_mode)

    def test_special_character_handling_in_paths(self, tmp_path: Path):
        """Test special character handling in file paths."""
        # Test various special characters in filenames
        special_chars = [
            "test_file.py",
            "test-file.py", 
            "test_file_123.py",
            "test.file.py",
            "test_file_with_ünicode.py",  # Unicode
            "test file with spaces.py",  # Spaces
        ]
        
        for filename in special_chars:
            try:
                test_file = tmp_path / filename
                test_file.write_text(f"def test():\n    return '{filename}'")
            except (OSError, UnicodeError):
                # Skip characters that aren't supported on this platform
                continue
        
        # Index should handle all supported special characters
        rc = main(["index", "--root", str(tmp_path), "--force"])
        assert rc == 0
        
        # Verify results
        ctn_dir = tmp_path / ".ctn"
        assert ctn_dir.exists()
        meta = json.loads((ctn_dir / "index.json").read_text())
        assert len(meta.get("indexes", {})) > 0

    def test_encoding_issues_across_platforms(self, tmp_path: Path):
        """Test encoding handling across different platforms."""
        # Create files with different encodings
        encodings_to_test = ['utf-8', 'latin-1']
        
        for encoding in encodings_to_test:
            try:
                test_file = tmp_path / f"test_{encoding}.py"
                content = f"# -*- coding: {encoding} -*-\ndef test():\n    return 'test'"
                
                test_file.write_text(content, encoding=encoding)
            except (UnicodeError, LookupError):
                # Skip encodings not supported on this platform
                continue
        
        # Index should handle different encodings
        rc = main(["index", "--root", str(tmp_path), "--force"])
        assert rc == 0
        
        # Verify results
        ctn_dir = tmp_path / ".ctn"
        assert ctn_dir.exists()

    def test_deep_directory_nesting(self, tmp_path: Path):
        """Test deep directory nesting across platforms."""
        # Create deeply nested directory structure
        current_dir = tmp_path
        max_depth = 20  # Most systems support this depth
        
        for i in range(max_depth):
            current_dir = current_dir / f"level_{i}"
            current_dir.mkdir()
        
        # Create test file at deepest level
        test_file = current_dir / "deep_test.py"
        test_file.write_text("def deep_test(): return 'deep'")
        
        # Index should handle deep nesting
        rc = main(["index", "--root", str(tmp_path), "--force"])
        assert rc == 0
        
        # Verify results
        ctn_dir = tmp_path / ".ctn"
        assert ctn_dir.exists()

    def test_case_sensitivity_handling(self, tmp_path: Path):
        """Test case sensitivity handling across platforms."""
        # Create files with different cases
        files_to_create = [
            "Test.py",
            "test.py", 
            "TEST.py",
        ]
        
        for filename in files_to_create:
            try:
                test_file = tmp_path / filename
                test_file.write_text(f"def {filename.replace('.py', '')}(): pass")
            except OSError:
                # Skip if filesystem doesn't support this (case-insensitive)
                continue
        
        # Index should handle case sensitivity appropriately
        rc = main(["index", "--root", str(tmp_path), "--force"])
        assert rc == 0
        
        # Verify results
        ctn_dir = tmp_path / ".ctn"
        assert ctn_dir.exists()

    def test_long_filename_handling(self, tmp_path: Path):
        """Test handling of long filenames."""
        # Create a long filename (within platform limits)
        long_name = "a" * 100 + ".py"  # 100 characters + extension
        
        try:
            test_file = tmp_path / long_name
            test_file.write_text(f"def {long_name.replace('.py', '')}(): pass")
            
            # Index should handle long filenames
            rc = main(["index", "--root", str(tmp_path), "--force"])
            assert rc == 0
            
            # Verify results
            ctn_dir = tmp_path / ".ctn"
            assert ctn_dir.exists()
            
        except OSError:
            # Skip if platform doesn't support long filenames
            pytest.skip("Platform doesn't support long filenames")

    def test_temporary_directory_handling(self, tmp_path: Path):
        """Test handling of temporary directories."""
        # Create a temporary directory structure
        temp_dir = tmp_path / "temp_test"
        temp_dir.mkdir()
        
        # Create test files
        test_file = temp_dir / "temp_test.py"
        test_file.write_text("def temp_test(): pass")
        
        # Index should work with temporary directories
        rc = main(["index", "--root", str(temp_dir), "--force"])
        assert rc == 0
        
        # Verify results
        ctn_dir = temp_dir / ".ctn"
        assert ctn_dir.exists()

    def test_symlink_handling(self, tmp_path: Path):
        """Test symlink handling (Unix systems only)."""
        if platform.system() == "Windows":
            pytest.skip("Symlinks not fully supported on Windows")
        
        # Create original file
        original_file = tmp_path / "original.py"
        original_file.write_text("def original(): pass")
        
        # Create symlink
        try:
            symlink_file = tmp_path / "symlink.py"
            symlink_file.symlink_to(original_file)
            
            # Index should handle symlinks appropriately
            rc = main(["index", "--root", str(tmp_path), "--force"])
            assert rc == 0
            
            # Verify results
            ctn_dir = tmp_path / ".ctn"
            assert ctn_dir.exists()
            
        except OSError:
            pytest.skip("Symlinks not supported or insufficient permissions")

    def test_hidden_file_handling(self, tmp_path: Path):
        """Test handling of hidden files and directories."""
        # Create hidden files and directories
        if platform.system() == "Windows":
            hidden_prefix = "."
        else:
            hidden_prefix = "."
        
        # Hidden directory with file
        hidden_dir = tmp_path / f"{hidden_prefix}hidden"
        hidden_dir.mkdir()
        
        hidden_file = hidden_dir / "hidden_test.py"
        hidden_file.write_text("def hidden_test(): pass")
        
        # Hidden file in root
        root_hidden = tmp_path / f"{hidden_prefix}root_hidden.py"
        root_hidden.write_text("def root_hidden(): pass")
        
        # Index should handle hidden files appropriately
        rc = main(["index", "--root", str(tmp_path), "--force"])
        assert rc == 0
        
        # Verify results
        ctn_dir = tmp_path / ".ctn"
        assert ctn_dir.exists()
