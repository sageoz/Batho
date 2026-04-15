"""Deterministic failure synthesizer and evolution ledger persistence.

This module converts patch/webhook failures into concise "Don't" guidance and
stores entries in `.ctn/evolution_ledger.json`.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from batho.context.storage import persist_json
from batho.utils.logging import get_logger

logger = get_logger(__name__, component="synthesizer")

_LEDGER_SCHEMA_VERSION = "evolution-ledger.v1"
_LEDGER_FILENAME = "evolution_ledger.json"
_MAX_LEDGER_ENTRIES = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ledger_path(ctn_dir: Path) -> Path:
    ctn_dir.mkdir(parents=True, exist_ok=True)
    return ctn_dir / _LEDGER_FILENAME


def _default_ledger() -> dict[str, Any]:
    return {
        "schema_version": _LEDGER_SCHEMA_VERSION,
        "updated_at": _now_iso(),
        "entries": [],
    }


def _load_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _default_ledger()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("evolution_ledger_load_failed", path=path.as_posix())
        return _default_ledger()

    if not isinstance(payload, dict):
        return _default_ledger()

    entries = payload.get("entries")
    if not isinstance(entries, list):
        entries = []

    return {
        "schema_version": _LEDGER_SCHEMA_VERSION,
        "updated_at": str(payload.get("updated_at") or _now_iso()),
        "entries": entries,
    }


def _save_ledger(path: Path, payload: dict[str, Any]) -> None:
    payload["schema_version"] = _LEDGER_SCHEMA_VERSION
    payload["updated_at"] = _now_iso()

    ctn_dir = path.parent
    persist_json(
        ctn_dir,
        path,
        payload,
        artifact_type="evolution_ledger_json",
        producer="synthesizer",
        metadata={"entry_count": len(payload.get("entries") or [])},
        schema_version=_LEDGER_SCHEMA_VERSION,
    )


def _normalize_changed_files(changed_files: Iterable[str] | None) -> list[str]:
    if not changed_files:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for value in changed_files:
        path = str(value).strip()
        if not path or path in seen:
            continue
        seen.add(path)
        normalized.append(path)

    return sorted(normalized)


def _looks_generated(path: str) -> bool:
    lowered = path.lower()
    generated_markers = (
        "/node_modules/",
        "/dist/",
        "/build/",
        "__pycache__/",
        ".generated.",
        ".gen.",
        ".min.js",
    )
    generated_suffixes = (
        ".pb.go",
        ".pb.cc",
        ".pb.h",
        ".g.dart",
        ".designer.cs",
    )

    return any(marker in lowered for marker in generated_markers) or lowered.endswith(
        generated_suffixes
    )


def synthesize_failure_rule(
    error_message: str, changed_files: Iterable[str] | None = None
) -> dict[str, str]:
    message = str(error_message or "").strip()
    lowered = message.lower()
    files = _normalize_changed_files(changed_files)

    if any(_looks_generated(path) for path in files) or "generated" in lowered:
        return {
            "category": "generated-artifacts",
            "dont_rule": "Don't manually edit generated artifacts; modify the source definitions and regenerate.",
            "rationale": "Generated files are overwritten by tooling and should not be hand-maintained.",
        }

    if "snapshot" in lowered and any(
        token in lowered for token in ("not found", "missing", "invalid")
    ):
        return {
            "category": "snapshot",
            "dont_rule": "Don't patch without a valid base snapshot; refresh index/snapshot state first.",
            "rationale": "Incremental patching depends on a consistent base snapshot chain.",
        }

    if "permission" in lowered and "denied" in lowered:
        return {
            "category": "permissions",
            "dont_rule": "Don't run patch operations on files you cannot write; fix permissions before retrying.",
            "rationale": "Permission-denied failures prevent deterministic patch application.",
        }

    if "timeout" in lowered:
        return {
            "category": "timeout",
            "dont_rule": "Don't patch very large change sets in one run; split changes into smaller batches.",
            "rationale": "Large patch sets increase timeout risk and reduce recoverability.",
        }

    if "too many changes" in lowered or "max_changes" in lowered:
        return {
            "category": "scope",
            "dont_rule": "Don't exceed configured patch limits; chunk the change set and apply incrementally.",
            "rationale": "Patch safety guards reject oversized operations by design.",
        }

    if "diff" in lowered and "parse" in lowered:
        return {
            "category": "diff-format",
            "dont_rule": "Don't apply malformed diff payloads; validate unified diff structure before patching.",
            "rationale": "Invalid diff format prevents reliable file-change extraction.",
        }

    return {
        "category": "general",
        "dont_rule": "Don't repeat a failing patch unchanged; verify inputs and run a narrow dry-run before retry.",
        "rationale": "Replaying identical failing operations usually compounds state drift.",
    }


def _is_duplicate(
    existing_entries: list[dict[str, Any]], candidate: dict[str, Any]
) -> bool:
    if not existing_entries:
        return False

    last = existing_entries[-1]
    return (
        str(last.get("source")) == str(candidate.get("source"))
        and str(last.get("error_message")) == str(candidate.get("error_message"))
        and list(last.get("changed_files") or [])
        == list(candidate.get("changed_files") or [])
        and str(last.get("dont_rule")) == str(candidate.get("dont_rule"))
    )


def record_failure_rule(
    ctn_dir: Path,
    source: str,
    error_message: str,
    changed_files: Iterable[str] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a deterministic evolution-ledger entry for a failure path."""
    files = _normalize_changed_files(changed_files)
    synthesis = synthesize_failure_rule(
        error_message=error_message, changed_files=files
    )

    entry = {
        "entry_id": uuid.uuid4().hex[:12],
        "timestamp": _now_iso(),
        "source": str(source),
        "error_message": str(error_message or "").strip(),
        "changed_files": files,
        "dont_rule": synthesis["dont_rule"],
        "category": synthesis["category"],
        "rationale": synthesis["rationale"],
        "context": dict(context or {}),
    }

    path = _ledger_path(ctn_dir)
    ledger = _load_ledger(path)
    entries = ledger.setdefault("entries", [])
    if not isinstance(entries, list):
        entries = []
        ledger["entries"] = entries

    if not _is_duplicate(entries, entry):
        entries.append(entry)
        if len(entries) > _MAX_LEDGER_ENTRIES:
            ledger["entries"] = entries[-_MAX_LEDGER_ENTRIES:]
        _save_ledger(path, ledger)

        logger.info(
            "evolution_ledger_entry_recorded",
            source=entry["source"],
            entry_id=entry["entry_id"],
            category=entry["category"],
            file_count=len(files),
        )
    else:
        entry = dict(entries[-1])

    return entry


def load_evolution_ledger(ctn_dir: Path) -> dict[str, Any]:
    """Load the evolution ledger payload (creates default structure in-memory if absent)."""
    return _load_ledger(_ledger_path(ctn_dir))
