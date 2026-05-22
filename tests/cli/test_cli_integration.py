"""End-to-end CLI integration tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from batho_cli import main

# ---------------------------------------------------------------------------
# Full workflows via main()
# ---------------------------------------------------------------------------


class TestCLIIntegration:

    def test_index_and_stats(self, simple_python_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Index → Stats workflow."""
        # Copy repo to tmp_path to avoid polluting the permanent test repository
        repo_copy = tmp_path / "simple_python"
        shutil.copytree(simple_python_repo, repo_copy)
        
        # Override ctn_dir to use temporary directory
        monkeypatch.setattr(
            "batho_cli.get_config_cached",
            lambda: {
                "paths": {"ctn_dir": str(repo_copy / ".ctn")},
                "logging": {"level": "INFO", "json_format": None, "quiet": False},
            }
        )
        
        rc = main(["index", "--root", str(repo_copy), "--verbose"])
        assert rc == 0

        rc = main(["stats", "--root", str(repo_copy)])
        assert rc == 0

    def test_index_and_invalidate(self, simple_python_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Index → Invalidate workflow."""
        # Copy repo to tmp_path to avoid polluting the permanent test repository
        repo_copy = tmp_path / "simple_python"
        shutil.copytree(simple_python_repo, repo_copy)
        
        # Override ctn_dir to use temporary directory
        monkeypatch.setattr(
            "batho_cli.get_config_cached",
            lambda: {
                "paths": {"ctn_dir": str(repo_copy / ".ctn")},
                "logging": {"level": "INFO", "json_format": None, "quiet": False},
            }
        )
        
        rc = main(["index", "--root", str(repo_copy)])
        assert rc == 0

        rc = main(["invalidate", "--root", str(repo_copy)])
        assert rc == 0

    def test_index_creates_output_files(self, simple_python_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Verify that index creates the expected output files."""
        # Copy repo to tmp_path to avoid polluting the permanent test repository
        repo_copy = tmp_path / "simple_python"
        shutil.copytree(simple_python_repo, repo_copy)
        
        # Override ctn_dir to use temporary directory
        monkeypatch.setattr(
            "batho_cli.get_config_cached",
            lambda: {
                "paths": {"ctn_dir": str(repo_copy / ".ctn")},
                "logging": {"level": "INFO", "json_format": None, "quiet": False},
            }
        )
        
        main(["index", "--root", str(repo_copy), "--force"])

        ctn_dir = repo_copy / ".ctn"
        assert ctn_dir.exists()

        index_meta = ctn_dir / "index.json"
        assert index_meta.exists()

        meta = json.loads(index_meta.read_text())
        current_id = meta.get("current_index_id")
        assert current_id

        versioned_dir = ctn_dir / current_id
        assert versioned_dir.exists()
        assert (versioned_dir / "graph.json").exists()
        assert (versioned_dir / "bsg.json").exists()

        bsg_payload = json.loads(
            (versioned_dir / "bsg.json").read_text(encoding="utf-8")
        )
        assert isinstance(bsg_payload.get("quality_warnings"), list)
        assert bsg_payload.get("stats", {}).get("quality_warnings") == len(
            bsg_payload.get("quality_warnings", [])
        )

        # Multi-file context outputs
        context_dir = versioned_dir / "context"
        assert context_dir.exists()
        assert (context_dir / "overview.md").exists()
        assert (context_dir / "files.md").exists()

    def test_snapshots_empty(self, tmp_path: Path):
        root = tmp_path / "repo"
        root.mkdir()
        rc = main(["snapshots", "--root", str(root)])
        assert rc == 0
