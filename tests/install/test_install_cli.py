"""Tests for batho.cli.install — single-command surface (skills + MCP)."""

from __future__ import annotations

from pathlib import Path

import pytest

import batho.install as skills_mod
import batho.install.fetch as fetch_mod
from batho_cli import _build_parser


def test_install_registered_with_flags() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        [
            "install",
            "--agent",
            "cursor",
            "--all",
            "--project",
            "--version",
            "1.2.0",
            "--copy",
            "--force",
            "--no-mcp",
        ]
    )
    assert args.command == "install"
    assert args.agent == ["cursor"]
    assert args.all and args.project and args.copy and args.force
    assert args.version == "1.2.0"
    assert args.no_mcp


def test_no_subcommands_remain() -> None:
    """The install surface is exactly one command — `skill`/`update`/
    `mcp install` subcommands are gone."""
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["install", "skill"])
    with pytest.raises(SystemExit):
        parser.parse_args(["install", "skill", "update"])
    with pytest.raises(SystemExit):
        parser.parse_args(["mcp", "install"])


def test_install_error_returns_nonzero(
    isolated_home: Path, empty_path: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    def _boom(*a, **k):
        raise skills_mod.SkillsError("offline")

    monkeypatch.setattr(skills_mod, "fetch_pack", _boom)
    args = _ns()
    from batho.cli.install import cmd_install

    assert cmd_install(args) == 1
    assert "offline" in capsys.readouterr().err


def test_install_up_to_date_skips_refetch(
    isolated_home: Path, empty_path: Path, monkeypatch, capsys
) -> None:
    """Receipt version == upstream latest → no re-download; MCP still runs."""
    from batho.install.receipt import write_receipt

    write_receipt("v2.0.0", "global", [])
    monkeypatch.setattr(fetch_mod, "resolve_latest_version", lambda *a, **k: "v2.0.0")

    def _no_install(*a, **k):
        raise AssertionError("install_pack ran despite an up-to-date receipt")

    monkeypatch.setattr(skills_mod, "install_pack", _no_install)
    from batho.cli.install import cmd_install

    assert cmd_install(_ns()) == 0
    out = capsys.readouterr()
    assert "already up to date (v2.0.0)" in out.out
    assert "no coding-agent client detected" in out.out


def test_install_honors_version_pin(isolated_home: Path, empty_path: Path, monkeypatch, capsys) -> None:
    """SKL-02 mirror: with BATHO_VERSION pinned, `batho install` reports
    up-to-date at the PINNED tag — the upstream latest is never consulted."""
    from batho.install.receipt import write_receipt

    write_receipt("v1.0.0", "global", [])
    monkeypatch.setenv("BATHO_VERSION", "v1.0.0")

    def _no_network(*a, **k):
        raise AssertionError("latest-tag lookup ran despite the pin")

    monkeypatch.setattr(fetch_mod, "resolve_latest_version", _no_network)
    from batho.cli.install import cmd_install

    assert cmd_install(_ns()) == 0
    assert "up to date (v1.0.0)" in capsys.readouterr().out


def test_install_drifted_pack_refetches_with_force(
    isolated_home: Path, empty_path: Path, monkeypatch, capsys
) -> None:
    """Re-running `batho install` after an upstream release is the update path."""
    from batho.install.install import InstallResult
    from batho.install.receipt import write_receipt

    write_receipt("v1.0.0", "global", [])
    monkeypatch.setattr(fetch_mod, "resolve_latest_version", lambda *a, **k: "v2.0.0")
    calls: dict = {}

    def _fake_install(*a, **k):
        calls.update(k)
        return InstallResult(version="v2.0.0", scope="global", records=[], receipt_path=None)

    monkeypatch.setattr(skills_mod, "install_pack", _fake_install)
    from batho.cli.install import cmd_install

    assert cmd_install(_ns()) == 0
    assert calls.get("force") is True
    assert calls.get("scope") == "global"
    assert "updated to v2.0.0" in capsys.readouterr().out


def test_install_no_mcp_flag_skips_registration(
    isolated_home: Path, empty_path: Path, monkeypatch, capsys
) -> None:
    from batho.install.receipt import write_receipt

    write_receipt("v2.0.0", "global", [])
    monkeypatch.setattr(fetch_mod, "resolve_latest_version", lambda *a, **k: "v2.0.0")

    def _no_mcp(*a, **k):
        raise AssertionError("MCP registration ran despite --no-mcp")

    monkeypatch.setattr("batho.install.mcp_config.install_mcp_config", _no_mcp)
    from batho.cli.install import cmd_install

    assert cmd_install(_ns(no_mcp=True)) == 0


def test_install_unsupported_agent_warns_but_installs_skills(
    isolated_home: Path, empty_path: Path, monkeypatch, capsys
) -> None:
    """`--agent roo` (skills-only agent) installs skills, warns for MCP."""
    from batho.install.install import InstallResult
    from batho.install.receipt import write_receipt

    write_receipt("v2.0.0", "global", [])
    monkeypatch.setattr(fetch_mod, "resolve_latest_version", lambda *a, **k: "v2.0.0")
    monkeypatch.setattr(
        skills_mod,
        "install_pack",
        lambda *a, **k: InstallResult(version="v2.0.0", scope="global", records=[], receipt_path=None),
    )
    from batho.cli.install import cmd_install

    assert cmd_install(_ns(agent=["roo"])) == 0
    out = capsys.readouterr().out
    assert "no MCP support for roo" in out


def _ns(**overrides):
    """A fully-populated install Namespace (matches the parser's defaults)."""
    defaults = dict(
        command="install",
        agent=[],
        all=False,
        project=False,
        version=None,
        copy=False,
        force=False,
        no_mcp=False,
    )
    defaults.update(overrides)
    import argparse

    return argparse.Namespace(**defaults)
