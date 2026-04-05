from __future__ import annotations

import importlib
from pathlib import Path

import batho.config as config_module
import batho.utils.patch_errors as patch_errors_module


def test_patch_error_classes_capture_context() -> None:
    validation = patch_errors_module.PatchValidationError("bad input", details={"field": "x"})
    consistency = patch_errors_module.PatchConsistencyError("inconsistent", inconsistencies=["edge-1"])
    snapshot = patch_errors_module.PatchSnapshotError("missing", snapshot_id="snap-1")
    file_error = patch_errors_module.PatchFileError("io", file_path="a.py", operation="write")
    timeout = patch_errors_module.PatchTimeoutError("slow", timeout_seconds=3.5)

    assert validation.details == {"field": "x"}
    assert consistency.inconsistencies == ["edge-1"]
    assert snapshot.snapshot_id == "snap-1"
    assert file_error.file_path == "a.py"
    assert file_error.operation == "write"
    assert timeout.timeout_seconds == 3.5


def test_patch_audit_log_entry_complete_merges_metadata() -> None:
    logger = patch_errors_module.PatchAuditLogger()
    entry = logger.start_operation(
        operation_id="op-1",
        operation_type="incremental_patch",
        metadata={"source": "test"},
    )

    entry.complete(
        success=True,
        new_snapshot_id="snap-2",
        metadata={"duration_ms": 12},
    )

    payload = entry.to_dict()
    assert payload["success"] is True
    assert payload["new_snapshot_id"] == "snap-2"
    assert payload["metadata"]["source"] == "test"
    assert payload["metadata"]["duration_ms"] == 12


def test_patch_audit_logger_short_circuit_and_history_filters(
    tmp_path: Path,
    monkeypatch,
) -> None:
    logger = patch_errors_module.PatchAuditLogger(log_file=None)
    logger._write_audit_log()

    failing_log = patch_errors_module.PatchAuditLogger(log_file=tmp_path / "audit.json")

    monkeypatch.setattr(
        Path,
        "write_text",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    first = failing_log.start_operation("op-1", "incremental_patch", base_snapshot_id="base-1")
    second = failing_log.start_operation("op-2", "rollback", base_snapshot_id="base-2")
    failing_log.complete_operation("op-1", success=True, change_count=2)
    failing_log.complete_operation("op-2", success=False, error_message="boom", change_count=1)

    all_history = failing_log.get_operation_history(limit=10)
    assert len(all_history) == 2

    filtered = failing_log.get_operation_history(operation_type="incremental_patch", base_snapshot_id="base-1", limit=1)
    assert len(filtered) == 1
    assert filtered[0]["operation_id"] == "op-1"


def test_patch_errors_module_level_audit_logger_fallbacks(monkeypatch) -> None:
    monkeypatch.setattr(config_module, "get_config_cached", lambda: {"patch": {}})
    reloaded = importlib.reload(patch_errors_module)
    assert isinstance(reloaded.audit_logger, reloaded.PatchAuditLogger)

    call_count = {"n": 0}

    def _config_side_effect():
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"flags": {"audit_log_enabled": True}}
        raise RuntimeError("config failed")

    monkeypatch.setattr(
        config_module,
        "get_config_cached",
        _config_side_effect,
    )
    reloaded = importlib.reload(reloaded)
    assert isinstance(reloaded.audit_logger, reloaded.PatchAuditLogger)
