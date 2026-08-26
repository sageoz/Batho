"""Tests for RepoRegistry v2 schema."""

import json
from pathlib import Path

from batho.mcp.registry import RepoRegistry, RepoEntry


def test_load_v1_schema_defaults(tmp_path: Path):
    cfg = tmp_path / "mcp-repos.json"
    # Write v1 schema without watch/debounce/sync_state
    v1_content = {
        "repos": [
            {"name": "repo1", "path": "/path/to/repo1"}
        ]
    }
    cfg.write_text(json.dumps(v1_content), encoding="utf-8")

    reg = RepoRegistry(config_path=cfg)
    entries = reg.load()
    assert len(entries) == 1
    e = entries[0]
    assert e.name == "repo1"
    assert e.path == "/path/to/repo1"
    assert e.watch is False
    assert e.debounce_ms == 2000
    assert e.sync_state == "idle"
    assert e.last_synced is None


def test_save_writes_current_schema_version(tmp_path: Path):
    cfg = tmp_path / "mcp-repos.json"
    reg = RepoRegistry(config_path=cfg)
    reg.add("repo2", "/path/to/repo2", watch=True, debounce_ms=1500)

    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data.get("version") == 3
    r = data["repos"][0]
    assert r["name"] == "repo2"
    assert r["watch"] is True
    assert r["debounce_ms"] == 1500
    assert r["sync_state"] == "idle"


def test_add_with_watch_flag(tmp_path: Path):
    cfg = tmp_path / "mcp-repos.json"
    reg = RepoRegistry(config_path=cfg)
    entry = reg.add("repo3", "/path/to/repo3", watch=True, debounce_ms=3000, max_file_size_kb=500)
    assert entry.watch is True
    assert entry.debounce_ms == 3000
    assert entry.max_file_size_kb == 500

    loaded = reg.get("repo3")
    assert loaded is not None
    assert loaded.watch is True
    assert loaded.max_file_size_kb == 500


def test_update_sync_state(tmp_path: Path):
    cfg = tmp_path / "mcp-repos.json"
    reg = RepoRegistry(config_path=cfg)
    reg.add("repo4", "/path/to/repo4")

    updated = reg.update_sync_state("repo4", "patching", last_synced="2026-08-12T00:00:00Z")
    assert updated is not None
    assert updated.sync_state == "patching"
    assert updated.last_synced == "2026-08-12T00:00:00Z"

    reloaded = reg.get("repo4")
    assert reloaded.sync_state == "patching"
    assert reloaded.last_synced == "2026-08-12T00:00:00Z"


def test_debounce_clamping(tmp_path: Path):
    cfg = tmp_path / "mcp-repos.json"
    reg = RepoRegistry(config_path=cfg)
    e1 = reg.add("repo_low", "/path/low", debounce_ms=10)
    assert e1.debounce_ms == 100

    e2 = reg.add("repo_high", "/path/high", debounce_ms=100000)
    assert e2.debounce_ms == 60000
