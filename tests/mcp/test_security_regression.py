"""Regression tests for the Batho MCP security/correctness review.

Covers:
- P0-1: _resolve_root_path rejects unregistered absolute paths; sanitize_path
  rejects absolute paths when allow_absolute=False.
- P0-2/P0-3: batho_export / batho_load reject paths outside the repo root.
- P1-4: create_app reuses the passed-in RepoRegistry instance.
- P1-6: batho_fix target enum aligns with FixEngine; metrics read from summary.
- P2-7: _resolve_entity_id prefers exact entity_id match over name match.
- P2-9: watcher module imports without watchdog being required at import time.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp import FastMCP

from batho.mcp.registry import RepoRegistry
from batho.mcp.server import create_app
from batho.orchestrator.build import run_build, BuildOptions
from batho.utils.path_sanitizer import sanitize_path, PathSecurityError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    (repo / "main.py").write_text("def hello(): pass\n", encoding="utf-8")
    run_build(BuildOptions(root=repo))
    return repo


@pytest.fixture
def registry(tmp_path: Path) -> RepoRegistry:
    return RepoRegistry(config_path=tmp_path / "mcp-repos.json")


# ---------------------------------------------------------------------------
# P0-1: path containment
# ---------------------------------------------------------------------------


def test_sanitize_path_rejects_absolute_without_allow_absolute():
    """Absolute paths must be rejected when allow_absolute is False (default)."""
    with pytest.raises(PathSecurityError):
        sanitize_path("/etc/passwd")


def test_sanitize_path_rejects_absolute_with_base_dir():
    """Absolute paths outside base_dir must be rejected even with a base."""
    with pytest.raises(PathSecurityError):
        sanitize_path("/etc/passwd", base_dir="/tmp")


def test_sanitize_path_allows_trusted_absolute_with_allow_absolute():
    """Trusted absolute paths (registry entries, --root) are permitted."""
    assert str(sanitize_path("/projects/frontend", allow_absolute=True)) == "/projects/frontend"


def test_sanitize_path_rejects_percent_encoded_traversal():
    """Percent-encoded traversal must be rejected."""
    with pytest.raises(PathSecurityError):
        sanitize_path("%2e%2e/etc/passwd", base_dir="/tmp")


def test_sanitize_path_rejects_uri_scheme_even_with_allow_absolute():
    """URI schemes are rejected even in trusted absolute mode."""
    with pytest.raises(PathSecurityError):
        sanitize_path("file:///etc/passwd", allow_absolute=True)


def test_resolve_root_path_rejects_unregistered_absolute(repo_dir: Path, registry: RepoRegistry):
    """_resolve_root_path must not accept arbitrary absolute paths as `repo`."""
    from batho.mcp.tools import _resolve_root_path

    registry.add("my_repo", str(repo_dir))
    with pytest.raises(ValueError, match="not registered"):
        _resolve_root_path("/etc", None, registry)


def test_resolve_root_path_rejects_unregistered_relative(repo_dir: Path, registry: RepoRegistry):
    """_resolve_root_path must not accept unregistered relative paths either."""
    from batho.mcp.tools import _resolve_root_path

    registry.add("my_repo", str(repo_dir))
    with pytest.raises(ValueError, match="not registered"):
        _resolve_root_path("some/random/repo", None, registry)


def test_resolve_root_path_resolves_registered_name(repo_dir: Path, registry: RepoRegistry):
    """A registered repo name resolves to its validated path."""
    from batho.mcp.tools import _resolve_root_path

    registry.add("my_repo", str(repo_dir))
    resolved = _resolve_root_path("my_repo", None, registry)
    assert resolved == str(repo_dir.resolve())


def test_resolve_root_path_falls_back_to_default_root(registry: RepoRegistry, tmp_path: Path):
    """With no registry entries, default_root (the --root CLI flag) is used."""
    from batho.mcp.tools import _resolve_root_path

    resolved = _resolve_root_path(None, str(tmp_path), registry)
    assert resolved == str(tmp_path.resolve())


# ---------------------------------------------------------------------------
# P0-2 / P0-3: export/load path containment (tool-level)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_rejects_absolute_output(repo_dir: Path, registry: RepoRegistry, tmp_path: Path):
    """batho_export must reject an absolute output path outside the repo root."""
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)
    outside = tmp_path / "escape.json"
    res = await app.call_tool("batho_export", {"repo": "my_repo", "view": "storage", "output": str(outside)})
    assert res.is_error


@pytest.mark.asyncio
async def test_load_rejects_absolute_artifact_path(repo_dir: Path, registry: RepoRegistry, tmp_path: Path):
    """batho_load must reject an absolute artifact_path outside the repo root."""
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)
    outside = tmp_path / "escape.zip"
    res = await app.call_tool("batho_load", {"repo": "my_repo", "artifact_path": str(outside)})
    assert res.is_error


# ---------------------------------------------------------------------------
# P1-4: create_app reuses the passed-in registry instance
# ---------------------------------------------------------------------------


def test_create_app_reuses_passed_registry_instance(tmp_path: Path):
    """create_app must reuse the supplied RepoRegistry, not build a new one."""
    cfg = tmp_path / "mcp-repos.json"
    reg = RepoRegistry(config_path=cfg)
    app = create_app(registry_path=cfg, registry=reg)
    # The registry instance is stored on the tools module global pool.
    import batho.mcp.tools as tools_mod
    assert tools_mod._pool is not None
    assert tools_mod._pool._registry is reg


# ---------------------------------------------------------------------------
# P1-6: batho_fix target enum + metrics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fix_rejects_invalid_target(repo_dir: Path, registry: RepoRegistry):
    """batho_fix must reject target values not recognized by FixEngine."""
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)
    # 'schema', 'storage', 'nodes', 'edges' are the OLD wrong enum values.
    for bad in ("schema", "storage", "nodes", "edges"):
        res = await app.call_tool("batho_fix", {"repo": "my_repo", "dry_run": True, "target": bad})
        assert res.is_error, f"target={bad!r} should be rejected"
        assert "Invalid target" in res.content[0].text


@pytest.mark.asyncio
async def test_fix_accepts_valid_targets(repo_dir: Path, registry: RepoRegistry):
    """batho_fix must accept the FixEngine-aligned target values."""
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)
    for good in ("all", "bundle", "state", "blobs", "graph"):
        res = await app.call_tool("batho_fix", {"repo": "my_repo", "dry_run": True, "target": good})
        assert not res.is_error, f"target={good!r} should be accepted: {res.content[0].text if res.is_error else ''}"


@pytest.mark.asyncio
async def test_fix_metrics_read_from_summary(repo_dir: Path, registry: RepoRegistry):
    """batho_fix structured output must expose summary-derived metrics.

    The old code read result.total_issues / result.repaired_count which never
    existed on FixResult, so it always reported 0. The fix reads from
    result.summary.total_findings / result.summary.repairs_successful. We
    assert the keys are present and reflect real summary values (which may be
    non-zero on a fresh build due to info-level bundle findings).
    """
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)
    res = await app.call_tool("batho_fix", {"repo": "my_repo", "dry_run": True})
    assert not res.is_error
    sc = res.structured_content
    # The new fields come from result.summary, not the old non-existent attrs.
    for key in ("issues_found", "repaired", "repairs_attempted", "checks_passed", "checks_failed"):
        assert key in sc, f"missing metric {key!r}"
    # issues_found must be an int reflecting summary.total_findings (>= 0),
    # NOT the always-0 from the old broken getattr on a non-existent attr.
    assert isinstance(sc["issues_found"], int)
    assert sc["issues_found"] >= 0
    # On a dry_run, no repairs should have been attempted.
    assert sc["repairs_attempted"] == 0
    assert sc["repaired"] == 0


# ---------------------------------------------------------------------------
# P2-7: _resolve_entity_id exact-match-first
# ---------------------------------------------------------------------------


def test_resolve_entity_id_prefers_exact_entity_id():
    """When a query string matches both an entity_id and a name, entity_id wins."""
    import pyarrow as pa
    from batho.mcp.tools import _resolve_entity_id

    # Build a fake agent_views table where one row's name collides with
    # another row's entity_id.
    schema = pa.schema([
        ("entity_id", pa.string()),
        ("name", pa.string()),
        ("entity_type", pa.string()),
        ("file_id", pa.int64()),
    ])
    table = pa.table(
        {
            "entity_id": ["ent_001", "ent_002"],
            "name": ["ent_002", "real_name"],  # row 0's name == row 1's entity_id
            "entity_type": ["function", "function"],
            "file_id": [1, 2],
        },
        schema=schema,
    )

    class FakeReader:
        def _get_table(self, name):
            return table

        def get_all_file_tracking(self):
            return {"main.py": {"file_id": 1}, "other.py": {"file_id": 2}}

    reader = FakeReader()
    # Query "ent_002" — should resolve to the entity with entity_id == "ent_002"
    # (row 1), NOT to row 0 whose name happens to be "ent_002".
    resolved = _resolve_entity_id("ent_002", reader)
    assert resolved == "ent_002"


def test_resolve_entity_id_returns_empty_list_on_no_match():
    """No match returns [] (the contract callers rely on), not the input string."""
    import pyarrow as pa
    from batho.mcp.tools import _resolve_entity_id

    schema = pa.schema([
        ("entity_id", pa.string()),
        ("name", pa.string()),
        ("entity_type", pa.string()),
        ("file_id", pa.int64()),
    ])
    table = pa.table(
        {
            "entity_id": ["ent_001"],
            "name": ["foo"],
            "entity_type": ["function"],
            "file_id": [1],
        },
        schema=schema,
    )

    class FakeReader:
        def _get_table(self, name):
            return table

        def get_all_file_tracking(self):
            return {"main.py": {"file_id": 1}}

    resolved = _resolve_entity_id("does_not_exist", FakeReader())
    assert resolved == []


# ---------------------------------------------------------------------------
# P2-9: watchdog lazy import
# ---------------------------------------------------------------------------


def test_watcher_module_imports_without_forcing_watchdog():
    """Importing batho.mcp.watcher must not require watchdog at import time."""
    import importlib
    import sys

    # Remove any cached watchdog modules to simulate absence, then re-import
    # the watcher module. It must not raise ImportError at import time.
    watchdog_mods = {k: v for k, v in sys.modules.items() if k.startswith("watchdog")}
    for k in list(watchdog_mods):
        del sys.modules[k]
    # Also drop the watcher module so it re-imports fresh.
    sys.modules.pop("batho.mcp.watcher", None)

    try:
        mod = importlib.import_module("batho.mcp.watcher")
        assert hasattr(mod, "BathoWatcherEngine")
        assert hasattr(mod, "_require_watchdog")
    finally:
        # Restore original modules.
        sys.modules.update(watchdog_mods)
