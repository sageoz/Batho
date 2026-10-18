"""Tests for batho.install.mcp_config — per-client MCP config registration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from batho.install import mcp_config
from batho.install.mcp_config import (
    McpConfigError,
    install_mcp_config,
    server_argv,
)


@pytest.fixture
def pinned_argv(monkeypatch):
    """Pin the server argv so merge tests are deterministic."""
    argv = ["/usr/local/bin/batho", "mcp"]
    monkeypatch.setattr(mcp_config, "server_argv", lambda: argv)
    return argv


# --- server argv -------------------------------------------------------------


def test_server_argv_prefers_batho_on_path(isolated_home, tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "batho"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{tmp_path / 'nothing'}")
    argv = server_argv()
    assert argv[0] == str(fake)
    assert argv[1:] == ["mcp"]


def test_server_argv_falls_back_to_module(isolated_home, empty_path):
    argv = server_argv()
    assert argv[1:3] == ["-m", "batho_cli"]
    assert argv[3] == "mcp"


# --- target resolution -------------------------------------------------------


def test_compute_targets_detects_via_detect_markers(isolated_home, empty_path):
    (isolated_home / ".cursor").mkdir()
    targets = mcp_config.compute_mcp_targets()
    ids = {t.agent_id for t in targets}
    assert "cursor" in ids
    assert "claude-desktop" not in ids


def test_claude_code_not_detected_without_markers(isolated_home, empty_path):
    # Regression: ~/.claude.json's parent ($HOME) always exists — detection
    # must rely on detect markers, not config-parent existence.
    targets = mcp_config.compute_mcp_targets()
    assert "claude-code" not in {t.agent_id for t in targets}


def test_compute_targets_forced_agent(isolated_home, empty_path):
    targets = mcp_config.compute_mcp_targets(agents=["codex"])
    assert [t.agent_id for t in targets] == ["codex"]
    assert targets[0].config_path == isolated_home / ".codex" / "config.toml"
    assert targets[0].fmt == "toml"


def test_compute_targets_unknown_agent_raises(isolated_home):
    with pytest.raises(ValueError, match="unknown agent"):
        mcp_config.compute_mcp_targets(agents=["not-an-agent"])


def test_compute_targets_writes_all_live_config_paths(isolated_home, empty_path):
    # Windsurf documents two live locations — both detect dirs exist → both written.
    (isolated_home / ".codeium/windsurf").mkdir(parents=True)
    (isolated_home / ".config/devin").mkdir(parents=True)
    targets = mcp_config.compute_mcp_targets(agents=["windsurf"])
    assert len(targets) == 2
    assert {t.config_path.parent.name for t in targets} == {"windsurf", "devin"}


def test_vscode_target_uses_servers_key(isolated_home, empty_path):
    targets = mcp_config.compute_mcp_targets(agents=["vscode"])
    assert targets[0].key == "servers"


def test_opencode_target_uses_command_array(isolated_home, empty_path):
    targets = mcp_config.compute_mcp_targets(agents=["opencode"])
    assert targets[0].entry_shape == "command_array"
    assert targets[0].key == "mcp"


# --- JSON merge ---------------------------------------------------------------


def test_merge_json_fresh_install(isolated_home, empty_path, pinned_argv):
    (isolated_home / ".cursor").mkdir()
    targets = mcp_config.compute_mcp_targets(agents=["cursor"])
    status = mcp_config._write_target(targets[0])
    assert status == "installed"
    data = json.loads((isolated_home / ".cursor" / "mcp.json").read_text())
    assert data["mcpServers"]["batho"] == {
        "command": "/usr/local/bin/batho",
        "args": ["mcp"],
    }


def test_merge_json_preserves_existing_content(isolated_home, empty_path, pinned_argv):
    path = isolated_home / ".cursor" / "mcp.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "other": {"command": "uvx", "args": ["something"]},
                    "batho": {"command": "/old/batho", "args": ["mcp", "--old"]},
                },
                "unrelated": {"keep": True},
            }
        )
    )
    targets = mcp_config.compute_mcp_targets(agents=["cursor"])
    status = mcp_config._write_target(targets[0])
    assert status == "updated"
    data = json.loads(path.read_text())
    assert data["mcpServers"]["other"] == {"command": "uvx", "args": ["something"]}
    assert data["unrelated"] == {"keep": True}
    assert data["mcpServers"]["batho"]["args"] == ["mcp"]


def test_merge_json_corrupt_file_raises(isolated_home, empty_path, pinned_argv):
    (isolated_home / ".cursor").mkdir()
    (isolated_home / ".cursor/mcp.json").write_text("{corrupt")
    targets = mcp_config.compute_mcp_targets(agents=["cursor"])
    with pytest.raises(McpConfigError, match="not valid JSON"):
        mcp_config._write_target(targets[0])


def test_merge_json_non_object_servers_raises(isolated_home, empty_path, pinned_argv):
    path = isolated_home / ".cursor" / "mcp.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": ["not", "an", "object"]}))
    targets = mcp_config.compute_mcp_targets(agents=["cursor"])
    with pytest.raises(McpConfigError, match="not an object"):
        mcp_config._write_target(targets[0])


# --- TOML merge (codex) --------------------------------------------------------


def test_merge_toml_fresh_appends_table(isolated_home, empty_path, pinned_argv):
    path = isolated_home / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text('model = "gpt-5"\n\n[other_section]\nkey = "value"\n')
    targets = mcp_config.compute_mcp_targets(agents=["codex"])
    status = mcp_config._write_target(targets[0])
    assert status == "installed"
    text = path.read_text()
    assert "[mcp_servers.batho]" in text
    assert 'command = "/usr/local/bin/batho"' in text
    assert 'args = ["mcp"]' in text
    assert "[other_section]" in text


def test_merge_toml_replaces_only_batho_table(isolated_home, empty_path, pinned_argv):
    path = isolated_home / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "[mcp_servers.batho]\n"
        'command = "/old/batho"\n'
        'args = ["mcp", "--stale"]\n'
        "\n"
        "[mcp_servers.other]\n"
        'command = "npx"\n'
        "\n"
        "[profile.x]\n"
        'k = "v"\n'
    )
    targets = mcp_config.compute_mcp_targets(agents=["codex"])
    status = mcp_config._write_target(targets[0])
    assert status == "updated"
    text = path.read_text()
    assert "/old/batho" not in text
    assert "[mcp_servers.other]" in text and 'command = "npx"' in text
    assert "[profile.x]" in text
    assert text.count("[mcp_servers.batho]") == 1


# --- end-to-end -----------------------------------------------------------------


def test_install_mcp_config_end_to_end(isolated_home, empty_path, pinned_argv):
    (isolated_home / ".cursor").mkdir()
    (isolated_home / ".gemini").mkdir()
    records = install_mcp_config()
    by_agent = {r.agent_id: r for r in records}
    assert set(by_agent) == {"cursor", "gemini"}
    assert all(r.status == "installed" for r in records)
    entry = json.loads((isolated_home / ".cursor/mcp.json").read_text())["mcpServers"]["batho"]
    assert entry == {"command": "/usr/local/bin/batho", "args": ["mcp"]}


def test_install_mcp_config_idempotent(isolated_home, empty_path, pinned_argv):
    (isolated_home / ".cursor").mkdir()
    first = install_mcp_config()
    second = install_mcp_config()
    assert [r.status for r in first] == ["installed"]
    assert [r.status for r in second] == ["updated"]


def test_install_mcp_config_no_tmp_leftovers(isolated_home, empty_path, pinned_argv):
    (isolated_home / ".cursor").mkdir()
    install_mcp_config()
    assert list((isolated_home / ".cursor").glob(".*tmp*")) == []


def test_one_broken_config_does_not_block_others(isolated_home, empty_path, pinned_argv):
    (isolated_home / ".cursor").mkdir()
    (isolated_home / ".gemini").mkdir()
    (isolated_home / ".cursor/mcp.json").write_text("{corrupt")
    records = install_mcp_config()
    by_agent = {r.agent_id: r for r in records}
    assert by_agent["cursor"].status.startswith("error(")
    assert by_agent["gemini"].status == "installed"


def test_all_agents_flag_writes_every_supported_client(isolated_home, empty_path, pinned_argv):
    records = install_mcp_config(all_agents=True)
    agents = {r.agent_id for r in records}
    assert {
        "claude-desktop", "claude-code", "cursor", "windsurf",
        "vscode", "codex", "gemini", "opencode", "copilot",
    } <= agents
    assert len(records) >= 10  # windsurf contributes two config paths
