"""Batho MCP Repo Registry — JSON-based registry of repos for multi-repo MCP mode.

Manages ~/.batho/mcp-repos.json which maps repo names to filesystem paths.
The MCP server reads this registry to create one BathoBundleReader per repo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import structlog

LOGGER = structlog.get_logger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".batho" / "mcp-repos.json"


@dataclass
class RepoEntry:
    """A single registered repository."""

    name: str
    path: str

    @property
    def artifact_dir(self) -> Path:
        return Path(self.path).resolve() / ".batho" / "artifact"


class RepoRegistry:
    """Manages a JSON registry of Batho repos at ~/.batho/mcp-repos.json."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

    def load(self) -> list[RepoEntry]:
        """Load entries from the JSON config file. Returns empty list if file doesn't exist."""
        if not self.config_path.exists():
            return []
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            LOGGER.warning("registry_load_error", path=str(self.config_path), error=str(exc))
            return []
        repos = data.get("repos", [])
        return [RepoEntry(name=r["name"], path=r["path"]) for r in repos if "name" in r and "path" in r]

    def save(self, entries: list[RepoEntry]) -> None:
        """Write entries to the JSON config file. Creates parent dirs if needed."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"repos": [asdict(e) for e in entries]}
        self.config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def add(self, name: str, path: str) -> RepoEntry:
        """Add or update a repo entry. Returns the entry."""
        entries = self.load()
        resolved = str(Path(path).resolve())
        entry = RepoEntry(name=name, path=resolved)
        # Upsert: replace if name exists, otherwise append
        entries = [e for e in entries if e.name != name]
        entries.append(entry)
        self.save(entries)
        LOGGER.info("registry_add", name=name, path=resolved)
        return entry

    def remove(self, name: str) -> bool:
        """Remove a repo entry by name. Returns True if removed, False if not found."""
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
