"""High-level cloud sync orchestration for registry artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from batho.cloud_sync.client import SyncClient
from batho.cloud_sync.config import CloudSyncConfig
from batho.config import get_config_cached
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="cloud_sync_uploader")


@dataclass
class SyncSummary:
    total: int = 0
    uploaded: int = 0
    failed: int = 0
    dry_run: bool = False
    duration_seconds: float = 0.0
    by_type: dict[str, dict[str, int]] = field(default_factory=dict)
    failures: list[dict[str, Any]] = field(default_factory=list)


class CloudSyncUploader:
    def __init__(
        self,
        config: CloudSyncConfig | dict[str, Any] | None = None,
        *,
        client: SyncClient | None = None,
    ):
        if config is None:
            cfg = get_config_cached().get("cloud_sync", {})
            config = cfg if isinstance(cfg, dict) else {}

        if isinstance(config, CloudSyncConfig):
            self.config = config
        else:
            self.config = CloudSyncConfig.model_validate(config)

        self.client = client or SyncClient(self.config)

    def _project_id(self, ctn_dir: Path) -> str:
        configured = str(self.config.project_id or "").strip()
        if configured:
            return configured
        return ctn_dir.parent.name
