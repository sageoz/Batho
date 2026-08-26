"""Tests for RepoRegistry v3 schema (dashboard fields)."""

import json
from pathlib import Path

from batho.mcp.registry import RepoEntry, RepoRegistry


def _write_v2_fixture(path: Path) -> None:
    """Write a v2-schema registry file (no dashboard fields)."""
    v2_content = {
        "version": 2,
        "repos": [
            {
                "name": "legacy-repo",
                "path": "/path/to/legacy",
                "watch": True,
                "debounce_ms": 3000,
                "max_file_size_kb": 500,
                "last_synced": "2026-08-01T00:00:00Z",
                "sync_state": "pending",
            }
        ],
    }
    path.write_text(json.dumps(v2_content), encoding="utf-8")


def _write_v3_fixture(path: Path) -> None:
    """Write a v3-schema registry file with all dashboard fields."""
    v3_content = {
        "version": 3,
        "repos": [
            {
                "name": "modern-repo",
                "path": "/path/to/modern",
                "watch": False,
                "debounce_ms": 2000,
                "max_file_size_kb": None,
                "last_synced": None,
                "sync_state": "idle",
                "id": "abc123",
                "mode": "github",
                "branch": "main",
                "status": "ready",
                "last_built_at": "2026-08-10T12:00:00Z",
                "created_at": "2026-08-01T09:00:00Z",
            }
        ],
    }
    path.write_text(json.dumps(v3_content), encoding="utf-8")


class TestV2ToV3Migration:
    def test_v2_entries_get_v3_defaults(self, tmp_path: Path):
        cfg = tmp_path / "mcp-repos.json"
        _write_v2_fixture(cfg)

        reg = RepoRegistry(config_path=cfg)
        entries = reg.load()
        assert len(entries) == 1
        e = entries[0]
        # Existing v2 fields preserved
        assert e.name == "legacy-repo"
        assert e.watch is True
        assert e.debounce_ms == 3000
        assert e.max_file_size_kb == 500
        assert e.last_synced == "2026-08-01T00:00:00Z"
        assert e.sync_state == "pending"
        # v3 fields are genuinely migrated: id + created_at are generated
        assert len(e.id) == 32  # uuid4 hex
        assert e.created_at != ""
        assert e.mode == "local"
        assert e.branch is None
        # No artifact on disk for the fixture path → not indexed
        assert e.status == "not_indexed"
        assert e.last_built_at is None

    def test_v2_migration_persisted_immediately(self, tmp_path: Path):
        """Migration is written back on first load so ids are stable."""
        cfg = tmp_path / "mcp-repos.json"
        _write_v2_fixture(cfg)

        reg = RepoRegistry(config_path=cfg)
        first = reg.load()[0]

        data = json.loads(cfg.read_text(encoding="utf-8"))
        assert data["version"] == 3
        assert data["repos"][0]["id"] == first.id

        # Second load returns the SAME id (not regenerated)
        second = reg.load()[0]
        assert second.id == first.id
        assert second.created_at == first.created_at

    def test_v2_with_artifact_migrates_to_ready(self, tmp_path: Path):
        """Legacy repos with .batho/artifact/ derive status=ready."""
        repo_dir = tmp_path / "myrepo"
        artifact = repo_dir / ".batho" / "artifact"
        artifact.mkdir(parents=True)
        # Populate a minimal meta.json so the fixture reflects a real artifact
        # bundle, not just an empty directory. This guards against regressions
        # if has_artifact() is later tightened to validate artifact contents.
        (artifact / "meta.json").write_text(
            json.dumps({"version": 1, "tables": {}}), encoding="utf-8"
        )
        cfg = tmp_path / "mcp-repos.json"
        cfg.write_text(
            json.dumps(
                {
                    "version": 2,
                    "repos": [{"name": "built-repo", "path": str(repo_dir), "watch": False}],
                }
            ),
            encoding="utf-8",
        )

        reg = RepoRegistry(config_path=cfg)
        e = reg.load()[0]
        assert e.status == "ready"
        assert e.last_built_at is not None
        assert len(e.id) == 32

    def test_v2_resaved_as_v3_on_mutation(self, tmp_path: Path):
        cfg = tmp_path / "mcp-repos.json"
        _write_v2_fixture(cfg)

        reg = RepoRegistry(config_path=cfg)
        reg.update_sync_state("legacy-repo", "idle")

        data = json.loads(cfg.read_text(encoding="utf-8"))
        assert data["version"] == 3
        r = data["repos"][0]
        assert len(r["id"]) == 32
        assert r["mode"] == "local"
        assert r["status"] == "not_indexed"


class TestV3RoundTrip:
    def test_v3_roundtrip(self, tmp_path: Path):
        cfg = tmp_path / "mcp-repos.json"
        _write_v3_fixture(cfg)

        reg = RepoRegistry(config_path=cfg)
        entries = reg.load()
        assert len(entries) == 1
        e = entries[0]
        assert e.id == "abc123"
        assert e.mode == "github"
        assert e.branch == "main"
        assert e.status == "ready"
        assert e.last_built_at == "2026-08-10T12:00:00Z"
        assert e.created_at == "2026-08-01T09:00:00Z"

        # Mutate and re-save, then verify persistence
        reg.update_status("modern-repo", "stale")
        reloaded = reg.get("modern-repo")
        assert reloaded is not None
        assert reloaded.status == "stale"
        assert reloaded.id == "abc123"
        assert reloaded.mode == "github"

    def test_invalid_status_and_mode_fall_back(self, tmp_path: Path):
        cfg = tmp_path / "mcp-repos.json"
        content = {
            "version": 3,
            "repos": [
                {
                    "name": "bad",
                    "path": "/x",
                    "status": "bogus",
                    "mode": "gitlab",
                }
            ],
        }
        cfg.write_text(json.dumps(content), encoding="utf-8")
        reg = RepoRegistry(config_path=cfg)
        e = reg.get("bad")
        assert e is not None
        assert e.status == "not_indexed"
        assert e.mode == "local"


