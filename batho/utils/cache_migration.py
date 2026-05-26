"""Utilities to migrate legacy cache databases into cache.db."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from batho.config import get_config_cached, set_active_root
from batho.context.unified_cache import BathoCache
from batho.utils.logging import get_logger

logger = get_logger(__name__, component="cache_migration")


def _count_rows(conn: sqlite3.Connection, table: str) -> int:
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
    return int(cursor.fetchone()["count"])


def _copy_ast_entries(old_db: Path, new_db: Path) -> int:
    if not old_db.exists():
        return 0

    old_conn = sqlite3.connect(old_db)
    old_conn.row_factory = sqlite3.Row
    new_conn = sqlite3.connect(new_db)
    new_conn.row_factory = sqlite3.Row

    try:
        old_cursor = old_conn.cursor()
        new_cursor = new_conn.cursor()
        old_cursor.execute(
            """
            SELECT file_hash, file_path, entities, relationships, mtime, size, cached_at, ttl_days
            FROM cache_entries
            """
        )
        rows = old_cursor.fetchall()
        new_cursor.executemany(
            """
            INSERT OR REPLACE INTO ast_entries
            (file_hash, file_path, entities, relationships, mtime, size, cached_at, ttl_days)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["file_hash"],
                    row["file_path"],
                    row["entities"],
                    row["relationships"],
                    row["mtime"],
                    row["size"],
                    row["cached_at"],
                    row["ttl_days"],
                )
                for row in rows
            ],
        )
        new_conn.commit()
        return len(rows)
    finally:
        old_conn.close()
        new_conn.close()


def _copy_file_hashes(old_db: Path, new_db: Path, is_indexed: bool) -> int:
    if not old_db.exists():
        return 0

    old_conn = sqlite3.connect(old_db)
    old_conn.row_factory = sqlite3.Row
    new_conn = sqlite3.connect(new_db)
    new_conn.row_factory = sqlite3.Row

    try:
        old_cursor = old_conn.cursor()
        new_cursor = new_conn.cursor()
        old_cursor.execute(
            """
            SELECT file_path, content_hash, mtime, size, updated_at
            FROM file_hashes
            """
        )
        rows = old_cursor.fetchall()
        new_cursor.executemany(
            """
            INSERT OR REPLACE INTO file_tracking
            (file_path, content_hash, mtime, size, is_indexed, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["file_path"],
                    row["content_hash"],
                    row["mtime"],
                    row["size"],
                    int(is_indexed),
                    row["updated_at"],
                )
                for row in rows
            ],
        )
        new_conn.commit()
        return len(rows)
    finally:
        old_conn.close()
        new_conn.close()


def migrate_cache(
    root: Path,
    old_ast_path: Path | None = None,
    old_file_hash_path: Path | None = None,
    new_cache_path: Path | None = None,
    assume_indexed: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    set_active_root(root)
    cfg = get_config_cached()
    ctn_dir = root / cfg["paths"]["config_dir"]
    old_ast = old_ast_path or (ctn_dir / "local" / "cache" / "ast_cache.db")
    old_file_hash = (
        old_file_hash_path
        or (ctn_dir / "local" / "cache" / "file_hash_cache.db")
    )
    new_cache = new_cache_path or (ctn_dir / "local" / "cache" / "cache.db")

    ctn_dir.mkdir(parents=True, exist_ok=True)
    BathoCache(str(new_cache))

    result: dict[str, Any] = {
        "root": str(root),
        "new_cache": str(new_cache),
        "old_ast_cache": str(old_ast),
        "old_file_hash_cache": str(old_file_hash),
        "ast_entries": {"migrated": 0, "source_rows": 0, "valid": True},
        "file_hashes": {"migrated": 0, "source_rows": 0, "valid": True},
        "warnings": [],
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    if old_ast.exists():
        try:
            old_conn = sqlite3.connect(old_ast)
            old_conn.row_factory = sqlite3.Row
            try:
                source_rows = _count_rows(old_conn, "cache_entries")
            finally:
                old_conn.close()
            migrated = _copy_ast_entries(old_ast, new_cache)
            result["ast_entries"]["source_rows"] = source_rows
            result["ast_entries"]["migrated"] = migrated
            result["ast_entries"]["valid"] = migrated == source_rows
            if migrated != source_rows:
                result["warnings"].append("ast_entry_count_mismatch")
        except sqlite3.Error as exc:
            result["ast_entries"]["valid"] = False
            result["ast_entries"]["error"] = str(exc)
            result["warnings"].append("ast_cache_read_failed")
    else:
        result["warnings"].append("ast_cache_missing")

    if old_file_hash.exists():
        try:
            old_conn = sqlite3.connect(old_file_hash)
            old_conn.row_factory = sqlite3.Row
            try:
                source_rows = _count_rows(old_conn, "file_hashes")
            finally:
                old_conn.close()
            migrated = _copy_file_hashes(old_file_hash, new_cache, assume_indexed)
            result["file_hashes"]["source_rows"] = source_rows
            result["file_hashes"]["migrated"] = migrated
            result["file_hashes"]["valid"] = migrated == source_rows
            if migrated != source_rows:
                result["warnings"].append("file_hash_count_mismatch")
        except sqlite3.Error as exc:
            result["file_hashes"]["valid"] = False
            result["file_hashes"]["error"] = str(exc)
            result["warnings"].append("file_hash_cache_read_failed")
    else:
        result["warnings"].append("file_hash_cache_missing")

    return result


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate legacy cache databases.")
    parser.add_argument("--root", default=".", help="Repository root path")
    parser.add_argument("--old-ast", default=None, help="Path to ast_cache.db")
    parser.add_argument(
        "--old-file-hash", default=None, help="Path to file_hash_cache.db"
    )
    parser.add_argument("--new-cache", default=None, help="Path to cache.db")
    parser.add_argument(
        "--assume-indexed",
        action="store_true",
        help="Mark migrated file hashes as indexed",
    )
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()
    result = migrate_cache(
        root=Path(args.root),
        old_ast_path=Path(args.old_ast) if args.old_ast else None,
        old_file_hash_path=Path(args.old_file_hash) if args.old_file_hash else None,
        new_cache_path=Path(args.new_cache) if args.new_cache else None,
        assume_indexed=bool(args.assume_indexed),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
