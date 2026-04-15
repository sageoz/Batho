"""Helpers for loading persisted graph artifacts from .ctn storage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from batho.config import get_config_cached
from batho.context.codegraph import InMemoryGraph
from batho.context.mmap_storage import load_json_with_optional_mmap
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="graph_cache")


def _storage_mmap_config() -> tuple[bool, int]:
    cfg = get_config_cached()
    bsg_cfg = cfg.get("bsg", {}) if isinstance(cfg, dict) else {}
    storage_cfg = bsg_cfg.get("storage", {}) if isinstance(bsg_cfg, dict) else {}
    mmap_enabled = bool(storage_cfg.get("mmap_enabled", False))
    mmap_min_size_mb = max(1, int(storage_cfg.get("mmap_min_size_mb", 8)))
    return mmap_enabled, mmap_min_size_mb * 1024 * 1024


def load_graph_payload(ctn_dir: Path, index_id: str) -> dict[str, Any] | None:
    """Load persisted graph payload for an index using optional mmap acceleration."""
    graph_path = ctn_dir / index_id / "graph.json"
    if not graph_path.exists():
        return None

    mmap_enabled, mmap_min_size_bytes = _storage_mmap_config()
    try:
        payload = load_json_with_optional_mmap(
            graph_path,
            mmap_enabled=mmap_enabled,
            min_size_bytes=mmap_min_size_bytes,
        )
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        LOGGER.warning(
            "graph_cache_load_failed",
            index_id=index_id,
            path=str(graph_path),
            error=str(exc),
        )
        return None

    if not isinstance(payload, dict):
        return None
    return payload


def load_cached_graph(ctn_dir: Path, index_id: str) -> InMemoryGraph | None:
    """Load graph object from persisted graph.json for index_id."""
    payload = load_graph_payload(ctn_dir, index_id)
    if payload is None:
        return None

    try:
        return InMemoryGraph.from_dict(payload)
    except Exception as exc:
        LOGGER.warning(
            "graph_cache_deserialize_failed",
            index_id=index_id,
            error=str(exc),
        )
        return None


def get_cached_graph_stats(
    ctn_dir: Path, index_id: str | None = None
) -> dict[str, Any]:
    """Return cache stats for persisted graph artifacts."""
    metadata_path = ctn_dir / "index.json"
    current_index_id = index_id

    if not current_index_id and metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            current_index_id = str(metadata.get("current_index_id") or "") or None
        except (json.JSONDecodeError, OSError):
            current_index_id = None

    graph_size_bytes = 0
    graph_exists = False
    if current_index_id:
        graph_path = ctn_dir / current_index_id / "graph.json"
        graph_exists = graph_path.exists()
        if graph_exists:
            try:
                graph_size_bytes = int(graph_path.stat().st_size)
            except OSError:
                graph_size_bytes = 0

    return {
        "current_index_id": current_index_id or "",
        "graph_exists": graph_exists,
        "graph_size_bytes": graph_size_bytes,
    }
