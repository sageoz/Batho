"""Workspace discovery for glob-based bulk workspace detection."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterator

from batho.bridge.constants import WORKSPACE_ID_REGEX
from batho.bridge.models import DiscoveryConfig, HubConfigDiff, WorkspaceConfig
from batho.bridge.workspace_registry import WorkspaceRegistry
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge.discovery")

_workspace_id_pattern = re.compile(WORKSPACE_ID_REGEX)


def _slugify(name: str) -> str:
    """Convert a directory name to a valid workspace ID."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    if not slug:
        slug = "workspace"
    if not _workspace_id_pattern.match(slug):
        slug = "workspace-" + slug
    return slug[:63]


def _generate_unique_id(base_id: str, existing_ids: set[str]) -> str:
    """Generate a unique workspace ID by appending a suffix if needed."""
    if base_id not in existing_ids:
        return base_id
    counter = 2
    while f"{base_id}-{counter}" in existing_ids:
        counter += 1
    return f"{base_id}-{counter}"


def _find_ctn_directories(globs: list[str]) -> Iterator[Path]:
    """Find all artifact_*.batho databases matching the given globs."""
    for glob_pattern in globs:
        expanded = os.path.expanduser(glob_pattern)
        for match in Path(".").glob(expanded) if Path(".").exists() else []:
            if match.is_file() and match.name.startswith("artifact_") and match.name.endswith(".batho"):
                yield match.parent
            elif match.is_dir():
                if any(match.glob("artifact_*.batho")):
                    yield match


def _is_valid_ctn_directory(ctn_dir: Path) -> bool:
    """Check if a directory has a valid artifact_*.batho database."""
    return any(ctn_dir.glob("artifact_*.batho"))


def _matches_ignore_pattern(workspace_id: str, ignore_patterns: list[str]) -> bool:
    """Check if a workspace ID matches any ignore pattern."""
    for pattern in ignore_patterns:
        regex_pattern = pattern.replace("*", ".*").replace("?", ".")
        if re.match(f"^{regex_pattern}$", workspace_id):
            return True
    return False


class WorkspaceDiscovery:
    """Discovers workspaces from filesystem globs."""

    def __init__(self, registry: WorkspaceRegistry, config: DiscoveryConfig):
        self._registry = registry
        self._config = config

    def scan(self) -> HubConfigDiff:
        """Scan filesystem for .batho databases and update registry."""
        existing = {ws.id: ws for ws in self._registry.list()}
        discovered: dict[str, WorkspaceConfig] = {}

        for ctn_dir in _find_ctn_directories(self._config.ctn_dir_globs):
            parent_name = ctn_dir.parent.name
            base_id = _slugify(parent_name)
            workspace_id = _generate_unique_id(base_id, set(existing.keys()) | set(discovered.keys()))

            if _matches_ignore_pattern(workspace_id, self._config.ignore_ids):
                LOGGER.info("workspace_ignored", workspace_id=workspace_id, ctn_dir=str(ctn_dir))
                continue

            if not _is_valid_ctn_directory(ctn_dir):
                LOGGER.warning("invalid_ctn_directory", ctn_dir=str(ctn_dir))
                continue

            workspace = WorkspaceConfig(
                id=workspace_id,
                label=parent_name,
                ctn_dir=str(ctn_dir.resolve()),
                enabled=True,
                pinned=False,
                tags=["auto-discovered"],
                read_only=True,
                source="auto-discovered",
            )
            discovered[workspace_id] = workspace
            LOGGER.info("workspace_discovered", workspace_id=workspace_id, ctn_dir=str(ctn_dir))

        added: list[WorkspaceConfig] = []
        updated: list[WorkspaceConfig] = []
        removed: list[str] = []

        for ws_id, ws in discovered.items():
            if ws_id not in existing:
                added.append(ws)
                self._registry.add(ws)
            elif existing[ws_id].source != "manual":
                existing_ws = existing[ws_id]
                if existing_ws.ctn_dir != ws.ctn_dir or existing_ws.label != ws.label:
                    updated.append(ws)
                    self._registry.update(ws_id, ctn_dir=ws.ctn_dir, label=ws.label)

        existing_ids = set(existing.keys())
        discovered_ids = set(discovered.keys())
        for ws_id in existing_ids - discovered_ids:
            ws = existing[ws_id]
            if ws.source == "auto-discovered" and not ws.enabled:
                continue
            if ws.source == "auto-discovered":
                removed.append(ws_id)
                self._registry.update(ws_id, enabled=False)

        return HubConfigDiff(
            added=added,
            removed=removed,
            updated=updated,
            discovery_changed=True,
        )

    def start_watcher(self) -> None:
        """Start watching filesystem for changes (requires discovery.watch=true)."""
        if not self._config.watch:
            LOGGER.info("filesystem_watch_disabled")
            return

        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            LOGGER.warning("watchdog_not_installed")
            return

        class CtnDirHandler(FileSystemEventHandler):
            def __init__(inner_self, discovery: WorkspaceDiscovery):
                inner_self.discovery = discovery
                inner_self._pending_scan = False

            def on_any_event(inner_self, event):
                filename = Path(event.src_path).name
                if filename.startswith("artifact_") and ".batho" in filename:
                    if not inner_self._pending_scan:
                        inner_self._pending_scan = True
                        LOGGER.info("batho_db_changed", path=event.src_path)

        self._file_watcher = Observer()
        for glob_pattern in self._config.ctn_dir_globs:
            expanded = os.path.expanduser(glob_pattern)
            base_dir = Path(expanded).parent
            if base_dir.exists():
                self._file_watcher.schedule(CtnDirHandler(self), str(base_dir), recursive=True)
        self._file_watcher.start()
        LOGGER.info("discovery_watcher_started")

    def stop_watcher(self) -> None:
        """Stop watching filesystem for changes."""
        if hasattr(self, "_file_watcher") and self._file_watcher:
            self._file_watcher.stop()
            self._file_watcher.join()


__all__ = [
    "WorkspaceDiscovery",
]
