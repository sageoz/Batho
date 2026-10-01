"""Tests for batho.install.receipt — install.sh schema compatibility."""

from __future__ import annotations

import json
from pathlib import Path

from batho.install.receipt import read_receipt, remove_receipt, write_receipt

FIXTURE = Path(__file__).parent / "fixtures" / "skills-receipt.json"


def test_round_trip(isolated_home: Path) -> None:
    path = write_receipt("v1.2.3", "global", ["/b", "/a", "/a"])
    assert path.name == "skills-receipt.json"
    data = read_receipt()
    assert data is not None
    assert data["pack"] == "batho"
    assert data["version"] == "v1.2.3"
    assert data["scope"] == "global"
    assert data["dirs"] == ["/a", "/b"]  # deduped + sorted
    assert "T" in data["installed_at"]


def test_install_sh_schema_fixture() -> None:
    """A receipt written in install.sh's exact schema parses correctly."""
    data = read_receipt(FIXTURE)
    assert data is not None
    assert data["pack"] == "batho"
    assert data["version"] == "v1.4.2"
    assert data["scope"] == "global"
    assert len(data["dirs"]) == 3


def test_missing_returns_none(isolated_home: Path) -> None:
    assert read_receipt() is None


def test_foreign_pack_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "skills-receipt.json"
    p.write_text(json.dumps({"pack": "other", "version": "v1"}))
    assert read_receipt(p) is None


def test_corrupt_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "skills-receipt.json"
    p.write_text("{not json")
    assert read_receipt(p) is None


def test_remove_receipt(isolated_home: Path) -> None:
    write_receipt("v1.0.0", "global", [])
    remove_receipt()
    assert read_receipt() is None
    remove_receipt()  # idempotent


def test_receipt_write_atomic_cleanup(isolated_home: Path, monkeypatch) -> None:
    """SKL-11: a crash mid-write leaves no torn receipt and no tmp litter."""
    import json
    import os as _os
    from unittest.mock import patch as _patch

    from batho.install.receipt import receipt_path, write_receipt

    real_fdopen = _os.fdopen

    def _boom(fd, *a, **k):
        fh = real_fdopen(fd, *a, **k)
        fh.write('{"partial":')
        fh.close()
        raise OSError("disk full")

    p = receipt_path()
    with _patch.object(_os, "fdopen", _boom):
        try:
            write_receipt("v1.0.0", "global", [])
        except OSError:
            pass
    assert not p.exists()
    assert not list(p.parent.glob("*.tmp"))

    write_receipt("v1.0.0", "global", ["/x"])
    assert json.loads(p.read_text())["version"] == "v1.0.0"
