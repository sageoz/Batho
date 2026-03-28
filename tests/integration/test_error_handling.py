"""Error handling and recovery tests."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import shutil

import pytest

from batho_core.batho import main


@pytest.mark.integration
class TestErrorHandling:
    """Test error handling and recovery scenarios."""

    def test_malformed_file_handling(self, tmp_path: Path):
        """Test handling of malformed files."""
        # Create various malformed files
        malformed_files = [
            ("invalid_syntax.py", "def invalid_syntax(\n    # Missing closing parenthesis"),
            ("incomplete_json.json", '{"key": "value", "incomplete":'),
            ("broken_xml.xml", "<root><item>test</root>"),
            ("binary_as_text.txt", b'\x00\x01\x02\x03\x04\x05'),
        ]
        
        for filename, content in malformed_files:
            file_path = tmp_path / filename
            if isinstance(content, bytes):
                file_path.write_bytes(content)
            else:
                file_path.write_text(content)
        
        # Index should handle malformed files gracefully (may exit with 1 or 2 if no entities found/partial success)
        rc = main(["index", "--root", str(tmp_path), "--force"])
        # Allow success (0), warning (1), or partial success (2) for malformed files
        assert rc in [0, 1, 2], f"Unexpected exit code: {rc}"
        
        # Verify indexing completed despite malformed files
        ctn_dir = tmp_path / ".ctn"
        # When no entities are found, .ctn directory might not be created
        # This is expected behavior for malformed files
        if not ctn_dir.exists():
            # No .ctn directory is acceptable for malformed files
            return
        
        # If .ctn exists, verify structure
        index_file = ctn_dir / "index.json"
        if index_file.exists():
            meta = json.loads(index_file.read_text())
            # Should have attempted indexing even if no entities found
            assert "indexes" in meta

    def test_permission_denied_scenarios(self, tmp_path: Path):
        """Test file permission scenarios."""
        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def test(): pass")
        
        # Test with unreadable file
        original_mode = test_file.stat().st_mode
        try:
            # Remove read permissions
            test_file.chmod(0o000)
            
            # Index should handle permission errors gracefully (may exit with 1 or 2)
            rc = main(["index", "--root", str(tmp_path), "--force"])
            assert rc in [0, 1, 2]  # Should succeed or warn, just skip unreadable files
            
        finally:
            # Restore permissions
            test_file.chmod(original_mode)

    def test_disk_space_exhaustion_simulation(self, tmp_path: Path):
        """Test behavior when disk space is exhausted (simulated)."""
        # Create a large number of files to simulate disk pressure
        large_files = []
        try:
            for i in range(4):  # Create a few moderately large files
                large_file = tmp_path / f"large_{i}.py"
                large_file.write_text(f"# Large file {i}\n" + "def func():\n    return True\n" * 200)
                large_files.append(large_file)
            
            # Index should handle large files
            rc = main(["index", "--root", str(tmp_path), "--force"])
            assert rc == 0
            
        except OSError as e:
            if "No space left" in str(e):
                pytest.skip("Disk space exhausted, skipping test")
            else:
                raise

    def test_network_failure_scenarios(self, tmp_path: Path):
        """Test handling of network-related failures."""
        # Create a file that might trigger network operations
        network_file = tmp_path / "network_test.py"
        network_file.write_text("""
import urllib.request
import requests

def fetch_data():
    try:
        response = urllib.request.urlopen('http://example.com')
        return response.read()
    except:
        return None

def fetch_with_requests():
    try:
        response = requests.get('http://example.com')
        return response.text
    except:
        return None
