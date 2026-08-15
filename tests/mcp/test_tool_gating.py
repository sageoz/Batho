"""Tests for config-based MCP tool gating (allow/block lists).

Verifies the tiered tool exposure model:
- Tier 1 (13 read-only/diagnostic tools): always exposed by default
- Tier 2 (batho_patch, batho_fix): exposed with destructiveHint=True
- Tier 3 (batho_build, batho_export, batho_load, batho_gc): disabled by default,
  opt-in via config/env/CLI

Scenarios:
    1. Default config disables 4 Tier-3 tools → 15 tools registered.
    2. disabled_tools=set() → all 19 tools registered.
    3. Allowlist mode → only listed tools registered.
    4. Env var override (BATHO_MCP_TOOLS_DISABLED) disables tools.
    5. Calling an unregistered tool raises an error.
    6. CLI --enable-tool flag removes a tool from the disabled set.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from batho.mcp.server import create_app


# -----------------------------------------------------------------------
# Default config: 4 Tier-3 tools disabled → 15 tools
# -----------------------------------------------------------------------

DEFAULT_EXPECTED_TOOLS = {
    # Tier 1 — read-only (13)
    "list_repos", "add_repo", "remove_repo",
    "graph_overview", "graph_query", "get_entity", "trace_path",
    "get_file_graph", "search_entities", "get_delta",
    "batho_status", "batho_list_runs", "batho_diff",
    # Tier 2 — destructive but enabled (2)
    "batho_patch", "batho_fix",
}

DEFAULT_DISABLED_TOOLS = {"batho_build", "batho_export", "batho_load", "batho_gc"}

ALL_19_TOOLS = DEFAULT_EXPECTED_TOOLS | DEFAULT_DISABLED_TOOLS


@pytest.mark.asyncio
async def test_default_disables_tier3():
    """Default config disables 4 Tier-3 tools → 15 tools registered."""
    app = create_app(disabled_tools={"batho_build", "batho_export", "batho_load", "batho_gc"})
    tools = await app.list_tools()
    names = {t.name for t in tools}
    assert len(names) == 15
    assert names == DEFAULT_EXPECTED_TOOLS
    for disabled in DEFAULT_DISABLED_TOOLS:
        assert disabled not in names


@pytest.mark.asyncio
async def test_all_tools_when_disabled_empty():
    """When disabled_tools=set(), all 19 tools registered."""
    app = create_app(disabled_tools=set())
    tools = await app.list_tools()
    names = {t.name for t in tools}
    assert len(names) == 19
    assert names == ALL_19_TOOLS


# -----------------------------------------------------------------------
# Allowlist mode
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_allowlist_only_registers_listed():
    """enabled_tools set → only those tools registered."""
    allowlist = {"list_repos", "graph_overview", "search_entities"}
    app = create_app(enabled_tools=allowlist)
    tools = await app.list_tools()
    names = {t.name for t in tools}
    assert names == allowlist


@pytest.mark.asyncio
async def test_allowlist_empty_registers_nothing():
    """enabled_tools=set() → no tools registered."""
    app = create_app(enabled_tools=set())
    tools = await app.list_tools()
    assert len(tools) == 0


# -----------------------------------------------------------------------
# Blocklist mode
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_blocklist_removes_specified_tools():
    """disabled_tools set removes only those tools."""
    app = create_app(disabled_tools={"batho_patch", "graph_overview"})
    tools = await app.list_tools()
    names = {t.name for t in tools}
    assert "batho_patch" not in names
    assert "graph_overview" not in names
    assert "list_repos" in names
    assert "batho_fix" in names
    assert len(names) == 17


# -----------------------------------------------------------------------
# Env var override
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_env_override_disables_tool(monkeypatch, tmp_path: Path):
    """BATHO_MCP_TOOLS_DISABLED env var disables tools via config loading."""
    monkeypatch.setenv("BATHO_MCP_TOOLS_DISABLED", "batho_patch,batho_fix")
    # create_app with no explicit filter loads from config (which reads env)
    app = create_app(root=str(tmp_path.resolve()))
    tools = await app.list_tools()
    names = {t.name for t in tools}
    assert "batho_patch" not in names
    assert "batho_fix" not in names
    assert "graph_overview" in names


@pytest.mark.asyncio
async def test_env_override_empty_string_enables_all(monkeypatch, tmp_path: Path):
    """BATHO_MCP_TOOLS_DISABLED='' → empty disabled list → all 19 tools."""
    monkeypatch.setenv("BATHO_MCP_TOOLS_DISABLED", "")
    app = create_app(root=str(tmp_path.resolve()))
    tools = await app.list_tools()
    names = {t.name for t in tools}
    assert len(names) == 19
    assert "batho_build" in names


@pytest.mark.asyncio
async def test_env_override_allowlist(monkeypatch, tmp_path: Path):
    """BATHO_MCP_TOOLS_ENABLED env var sets allowlist."""
    monkeypatch.setenv("BATHO_MCP_TOOLS_ENABLED", "list_repos,graph_overview")
    app = create_app(root=str(tmp_path.resolve()))
    tools = await app.list_tools()
    names = {t.name for t in tools}
    assert names == {"list_repos", "graph_overview"}


# -----------------------------------------------------------------------
# Calling unregistered tools
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calling_unregistered_tool_raises():
    """Calling a disabled tool raises an error (not silently ignored)."""
    app = create_app(disabled_tools={"batho_build"})
    with pytest.raises(Exception):
        await app.call_tool("batho_build", {"repo": "x"})


# -----------------------------------------------------------------------
# Secure-by-default
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_secure_by_default_no_args(tmp_path: Path):
    """create_app() with no args applies secure-by-default (4 Tier-3 disabled).

    This uses the real config system. In the test environment, there's no
    batho.yaml, so the Config() defaults apply — which disable Tier-3 tools.
    """
    root = str(tmp_path.resolve())
    app = create_app(root=root)
    tools = await app.list_tools()
    names = {t.name for t in tools}
    # Tier-3 should be disabled by default
    assert "batho_build" not in names
    assert "batho_export" not in names
    assert "batho_load" not in names
    assert "batho_gc" not in names
    # Tier 1 + Tier 2 should be present
    assert "batho_patch" in names
    assert "graph_overview" in names
    assert len(names) == 15
