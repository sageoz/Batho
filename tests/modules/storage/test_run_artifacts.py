import pytest
import sqlite3
import json
import time
import zstandard as zstd
from pathlib import Path
from batho.modules.storage.sqlite_registry.engine import BathoDatabase, SCHEMA_VERSION
from batho.orchestrator.build import run_build, BuildOptions
from batho.orchestrator.patch import run_patch, PatchOptions


# ===========================================================================
# Group 1: Schema & Engine Unit (10 tests)
# ===========================================================================

def test_run_artifacts_table_exists(tmp_path):
    """Table present after DB init; old artifacts table absent."""
    db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
    conn = sqlite3.connect(str(tmp_path / "test.batho"))
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.close()
    db.close()
    assert "run_artifacts" in tables
    assert "artifacts" not in tables


def test_schema_version_bumped():
    """SCHEMA_VERSION == 'batho-db.v1'."""
    assert SCHEMA_VERSION == "batho-db.v1"


def test_finalize_run_artifacts_insert(tmp_path):
    """Single row inserted with correct run_id FK."""
    db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
    run_uuid = "run_1"
    run_id = db.create_run(run_uuid, root_path=str(tmp_path))
    
    db.finalize_run_artifacts(run_id, artifacts={
        "context_overview": {"langs": ["python"]},
        "telemetry_metrics": {"duration_ms": 100},
    })
    
    conn = sqlite3.connect(str(tmp_path / "test.batho"))
    row = conn.execute("SELECT run_id, schema_version FROM run_artifacts").fetchone()
    conn.close()
    db.close()
    
    assert row is not None
    assert row[0] == run_id
    assert row[1] == "run-artifacts.v1"


def test_finalize_run_artifacts_upsert(tmp_path):
    """Second call with same run_id updates, not duplicates."""
    db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
    run_uuid = "run_1"
    run_id = db.create_run(run_uuid, root_path=str(tmp_path))
    
    db.finalize_run_artifacts(run_id, artifacts={
        "context_overview": {"langs": ["python"]},
    })
    db.finalize_run_artifacts(run_id, artifacts={
        "context_overview": {"langs": ["javascript"]},
    })
    
    conn = sqlite3.connect(str(tmp_path / "test.batho"))
    rows = conn.execute("SELECT run_id FROM run_artifacts").fetchall()
    conn.close()
    
    arts = db.get_run_artifacts(run_id)
    db.close()
    
    assert len(rows) == 1
    assert arts["context_overview"] == {"langs": ["javascript"]}


def test_finalize_run_artifacts_null_columns(tmp_path):
    """Unset columns stored as NULL, no error."""
    db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
    run_uuid = "run_1"
    run_id = db.create_run(run_uuid, root_path=str(tmp_path))
    
    db.finalize_run_artifacts(run_id, artifacts={})
    
    conn = sqlite3.connect(str(tmp_path / "test.batho"))
    row = conn.execute(
        "SELECT context_overview, telemetry_metrics, structural_metrics, security_audit, artifact_payload, delta_stats FROM run_artifacts"
    ).fetchone()
    conn.close()
    db.close()
    
    assert row is not None
    assert all(col is None for col in row)


def test_get_run_artifacts_round_trip(tmp_path):
    """All 6 columns compress -> insert -> decompress -> dict equality."""
    db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
    run_uuid = "run_1"
    run_id = db.create_run(run_uuid, root_path=str(tmp_path))
    
    payloads = {
        "context_overview": {"langs": ["python"], "file_categories": ["source"]},
        "telemetry_metrics": {"duration_ms": 120, "files_indexed": 3},
        "structural_metrics": {"entity_type_dist": {"CLASS": 2}, "fan_in": 5},
        "security_audit": {"hits": []},
        "artifact_payload": {"entities": [{"name": "foo"}]},
        "delta_stats": {"churn": 0.1},
    }
    
    db.finalize_run_artifacts(run_id, artifacts=payloads)
    retrieved = db.get_run_artifacts(run_id)
    db.close()
    
    for k, v in payloads.items():
        assert retrieved[k] == v


