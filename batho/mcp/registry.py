"""Batho MCP Repo Registry — JSON-based registry of repos for multi-repo MCP mode.

Manages ~/.batho/mcp-repos.json which maps repo names to filesystem paths.
The MCP server reads this registry to create one BathoBundleReader per repo.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import structlog

LOGGER = structlog.get_logger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".batho" / "mcp-repos.json"


@dataclass
class RepoEntry:
    """A single registered repository."""

    name: str
    path: str
    watch: bool = False
    debounce_ms: int = 2000
    max_file_size_kb: int | None = None
    last_synced: str | None = None  # ISO 8601 timestamp
    sync_state: str = "idle"  # idle | pending | patching | error

    @property
    def artifact_dir(self) -> Path:
        return Path(self.path).resolve() / ".batho" / "artifact"


class RepoRegistry:
    """Manages a JSON registry of Batho repos at ~/.batho/mcp-repos.json."""

    VALID_SYNC_STATES = {"idle", "pending", "patching", "error"}

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._lock = threading.Lock()

    @staticmethod
    def _clamp_debounce_ms(val: Any) -> int:
        try:
            val_int = int(val)
            return max(100, min(60000, val_int))
        except (ValueError, TypeError):
            return 2000

    def load(self) -> list[RepoEntry]:
        """Load entries from the JSON config file. Returns empty list if file doesn't exist."""
        if not self.config_path.exists():
            return []
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            LOGGER.warning("registry_load_error", path=str(self.config_path), error=str(exc))
            return []
        
        repos = data.get("repos", []) if isinstance(data, dict) else []
        entries: list[RepoEntry] = []
        for r in repos:
            if not isinstance(r, dict) or "name" not in r or "path" not in r:
                continue
            name = str(r["name"])
            path = str(r["path"])
            watch = bool(r.get("watch", False))
            debounce_ms = self._clamp_debounce_ms(r.get("debounce_ms", 2000))
            max_file_size_kb = r.get("max_file_size_kb")
            if max_file_size_kb is not None:
                try:
                    max_file_size_kb = int(max_file_size_kb)
                except (ValueError, TypeError):
                    max_file_size_kb = None
            last_synced = str(r["last_synced"]) if r.get("last_synced") is not None else None
            sync_state = str(r.get("sync_state", "idle"))
            if sync_state not in self.VALID_SYNC_STATES:
                sync_state = "idle"
            entries.append(
                RepoEntry(
                    name=name,
                    path=path,
                    watch=watch,
                    debounce_ms=debounce_ms,
                    max_file_size_kb=max_file_size_kb,
                    last_synced=last_synced,
                    sync_state=sync_state,
                )
            )
        return entries

    def save(self, entries: list[RepoEntry]) -> None:
        """Write entries to the JSON config file atomically. Creates parent dirs if needed."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 2, "repos": [asdict(e) for e in entries]}
        fd, tmp_path = tempfile.mkstemp(dir=self.config_path.parent, prefix="mcp-repos.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=2))
            os.replace(tmp_path, str(self.config_path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def add(
        self,
        name: str,
        path: str,
        watch: bool = False,
        debounce_ms: int = 2000,
        max_file_size_kb: int | None = None,
    ) -> RepoEntry:
        """Add or update a repo entry. Returns the entry."""
        with self._lock:
            entries = self.load()
            resolved = str(Path(path).resolve())
            clamped_debounce = self._clamp_debounce_ms(debounce_ms)
            entry = RepoEntry(
                name=name,
                path=resolved,
                watch=watch,
                debounce_ms=clamped_debounce,
                max_file_size_kb=max_file_size_kb,
            )
            # Upsert: replace if name exists, otherwise append
            entries = [e for e in entries if e.name != name]
            entries.append(entry)
            self.save(entries)
            LOGGER.info("registry_add", name=name, path=resolved, watch=watch, debounce_ms=clamped_debounce)
            return entry

    def update_sync_state(
        self,
        name: str,
        sync_state: str,
        last_synced: str | None = None,
    ) -> RepoEntry | None:
        """Update only the sync state and last_synced fields for a repo entry."""
        if sync_state not in self.VALID_SYNC_STATES:
            sync_state = "idle"
        with self._lock:
            entries = self.load()
            target_entry: RepoEntry | None = None
            for e in entries:
                if e.name == name:
                    e.sync_state = sync_state
                    if last_synced is not None:
                        e.last_synced = last_synced
                    target_entry = e
                    break
            if target_entry:
                self.save(entries)
                LOGGER.debug("registry_update_sync_state", name=name, sync_state=sync_state, last_synced=last_synced)
            return target_entry

    def remove(self, name: str) -> bool:
        """Remove a repo entry by name. Returns True if removed, False if not found."""
        with self._lock:
            entries = self.load()
            filtered = [e for e in entries if e.name != name]
            if len(filtered) == len(entries):
                return False
            self.save(filtered)
            LOGGER.info("registry_remove", name=name)
            return True

    def get(self, name: str) -> RepoEntry | None:
        """Look up a repo entry by name."""
        for entry in self.load():
            if entry.name == name:
                return entry
        return None

    def list_all(self) -> list[RepoEntry]:
        """Return all registered repo entries."""
        return self.load()

    @staticmethod
    def has_artifact(entry: RepoEntry) -> bool:
        """Check if the repo has a .batho/artifact/ directory."""
        return entry.artifact_dir.exists()