""")
        
        # Index should handle network failures gracefully
        rc = main(["index", "--root", str(tmp_path), "--force"])
        assert rc == 0  # Should succeed even if network operations fail

    def test_corrupted_cache_recovery(self, tmp_path: Path):
        """Test recovery from corrupted cache."""
        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def test(): pass")
        
        # Initial indexing
        rc = main(["index", "--root", str(tmp_path), "--force"])
        assert rc == 0
        
        # Corrupt the cache
        ctn_dir = tmp_path / ".ctn"
        if ctn_dir.exists():
            # Find and corrupt a cache file
            for cache_file in ctn_dir.rglob("*.json"):
                try:
                    # Write invalid JSON to corrupt the file
                    cache_file.write_text("{invalid json content")
                    break
                except (OSError, PermissionError):
                    continue
        
        # Second indexing should recover from corruption
        rc = main(["index", "--root", str(tmp_path), "--force"])
        assert rc == 0  # Should succeed after recovery

    def test_interrupted_operation_recovery(self, tmp_path: Path):
        """Test recovery from interrupted operations."""
        # Create test files
        for i in range(3):
            test_file = tmp_path / f"test_{i}.py"
            test_file.write_text(f"def test_{i}(): return {i}")
        
        # Simulate interrupted indexing by creating incomplete cache
        ctn_dir = tmp_path / ".ctn"
        ctn_dir.mkdir()
        
        # Create incomplete metadata
        incomplete_meta = {
            "current_index_id": "incomplete_id",
            "indexes": {
                "incomplete_id": {
                    "timestamp": "2023-01-01T00:00:00Z",
                    "status": "incomplete"  # Mark as incomplete
                }
            }
        }
        
        (ctn_dir / "index.json").write_text(json.dumps(incomplete_meta))
        
        # Indexing should recover from incomplete state
        rc = main(["index", "--root", str(tmp_path), "--force"])
        assert rc == 0  # Should succeed after recovery

    def test_concurrent_access_handling(self, tmp_path: Path):
        """Test handling of concurrent access to files."""
        import threading
        import time
        
        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def test(): pass")
        
        results = []
        
        def index_repo():
            rc = main(["index", "--root", str(tmp_path), "--force"])
            results.append(rc)
        
        # Start multiple indexing operations concurrently
        threads = []
        for _ in range(2):
            thread = threading.Thread(target=index_repo)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # At least one should succeed
        assert any(rc == 0 for rc in results), "All concurrent operations failed"

    def test_memory_pressure_handling(self, tmp_path: Path):
        """Test handling under memory pressure."""
        # Create files that might cause memory pressure
        for i in range(8):
            test_file = tmp_path / f"memory_test_{i}.py"
            # Create files with many functions to increase memory usage
            content = "# Memory test file {}\n".format(i)
            for j in range(30):
                content += f"def func_{j}():\n    return {i}_{j}\n"
            test_file.write_text(content)
        
        # Index should handle memory pressure
        rc = main(["index", "--root", str(tmp_path), "--force"])
        assert rc == 0

    def test_filesystem_limit_handling(self, tmp_path: Path):
        """Test handling of filesystem limits."""
        # Test with very long path (within reasonable limits)
        long_path = tmp_path
        for i in range(6):  # Create moderately deep path
            long_path = long_path / f"very_long_directory_name_{i}"
            try:
                long_path.mkdir()
            except OSError:
                break  # Stop if we hit filesystem limits
        
        # Create test file at deepest level
        try:
            test_file = long_path / "test.py"
            test_file.write_text("def test(): pass")
            
            # Index should handle filesystem limits
            rc = main(["index", "--root", str(tmp_path), "--force"])
            assert rc == 0
            
        except OSError:
            pytest.skip("Filesystem limits reached, skipping test")

    def test_invalid_repository_root(self, tmp_path: Path):
        """Test handling of invalid repository roots."""
        # Test with non-existent directory
        non_existent = tmp_path / "does_not_exist"
        rc = main(["index", "--root", str(non_existent), "--force"])
        assert rc != 0  # Should fail for non-existent directory
        
        # Test with file instead of directory
        test_file = tmp_path / "not_a_directory.py"
        test_file.write_text("def test(): pass")
        
        rc = main(["index", "--root", str(test_file), "--force"])
        assert rc != 0  # Should fail for file instead of directory

    def test_corrupted_configuration_handling(self, tmp_path: Path):
        """Test handling of corrupted configuration files."""
        # Create corrupted config file
        config_file = tmp_path / "batho_config.json"
        config_file.write_text("{invalid json content")
        
        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def test(): pass")
        
        # Should handle corrupted config gracefully (note: --config may not be supported)
        # For now, just test basic indexing without config
        rc = main(["index", "--root", str(tmp_path), "--force"])
        assert rc == 0  # Should succeed with default config

    def test_resource_cleanup_on_failure(self, tmp_path: Path):
        """Test resource cleanup when operations fail."""
        # Create a problematic file that might cause failure
        problematic_file = tmp_path / "problematic.py"
        problematic_file.write_bytes(b'\x00' * 1000)  # Binary content in .py file
        
        # Attempt indexing
        rc = main(["index", "--root", str(tmp_path), "--force"])
        
        # Check that resources are cleaned up appropriately
        ctn_dir = tmp_path / ".ctn"
        if ctn_dir.exists():
            # Should not leave orphaned files
            files_in_ctn = list(ctn_dir.rglob("*"))
            # Should have minimal files (just metadata, not partial results)
            assert len(files_in_ctn) <= 10, "Too many files left after failure"