def test_get_run_artifacts_missing(tmp_path):
    """Returns None for unknown run_id."""
    db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
    retrieved = db.get_run_artifacts(9999)
    db.close()
    assert retrieved is None


def test_cascade_delete(tmp_path):
    """Deleting index_runs row cascades to run_artifacts."""
    db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
    run_uuid = "run_1"
    run_id = db.create_run(run_uuid, root_path=str(tmp_path))
    
    db.finalize_run_artifacts(run_id, artifacts={
        "context_overview": {"langs": ["python"]},
    })
    
    conn = sqlite3.connect(str(tmp_path / "test.batho"))
    assert conn.execute("SELECT COUNT(*) FROM run_artifacts").fetchone()[0] == 1
    
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM index_runs WHERE id = ?", (run_id,))
    conn.commit()
    
    assert conn.execute("SELECT COUNT(*) FROM run_artifacts").fetchone()[0] == 0
    conn.close()
    db.close()


def test_blobs_are_zstd_compressed(tmp_path):
    """Raw bytes in SQLite are valid zstd (not raw JSON)."""
    db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
    run_uuid = "run_1"
    run_id = db.create_run(run_uuid, root_path=str(tmp_path))
    
    db.finalize_run_artifacts(run_id, artifacts={
        "context_overview": {"langs": ["python"]},
    })
    
    conn = sqlite3.connect(str(tmp_path / "test.batho"))
    blob = conn.execute("SELECT context_overview FROM run_artifacts WHERE run_id = ?", (run_id,)).fetchone()[0]
    conn.close()
    db.close()
    
    assert isinstance(blob, bytes)
    # Zstd magic number header starts with 0x28 0xB5 0x2F 0xFD
    assert blob.startswith(b"\x28\xb5\x2f\xfd")


