"""Utilities to clean up old cache files after migration to unified cache.db."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from batho.config import get_config_cached_for_root
from batho.utils.logging import get_logger

logger = get_logger(__name__, component="cache_cleanup")


def cleanup_old_caches(root: Path, dry_run: bool = False) -> dict[str, Any]:
    """
    Remove old cache files after migration to unified cache.db.

    Args:
        root: Repository root path
        dry_run: If True, only report what would be deleted without deleting

    Returns:
        Summary of cleanup operation including deleted files and warnings
    """
    root = root.resolve()
    cfg = get_config_cached_for_root(root)
    ctn_dir = root / cfg["paths"]["ctn_dir"]

    old_cache_dir = ctn_dir / "local" / "cache"
    backup_dir = ctn_dir / "local" / "cache.backup"

    files_to_delete = [
        old_cache_dir / "ast_cache.db",
        old_cache_dir / "file_hash_cache.db",
        old_cache_dir / "rules_cache.bin",
    ]

    result: dict[str, Any] = {
        "root": str(root),
        "dry_run": dry_run,
        "deleted": [],
        "skipped": [],
        "errors": [],
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    if not old_cache_dir.exists():
        result["skipped"].append("cache_directory_missing")
        return result

    for file_path in files_to_delete:
        if file_path.exists():
            if dry_run:
                result["skipped"].append(f"would_delete:{file_path.name}")
                continue
            try:
                backup_path = backup_dir / file_path.name
                backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, backup_path)
                file_path.unlink()
                result["deleted"].append(str(file_path))
                logger.info("cache_file_deleted", path=str(file_path), backed_up=str(backup_path))
            except Exception as exc:
                result["errors"].append(f"{file_path.name}: {str(exc)}")
                logger.error("cache_file_delete_failed", path=str(file_path), error=str(exc))
        else:
            result["skipped"].append(f"not_found:{file_path.name}")

    try:
        if old_cache_dir.exists() and not any(old_cache_dir.iterdir()):
            old_cache_dir.rmdir()
            result["deleted"].append(str(old_cache_dir))
            logger.info("empty_cache_directory_removed", path=str(old_cache_dir))
    except Exception as exc:
        result["errors"].append(f"directory_cleanup: {str(exc)}")

    return result


def get_cache_dir_status(root: Path) -> dict[str, Any]:
    """Check status of old and new cache directories."""
    root = root.resolve()
    cfg = get_config_cached_for_root(root)
    ctn_dir = root / cfg["paths"]["ctn_dir"]

    old_cache_dir = ctn_dir / "local" / "cache"
    new_cache_file = ctn_dir / "local" / "cache.db"

    status: dict[str, Any] = {
        "old_cache_dir_exists": old_cache_dir.exists(),
        "old_cache_files": [],
        "new_cache_exists": new_cache_file.exists(),
    }

    if old_cache_dir.exists():
        try:
            for f in old_cache_dir.iterdir():
                if f.is_file():
                    status["old_cache_files"].append({
                        "name": f.name,
                        "size_bytes": f.stat().st_size,
                    })
        except Exception as exc:
            status["error"] = str(exc)

    if new_cache_file.exists():
        status["new_cache_size_bytes"] = new_cache_file.stat().st_size

    return status