class TestAddGeneratesV3Fields:
    def test_add_generates_uuid_and_timestamp(self, tmp_path: Path):
        cfg = tmp_path / "mcp-repos.json"
        reg = RepoRegistry(config_path=cfg)
        entry = reg.add("newrepo", "/path/to/newrepo")
        assert entry.id != ""
        assert len(entry.id) == 32  # uuid4 hex
        assert entry.created_at != ""
        assert entry.status == "not_indexed"
        assert entry.mode == "local"

        loaded = reg.get("newrepo")
        assert loaded is not None
        assert loaded.id == entry.id
        assert loaded.created_at == entry.created_at

    def test_add_with_artifact_marks_ready(self, tmp_path: Path):
        """add() reflects on-disk artifact state so pre-built repos do not
        briefly misreport as not_indexed."""
        repo_dir = tmp_path / "builtrepo"
        artifact = repo_dir / ".batho" / "artifact"
        artifact.mkdir(parents=True)
        (artifact / "meta.json").write_text(
            json.dumps({"version": 1, "tables": {}}), encoding="utf-8"
        )
        cfg = tmp_path / "mcp-repos.json"
        reg = RepoRegistry(config_path=cfg)
        entry = reg.add("builtrepo", str(repo_dir))
        assert entry.status == "ready"
        assert entry.last_built_at is not None

        loaded = reg.get("builtrepo")
        assert loaded is not None
        assert loaded.status == "ready"
        assert loaded.last_built_at is not None

    def test_add_without_artifact_stays_not_indexed(self, tmp_path: Path):
        cfg = tmp_path / "mcp-repos.json"
        reg = RepoRegistry(config_path=cfg)
        entry = reg.add("emptyrepo", str(tmp_path / "emptyrepo"))
        assert entry.status == "not_indexed"
        assert entry.last_built_at is None


class TestGetById:
    def test_get_by_id_found(self, tmp_path: Path):
        cfg = tmp_path / "mcp-repos.json"
        reg = RepoRegistry(config_path=cfg)
        entry = reg.add("repo-a", "/path/a")
        other = reg.add("repo-b", "/path/b")

        found = reg.get_by_id(other.id)
        assert found is not None
        assert found.name == "repo-b"
        assert found.id == other.id

        assert reg.get_by_id(entry.id) is not None

    def test_get_by_id_not_found(self, tmp_path: Path):
        cfg = tmp_path / "mcp-repos.json"
        reg = RepoRegistry(config_path=cfg)
        reg.add("repo", "/path")
        assert reg.get_by_id("nonexistent") is None


class TestUpdateStatus:
    def test_update_status_persists(self, tmp_path: Path):
        cfg = tmp_path / "mcp-repos.json"
        reg = RepoRegistry(config_path=cfg)
        reg.add("repo", "/path")

        updated = reg.update_status("repo", "indexing")
        assert updated is not None
        assert updated.status == "indexing"

        reloaded = reg.get("repo")
        assert reloaded is not None
        assert reloaded.status == "indexing"

    def test_update_status_with_last_built_at(self, tmp_path: Path):
        cfg = tmp_path / "mcp-repos.json"
        reg = RepoRegistry(config_path=cfg)
        reg.add("repo", "/path")

        updated = reg.update_status("repo", "ready", last_built_at="2026-08-15T10:00:00Z")
        assert updated is not None
        assert updated.status == "ready"
        assert updated.last_built_at == "2026-08-15T10:00:00Z"

        reloaded = reg.get("repo")
        assert reloaded is not None
        assert reloaded.last_built_at == "2026-08-15T10:00:00Z"

    def test_update_status_nonexistent_returns_none(self, tmp_path: Path):
        cfg = tmp_path / "mcp-repos.json"
        reg = RepoRegistry(config_path=cfg)
        assert reg.update_status("ghost", "ready") is None

    def test_update_status_invalid_status_becomes_error(self, tmp_path: Path):
        cfg = tmp_path / "mcp-repos.json"
        reg = RepoRegistry(config_path=cfg)
        reg.add("repo", "/path")
        updated = reg.update_status("repo", "bogus")
        assert updated is not None
        assert updated.status == "error"


class TestBackwardCompat:
    def test_repo_entry_dataclass_defaults(self):
        entry = RepoEntry(name="x", path="/y")
        assert entry.id == ""
        assert entry.mode == "local"
        assert entry.branch is None
        assert entry.status == "not_indexed"
        assert entry.last_built_at is None
        assert entry.created_at == ""

    def test_artifact_dir_still_works(self, tmp_path: Path):
        entry = RepoEntry(name="x", path=str(tmp_path))
        assert entry.artifact_dir == tmp_path.resolve() / ".batho" / "artifact"
