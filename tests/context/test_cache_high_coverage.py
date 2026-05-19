from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from batho.context.cache import ASTCache
from batho.context.schema import Entity, EntityType, Relationship, RelationshipType


def _entity(file_path: str, name: str) -> Entity:
    return Entity(
        type=EntityType.FUNCTION,
        name=name,
        file=file_path,
        start_line=1,
        end_line=2,
        metadata={"payload": "x" * 8000},
    )


def test_file_hash_matches_sha256_for_large_payload(tmp_path: Path) -> None:
    cache = ASTCache(cache_path=str(tmp_path / "cache.db"))
    content = (b"a" * 70000) + (b"b" * 123)

    assert cache.file_hash("src/a.py", content) == hashlib.sha256(content).hexdigest()


def test_get_cached_entities_removes_expired_entries(tmp_path: Path) -> None:
    cache = ASTCache(cache_path=str(tmp_path / "cache.db"))
    cache.cache_entities("src/a.py", "hash-expired", [_entity("src/a.py", "a")], 1.0, 10)

    stale_time = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    with sqlite3.connect(str(cache._path)) as conn:
        conn.execute(
            "UPDATE cache_entries SET cached_at = ?, ttl_days = ? WHERE file_hash = ?",
            (stale_time, 1, "hash-expired"),
        )
        conn.commit()

    assert cache.get_cached_entities("src/a.py", "hash-expired", 1.0, 10) is None

    with sqlite3.connect(str(cache._path)) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM cache_entries WHERE file_hash = ?", ("hash-expired",)
        ).fetchone()
    assert rows is not None
    assert rows[0] == 0


def test_get_cached_entities_removes_corrupt_entries(tmp_path: Path) -> None:
    cache = ASTCache(cache_path=str(tmp_path / "cache.db"))
    cache.cache_entities("src/a.py", "hash-corrupt", [_entity("src/a.py", "a")], 1.0, 10)

    with sqlite3.connect(str(cache._path)) as conn:
        conn.execute(
            "UPDATE cache_entries SET entities = ? WHERE file_hash = ?",
            ("not valid json", "hash-corrupt"),
        )
        conn.commit()

    assert cache.get_cached_entities("src/a.py", "hash-corrupt", 1.0, 10) is None

    with sqlite3.connect(str(cache._path)) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM cache_entries WHERE file_hash = ?", ("hash-corrupt",)
        ).fetchone()
    assert rows is not None
    assert rows[0] == 0


def test_cache_roundtrip_with_relationships(tmp_path: Path) -> None:
    cache = ASTCache(cache_path=str(tmp_path / "cache.db"))
    entity = _entity("src/a.py", "a")
    now = datetime.now(timezone.utc).isoformat()
    unresolved = Entity(
        type=EntityType.UNRESOLVED,
        name="foo",
        file="src/a.py",
        start_line=5,
        end_line=5,
        metadata={
            "reference_type": "imports",
            "resolution_reason": "not_found",
            "attempts": 1,
            "created_at": now,
            "last_attempt": now,
            "is_visible": False,
        },
    )
    rel = Relationship(
        source_id=entity.id,
        target_id=unresolved.id,
        type=RelationshipType.IMPORTS,
    )
    cache.cache_entities(
        "src/a.py", "hash-rel", [entity, unresolved], 1.0, 10, relationships=[rel]
    )

    result = cache.get_cached_entities("src/a.py", "hash-rel", 1.0, 10)
    assert result is not None
    entities, relationships = result
    assert len(entities) == 2
    assert entities[0].name == "a"
    assert len(relationships) == 1
    assert relationships[0].source_id == entity.id
    assert relationships[0].type == RelationshipType.IMPORTS


def test_invalidate_cache_without_pattern_clears_all_entries(tmp_path: Path) -> None:
    cache = ASTCache(cache_path=str(tmp_path / "cache.db"))
    cache.cache_entities("src/a.py", "hash-1", [_entity("src/a.py", "a")], 1.0, 10)
    cache.cache_entities("src/b.py", "hash-2", [_entity("src/b.py", "b")], 2.0, 20)

    cache.invalidate_cache()

    stats = cache.get_cache_stats()
    assert stats["entry_count"] == 0


def test_cleanup_expired_cache_removes_stale_records(tmp_path: Path) -> None:
    cache = ASTCache(cache_path=str(tmp_path / "cache.db"))
    cache.cache_entities("src/a.py", "hash-cleanup", [_entity("src/a.py", "a")], 1.0, 10)

    stale_time = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    with sqlite3.connect(str(cache._path)) as conn:
        conn.execute(
            "UPDATE cache_entries SET cached_at = ?, ttl_days = ? WHERE file_hash = ?",
            (stale_time, 1, "hash-cleanup"),
        )
        conn.commit()

    deleted = cache.cleanup_expired_cache()
    assert deleted >= 1


def test_enforce_max_size_noop_then_lru_eviction(tmp_path: Path) -> None:
    cache = ASTCache(cache_path=str(tmp_path / "cache.db"))

    cache.cache_entities("src/a.py", "hash-size-1", [_entity("src/a.py", "a")], 1.0, 10)
    cache.cache_entities("src/b.py", "hash-size-2", [_entity("src/b.py", "b")], 2.0, 20)

    assert cache.enforce_max_size(max_size_mb=100) == 0

    deleted = cache.enforce_max_size(max_size_mb=0)
    assert deleted >= 1
    assert cache.get_cache_stats()["entry_count"] <= 1


def test_close_releases_thread_local_connection(tmp_path: Path) -> None:
    cache = ASTCache(cache_path=str(tmp_path / "cache.db"))
    conn = cache._get_connection()
    assert conn is not None

    cache.close()
    assert cache._local.conn is None
