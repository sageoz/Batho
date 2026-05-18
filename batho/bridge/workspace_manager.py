"""Workspace manager with LRU residency pool, lazy mount, and state machine."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from batho.bridge.artifact_cache import ArtifactCache
from batho.bridge.connection_pool import ConnectionPool
from batho.bridge.constants import MOUNT_BACKOFF_SECONDS
from batho.bridge.models import (
    ConcurrencyConfig,
    CrossRepoConfig,
    HubConfigDiff,
    ResidencyConfig,
    WorkspaceConfig,
    WorkspaceHealth,
    WorkspaceState,
)
from batho.bridge.cross_index import CrossRepoIndex
from batho.bridge.workspace_discovery import WorkspaceDiscovery
from batho.bridge.workspace_handle import WorkspaceHandle
from batho.bridge.workspace_registry import WorkspaceRegistry
from batho.bridge.registry_client import ArtifactRegistryBridge
from batho.bridge.artifact_loader import ArtifactLoader
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge.manager")


class WorkspaceManager:
    """LRU residency pool with lazy mount, eviction, and state machine."""

    def __init__(
        self,
        registry: WorkspaceRegistry,
        residency: ResidencyConfig,
        concurrency: ConcurrencyConfig,
        cache: ArtifactCache,
        cross_repo: CrossRepoConfig | None = None,
    ):
        self._registry = registry
        self._residency = residency
        self._concurrency = concurrency
        self._cache = cache
        self._cross_repo = cross_repo or CrossRepoConfig()
        self._cross_index: CrossRepoIndex | None = None
        self._handles: dict[str, WorkspaceHandle] = {}
        self._handles_lock = threading.RLock()
        self._mount_futures: dict[str, asyncio.Future] = {}
        self._mount_futures_lock = threading.Lock()
        self._global_semaphore = asyncio.Semaphore(concurrency.global_inflight_limit)
        self._reaper_task: asyncio.Task | None = None
        self._running = False
        self._ready = False
        self._discovery: WorkspaceDiscovery | None = None
        self._evicting: set[str] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        """Return the event loop the manager is running in."""
        return self._loop

    @property
    def ready(self) -> bool:
        """Return whether the manager is ready (astart completed)."""
        return self._ready

    @property
    def registry(self) -> WorkspaceRegistry:
        return self._registry

    @property
    def cache(self) -> ArtifactCache:
        return self._cache

    @property
    def cross_repo(self) -> CrossRepoConfig:
        return self._cross_repo

    @property
    def cross_index(self) -> CrossRepoIndex | None:
        if not self._cross_repo.enabled:
            return None
        if self._cross_index is None:
            budget = int(self._cache.max_per_workspace_bytes * 0.25)
            self._cross_index = CrossRepoIndex(self._cross_repo, max_index_bytes=budget)
        return self._cross_index

    def start(self) -> None:
        """Start the manager and register all workspaces (sync entrypoint)."""
        self._running = True
        config = self._registry.load()

        for ws_config in config.workspaces:
            with self._handles_lock:
                if ws_config.id not in self._handles:
                    handle = WorkspaceHandle(
                        config=ws_config,
                        state=WorkspaceState.REGISTERED,
                    )
                    handle.semaphore = asyncio.Semaphore(self._concurrency.per_workspace_inflight_limit)
                    self._handles[ws_config.id] = handle
                    LOGGER.info("workspace_registered", workspace_id=ws_config.id)

        if config.discovery.ctn_dir_globs:
            self._discovery = WorkspaceDiscovery(self._registry, config.discovery)
            self._discovery.scan()

        LOGGER.info("workspace_manager_started", workspaces=len(self._handles))

    async def astart(self) -> None:
        """Async start: register workspaces, optionally prefetch default, start reaper."""
        self._loop = asyncio.get_running_loop()
        self.start()
        config = self._registry.load()

        for ws_id, handle in self._handles.items():
            handle.semaphore = asyncio.Semaphore(self._concurrency.per_workspace_inflight_limit)

        if self._residency.prefetch_default_workspace and config.server.default_workspace:
            default_ws = config.server.default_workspace
            if default_ws in self._handles:
                await self.mount(default_ws)

        if self._cross_repo.enabled and self._cross_repo.background_warmup:
            try:
                from batho.bridge.cross import warmup_cross_index

                pinned = [h for h in self._handles.values() if h.is_pinned]
                if pinned:
                    asyncio.create_task(warmup_cross_index(self, pinned))
            except Exception as exc:
                LOGGER.warning("cross_index_warmup_failed", error=str(exc))

        self._global_semaphore = asyncio.Semaphore(self._concurrency.global_inflight_limit)
        self._reaper_task = asyncio.create_task(self._reaper_loop())
        self._ready = True

    async def stop(self) -> None:
        """Stop the manager and unmount all workspaces."""
        self._running = False
        if self._reaper_task:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass

        with self._handles_lock:
            for ws_id in list(self._handles.keys()):
                await self.unmount(ws_id, reason="manager_stopped")

        if self._discovery:
            self._discovery.stop_watcher()

        LOGGER.info("workspace_manager_stopped")

    async def mount(self, workspace_id: str) -> WorkspaceHandle:
        """Mount a workspace, opening SQLite and initializing resources."""
        async with self._global_semaphore:
            with self._handles_lock:
                if workspace_id not in self._handles:
                    raise KeyError(f"Workspace not found: {workspace_id}")
                handle = self._handles[workspace_id]

            if handle.is_ready:
                handle.mark_used()
                return handle

            if handle.state == WorkspaceState.MOUNTING:
                with self._mount_futures_lock:
                    future = self._mount_futures.get(workspace_id)
                if future:
                    return await future

            async with handle.semaphore:
                with self._handles_lock:
                    if handle.is_ready:
                        handle.mark_used()
                        return handle
                    if handle.state == WorkspaceState.MOUNTING:
                        with self._mount_futures_lock:
                            future = self._mount_futures.get(workspace_id)
                        if future:
                            return await future

                    handle.state = WorkspaceState.MOUNTING
                    handle.mount_attempts += 1

                try:
                    await self._do_mount(handle)
                    handle.state = WorkspaceState.READY
                    handle.last_error = None
                    handle.mark_used()
                    self._enforce_lru()
                    LOGGER.info("workspace_mounted", workspace_id=workspace_id)
                except Exception as exc:
                    handle.state = WorkspaceState.FAILED
                    handle.last_error = str(exc)
                    backoff = self._get_backoff(handle.mount_attempts)
                    LOGGER.warning(
                        "workspace_mount_failed",
                        workspace_id=workspace_id,
                        error=str(exc),
                        backoff=backoff,
                    )
                    raise
                finally:
                    with self._mount_futures_lock:
                        self._mount_futures.pop(workspace_id, None)

                return handle

    async def _do_mount(self, handle: WorkspaceHandle) -> None:
        """Perform the actual mount operations."""
        ctn_dir = handle.ctn_dir
        if not ctn_dir.exists():
            raise FileNotFoundError(f"CTN directory not found: {ctn_dir}")

        db_path = ctn_dir / "artifact_registry.sqlite3"
        if db_path.exists():
            handle.pool = ConnectionPool(db_path)

        handle.bridge = ArtifactRegistryBridge(ctn_dir, pool=handle.pool)
        handle.loader = ArtifactLoader(ctn_dir)

    def _get_backoff(self, attempts: int) -> float:
        """Get backoff delay for retry attempts."""
        idx = min(attempts - 1, len(MOUNT_BACKOFF_SECONDS) - 1)
        return MOUNT_BACKOFF_SECONDS[idx]

    def _enforce_lru(self) -> None:
        """Evict least recently used non-pinned workspaces if over limit."""
        with self._handles_lock:
            ready_handles = [
                h for h in self._handles.values()
                if h.is_ready and not h.is_pinned and h.workspace_id not in self._evicting
            ]
            ready_handles.sort(key=lambda h: h.last_used_at)

            excess = len(ready_handles) - self._residency.max_resident_workspaces
            if excess > 0:
                to_evict = ready_handles[:excess]
                for handle in to_evict:
                    asyncio.create_task(self._safe_unmount(handle.workspace_id, "lru_eviction"))

    async def _safe_unmount(self, workspace_id: str, reason: str) -> None:
        """Wrapper around unmount that cleans up evicting state."""
        self._evicting.add(workspace_id)
        try:
            await self.unmount(workspace_id, reason=reason)
        finally:
            self._evicting.discard(workspace_id)

    async def unmount(self, workspace_id: str, *, reason: str) -> None:
        """Unmount a workspace, releasing resources."""
        with self._handles_lock:
            if workspace_id not in self._handles:
                return
            handle = self._handles[workspace_id]

            if handle.state in (WorkspaceState.UNMOUNTING, WorkspaceState.REGISTERED):
                return

            handle.state = WorkspaceState.UNMOUNTING

        try:
            if handle.pool:
                handle.pool.close()
                handle.pool = None

            self._cache.invalidate_workspace(workspace_id)
            if self._cross_index:
                self._cross_index.invalidate_workspace(workspace_id)

            with self._handles_lock:
                handle.state = WorkspaceState.REGISTERED

            LOGGER.info("workspace_unmounted", workspace_id=workspace_id, reason=reason)
        except Exception as exc:
            LOGGER.error("workspace_unmount_failed", workspace_id=workspace_id, error=str(exc))
            with self._handles_lock:
                handle.state = WorkspaceState.FAILED

    async def resolve(self, workspace_id: str | None) -> WorkspaceHandle:
        """Resolve a workspace handle, mounting if necessary."""
        if workspace_id is None:
            config = self._registry.load()
            workspace_id = config.server.default_workspace

        if not workspace_id:
            raise ValueError("No workspace_id provided and no default workspace configured")

        with self._handles_lock:
            if workspace_id not in self._handles:
                raise KeyError(f"Workspace not found: {workspace_id}")
            handle = self._handles[workspace_id]

        if handle.is_ready:
            handle.mark_used()
            return handle

        if handle.state in (WorkspaceState.REGISTERED, WorkspaceState.EVICTED):
            return await self.mount(workspace_id)

        if handle.state == WorkspaceState.FAILED:
            if handle.mount_attempts >= len(MOUNT_BACKOFF_SECONDS):
                raise RuntimeError(f"Workspace {workspace_id} in failed state: {handle.last_error}")
            return await self.mount(workspace_id)

        if handle.state in (WorkspaceState.MOUNTING, WorkspaceState.UNMOUNTING):
            with self._mount_futures_lock:
                future = self._mount_futures.get(workspace_id)
            if future:
                return await future
            await asyncio.sleep(0.1)
            return await self.resolve(workspace_id)

        return handle

    def list(self) -> list[WorkspaceConfig]:
        """List all registered workspaces."""
        with self._handles_lock:
            return [h.config for h in self._handles.values()]

    def get_handle(self, workspace_id: str) -> WorkspaceHandle | None:
        """Return a handle without forcing a mount."""
        with self._handles_lock:
            return self._handles.get(workspace_id)

    def resident(self) -> list[WorkspaceHandle]:
        """List all currently mounted (ready) workspaces."""
        with self._handles_lock:
            return [h for h in self._handles.values() if h.is_ready]

    async def apply_diff(self, diff: HubConfigDiff) -> None:
        """Apply a configuration diff."""
        unmount_tasks = []

        for ws_id in diff.removed:
            unmount_tasks.append(self.unmount(ws_id, reason="config_removed"))

        for ws_config in diff.updated:
            with self._handles_lock:
                if ws_config.id in self._handles:
                    old_handle = self._handles[ws_config.id]
                    if old_handle.config.ctn_dir != ws_config.ctn_dir:
                        unmount_tasks.append(self.unmount(ws_config.id, reason="ctn_dir_changed"))

        if unmount_tasks:
            await asyncio.gather(*unmount_tasks, return_exceptions=True)

        with self._handles_lock:
            for ws_id in diff.removed:
                self._handles.pop(ws_id, None)
                if self._cross_index:
                    self._cross_index.invalidate_workspace(ws_id)

            for ws_config in diff.added:
                self._handles[ws_config.id] = WorkspaceHandle(
                    config=ws_config,
                    state=WorkspaceState.REGISTERED,
                )
                LOGGER.info("workspace_added", workspace_id=ws_config.id)

            for ws_config in diff.updated:
                if ws_config.id in self._handles:
                    self._handles[ws_config.id].config = ws_config

    async def health_check(self, workspace_id: str | None = None) -> list[WorkspaceHealth]:
        """Check health of all or specific workspace."""
        results = []
        workspace_ids = [workspace_id] if workspace_id else list(self._handles.keys())

        for ws_id in workspace_ids:
            with self._handles_lock:
                if ws_id not in self._handles:
                    continue
                handle = self._handles[ws_id]

            ctn_exists = handle.ctn_dir.exists()
            registry_enabled = handle.bridge.enabled if handle.bridge else False
            artifact_count = 0
            last_index_id = None

            if handle.bridge and handle.is_ready:
                try:
                    artifact_count = handle.bridge.stats().artifact_count
                    idx = handle.bridge.get_latest_index()
                    last_index_id = idx.index_id if idx else None
                except Exception:
                    pass

            ok = handle.is_ready or (handle.is_degraded and ctn_exists)

            results.append(WorkspaceHealth(
                id=ws_id,
                state=handle.state.value,
                ok=ok,
                ctn_exists=ctn_exists,
                registry_enabled=registry_enabled,
                last_index_id=last_index_id,
                artifact_count=artifact_count,
                resident=handle.is_ready,
                last_used_at=str(handle.last_used_at),
                cache_bytes=handle.cache_bytes,
                inflight=handle.inflight,
                last_error=handle.last_error,
                checked_at=str(time.time()),
            ))

        return results

    async def refresh(self, workspace_id: str) -> None:
        """Invalidate caches for a workspace."""
        self._cache.invalidate_workspace(workspace_id)
        if self._cross_index:
            self._cross_index.invalidate_workspace(workspace_id)
        LOGGER.info("workspace_cache_invalidated", workspace_id=workspace_id)

    async def _reaper_loop(self) -> None:
        """Background task to evict idle workspaces."""
        while self._running:
            await asyncio.sleep(60)
            if not self._running:
                break

            now = time.time()
            with self._handles_lock:
                for handle in self._handles.values():
                    if handle.is_pinned or not handle.is_ready:
                        continue
                    if handle.inflight > 0:
                        continue
                    if now - handle.last_used_at > self._residency.idle_evict_seconds:
                        asyncio.create_task(
                            self.unmount(handle.workspace_id, reason="idle_eviction")
                        )


__all__ = [
    "WorkspaceManager",
]
