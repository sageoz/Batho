"""Workspace handle representing a mounted workspace with its state."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from batho.bridge.models import WorkspaceConfig, WorkspaceState

if TYPE_CHECKING:
    from batho.bridge.connection_pool import ConnectionPool
    from batho.bridge.registry_client import ArtifactRegistryBridge
    from batho.bridge.artifact_loader import ArtifactLoader


@dataclass
class WorkspaceHandle:
    """Handle representing a mounted workspace with its state, locks, and resources."""

    config: WorkspaceConfig
    state: WorkspaceState = WorkspaceState.REGISTERED
    pool: "ConnectionPool | None" = None
    bridge: "ArtifactRegistryBridge | None" = None
    loader: "ArtifactLoader | None" = None
    last_used_at: float = field(default_factory=time.time)
    mount_attempts: int = 0
    last_error: str | None = None
    inflight: int = 0
    semaphore: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(16))
    lock: threading.RLock = field(default_factory=threading.RLock)
    cache_bytes: int = 0

    @property
    def ctn_dir(self) -> Path:
        return Path(self.config.ctn_dir)

    @property
    def workspace_id(self) -> str:
        return self.config.id

    @property
    def is_pinned(self) -> bool:
        return self.config.pinned

    @property
    def is_ready(self) -> bool:
        return self.state == WorkspaceState.READY

    @property
    def is_failed(self) -> bool:
        return self.state == WorkspaceState.FAILED

    @property
    def is_degraded(self) -> bool:
        return self.state == WorkspaceState.DEGRADED

    async def get_index(self) -> dict:
        """Load and return index.json content."""
        if not self.loader:
            raise RuntimeError(f"Workspace {self.workspace_id} loader not available")
        return self.loader.load_json("index_json")

    @property
    def artifact_count(self) -> int:
        """Return total number of artifacts in the registry."""
        if not self.bridge:
            return 0
        stats = self.bridge.stats()
        return stats.total_artifacts

    @property
    def last_index_time(self) -> float | None:
        """Return timestamp of the last index operation."""
        if not self.bridge:
            return None
        entries, _, _, _ = self.bridge.list_indexes()
        if not entries:
            return None
        # Entries are sorted by timestamp desc, so first one is most recent
        return entries[0].timestamp

    def mark_used(self) -> None:
        """Update last_used_at timestamp."""
        self.last_used_at = time.time()

    def increment_inflight(self) -> int:
        """Increment in-flight request counter."""
        self.inflight += 1
        return self.inflight

    def decrement_inflight(self) -> int:
        """Decrement in-flight request counter."""
        self.inflight = max(0, self.inflight - 1)
        return self.inflight

    def __lt__(self, other: "WorkspaceHandle") -> bool:
        return self.last_used_at < other.last_used_at


__all__ = [
    "WorkspaceHandle",
]
