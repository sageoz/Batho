"""Time Machine utilities for Batho core (JSON snapshots and diffs).

- Snapshots are stored under `.ctn/snapshots/<snapshot_id>.json`.
- snapshot_id format: `batho_<uuid>_<timestamp>` (UTC).
- Diff reports entity/relationship deltas and changed files.
- PR patching stub provided for future incremental updates.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from batho_core.config import SNAPSHOT_SCHEMA_VERSION
from batho_core.context.codegraph import InMemoryGraph
from batho_core.context.repomap import RepoMap
from batho_core.utils.hash import compute_bytes_hash
from batho_core.utils.logging import get_logger

logger = get_logger(__name__, component="time_machine")


def _snapshot_dir(ctn_dir: Path) -> Path:
    p = ctn_dir / "snapshots"
    p.mkdir(parents=True, exist_ok=True)
    return p


def generate_snapshot_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"batho_{uuid.uuid4().hex}_{ts}"


def create_snapshot(
    ctn_dir: Path,
    root: Path,
    graph: InMemoryGraph,
    repomap: RepoMap,
    label: str | None = None,
) -> str:
    """Persist a snapshot of the current graph/repomap to JSON."""
    snapshot_id = generate_snapshot_id()
    snap_path = _snapshot_dir(ctn_dir) / f"{snapshot_id}.json"

    data = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "label": label or "",
        "graph": graph.to_dict(),
        "repomap": repomap.render_json(),
        "stats": {
            "entity_count": len(graph.entities),
            "relationship_count": len(graph.relationships),
            "file_count": len(repomap._by_file),
        },
    }
    data["_checksum"] = compute_bytes_hash(
        json.dumps({k: v for k, v in data.items() if k != "_checksum"}, sort_keys=True).encode(
            "utf-8"
        )
    )
    tmp = snap_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(snap_path)
    logger.info("snapshot_created", snapshot_id=snapshot_id, path=str(snap_path))
    return snapshot_id


def list_snapshots(ctn_dir: Path) -> list[dict[str, Any]]:
    snaps = []
    snap_dir = _snapshot_dir(ctn_dir)
    for p in sorted(snap_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            snaps.append(
                {
                    "snapshot_id": data.get("snapshot_id", p.stem),
                    "created_at": data.get("created_at"),
                    "label": data.get("label", ""),
                    "path": str(p),
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
    return snaps


def load_snapshot(ctn_dir: Path, snapshot_id: str) -> dict[str, Any] | None:
    snap_path = _snapshot_dir(ctn_dir) / f"{snapshot_id}.json"
    if not snap_path.exists():
        return None
    try:
        data = json.loads(snap_path.read_text(encoding="utf-8"))
        checksum = data.get("_checksum")
        if checksum:
            calc = compute_bytes_hash(
                json.dumps(
                    {k: v for k, v in data.items() if k != "_checksum"}, sort_keys=True
                ).encode("utf-8")
            )
            if calc != checksum:
                logger.warning("snapshot_corrupt_checksum", snapshot_id=snapshot_id)
                return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def diff_snapshots(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    def _files(rep_json: dict[str, Any]) -> set[str]:
        return set((rep_json or {}).get("files", {}).keys())

    files_a = _files(a.get("repomap", {}))
    files_b = _files(b.get("repomap", {}))
    return {
        "entity_delta": (
            b.get("stats", {}).get("entity_count", 0) - a.get("stats", {}).get("entity_count", 0)
        ),
        "relationship_delta": (
            b.get("stats", {}).get("relationship_count", 0)
            - a.get("stats", {}).get("relationship_count", 0)
        ),
        "added_files": sorted(files_b - files_a),
        "removed_files": sorted(files_a - files_b),
        "common_files": len(files_a & files_b),
    }


def compute_staleness(
    prev_entry: dict[str, Any] | None, current_repo_hash: str, stats: dict[str, Any] | None = None
) -> float:
    """
    Compute staleness using repo hash equality + change ratio + age + error rate.

    Returns float in [0,1], where 1 is fully stale.
    """

    if not prev_entry:
        return 1.0

    prev_repo_hash = prev_entry.get("repo_hash") if isinstance(prev_entry, dict) else None
    if prev_repo_hash and prev_repo_hash == current_repo_hash:
        base = 0.1
    else:
        base = 0.6

    prev_file_count = (
        max(1, int(prev_entry.get("file_count", 1))) if isinstance(prev_entry, dict) else 1
    )
    parsed = int(stats.get("files_parsed", 0)) if stats else 0
    change_ratio = min(1.0, parsed / prev_file_count) if prev_file_count else 0.0

    errors = int(stats.get("errors", 0)) if stats else 0
    error_factor = min(1.0, errors / max(parsed, 1)) if parsed else 0.0

    age_factor = 0.0
    try:
        prev_ts = datetime.fromisoformat(prev_entry.get("timestamp")) if prev_entry else None
        if prev_ts:
            age_hours = (datetime.now(timezone.utc) - prev_ts).total_seconds() / 3600
            age_factor = min(1.0, age_hours / 24)  # age out over a day
    except Exception:
        age_factor = 0.0

    score = min(1.0, base + 0.3 * change_ratio + 0.2 * error_factor + 0.1 * age_factor)
    return round(score, 3)


def incremental_patch_stub(ctn_dir: Path, changed_files: Iterable[Path]) -> dict[str, Any]:
    """Stub for PR diff patching (placeholder for future incremental index updates)."""
    # NOTE: Commented placeholder logic; keep minimal stub return to avoid accidental use.
    # file_hashes = {}
    # for p in changed_files:
    #     try:
    #         file_hashes[str(p)] = compute_bytes_hash(p.read_bytes())
    #     except OSError:
    #         continue
    logger.info("incremental_patch_stub", files=len(list(changed_files)))
    return {
        "patched_files": [],
        "note": "incremental patching not implemented in v1; run full rebuild",
    }


def webhook_stub(event_payload: dict[str, Any]) -> dict[str, Any]:
    """Placeholder webhook handler for GitHub push/PR events."""
    # NOTE: Commented placeholder logic; keep minimal stub return to avoid accidental use.
    # event_type = event_payload.get("event") or "unknown"
    # repo = event_payload.get("repository", {}).get("full_name")
    # logger.info("webhook_stub", event=event_type, repo=repo)
    logger.info("webhook_stub", status="not_implemented")
    return {
        "event": event_payload.get("event") or "unknown",
        "repo": event_payload.get("repository", {}).get("full_name"),
        "status": "not_implemented",
        "note": "webhook handling deferred to v2",
    }
