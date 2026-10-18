"""Shared fixtures for tests/install — HOME + BATHO_* env isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

_BATHO_ENV = [
    "BATHO_RECEIPT_DIR",
    "BATHO_AGENTS",
    "BATHO_INSTALL_DIR",
    "BATHO_VERSION",
    "BATHO_BASE_URL",
    "BATHO_NO_SKILL_SYNC",
    "BATHO_SCOPE",
    "BATHO_COPY",
    "BATHO_NO_ANALYTICS",
    "BATHO_EXPECTED_SHA256",
]


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect HOME and the receipt dir into tmp_path; clear BATHO_* env."""
    for var in _BATHO_ENV:
        monkeypatch.delenv(var, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("BATHO_RECEIPT_DIR", str(tmp_path / "batho-state"))
    return home


@pytest.fixture
def empty_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point PATH at an empty dir so no agent binaries are detected."""
    bindir = tmp_path / "empty-bin"
    bindir.mkdir()
    monkeypatch.setenv("PATH", str(bindir))
    return bindir
