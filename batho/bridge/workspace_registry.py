"""Workspace registry with config loading, atomic writes, and hot reload."""

from __future__ import annotations

import fcntl
import os
import re
import threading
from pathlib import Path
from typing import Callable

import yaml

from batho.bridge.constants import (
    DEFAULT_USER_CONFIG_PATH,
    PROJECT_CONFIG_FILENAME,
    WORKSPACE_ID_REGEX,
)
from batho.bridge.models import HubConfig, HubConfigDiff, WorkspaceConfig
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge.registry")

_workspace_id_pattern = re.compile(WORKSPACE_ID_REGEX)


class WorkspaceRegistry:
    """Manages hub configuration with atomic writes and hot reload."""

    def __init__(
        self,
        user_config_path: str | Path | None = None,
        project_config_path: Path | None = None,
    ):
        self._user_config_path = Path(
            os.path.expanduser(user_config_path or DEFAULT_USER_CONFIG_PATH)
        ).resolve()
        self._project_config_path = project_config_path
        self._lock = threading.RLock()
        self._config: HubConfig | None = None
        self._watchers: list[Callable[[HubConfigDiff], None]] = []
        self._file_watcher = None

    @property
    def user_config_path(self) -> Path:
        return self._user_config_path

    @property
    def project_config_path(self) -> Path | None:
        return self._project_config_path

    def load(self) -> HubConfig:
        """Load configuration from user and project config files."""
        with self._lock:
            user_config = self._load_user_config()
            project_config = self._load_project_config()
            self._config = self._merge_configs(user_config, project_config)
            self._validate_config(self._config)
            return self._config

    def _load_user_config(self) -> HubConfig:
        """Load user-level configuration."""
        if not self._user_config_path.exists():
            return HubConfig()
        try:
            data = yaml.safe_load(self._user_config_path.read_text(encoding="utf-8"))
            if data is None:
                return HubConfig()
            return HubConfig.model_validate(data)
        except (yaml.YAMLError, ValueError) as exc:
            LOGGER.warning("user_config_load_failed", path=str(self._user_config_path), error=str(exc))
            return HubConfig()

    def _load_project_config(self) -> HubConfig | None:
        """Load project-level configuration if present."""
        if not self._project_config_path or not self._project_config_path.exists():
            return None
        try:
            data = yaml.safe_load(self._project_config_path.read_text(encoding="utf-8"))
            if data is None:
                return None
            return HubConfig.model_validate(data)
        except (yaml.YAMLError, ValueError) as exc:
            LOGGER.warning("project_config_load_failed", path=str(self._project_config_path), error=str(exc))
            return None

    def _merge_configs(self, user: HubConfig, project: HubConfig | None) -> HubConfig:
        """Merge project config on top of user config."""
        if project is None:
            return user
        merged = user.model_copy(deep=True)
        merged.server = project.server
        merged.residency = project.residency
        merged.concurrency = project.concurrency
        merged.discovery = project.discovery
        merged.cross_repo = project.cross_repo
        if project.workspaces:
            merged.workspaces = project.workspaces
        return merged

    def _validate_config(self, config: HubConfig) -> None:
        """Validate configuration values."""
        ids = set()
        for ws in config.workspaces:
            if not _workspace_id_pattern.match(ws.id):
                raise ValueError(f"Invalid workspace ID: {ws.id!r} (must match {WORKSPACE_ID_REGEX})")
            if ws.id in ids:
                raise ValueError(f"Duplicate workspace ID: {ws.id}")
            ids.add(ws.id)
            ctn_dir = Path(ws.ctn_dir)
            if not ctn_dir.exists():
                LOGGER.warning("ctn_dir_not_found", workspace_id=ws.id, ctn_dir=ws.ctn_dir)
            elif not (ctn_dir / "index.json").exists() and not (ctn_dir / "artifact_registry.sqlite3").exists():
                LOGGER.warning("ctn_dir_invalid", workspace_id=ws.id, ctn_dir=ws.ctn_dir)
        if config.residency.max_resident_workspaces < 1 or config.residency.max_resident_workspaces > 4096:
            raise ValueError("max_resident_workspaces must be between 1 and 4096")

    def save(self, config: HubConfig) -> None:
        """Atomically write configuration to user config file."""
        lock_path = self._user_config_path.with_suffix(".yaml.lock")
        with self._lock:
            self._validate_config(config)
            with open(lock_path, "w") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    tmp_path = self._user_config_path.with_suffix(".yaml.tmp")
                    content = yaml.dump(config.model_dump(exclude_none=True), default_flow_style=False, sort_keys=False)
                    tmp_path.write_text(content, encoding="utf-8")
                    with open(tmp_path, "r") as f:
                        os.fsync(f.fileno())
                    os.replace(tmp_path, self._user_config_path)
                    with open(self._user_config_path, "r") as f:
                        os.fsync(f.fileno())
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            self._config = config

    def add(self, workspace: WorkspaceConfig) -> HubConfig:
        """Add a workspace to the configuration."""
        if self._config is None:
            self.load()
        if any(ws.id == workspace.id for ws in self._config.workspaces):
            raise ValueError(f"Workspace already exists: {workspace.id}")
        self._config.workspaces.append(workspace)
        self.save(self._config)
        return self._config

    def remove(self, workspace_id: str) -> HubConfig:
        """Remove a workspace from the configuration."""
        if self._config is None:
            self.load()
        self._config.workspaces = [ws for ws in self._config.workspaces if ws.id != workspace_id]
        self.save(self._config)
        return self._config

    def update(self, workspace_id: str, **patch: object) -> HubConfig:
        """Update a workspace's configuration."""
        if self._config is None:
            self.load()
        for ws in self._config.workspaces:
            if ws.id == workspace_id:
                for key, value in patch.items():
                    if hasattr(ws, key):
                        setattr(ws, key, value)
                break
        else:
            raise ValueError(f"Workspace not found: {workspace_id}")
        self.save(self._config)
        return self._config

    def get(self, workspace_id: str) -> WorkspaceConfig | None:
        """Get a workspace by ID."""
        if self._config is None:
            self.load()
        for ws in self._config.workspaces:
            if ws.id == workspace_id:
                return ws
        return None

    def list(self) -> list[WorkspaceConfig]:
        """List all workspaces."""
        if self._config is None:
            self.load()
        return list(self._config.workspaces)

    def replace(self, config: HubConfig) -> None:
        """Replace the entire configuration."""
        self.save(config)

    def watch(self, callback: Callable[[HubConfigDiff], None]) -> "Watcher":
        """Register a callback for configuration changes."""
        self._watchers.append(callback)
        return Watcher(self, callback)

    def _notify_watchers(self, diff: HubConfigDiff) -> None:
        """Notify all registered watchers of a configuration change."""
        for callback in self._watchers:
            try:
                callback(diff)
            except Exception as exc:
                LOGGER.error("watcher_callback_failed", error=str(exc))

    def compute_diff(self, old_config: HubConfig, new_config: HubConfig) -> HubConfigDiff:
        """Compute the diff between two configurations."""
        old_ids = {ws.id for ws in old_config.workspaces}
        new_ids = {ws.id for ws in new_config.workspaces}

        added = [ws for ws in new_config.workspaces if ws.id not in old_ids]
        removed = list(old_ids - new_ids)
        updated = [
            ws for ws in new_config.workspaces
            if ws.id in old_ids and ws != next(old_ws for old_ws in old_config.workspaces if old_ws.id == ws.id)
        ]

        return HubConfigDiff(
            added=added,
            removed=removed,
            updated=updated,
            server_changed=old_config.server != new_config.server,
            residency_changed=old_config.residency != new_config.residency,
            discovery_changed=old_config.discovery != new_config.discovery,
        )

    def start_watcher(self) -> None:
        """Start watching for configuration file changes."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            LOGGER.warning("watchdog_not_installed")
            return

        class ConfigFileHandler(FileSystemEventHandler):
            def __init__(inner_self, registry: WorkspaceRegistry):
                inner_self.registry = registry
                inner_self._last_mtime = 0

            def on_modified(inner_self, event):
                if event.is_directory:
                    return
                if event.src_path != str(registry._user_config_path):
                    return
                try:
                    current_mtime = registry._user_config_path.stat().st_mtime
                    if current_mtime == inner_self._last_mtime:
                        return
                    inner_self._last_mtime = current_mtime
                    old_config = registry._config
                    new_config = registry.load()
                    if old_config:
                        diff = registry.compute_diff(old_config, new_config)
                        if diff.added or diff.removed or diff.updated:
                            registry._notify_watchers(diff)
                except Exception as exc:
                    LOGGER.error("config_watch_failed", error=str(exc))

        self._file_watcher = Observer()
        self._file_watcher.schedule(
            ConfigFileHandler(self),
            str(self._user_config_path.parent),
            recursive=False,
        )
        self._file_watcher.start()
        LOGGER.info("config_watcher_started", path=str(self._user_config_path))

    def stop_watcher(self) -> None:
        """Stop watching for configuration file changes."""
        if self._file_watcher:
            self._file_watcher.stop()
            self._file_watcher.join()
            self._file_watcher = None


class Watcher:
    """Handle for a registered configuration watcher."""

    def __init__(self, registry: WorkspaceRegistry, callback: Callable[[HubConfigDiff], None]):
        self._registry = registry
        self._callback = callback

    def close(self) -> None:
        """Unregister the watcher."""
        if self._callback in self._registry._watchers:
            self._registry._watchers.remove(self._callback)


__all__ = [
    "WorkspaceRegistry",
    "Watcher",
]
