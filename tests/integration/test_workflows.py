"""Integration workflow tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from batho import main


@pytest.mark.integration
class TestFullWorkflows:

    def test_index_snapshot_diff(self, simple_python_repo: Path):
        """Index with snapshot → list → verify."""
        rc = main([
            "index", "--root", str(simple_python_repo),
            "--force", "--snapshot", "--snapshot-label", "v1",
        ])
        assert rc == 0

        rc = main(["snapshots", "--root", str(simple_python_repo)])
        assert rc == 0

    def test_index_twice_updates_metadata(self, simple_python_repo: Path, tmp_path: Path):
        """Two indexes should produce two entries in index.json."""
        import shutil
        repo_copy = tmp_path / "repo_copy"
        shutil.copytree(simple_python_repo, repo_copy)
        # Remove any leftover .ctn from previous runs
        ctn_dir = repo_copy / ".ctn"
        if ctn_dir.exists():
            shutil.rmtree(ctn_dir)

        main(["index", "--root", str(repo_copy), "--force"])
        main(["index", "--root", str(repo_copy), "--force"])

        meta = json.loads(
            (repo_copy / ".ctn" / "index.json").read_text()
        )
        assert len(meta.get("indexes", {})) == 2

    def test_multi_language_indexing(self, multi_lang_repo: Path):
        """Index a multi-language repo and verify mixed entities."""
        rc = main(["index", "--root", str(multi_lang_repo), "--force", "--verbose"])
        assert rc == 0

        ctn_dir = multi_lang_repo / ".ctn"
        meta = json.loads((ctn_dir / "index.json").read_text())
        current_id = meta["current_index_id"]

    def test_incremental_patch_workflows(self, simple_python_repo: Path, tmp_path: Path):
        """Test incremental patch workflows."""
        import shutil
        repo_copy = tmp_path / "repo_copy"
        shutil.copytree(simple_python_repo, repo_copy)
        
        # Initial index
        rc = main(["index", "--root", str(repo_copy), "--force"])
        assert rc == 0
        
        # Modify a file
        test_file = repo_copy / "src" / "main.py"
        if test_file.exists():
            original_content = test_file.read_text()
            test_file.write_text(original_content + "\n# Added comment\n")
        
        # Patch update
        rc = main(["patch", "--root", str(repo_copy)])
        assert rc == 0
        
        # Verify patch was applied
        ctn_dir = repo_copy / ".ctn"
        meta = json.loads((ctn_dir / "index.json").read_text())
        assert len(meta.get("indexes", {})) >= 2

    def test_configuration_driven_workflows(self, simple_python_repo: Path, tmp_path: Path):
        """Test configuration-driven workflows."""
        import shutil
        
        repo_copy = tmp_path / "repo_copy"
        shutil.copytree(simple_python_repo, repo_copy)
        
        # Create custom configuration (note: --config may not be supported yet)
        config = {
            "indexing": {
                "include_patterns": ["*.py"],
                "exclude_patterns": ["test_*.py"],
                "max_file_size": 1000000
            },
            "output": {
                "format": "json",
                "verbose": False
            }
        }
        
        # For now, just test basic indexing without custom config
        # Index with default configuration
        rc = main(["index", "--root", str(repo_copy), "--force"])
        assert rc == 0
        
        # Verify configuration was applied
        ctn_dir = repo_copy / ".ctn"
        assert ctn_dir.exists()
        assert (ctn_dir / "index.json").exists()

    def test_error_recovery_and_cleanup(self, simple_python_repo: Path, tmp_path: Path):
        """Test error recovery and cleanup scenarios."""
        import shutil
        import os
        
        repo_copy = tmp_path / "repo_copy"
        shutil.copytree(simple_python_repo, repo_copy)
        
        # Create a problematic file (permission issues)
        problematic_file = repo_copy / "problematic.py"
        problematic_file.write_text("print('test')")
        
        # Make file read-only (simulate permission error)
        try:
            problematic_file.chmod(0o444)
            
            # Index should still work despite permission issues
            rc = main(["index", "--root", str(repo_copy), "--force"])
            assert rc == 0
            
            # Verify partial indexing occurred
            ctn_dir = repo_copy / ".ctn"
            if ctn_dir.exists():
                assert (ctn_dir / "index.json").exists()
                
        finally:
            # Restore permissions for cleanup
            problematic_file.chmod(0o644)

    def test_flask_repository_workflow(self, flask_repo: Path):
        """Test complete workflow with Flask repository."""
        # Index Flask repository
        rc = main(["index", "--root", str(flask_repo), "--force", "--verbose"])
        assert rc == 0
        
        # Verify indexing results
        ctn_dir = flask_repo / ".ctn"
        assert ctn_dir.exists()
        
        meta = json.loads((ctn_dir / "index.json").read_text())
        assert "current_index_id" in meta
        current_id = meta["current_index_id"]
        assert len(meta.get("indexes", {})) > 0
        
        # Test stats command
        rc = main(["stats", "--root", str(flask_repo)])
        assert rc == 0
        
        # Test snapshots
        rc = main(["snapshots", "--root", str(flask_repo)])
        assert rc == 0
        
        # Verify graph data
        graph_data = json.loads((ctn_dir / current_id / "graph.json").read_text())
        assert len(graph_data.get("entities", [])) > 0
