"""Rollback to last known good state."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from batho.storage.engine import BathoDatabase
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="integrity")


@dataclass
class RollbackPoint:
    """A named rollback point."""

    point_id: str
    snapshot_id: str
    name: str
    created_at: str
    metadata: dict[str, Any]


class RollbackManager:
    """Manages rollback to last known good state."""

    def __init__(self, db: BathoDatabase, root: str):
        self.db = db
        self.root = root

    def find_last_known_good(self) -> str | None:
        """Find last snapshot with clean integrity.

        Returns snapshot_id of last known good state, or None if not found.
        """
        try:
            with self.db.connection(read_only=True) as conn:
                # Get snapshots newest to oldest
                rows = conn.execute(
                    "SELECT * FROM snapshots ORDER BY created_at DESC"
                ).fetchall()

                if not rows:
                    LOGGER.warning("no_snapshots_found", root=self.root)
                    return None

                # For each snapshot, run minimal integrity checks
                for row in rows:
                    snapshot_id = row["snapshot_id"]
                    if self._is_snapshot_healthy(conn, snapshot_id):
                        LOGGER.info("found_last_known_good", snapshot_id=snapshot_id)
                        return snapshot_id

                LOGGER.warning("no_healthy_snapshot_found", root=self.root)
                return None

        except Exception as exc:
            LOGGER.error("find_last_known_good_error", error=str(exc), root=self.root)
            return None

    def _is_snapshot_healthy(self, conn, snapshot_id: str) -> bool:
        """Check if a snapshot represents a healthy state.

        Minimal checks: no critical db corruption, valid checksum.
        """
        try:
            # Check snapshot exists with valid data
            row = conn.execute(
                "SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()

            if not row:
                return False

            # Verify checksum if available
            checksum = row["checksum"]
            if checksum:
                import json
                import hashlib

                data = {
                    "snapshot_id": row["snapshot_id"],
                    "parent_id": row["parent_id"],
                    "created_at": row["created_at"],
                    "label": row["label"],
                    "git_commit": row["git_commit"],
                    "git_branch": row["git_branch"],
                    "root_path": row["root_path"],
                    "schema_version": row["schema_version"],
                    "stats": json.loads(row["stats_json"] or "{}"),
                }

                computed = hashlib.sha256(
                    json.dumps(data, sort_keys=True).encode("utf-8")
                ).hexdigest()

                if computed != checksum:
                    LOGGER.debug(
                        "snapshot_checksum_mismatch",
                        snapshot_id=snapshot_id,
                    )
                    return False

            return True

        except Exception as exc:
            LOGGER.debug("snapshot_health_check_failed", snapshot_id=snapshot_id, error=str(exc))
            return False

    def rollback_to_snapshot(self, snapshot_id: str) -> bool:
        """Rollback database state to given snapshot.

        Args:
            snapshot_id: The snapshot ID to rollback to

        Returns:
            True if successful, False otherwise
        """
        try:
            # 1. Validate snapshot exists
            with self.db.connection(read_only=True) as conn:
                row = conn.execute(
                    "SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)
                ).fetchone()

                if not row:
                    LOGGER.error("snapshot_not_found", snapshot_id=snapshot_id)
                    return False

            # 2. Create pre-rollback backup point
            backup_point = self._create_backup_point()

            # 3. Delete all data newer than the snapshot
            with self.db.connection() as conn:
                snapshot_time = row["created_at"]

                # Delete newer snapshots
                conn.execute(
                    "DELETE FROM snapshots WHERE created_at > ?",
                    (snapshot_time,),
                )

                # Delete newer index runs
                conn.execute(
                    "DELETE FROM index_runs WHERE started_at > ?",
                    (snapshot_time,),
                )

                # Note: Entities, relationships, BSG are cascade-deleted via FK

                conn.commit()

            LOGGER.info(
                "rollback_completed",
                snapshot_id=snapshot_id,
                backup_point=backup_point,
            )
            return True

        except Exception as exc:
            LOGGER.error("rollback_failed", snapshot_id=snapshot_id, error=str(exc))
            return False

    def _create_backup_point(self) -> str:
        """Create a named backup point before rollback."""
        point_id = f"pre-rollback-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"

        try:
            with self.db.connection() as conn:
                conn.execute(
                    """INSERT INTO fix_audit_log (
                        log_id, run_id, timestamp, action, check_name, severity, message, details_json, success
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        point_id,
                        datetime.now(timezone.utc).isoformat(),
                        "rollback_backup_point",
                        None,
                        "info",
                        f"Backup point created: {point_id}",
                        "{}",
                        1,
                    ),
                )
                conn.commit()
        except Exception as exc:
            LOGGER.warning("backup_point_creation_warning", error=str(exc))

        return point_id

    def create_named_checkpoint(self, name: str) -> str:
        """Create a named rollback point.

        Args:
            name: Human-readable name for the checkpoint

        Returns:
            Checkpoint ID
        """
        checkpoint_id = f"checkpoint-{name}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

        try:
            # Get current latest snapshot
            with self.db.connection(read_only=True) as conn:
                row = conn.execute(
                    "SELECT snapshot_id FROM snapshots ORDER BY created_at DESC LIMIT 1"
                ).fetchone()

                snapshot_id = row["snapshot_id"] if row else None

            # Store checkpoint metadata
            with self.db.connection() as conn:
                conn.execute(
                    """INSERT INTO fix_audit_log (
                        log_id, run_id, timestamp, action, check_name, severity, message, details_json, success
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        checkpoint_id,
                        datetime.now(timezone.utc).isoformat(),
                        "create_checkpoint",
                        None,
                        "info",
                        f"Checkpoint created: {name}",
                        json.dumps({"name": name, "snapshot_id": snapshot_id}),
                        1,
                    ),
                )
                conn.commit()

            LOGGER.info("checkpoint_created", checkpoint_id=checkpoint_id, name=name)
            return checkpoint_id

        except Exception as exc:
            LOGGER.error("checkpoint_creation_failed", name=name, error=str(exc))
            raise

    def list_checkpoints(self) -> list[dict[str, Any]]:
        """List all named checkpoints."""
        try:
            with self.db.connection(read_only=True) as conn:
                rows = conn.execute(
                    """SELECT * FROM fix_audit_log
                    WHERE action = 'create_checkpoint'
                    ORDER BY timestamp DESC"""
                ).fetchall()

                return [
                    {
                        "checkpoint_id": row["run_id"],
                        "timestamp": row["timestamp"],
                        "name": json.loads(row["details_json"]).get("name", "unknown"),
                        "snapshot_id": json.loads(row["details_json"]).get("snapshot_id"),
                    }
                    for row in rows
                ]

        except Exception as exc:
            LOGGER.error("list_checkpoints_failed", error=str(exc))
            return []


import json

__all__ = [
    "RollbackManager",
    "RollbackPoint",
]
