"""Read/write the batho skill-pack install receipt.

Schema is owned by batho-skills ``install.sh`` — this module is read/write
compatible and must not invent a new format:

    {
      "pack": "batho",
      "version": "v1.2.3",
      "scope": "global|project",
      "installed_at": "<UTC ISO-8601>",
      "dirs": ["<abs path>", ...]
    }
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT_NAME = "skills-receipt.json"


def receipt_path() -> Path:
    """Return the receipt path, honoring BATHO_RECEIPT_DIR."""
    base = os.environ.get("BATHO_RECEIPT_DIR")
    root = Path(base).expanduser() if base else Path.home() / ".batho"
    return root / RECEIPT_NAME


def read_receipt(path: Path | None = None) -> dict[str, Any] | None:
    """Read the receipt. Returns None when absent or unparseable."""
    p = path or receipt_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and data.get("pack") == "batho" else None


CHECK_NAME = "skills-last-check.json"
CHECK_TTL_S = 24 * 3600


def _atomic_write_json(p: Path, payload: dict[str, Any]) -> Path:
    """Write JSON atomically — tempfile in the same dir + os.replace, so a
    crash mid-write can't leave a torn file (RepoRegistry's pattern)."""
    import tempfile

    fd, tmp = tempfile.mkstemp(
        dir=p.parent, prefix=p.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, indent=2) + "\n")
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def write_receipt(
    version: str,
    scope: str,
    dirs: list[str],
    path: Path | None = None,
) -> Path:
    """Write the receipt in the install.sh schema. Returns the path written."""
    p = path or receipt_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pack": "batho",
        "version": version,
        "scope": scope,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dirs": sorted(dict.fromkeys(dirs)),
    }
    return _atomic_write_json(p, payload)


def last_check_path() -> Path:
    """Sidecar recording when we last asked GitHub for the latest tag.

    Kept OUT of the receipt — the receipt schema is owned by install.sh and
    must stay byte-compatible.
    """
    return receipt_path().parent / CHECK_NAME


def read_last_check() -> dict[str, Any] | None:
    """Return {'checked_at': ..., 'version': ...} when the last upstream
    version probe is fresher than CHECK_TTL_S, else None."""
    p = last_check_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("version"):
        return None
    try:
        checked_at = datetime.strptime(
            data["checked_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError):
        return None
    age = (datetime.now(timezone.utc) - checked_at).total_seconds()
    return data if age < CHECK_TTL_S else None


def write_last_check(version: str) -> Path:
    """Record a successful latest-version probe (atomic, same-dir)."""
    p = last_check_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    return _atomic_write_json(p, {
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version": version,
    })


def remove_receipt(path: Path | None = None) -> None:
    """Delete the receipt if present."""
    p = path or receipt_path()
    try:
        p.unlink()
    except FileNotFoundError:
        pass
