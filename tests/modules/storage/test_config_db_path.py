import tempfile
from pathlib import Path
import pytest

from batho.core.config import set_active_root, reload_config
from batho.modules.storage.sqlite_registry.engine import (
    resolve_db_path,
    get_database,
    artifact_filename,
    _DB_CACHE,
    _DB_CACHE_LOCK,
)

def close_all_databases():
    with _DB_CACHE_LOCK:
        for db in list(_DB_CACHE.values()):
            db.close()
        _DB_CACHE.clear()


@pytest.fixture(autouse=True)
def clean_caches():
    close_all_databases()
    from batho.core.config import _active_root, _get_config_cached_for_root
    _active_root.set(None)
    _get_config_cached_for_root.cache_clear()
    yield
    close_all_databases()
    _active_root.set(None)
    _get_config_cached_for_root.cache_clear()


@pytest.fixture
def temp_project():
    """Create a temporary directory structure for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        yield root


def test_resolve_db_path_default(temp_project):
    """Verify resolve_db_path uses default behavior when config is missing or set to default."""
    # Active root is set, but no batho.yaml exists (so defaults apply)
    set_active_root(temp_project)
    
    resolved = resolve_db_path(temp_project)
    expected = temp_project / artifact_filename(temp_project)
    assert resolved == expected


def test_resolve_db_path_root_placeholder(temp_project):
    """Verify resolve_db_path uses default behavior when config db_path is explicitly {root}."""
    (temp_project / "batho.yaml").write_text("paths:\n  db_path: '{root}'\n")
    set_active_root(temp_project)
    reload_config()
    
    resolved = resolve_db_path(temp_project)
    expected = temp_project / artifact_filename(temp_project)
    assert resolved == expected


def test_resolve_db_path_dot_batho(temp_project):
    """Verify resolve_db_path resolves relative to root when config db_path is '.batho'."""
    (temp_project / "batho.yaml").write_text("paths:\n  db_path: .batho\n")
    set_active_root(temp_project)
    reload_config()
    
    resolved = resolve_db_path(temp_project)
    expected = (temp_project / ".batho" / artifact_filename(temp_project)).resolve()
    assert resolved == expected


def test_resolve_db_path_existing_directory(temp_project):
    """Verify resolve_db_path resolves with filename when path is an existing directory."""
    # Pre-create directory with a suffix to prove directory detection works
    dir_path = temp_project / "custom.dir"
    dir_path.mkdir(parents=True, exist_ok=True)
    
    (temp_project / "batho.yaml").write_text("paths:\n  db_path: custom.dir\n")
    set_active_root(temp_project)
    reload_config()
    
    resolved = resolve_db_path(temp_project)
    expected = (dir_path / artifact_filename(temp_project)).resolve()
    assert resolved == expected


def test_resolve_db_path_custom_relative(temp_project):
    """Verify resolve_db_path resolves relative to root when config db_path is a custom path."""
    (temp_project / "batho.yaml").write_text("paths:\n  db_path: data/batho.db\n")
    set_active_root(temp_project)
    reload_config()
    
    resolved = resolve_db_path(temp_project)
    expected = (temp_project / "data/batho.db").resolve()
    assert resolved == expected


def test_get_database_uses_resolved_path(temp_project):
    """Verify get_database creates and loads database at the config-resolved path."""
    (temp_project / "batho.yaml").write_text("paths:\n  db_path: custom_dir/batho.db\n")
    set_active_root(temp_project)
    reload_config()
    
    db = get_database(temp_project)
    expected_path = (temp_project / "custom_dir/batho.db").resolve()
    assert db.path == expected_path
    assert expected_path.exists()


def test_get_database_path_conflict(temp_project):
    """Verify get_database raises a RuntimeError if the parent of the resolved DB path is a file."""
    conflict_file = temp_project / "conflict_file"
    conflict_file.touch() # Create it as a file
    
    (temp_project / "batho.yaml").write_text("paths:\n  db_path: conflict_file\n")
    set_active_root(temp_project)
    reload_config()
    
    with pytest.raises(RuntimeError) as exc_info:
        get_database(temp_project)
        
    assert "Database path conflict" in str(exc_info.value)


def test_config_yaml_preferred_over_batho_yaml(temp_project):
    """Verify config.yaml is loaded and takes precedence over batho.yaml."""
    (temp_project / "batho.yaml").write_text("paths:\n  db_path: batho_dir\n")
    (temp_project / "config.yaml").write_text("paths:\n  db_path: config_dir\n")
    set_active_root(temp_project)
    reload_config()
    
    resolved = resolve_db_path(temp_project)
    expected = (temp_project / "config_dir" / artifact_filename(temp_project)).resolve()
    assert resolved == expected


def test_resolve_db_path_unquoted_root(temp_project):
    """Verify unquoted {root} is resolved correctly and doesn't cause validation failure."""
    # Write config.yaml with unquoted {root}
    (temp_project / "config.yaml").write_text("paths:\n  db_path: {root}\n")
    set_active_root(temp_project)
    reload_config()
    
    resolved = resolve_db_path(temp_project)
    expected = temp_project / artifact_filename(temp_project)
    assert resolved == expected



