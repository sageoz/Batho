from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from batho.context.storage import (
    _safe_parse_iso,
    backfill_registry,
    cleanup_registry,
    describe_artifact,
    get_artifact_registry,
    get_registry_stats,
    infer_ctn_dir_for_path,
    persist_bytes,
    persist_json,
    persist_text,
    query_entities,
    query_relationships,
    rebuild_query_index,
    register_artifact,
    register_artifact_for_path,
    verify_registry,
)


def _rows(db_path: Path, query: str) -> int:
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute(query)
        row = cur.fetchone()
        return int(row[0]) if row else 0


def _values(db_path: Path, query: str) -> list[tuple]:
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute(query)
        return list(cur.fetchall())


def test_register_artifact_creates_registry_and_entry(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()

    artifact = ctn_dir / "sample.json"
    artifact.write_text('{"ok": true}', encoding="utf-8")

    ok = register_artifact(
        ctn_dir,
        artifact,
        "graph_json",
        producer="test",
        schema_version="graph.v1",
    )

    assert ok is True

    registry_db = ctn_dir / "artifact_registry.db"
    assert registry_db.exists()

    assert _rows(registry_db, "SELECT COUNT(*) FROM artifacts") == 1
    assert _rows(registry_db, "SELECT COUNT(*) FROM content_blobs") == 1


def test_register_artifact_ignores_lock_and_tmp_files(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()

    lock_file = ctn_dir / "ctn.lock"
    lock_file.write_text("123", encoding="utf-8")

    tmp_file = ctn_dir / "graph.json.tmp"
    tmp_file.write_text("{}", encoding="utf-8")

    lock_ok = register_artifact(ctn_dir, lock_file, "lock")
    tmp_ok = register_artifact(ctn_dir, tmp_file, "tmp")

    assert lock_ok is False
    assert tmp_ok is False

    registry_db = ctn_dir / "artifact_registry.db"
    if registry_db.exists():
        assert _rows(registry_db, "SELECT COUNT(*) FROM artifacts") == 0


def test_register_artifact_for_path_infers_ctn_dir(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    snap_dir = ctn_dir / "snapshots"
    snap_dir.mkdir(parents=True)

    artifact = snap_dir / "batho_test_snapshot.json"
    artifact.write_text('{"snapshot_id": "s1"}', encoding="utf-8")

    ok = register_artifact_for_path(
        artifact,
        "snapshot_json",
        producer="test",
        schema_version="snapshot.v1",
    )

    assert ok is True

    registry_db = ctn_dir / "artifact_registry.db"
    assert _rows(registry_db, "SELECT COUNT(*) FROM artifacts") == 1


def test_register_artifact_rejects_paths_outside_ctn_dir(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()

    outside_file = tmp_path / "outside.json"
    outside_file.write_text("{}", encoding="utf-8")

    ok = register_artifact(
        ctn_dir,
        outside_file,
        "metrics_json",
        producer="test",
        schema_version="metrics.v1",
    )

    assert ok is False


def test_register_same_artifact_is_idempotent(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()

    artifact = ctn_dir / "bsg.json"
    artifact.write_text('{"nodes": []}', encoding="utf-8")

    first = register_artifact(
        ctn_dir,
        artifact,
        "bsg_json",
        producer="test",
        schema_version="bsg.v1",
    )
    second = register_artifact(
        ctn_dir,
        artifact,
        "bsg_json",
        producer="test",
        schema_version="bsg.v1",
    )

    assert first is True
    assert second is True

    registry_db = ctn_dir / "artifact_registry.db"
    assert _rows(registry_db, "SELECT COUNT(*) FROM artifacts") == 1
    assert _rows(registry_db, "SELECT COUNT(*) FROM content_blobs") == 1


def test_backfill_registry_registers_existing_durable_files(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    version_dir = ctn_dir / "batho_test"
    version_dir.mkdir(parents=True)

    (ctn_dir / "index.json").write_text('{"current_index_id":"batho_test"}', encoding="utf-8")
    (version_dir / "graph.json").write_text('{"entities":[]}', encoding="utf-8")
    (version_dir / "bsg.json").write_text('{"nodes":[]}', encoding="utf-8")
    (ctn_dir / "ctn.lock").write_text("lock", encoding="utf-8")

    result = backfill_registry(ctn_dir)

    assert result["enabled"] is True
    assert result["scanned"] >= 3
    assert result["registered"] >= 3

    registry_db = ctn_dir / "artifact_registry.db"
    logical_paths = {
        row[0]
        for row in _values(registry_db, "SELECT logical_path FROM artifacts WHERE deleted = 0")
    }
    # Normalize paths for cross-platform comparison
    logical_paths_normalized = {Path(p).as_posix() for p in logical_paths}
    assert ".ctn/index.json" not in logical_paths_normalized
    assert "index.json" in logical_paths_normalized
    assert "batho_test/graph.json" in logical_paths_normalized
    assert "ctn.lock" not in logical_paths_normalized


def test_verify_registry_reports_and_repairs_drift(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()

    existing = ctn_dir / "graph.json"
    existing.write_text('{"entities":[]}', encoding="utf-8")
    assert register_artifact(ctn_dir, existing, "graph_json") is True

    missing = ctn_dir / "missing.json"
    missing.write_text('{"x":1}', encoding="utf-8")
    assert register_artifact(ctn_dir, missing, "metrics_json") is True
    missing.unlink()

    unregistered = ctn_dir / "unregistered.json"
    unregistered.write_text('{"u":1}', encoding="utf-8")

    check = verify_registry(ctn_dir, repair=False)
    assert check["missing_on_disk"] >= 1
    assert check["unregistered_on_disk"] >= 1

    repaired = verify_registry(ctn_dir, repair=True)
    assert repaired["repaired_registered"] >= 1
    assert repaired["repaired_deleted"] >= 1


def test_cleanup_registry_dry_run_then_apply(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    snap_dir = ctn_dir / "snapshots"
    snap_dir.mkdir(parents=True)

    old_snapshot = snap_dir / "batho_old.json"
    old_snapshot.write_text('{"snapshot_id":"old"}', encoding="utf-8")
    assert (
        register_artifact(
            ctn_dir,
            old_snapshot,
            "snapshot_json",
            retention_class="snapshot",
        )
        is True
    )

    registry_db = ctn_dir / "artifact_registry.db"
    old_time = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    with sqlite3.connect(str(registry_db)) as conn:
        conn.execute("UPDATE artifacts SET updated_at = ?", (old_time,))
        conn.commit()

    dry_run = cleanup_registry(ctn_dir, dry_run=True)
    assert dry_run["dry_run"] is True
    assert dry_run["candidates"] >= 1
    assert old_snapshot.exists()

    applied = cleanup_registry(ctn_dir, dry_run=False)
    assert applied["dry_run"] is False
    assert applied["deleted_metadata"] >= 1
    assert not old_snapshot.exists()


def test_rebuild_and_query_persisted_query_indexes(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()

    graph_payload = {
        "entities_by_id": {
            "e1": {
                "id": "e1",
                "type": "FUNCTION",
                "name": "alpha",
                "file": "src/a.py",
                "signature": "alpha()",
                "metadata": {"language": "python"},
            },
            "e2": {
                "id": "e2",
                "type": "CLASS",
                "name": "Beta",
                "file": "src/b.py",
                "metadata": {"language": "python"},
            },
        },
        "relationships": [
            {
                "id": "r1",
                "type": "CALLS",
                "source_id": "e1",
                "target_id": "e2",
                "metadata": {},
            }
        ],
    }

    stats = rebuild_query_index(ctn_dir, "idx1", graph_payload)
    assert stats["entities_indexed"] == 2
    assert stats["relationships_indexed"] == 1

    functions = query_entities(ctn_dir, index_id="idx1", entity_type="function", limit=10)
    assert len(functions) == 1
    assert functions[0]["name"] == "alpha"

    by_file = query_entities(ctn_dir, index_id="idx1", file_path="src/b.py", limit=10)
    assert len(by_file) == 1
    assert by_file[0]["entity_id"] == "e2"

    calls = query_relationships(
        ctn_dir,
        index_id="idx1",
        relationship_type="calls",
        limit=10,
    )
    assert len(calls) == 1
    assert calls[0]["source_id"] == "e1"


def test_describe_artifact_and_infer_helpers(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    idx_dir = ctn_dir / "idx1"
    ctx_dir = idx_dir / "context"
    patches_dir = ctn_dir / "patches"
    snaps_dir = ctn_dir / "snapshots"
    for path in [idx_dir, ctx_dir, patches_dir, snaps_dir]:
        path.mkdir(parents=True, exist_ok=True)

    paths = [
        ctn_dir / "index.json",
        ctn_dir / "file_cache.json",
        ctn_dir / "file_hashes.json",
        ctn_dir / "evolution_ledger.json",
        ctn_dir / "patch_audit.log",
        ctn_dir / "rules_cache.pkl",
        ctn_dir / "interception_stats.json",
        snaps_dir / "snap.json",
        patches_dir / "index.json",
        patches_dir / "patch_001.json",
        idx_dir / "graph.json",
        idx_dir / "bsg.json",
        ctx_dir / "overview.md",
        ctx_dir / "architecture.md",
        ctx_dir / "tests.md",
        ctx_dir / "docs.md",
        ctx_dir / "config.md",
        ctx_dir / "extra.md",
        idx_dir / "metrics.json",
        idx_dir / "other.bin",
    ]
    for p in paths:
        p.write_text("x", encoding="utf-8")

    types = [describe_artifact(p, ctn_dir).artifact_type for p in paths]
    assert "index_metadata" in types
    assert "file_cache_sqlite" in types
    assert "file_hashes_json" in types
    assert "evolution_ledger_json" in types
    assert "patch_audit_log_json" in types
    assert "rules_cache_binary" in types
    assert "interception_stats_json" in types
    assert "snapshot_json" in types
    assert "patch_index_json" in types
    assert "patch_operation_json" in types
    assert "graph_json" in types
    assert "bsg_json" in types
    assert "context_overview" in types
    assert "context_architecture" in types
    assert "context_tests" in types
    assert "context_docs" in types
    assert "context_config" in types
    assert "context_markdown" in types
    assert "metrics_json" in types
    assert "artifact_file" in types

    inferred = infer_ctn_dir_for_path(idx_dir / "graph.json")
    assert inferred == ctn_dir.resolve()
    assert infer_ctn_dir_for_path(tmp_path / "outside.txt") is None


def test_safe_parse_iso_variants() -> None:
    assert _safe_parse_iso(None) is None
    assert _safe_parse_iso("   ") is None
    assert _safe_parse_iso("not-a-date") is None

    dtz = _safe_parse_iso("2026-04-05T10:00:00Z")
    assert dtz is not None
    assert dtz.tzinfo is not None

    dt_naive = _safe_parse_iso("2026-04-05T10:00:00")
    assert dt_naive is not None
    assert dt_naive.tzinfo is not None


def test_rebuild_query_index_generates_hash_when_relationship_id_missing(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()
    payload = {
        "entities_by_id": {"a": {"id": "a", "type": "FUNCTION", "name": "a", "file": "a.py"}},
        "relationships": [
            {
                "type": "CALLS",
                "source_id": "a",
                "target_id": "b",
                "metadata": {"x": 1},
            }
        ],
    }

    stats = rebuild_query_index(ctn_dir, "idx-hash", payload)
    assert stats["relationships_indexed"] == 1

    rels = query_relationships(ctn_dir, index_id="idx-hash", relationship_type="calls", limit=10)
    assert len(rels) == 1
    assert rels[0]["relationship_id"]


def test_rebuild_query_index_deduplicates_explicit_duplicate_relationship_ids(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()
    payload = {
        "entities_by_id": {
            "e1": {"id": "e1", "type": "FUNCTION", "name": "f1", "file": "a.py"},
            "e2": {"id": "e2", "type": "FUNCTION", "name": "f2", "file": "b.py"},
        },
        "relationships": [
            {
                "id": "r1",
                "type": "CALLS",
                "source_id": "e1",
                "target_id": "e2",
                "metadata": {"line": 10},
            },
            {
                "id": "r1",
                "type": "CALLS",
                "source_id": "e1",
                "target_id": "e2",
                "metadata": {"line": 20},
            },
        ],
    }

    stats = rebuild_query_index(ctn_dir, "idx-dup", payload)
    assert stats["relationships_indexed"] == 1

    rels = query_relationships(ctn_dir, index_id="idx-dup", relationship_type="calls", limit=10)
    assert len(rels) == 1
    assert rels[0]["relationship_id"] == "r1"


def test_rebuild_query_index_deduplicates_computed_hash_duplicates(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()
    payload = {
        "entities_by_id": {
            "e1": {"id": "e1", "type": "FUNCTION", "name": "f1", "file": "a.py"},
            "e2": {"id": "e2", "type": "FUNCTION", "name": "f2", "file": "b.py"},
        },
        "relationships": [
            {
                "type": "CALLS",
                "source_id": "e1",
                "target_id": "e2",
                "metadata": {"line": 10},
            },
            {
                "type": "CALLS",
                "source_id": "e1",
                "target_id": "e2",
                "metadata": {"line": 20},
            },
        ],
    }

    stats = rebuild_query_index(ctn_dir, "idx-hash-dup", payload)
    assert stats["relationships_indexed"] == 1

    rels = query_relationships(ctn_dir, index_id="idx-hash-dup", relationship_type="calls", limit=10)
    assert len(rels) == 1
    assert rels[0]["source_id"] == "e1"
    assert rels[0]["target_id"] == "e2"


def test_register_artifact_for_path_returns_false_when_no_ctn_ancestor(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}", encoding="utf-8")
    ok = register_artifact_for_path(artifact, "artifact_file", producer="test")
    assert ok is False


def test_persist_wrappers_write_and_register(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()

    j_path = ctn_dir / "persisted.json"
    t_path = ctn_dir / "persisted.txt"
    b_path = ctn_dir / "persisted.bin"

    assert persist_json(ctn_dir, j_path, {"ok": True}, artifact_type="metrics_json", producer="test")
    assert persist_text(ctn_dir, t_path, "hello", artifact_type="context_markdown", producer="test")
    assert persist_bytes(ctn_dir, b_path, b"abc", artifact_type="artifact_file", producer="test")

    registry_db = ctn_dir / "artifact_registry.db"
    assert registry_db.exists()
    assert _rows(registry_db, "SELECT COUNT(*) FROM artifacts WHERE deleted = 0") >= 3


def test_get_registry_stats_reports_sync_and_artifact_counts(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()

    payload_path = ctn_dir / "metrics.json"
    payload_path.write_text('{"ok": true}', encoding="utf-8")
    assert register_artifact(
        ctn_dir,
        payload_path,
        "metrics_json",
        producer="test",
        schema_version="metrics.v1",
    )

    stats = get_registry_stats(ctn_dir)
    assert stats.get("enabled") is True
    assert stats.get("artifact_count", 0) >= 1
    assert stats.get("content_blob_count", 0) >= 1
    sync_status = stats.get("sync_status", {})
    assert sync_status.get("pending", 0) >= 1


def test_registry_sync_failure_lifecycle_methods(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()

    payload_path = ctn_dir / "graph.json"
    payload_path.write_text('{"ok": true}', encoding="utf-8")
    assert register_artifact(
        ctn_dir,
        payload_path,
        "graph_json",
        producer="test",
        schema_version="graph.v1",
    )

    registry = get_artifact_registry(ctn_dir)
    pending = registry.get_pending_artifacts()
    assert len(pending) == 1
    artifact_id = str(pending[0].get("artifact_id"))

    assert registry.mark_sync_failed(artifact_id, "network timeout", retry_count=1)

    failed = registry.get_failed_artifacts(max_retries=3)
    assert len(failed) == 1
    assert failed[0].get("artifact_id") == artifact_id
    assert failed[0].get("retry_count") == 1
    assert failed[0].get("sync_error") == "network timeout"

    summary = registry.get_sync_summary()
    assert summary.get("failed", 0) == 1
    assert summary.get("pending", 0) == 0
    assert summary.get("total", 0) == 1


def test_get_failed_artifacts_respects_max_retries(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()

    payload_path = ctn_dir / "metrics.json"
    payload_path.write_text('{"ok": true}', encoding="utf-8")
    assert register_artifact(
        ctn_dir,
        payload_path,
        "metrics_json",
        producer="test",
        schema_version="metrics.v1",
    )

    registry = get_artifact_registry(ctn_dir)
    artifact_id = registry.get_pending_artifacts()[0]["artifact_id"]
    assert registry.mark_sync_failed(str(artifact_id), "retry exhausted", retry_count=3)

    failed = registry.get_failed_artifacts(max_retries=3)
    assert failed == []
