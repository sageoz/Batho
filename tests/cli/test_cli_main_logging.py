from __future__ import annotations

import pytest

import batho_cli as batho


def _base_logging_config(**overrides):
    payload = {
        "level": "INFO",
        "json_format": None,
        "quiet": False,
        "file": None,
        "format": "%(message)s",
    }
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def _reset_cli_output_state():
    batho.CLI_OUTPUT.configure(quiet=False, json_mode=False)
    batho._RUNTIME_LOGGING_INITIALIZED = False
    yield
    batho.CLI_OUTPUT.configure(quiet=False, json_mode=False)
    batho._RUNTIME_LOGGING_INITIALIZED = False


def test_main_uses_config_logging_defaults(monkeypatch):
    import logging

    captured = {}

    monkeypatch.setattr(
        batho,
        "get_config_cached_for_root",
        lambda root: {"logging": _base_logging_config(level=logging.WARNING, json_format=False)},
    )
    monkeypatch.setattr(batho, "configure_logging", lambda cfg: captured.setdefault("cfg", cfg))
    monkeypatch.setattr(batho, "cmd_stats", lambda _args: 0)

    result = batho.main(["stats", "--root", "/tmp/repo"])

    assert result == 0
    assert captured["cfg"]["level"] == logging.WARNING
    assert captured["cfg"]["json_format"] is False
    assert captured["cfg"]["quiet"] is False
    assert captured["cfg"]["file"] is None


def test_main_cli_logging_flags_override_config(monkeypatch):
    import logging

    captured = {}

    monkeypatch.setattr(
        batho,
        "get_config_cached_for_root",
        lambda root: {"logging": _base_logging_config(level=logging.INFO, json_format=False)},
    )
    monkeypatch.setattr(batho, "configure_logging", lambda cfg: captured.setdefault("cfg", cfg))
    monkeypatch.setattr(batho, "cmd_stats", lambda _args: 0)

    result = batho.main(
        [
            "--log-level",
            "DEBUG",
            "--quiet",
            "--log-json",
            "--log-file",
            "logs/run.log",
            "stats",
            "--root",
            "/tmp/repo",
        ]
    )

    assert result == 0
    assert captured["cfg"]["level"] == "DEBUG"
    assert captured["cfg"]["json_format"] is True
    assert captured["cfg"]["quiet"] is True
    assert captured["cfg"]["file"] == "logs/run.log"


def test_direct_commands_bootstrap_logging_from_config(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setattr(
        batho,
        "get_config_cached",
        lambda: {
            "logging": _base_logging_config(level="ERROR", json_format=True, quiet=True),
            "paths": {"ctn_dir": ".ctn"},
        },
    )
    monkeypatch.setattr(batho, "configure_logging", lambda cfg: captured.setdefault("cfg", cfg))

    out = batho._ensure_ctn_dir(tmp_path)

    assert out == tmp_path / ".ctn"
    assert captured["cfg"]["level"] == "ERROR"
    assert captured["cfg"]["quiet"] is True
    assert batho._RUNTIME_LOGGING_INITIALIZED is True