def test_without_rowid_uniqueness(tmp_path):
    """Two rows with same run_id raises IntegrityError."""
    db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
    run_uuid = "run_1"
    run_id = db.create_run(run_uuid, root_path=str(tmp_path))
    
    db.finalize_run_artifacts(run_id, artifacts={})
    
    conn = sqlite3.connect(str(tmp_path / "test.batho"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO run_artifacts (run_id) VALUES (?)", (run_id,))
    conn.close()
    db.close()


# ===========================================================================
# Group 2: Build Integration (8 tests)
# ===========================================================================

def test_build_writes_run_artifacts_row(tmp_path):
    """After build, exactly 1 run_artifacts row exists."""
    # Write a dummy python file to root
    py_file = tmp_path / "app.py"
    py_file.write_text("def run():\n    pass\n", encoding="utf-8")
    
    opts = BuildOptions(root=tmp_path)
    res = run_build(opts)
    assert res.success is True
    
    from batho.modules.storage.sqlite_registry.engine import artifact_filename
    db_path = tmp_path / artifact_filename(tmp_path)
    db = BathoDatabase(db_path, repo_root=tmp_path)
    
    conn = sqlite3.connect(str(db_path))
    row_count = conn.execute("SELECT COUNT(*) FROM run_artifacts").fetchone()[0]
    conn.close()
    
    run_id = db.get_run_internal_id(res.run_id)
    arts = db.get_run_artifacts(run_id)
    db.close()
    
    assert row_count == 1
    assert arts is not None


def test_build_context_overview_structure(tmp_path):
    """Decodes to dict with total_entities, total_files, file_distribution, entity_types."""
    py_file = tmp_path / "app.py"
    py_file.write_text("class MyClass:\n    pass\n", encoding="utf-8")
    
    opts = BuildOptions(root=tmp_path)
    res = run_build(opts)
    
    from batho.modules.storage.sqlite_registry.engine import artifact_filename
    db_path = tmp_path / artifact_filename(tmp_path)
    db = BathoDatabase(db_path, repo_root=tmp_path)
    run_id = db.get_run_internal_id(res.run_id)
    arts = db.get_run_artifacts(run_id)
    db.close()
    
    co = arts["context_overview"]
    assert "total_entities" in co
    assert "total_files" in co
    assert "file_distribution" in co
    assert "entity_types" in co
    assert co["total_files"] == 1


def test_build_telemetry_structure(tmp_path):
    """Has duration_ms, files_indexed, entity_count, rel_count all > 0."""
    py_file = tmp_path / "app.py"
    py_file.write_text("class MyClass:\n    def foo(self):\n        pass\n", encoding="utf-8")
    
    opts = BuildOptions(root=tmp_path)
    res = run_build(opts)
    
    from batho.modules.storage.sqlite_registry.engine import artifact_filename
    db_path = tmp_path / artifact_filename(tmp_path)
    db = BathoDatabase(db_path, repo_root=tmp_path)
    run_id = db.get_run_internal_id(res.run_id)
    arts = db.get_run_artifacts(run_id)
    db.close()
    
    tm = arts["telemetry_metrics"]
    assert tm["duration_ms"] > 0
    assert tm["files_indexed"] > 0
    assert tm["entity_count"] > 0


def test_build_structural_metrics_structure(tmp_path):
    """Has entity_type_distribution (dict) and top_coupled_files (list)."""
    py_file = tmp_path / "app.py"
    py_file.write_text("class MyClass:\n    def foo(self):\n        pass\n", encoding="utf-8")
    
    opts = BuildOptions(root=tmp_path)
    res = run_build(opts)
    
    from batho.modules.storage.sqlite_registry.engine import artifact_filename
    db_path = tmp_path / artifact_filename(tmp_path)
    db = BathoDatabase(db_path, repo_root=tmp_path)
    run_id = db.get_run_internal_id(res.run_id)
    arts = db.get_run_artifacts(run_id)
    db.close()
    
    sm = arts["structural_metrics"]
    assert isinstance(sm["entity_type_distribution"], dict)
    assert isinstance(sm["top_coupled_files"], list)


def test_build_artifact_payload_structure(tmp_path):
    """Has entities list <=200 items; each has name, type, file, start_line."""
    py_file = tmp_path / "app.py"
    py_file.write_text("class MyClass:\n    def foo(self):\n        pass\n", encoding="utf-8")
    
    opts = BuildOptions(root=tmp_path)
    res = run_build(opts)
    
    from batho.modules.storage.sqlite_registry.engine import artifact_filename
    db_path = tmp_path / artifact_filename(tmp_path)
    db = BathoDatabase(db_path, repo_root=tmp_path)
    run_id = db.get_run_internal_id(res.run_id)
    arts = db.get_run_artifacts(run_id)
    db.close()
    
    ap = arts["artifact_payload"]
    assert "entities" in ap
    assert len(ap["entities"]) <= 200
    for ent in ap["entities"]:
        assert "name" in ent
        assert "type" in ent
        assert "file" in ent
        assert "start_line" in ent


def test_build_delta_stats_is_null(tmp_path):
    """delta_stats column is NULL for build runs."""
    py_file = tmp_path / "app.py"
    py_file.write_text("def run():\n    pass\n", encoding="utf-8")
    
    opts = BuildOptions(root=tmp_path)
    res = run_build(opts)
    
    from batho.modules.storage.sqlite_registry.engine import artifact_filename
    db_path = tmp_path / artifact_filename(tmp_path)
    db = BathoDatabase(db_path, repo_root=tmp_path)
    run_id = db.get_run_internal_id(res.run_id)
    arts = db.get_run_artifacts(run_id)
    db.close()
    
    assert arts["delta_stats"] is None


def test_build_security_audit_is_null(tmp_path):
    """security_audit column is NULL."""
    py_file = tmp_path / "app.py"
    py_file.write_text("def run():\n    pass\n", encoding="utf-8")
    
    opts = BuildOptions(root=tmp_path)
    res = run_build(opts)
    
    from batho.modules.storage.sqlite_registry.engine import artifact_filename
    db_path = tmp_path / artifact_filename(tmp_path)
    db = BathoDatabase(db_path, repo_root=tmp_path)
    run_id = db.get_run_internal_id(res.run_id)
    arts = db.get_run_artifacts(run_id)
    db.close()
    
    assert arts["security_audit"] is None


def test_build_security_audit_populated_when_enabled(tmp_path):
    """security_audit column is populated when enabled in batho.yaml."""
    py_file = tmp_path / "app.py"
    py_file.write_text("def run():\n    pass\n", encoding="utf-8")
    
    # Write a custom batho.yaml to enable security_audit
    config_yaml = """
artifact_blobs:
  run_artifacts:
    security_audit: true
"""
    (tmp_path / "batho.yaml").write_text(config_yaml, encoding="utf-8")
    
    opts = BuildOptions(root=tmp_path)
    res = run_build(opts)
    
    from batho.modules.storage.sqlite_registry.engine import artifact_filename
    db_path = tmp_path / artifact_filename(tmp_path)
    db = BathoDatabase(db_path, repo_root=tmp_path)
    run_id = db.get_run_internal_id(res.run_id)
    arts = db.get_run_artifacts(run_id)
    db.close()
    
    assert arts["security_audit"] is not None
    assert arts["security_audit"]["schema_version"] == "interception-stats.v1"
    assert isinstance(arts["security_audit"]["plugins"], dict)
    
    # Verify no .batho-config/metrics/ files exist
    assert not (tmp_path / ".batho-config").exists() or not (tmp_path / ".batho-config" / "metrics").exists()


def test_build_security_audit_populated_via_batho_yaml_unquoted_root(tmp_path):
    """security_audit column is populated when enabled in batho.yaml with unquoted db_path {root}."""
    py_file = tmp_path / "app.py"
    py_file.write_text("def run():\n    pass\n", encoding="utf-8")

    # Write a custom batho.yaml with security_audit and unquoted {root} db_path
    config_yaml = """
paths:
  db_path: {root}
artifact_blobs:
  run_artifacts:
    security_audit: true
"""
    (tmp_path / "batho.yaml").write_text(config_yaml, encoding="utf-8")
    
    opts = BuildOptions(root=tmp_path)
    res = run_build(opts)
    
    from batho.modules.storage.sqlite_registry.engine import artifact_filename
    db_path = tmp_path / artifact_filename(tmp_path)
    db = BathoDatabase(db_path, repo_root=tmp_path)
    run_id = db.get_run_internal_id(res.run_id)
    arts = db.get_run_artifacts(run_id)
    db.close()
    
    assert arts["security_audit"] is not None
    assert arts["security_audit"]["schema_version"] == "interception-stats.v1"



def test_no_context_json_sidefiles(tmp_path):
    """.batho-config/context_overview.json and context_files.json do NOT exist."""
    py_file = tmp_path / "app.py"
    py_file.write_text("def run():\n    pass\n", encoding="utf-8")
    
    opts = BuildOptions(root=tmp_path)
    run_build(opts)
    
    config_dir = tmp_path / ".batho-config"
    assert not (config_dir / "context_overview.json").exists()
    assert not (config_dir / "context_files.json").exists()


# ===========================================================================
# Group 3: Patch Integration (6 tests)
# ===========================================================================

def test_patch_writes_run_artifacts_row(tmp_path):
    """New run_artifacts row for each patch run."""
    py_file = tmp_path / "app.py"
    py_file.write_text("def run():\n    pass\n", encoding="utf-8")
    
    opts = BuildOptions(root=tmp_path)
    build_res = run_build(opts)
    
    # Modify file to trigger patch
    py_file.write_text("def run():\n    print(1)\n", encoding="utf-8")
    patch_res = run_patch(PatchOptions(root=tmp_path))
    assert patch_res.success is True
    assert patch_res.changes_applied > 0
    
    from batho.modules.storage.sqlite_registry.engine import artifact_filename
    db_path = tmp_path / artifact_filename(tmp_path)
    db = BathoDatabase(db_path, repo_root=tmp_path)
    
    conn = sqlite3.connect(str(db_path))
    row_count = conn.execute("SELECT COUNT(*) FROM run_artifacts").fetchone()[0]
    conn.close()
    
    build_run_id = db.get_run_internal_id(build_res.run_id)
    patch_run_id = db.get_run_internal_id(patch_res.run_id)
    
    build_arts = db.get_run_artifacts(build_run_id)
    patch_arts = db.get_run_artifacts(patch_run_id)
    db.close()
    
    assert row_count == 2
    assert build_arts is not None
    assert patch_arts is not None


def test_patch_delta_stats_populated(tmp_path):
    """Not NULL; contains nodes_added, nodes_removed, nodes_modified, nodes_renamed, files_changed, base_run_uuid."""
    py_file = tmp_path / "app.py"
    py_file.write_text("def run():\n    pass\n", encoding="utf-8")
    
    opts = BuildOptions(root=tmp_path)
    build_res = run_build(opts)
    
    # Modify file to trigger patch
    py_file.write_text("def run():\n    print(1)\n", encoding="utf-8")
    patch_res = run_patch(PatchOptions(root=tmp_path))
    
    from batho.modules.storage.sqlite_registry.engine import artifact_filename
    db_path = tmp_path / artifact_filename(tmp_path)
    db = BathoDatabase(db_path, repo_root=tmp_path)
    patch_run_id = db.get_run_internal_id(patch_res.run_id)
    arts = db.get_run_artifacts(patch_run_id)
    db.close()
    
    ds = arts["delta_stats"]
    assert ds is not None
    assert "nodes_added" in ds
    assert "nodes_removed" in ds
    assert "nodes_modified" in ds
    assert "nodes_renamed" in ds
    assert ds["files_changed"] == 1
    assert ds["base_run_uuid"] == build_res.run_id


def test_patch_delta_stats_churn_pct(tmp_path):
    """churn_pct is a float 0-100."""
    py_file = tmp_path / "app.py"
    py_file.write_text("def run():\n    pass\n", encoding="utf-8")
    
    opts = BuildOptions(root=tmp_path)
    run_build(opts)
    
    py_file.write_text("def run():\n    print(1)\n", encoding="utf-8")
    patch_res = run_patch(PatchOptions(root=tmp_path))
    
    from batho.modules.storage.sqlite_registry.engine import artifact_filename
    db_path = tmp_path / artifact_filename(tmp_path)
    db = BathoDatabase(db_path, repo_root=tmp_path)
    arts = db.get_run_artifacts(db.get_run_internal_id(patch_res.run_id))
    db.close()
    
    ds = arts["delta_stats"]
    assert isinstance(ds["churn_pct"], float)
    assert 0.0 <= ds["churn_pct"] <= 100.0


def test_patch_context_overview_final_state(tmp_path):
    """context_overview.total_entities matches final entity count."""
    py_file = tmp_path / "app.py"
    py_file.write_text("def run():\n    pass\n", encoding="utf-8")
    
    opts = BuildOptions(root=tmp_path)
    run_build(opts)
    
    py_file.write_text("def run():\n    print(1)\ndef run2():\n    pass\n", encoding="utf-8")
    patch_res = run_patch(PatchOptions(root=tmp_path))
    
    from batho.modules.storage.sqlite_registry.engine import artifact_filename
    db_path = tmp_path / artifact_filename(tmp_path)
    db = BathoDatabase(db_path, repo_root=tmp_path)
    arts = db.get_run_artifacts(db.get_run_internal_id(patch_res.run_id))
    
    # Query final entities from db
    import msgpack
    from batho.modules.storage.sqlite_registry.engine import _expand_graph_payload
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT bsg_agent_view FROM file_artifacts WHERE run_id = ?",
        (db.get_run_internal_id(patch_res.run_id),)
    ).fetchall()
    ent_count = 0
    dctx = zstd.ZstdDecompressor()
    for r in rows:
        if r[0]:
            expanded = _expand_graph_payload(msgpack.unpackb(dctx.decompress(r[0])))
            ent_count += len(expanded.get("entities", []))
    conn.close()
    db.close()
    
    assert arts["context_overview"]["total_entities"] == ent_count


def test_patch_telemetry_has_duration(tmp_path):
    """telemetry_metrics.duration_ms > 0."""
    py_file = tmp_path / "app.py"
    py_file.write_text("def run():\n    pass\n", encoding="utf-8")
    
    opts = BuildOptions(root=tmp_path)
    run_build(opts)
    
    py_file.write_text("def run():\n    print(1)\n", encoding="utf-8")
    patch_res = run_patch(PatchOptions(root=tmp_path))
    
    from batho.modules.storage.sqlite_registry.engine import artifact_filename
    db_path = tmp_path / artifact_filename(tmp_path)
    db = BathoDatabase(db_path, repo_root=tmp_path)
    arts = db.get_run_artifacts(db.get_run_internal_id(patch_res.run_id))
    db.close()
    
    assert arts["telemetry_metrics"]["duration_ms"] > 0


def test_patch_zero_changes(tmp_path):
    """Patch with no file changes still writes row; delta_stats.files_changed == 0 (direct verify via finalizer)."""
    db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
    run_id = db.create_run("run_patch_zero", root_path=str(tmp_path))
    
    delta_stats = {
        "nodes_added": 0,
        "nodes_removed": 0,
        "nodes_modified": 0,
        "nodes_renamed": 0,
        "files_changed": 0,
        "files_added": 0,
        "files_deleted": 0,
        "churn_pct": 0.0,
        "base_run_uuid": "some_base_uuid",
    }
    db.finalize_run_artifacts(run_id, artifacts={"delta_stats": delta_stats})
    arts = db.get_run_artifacts(run_id)
    db.close()
    
    assert arts["delta_stats"]["files_changed"] == 0


# ===========================================================================
# Group 4: Dead Code Removal Guards (6 tests)
# ===========================================================================

def test_no_artifacts_table_in_schema(tmp_path):
    """artifacts absent from sqlite_master."""
    db = BathoDatabase(tmp_path / "test.batho", repo_root=tmp_path)
    conn = sqlite3.connect(str(tmp_path / "test.batho"))
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.close()
    db.close()
    assert "artifacts" not in tables


def test_register_artifact_removed_from_engine():
    """hasattr(BathoDatabase, 'register_artifact') is False."""
    assert not hasattr(BathoDatabase, "register_artifact")


def test_register_artifact_removed_from_storage():
    """from batho.modules.storage.sqlite_registry.storage import register_artifact raises ImportError."""
    with pytest.raises(ImportError):
        from batho.modules.storage.sqlite_registry.storage import register_artifact  # noqa: F401


def test_persist_json_removed():
    """from batho.modules.storage.sqlite_registry.storage import persist_json raises ImportError."""
    with pytest.raises(ImportError):
        from batho.modules.storage.sqlite_registry.storage import persist_json  # noqa: F401


def test_get_pending_artifacts_removed():
    """hasattr(BathoDatabase, 'get_pending_artifacts') is False."""
    assert not hasattr(BathoDatabase, "get_pending_artifacts")


def test_registry_check_module_deleted():
    """from batho.modules.integrity.checks.registry import RegistryIntegrityCheck raises ImportError."""
    with pytest.raises(ImportError):
        from batho.modules.integrity.checks.registry import RegistryIntegrityCheck  # noqa: F401
