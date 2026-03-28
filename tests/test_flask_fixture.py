"""Test Flask repository fixture and metadata."""
import pytest
import json
from pathlib import Path


def test_flask_repo_exists(flask_repo: Path):
    """Test that Flask repository fixture exists and is accessible."""
    assert flask_repo.exists()
    assert flask_repo.is_dir()
    
    # Check for key Flask files (Flask uses src layout)
    assert (flask_repo / "src" / "flask" / "__init__.py").exists()
    assert (flask_repo / "pyproject.toml").exists()


def test_flask_repo_metadata(flask_repo_metadata):
    """Test that Flask repository metadata is loaded correctly."""
    if flask_repo_metadata is None:
        pytest.skip("Flask metadata not available")
    
    assert flask_repo_metadata["name"] == "Flask"
    assert flask_repo_metadata["version"] == "2.3.3"
    assert flask_repo_metadata["total_files"] > 0
    assert "python" in flask_repo_metadata["languages"]
    assert len(flask_repo_metadata["python_modules"]) > 0


def test_flask_repo_structure(flask_repo: Path):
    """Test Flask repository structure is intact."""
    # Main flask module should exist (src layout)
    flask_module = flask_repo / "src" / "flask"
    assert flask_module.exists()
    assert flask_module.is_dir()
    
    # Check for core Flask files
    core_files = ["__init__.py", "app.py", "config.py"]
    for file_name in core_files:
        file_path = flask_module / file_name
        if file_path.exists():
            assert file_path.is_file()
    
    # Should have no .git directory (cleaned for testing)
    assert not (flask_repo / ".git").exists()


def test_flask_repo_metadata_file(flask_repo: Path):
    """Test that Flask repository metadata file exists and is valid JSON."""
    metadata_file = flask_repo / "repository_metadata.json"
    assert metadata_file.exists()
    
    # Should be valid JSON
    content = metadata_file.read_text(encoding="utf-8")
    data = json.loads(content)
    
    # Required fields should be present
    required_fields = ["name", "version", "total_files", "languages"]
    for field in required_fields:
        assert field in data
