from __future__ import annotations

import json
import sys
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import batho.time_machine as tm
from batho.time_machine import (
    FileChange,
    FileChangeType,
    PatchOperation,
)


def _mk_change(
    path: str,
    change_type: FileChangeType,
    old_hash: str | None = None,
    new_hash: str | None = None,
    file_size: int | None = None,
) -> FileChange:
    return FileChange(
        path=path,
        change_type=change_type,
        old_hash=old_hash,
        new_hash=new_hash,
        file_size=file_size,
    )


def _mk_patch_operation(
    operation_id: str = "op-1",
    *,
    timestamp: datetime | None = None,
) -> PatchOperation:
    ts = timestamp or datetime.now(timezone.utc)
    changes = [
        _mk_change("src/a.py", FileChangeType.MODIFIED, "old", "new", file_size=120),
        _mk_change("src/b.py", FileChangeType.ADDED, None, "new2", file_size=30),
    ]
    op = PatchOperation(
        operation_id=operation_id,
        base_snapshot_id="base-1",
        new_snapshot_id="snap-1",
        changes_applied=changes,
        timestamp=ts,
        checksum="",
        patch_chain=["op-0", operation_id],
        operation_type="incremental_patch",
        user_info={"source": "test"},
        metrics={"token_size": 99},
    )
    payload = {k: v for k, v in op.serialize().items() if k != "checksum"}
    op.checksum = tm.compute_bytes_hash(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    )
    return op


def _configure_incremental_patch_success(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    *,
    updater_raise: str | None = None,
    consistency_ok: bool = True,
    extractor_available: bool = True,
    load_snapshot_none: bool = False,
    timeout_raises: bool = False,
    save_raises: bool = False,
) -> None:
    monkeypatch.setattr(
        tm,
        "get_config_cached",
        lambda: {"patch": {"timeout_seconds": 5, "max_changes": 1000}},
    )

    if timeout_raises:

        @contextmanager
        def _timeout(_seconds: float):
            raise tm.PatchTimeoutError("timed out", timeout_seconds=5)
            yield

        monkeypatch.setattr(tm, "timeout_context", _timeout)
    else:
        monkeypatch.setattr(tm, "timeout_context", lambda _seconds: nullcontext())

    monkeypatch.setattr(
        tm.audit_logger,
        "start_operation",
        lambda **_kwargs: SimpleNamespace(operation_id="audit-op"),
    )
    monkeypatch.setattr(tm.audit_logger, "complete_operation", lambda **_kwargs: None)

    if load_snapshot_none:
        monkeypatch.setattr(tm, "load_snapshot", lambda *_a, **_k: None)
    else:
        monkeypatch.setattr(
            tm,
            "load_snapshot",
            lambda *_a, **_k: {"graph": {}, "bsg": {}, "root": str(root)},
        )

    class _FakeInMemoryGraph:
        @staticmethod
        def from_dict(_payload):
            return SimpleNamespace(entities={}, relationships=[])

    class _FakeBSG:
        def __init__(self):
            self._root = None

        def patch(self, _changes, _graph):
            return None

    class _FakeBSGMap:
        @staticmethod
        def from_dict(_payload, serialization_config=None):
            _ = serialization_config
            return _FakeBSG()

    class _FakeUpdater:
        def remove_entities_for_file(self, _graph, _path):
            if updater_raise == "remove":
                raise RuntimeError("remove failed")

        def update_entities_for_file(self, _graph, _path, _extractor):
            if updater_raise == "update":
                raise RuntimeError("update failed")

        def add_entities_for_file(self, _graph, _path, _extractor):
            if updater_raise == "add":
                raise RuntimeError("add failed")

        def _resolve_imports(self, _graph, symbol_index=None, fuzzy_matching=False):
            return _graph

        def validate_graph_consistency(self, _graph):
            return consistency_ok

    class _FakeTracker:
        def __init__(self, _root):
            self.file_hashes = {"del.py": "old"}

        def load(self, _path):
            return True

        def save(self, _path):
            return None

    monkeypatch.setattr(tm, "InMemoryGraph", _FakeInMemoryGraph)
    monkeypatch.setattr(tm, "BSGMap", _FakeBSGMap)
    monkeypatch.setattr(tm, "IncrementalGraphUpdater", _FakeUpdater)
    monkeypatch.setattr(tm, "FileChangeTracker", _FakeTracker)
    monkeypatch.setattr(tm, "create_snapshot", lambda *_a, **_k: "snap-new")
    monkeypatch.setattr(tm, "build_patch_chain", lambda *_a, **_k: ["op-0", "op-1"])
    monkeypatch.setattr(tm, "estimate_token_changes", lambda _changes: 123)

    import batho.bsg as bsg_mod

    monkeypatch.setattr(
        bsg_mod, "apply_semantic_overlay", lambda graph, root_path, logger=None: None
    )

    if save_raises:
        monkeypatch.setattr(
            tm,
            "save_patch_operation",
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("save failed")),
        )
    else:
        monkeypatch.setattr(tm, "save_patch_operation", lambda *_a, **_k: None)

    import batho.context.languages.detector as detector_mod
    import batho.context.languages.registry as registry_mod

    if extractor_available:
        monkeypatch.setattr(
            detector_mod.default_detector, "get_extractor", lambda *_a, **_k: object()
        )
        monkeypatch.setattr(registry_mod, "get_extractor", lambda *_a, **_k: object())
    else:
        monkeypatch.setattr(
            detector_mod.default_detector, "get_extractor", lambda *_a, **_k: None
        )
        monkeypatch.setattr(registry_mod, "get_extractor", lambda *_a, **_k: None)


@pytest.mark.skipif(
    sys.platform == "win32", reason="signal.alarm not available on Windows"
)
def test_timeout_context_raises_and_restores_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int | object]] = []
    holder: dict[str, object] = {}

    def _fake_signal(sig, handler):
        calls.append(("signal", sig))
        holder["handler"] = handler
        return "old-handler"

    def _fake_alarm(seconds):
        calls.append(("alarm", seconds))

    monkeypatch.setattr(tm.signal, "signal", _fake_signal)
    monkeypatch.setattr(tm.signal, "alarm", _fake_alarm)

    with tm.timeout_context(3):
        with pytest.raises(tm.PatchTimeoutError):
            holder["handler"](0, None)

    assert ("alarm", 3) in calls
    assert ("alarm", 0) in calls


def test_patch_limits_and_change_summary_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changes = [
        _mk_change("a.py", FileChangeType.ADDED, None, "x"),
        _mk_change("b.py", FileChangeType.MODIFIED, "o", "n"),
        _mk_change("c.py", FileChangeType.DELETED, "o", None),
    ]
    with pytest.raises(tm.PatchValidationError):
        tm.check_patch_limits(changes, 1)

    seen: list[dict[str, int]] = []

    def _capture(_event, **kwargs):
        seen.append(kwargs)

    monkeypatch.setattr(tm.logger, "info", _capture)
    tm.log_change_summary(changes)
    assert seen and seen[0]["added_files"] == 1 and seen[0]["deleted_files"] == 1


def test_patch_operation_roundtrip_validate_and_tamper() -> None:
    op = _mk_patch_operation("op-roundtrip")
    assert op.validate() is True

    serialized = op.serialize()
    restored = PatchOperation.from_dict(serialized)
    assert restored.operation_id == "op-roundtrip"
    assert len(restored.changes_applied) == 2

    restored.checksum = "bad"
    assert restored.validate() is False


def test_file_tracker_invalid_cache_and_helper_accessors(tmp_path: Path) -> None:
    tracker = tm.FileChangeTracker(tmp_path)
    bad = tmp_path / "bad_cache.json"
    bad.write_text("{invalid", encoding="utf-8")
    assert tracker.load(bad) is False
    assert tracker.file_hashes == {}

    changes = [
        _mk_change("x.py", FileChangeType.ADDED, None, "h"),
        _mk_change("y.py", FileChangeType.MODIFIED, "a", "b"),
        _mk_change("z.py", FileChangeType.DELETED, "a", None),
    ]
    changed = tracker.get_changed_files(changes)
    deleted = tracker.get_deleted_files(changes)
    assert len(changed) == 2
    assert deleted == ["z.py"]


def test_git_branch_name_success_blank_and_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        tm.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(stdout="main\n"),
    )
    assert tm._git_branch_name(tmp_path) == "main"

    monkeypatch.setattr(
        tm.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(stdout="\n"),
    )
    assert tm._git_branch_name(tmp_path) is None

    def _raise(*_a, **_k):
        raise tm.subprocess.CalledProcessError(1, "git")

    monkeypatch.setattr(tm.subprocess, "run", _raise)
    assert tm._git_branch_name(tmp_path) is None


def test_list_and_load_snapshot_parse_edge_cases(tmp_path: Path) -> None:
    ctn = tmp_path / ".ctn"
    snaps = ctn / "snapshots"
    snaps.mkdir(parents=True)

    good = snaps / "good.json"
    good.write_text(
        json.dumps({"snapshot_id": "good", "created_at": "t"}), encoding="utf-8"
    )
    bad = snaps / "bad.json"
    bad.write_text("{broken", encoding="utf-8")

    listed = tm.list_snapshots(ctn)
    assert len(listed) == 1
    assert listed[0]["snapshot_id"] == "good"

    no_checksum = snaps / "nocheck.json"
    no_checksum.write_text(json.dumps({"snapshot_id": "nocheck"}), encoding="utf-8")
    loaded = tm.load_snapshot(ctn, "nocheck")
    assert loaded is not None

    bad_checksum = snaps / "badcheck.json"
    bad_checksum.write_text(
        json.dumps({"snapshot_id": "badcheck", "_checksum": "x"}), encoding="utf-8"
    )
    assert tm.load_snapshot(ctn, "badcheck") is None


def test_diff_and_compare_and_parse_helpers_cover_fallbacks() -> None:
    a = {
        "stats": {"entity_count": 1, "relationship_count": 1},
        "bsg": {"nodes": [{"file": "a.py"}]},
    }
    b = {
        "stats": {"entity_count": 3, "relationship_count": 2},
        "bsg": {"nodes": [{"file": "b.py"}]},
    }
    diff = tm.diff_snapshots(a, b)
    assert diff["entity_delta"] == 2
    assert "b.py" in diff["added_files"]
    assert "a.py" in diff["removed_files"]

    compared = tm.compare_file_lists({"a": "1", "b": "2"}, {"b": "1", "c": "3"})
    types = {c.path: c.change_type for c in compared}
    assert types["a"] == FileChangeType.ADDED
    assert types["b"] == FileChangeType.MODIFIED
    assert types["c"] == FileChangeType.DELETED

    parsed = tm.parse_git_diff("\nA\ta.py\nX\tbad.py\nmissingtab\nM\tb.py\nD\tc.py\n")
    assert [c.path for c in parsed] == ["a.py", "b.py", "c.py"]


def test_compute_staleness_age_parse_error_branch() -> None:
    score = tm.compute_staleness(
        {"repo_hash": "same", "file_count": 10, "timestamp": "not-a-timestamp"},
        "same",
        {"files_parsed": 3, "errors": 1},
    )
    assert 0.0 <= score <= 1.0


def test_incremental_patch_success_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_incremental_patch_success(monkeypatch, tmp_path)

    changes = [
        _mk_change("del.py", FileChangeType.DELETED, "old", None),
        _mk_change("mod.py", FileChangeType.MODIFIED, "old", "new"),
        _mk_change("add.py", FileChangeType.ADDED, None, "new2"),
    ]
    result = tm.incremental_patch(tmp_path / ".ctn", "base-snap", changes)
    assert result["success"] is True
    assert result["new_snapshot_id"] == "snap-new"
    assert result["applied_changes"] == 3


def test_incremental_patch_validation_limit_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        tm,
        "get_config_cached",
        lambda: {"patch": {"timeout_seconds": 5, "max_changes": 0}},
    )
    result = tm.incremental_patch(
        tmp_path / ".ctn",
        "base",
        [_mk_change("a.py", FileChangeType.ADDED, None, "h")],
    )
    assert result["success"] is False
    assert "Too many changes" in result["error"]


def test_incremental_patch_timeout_and_snapshot_and_consistency_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Timeout path.
    _configure_incremental_patch_success(monkeypatch, tmp_path, timeout_raises=True)
    timeout_result = tm.incremental_patch(tmp_path / ".ctn", "base", [])
    assert timeout_result["success"] is False
    assert "timed out" in timeout_result["error"]

    # Snapshot missing path.
    _configure_incremental_patch_success(monkeypatch, tmp_path, load_snapshot_none=True)
    snap_result = tm.incremental_patch(tmp_path / ".ctn", "base", [])
    assert snap_result["success"] is False
    assert "not found" in snap_result["error"]

    # Consistency failure path.
    _configure_incremental_patch_success(monkeypatch, tmp_path, consistency_ok=False)
    consistency_result = tm.incremental_patch(
        tmp_path / ".ctn",
        "base",
        [_mk_change("del.py", FileChangeType.DELETED, "old", None)],
    )
    assert consistency_result["success"] is False
    assert "consistency" in consistency_result["error"].lower()


def test_incremental_patch_file_error_validation_error_and_unexpected_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # File operation failure -> PatchFileError path.
    _configure_incremental_patch_success(monkeypatch, tmp_path, updater_raise="remove")
    file_result = tm.incremental_patch(
        tmp_path / ".ctn",
        "base",
        [_mk_change("del.py", FileChangeType.DELETED, "old", None)],
    )
    assert file_result["success"] is False
    assert "Failed to apply change" in file_result["error"]

    # Inner PatchValidationError path in main try/except block.
    _configure_incremental_patch_success(monkeypatch, tmp_path)
    monkeypatch.setattr(
        tm,
        "aggregate_changes",
        lambda _changes: (_ for _ in ()).throw(
            tm.PatchValidationError("inner validation", details={"k": "v"})
        ),
    )
    validation_result = tm.incremental_patch(
        tmp_path / ".ctn",
        "base",
        [_mk_change("a.py", FileChangeType.ADDED, None, "new")],
    )
    assert validation_result["success"] is False
    assert "inner validation" in validation_result["error"]

    # Generic unexpected error path.
    monkeypatch.setattr(tm, "aggregate_changes", lambda changes: changes)
    _configure_incremental_patch_success(monkeypatch, tmp_path, save_raises=True)
    generic_result = tm.incremental_patch(
        tmp_path / ".ctn",
        "base",
        [_mk_change("a.py", FileChangeType.ADDED, None, "new")],
    )
    assert generic_result["success"] is False
    assert "Unexpected error" in generic_result["error"]


def test_incremental_patch_extractor_none_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_incremental_patch_success(
        monkeypatch, tmp_path, extractor_available=False
    )
    result = tm.incremental_patch(
        tmp_path / ".ctn",
        "base",
        [_mk_change("mod.py", FileChangeType.MODIFIED, "old", "new")],
    )
    assert result["success"] is True


def test_rollback_changes_action_paths_and_error_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str]] = []

    class _Updater:
        def add_entities_for_file(self, _graph, path, _extractor):
            calls.append(("add", path))
            raise RuntimeError("boom")

        def remove_entities_for_file(self, _graph, path):
            calls.append(("remove", path))

    tm._rollback_changes(
        graph=SimpleNamespace(),
        applied_changes=[_mk_change("a.py", FileChangeType.DELETED, "old", None)],
        rollback_actions=[
            ("add_file", "a.py"),
            ("restore_file", "b.py", "h"),
            ("delete_file", "c.py"),
        ],
        updater=_Updater(),
        root_path=tmp_path,
    )

    assert any(action == "remove" for action, _ in calls)


def test_save_and_load_patch_operation_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctn = tmp_path / ".ctn"
    ctn.mkdir()
    op = _mk_patch_operation("roundtrip-op")

    monkeypatch.setattr(tm, "register_artifact", lambda *_a, **_k: True)
    tm.save_patch_operation(ctn, op)

    loaded = tm.load_patch_operation(ctn, "roundtrip-op")
    assert loaded is not None
    assert loaded.operation_id == "roundtrip-op"


def test_load_patch_operation_missing_invalid_checksum_and_invalid_json(
    tmp_path: Path,
) -> None:
    ctn = tmp_path / ".ctn"
    ctn.mkdir()
    patches = ctn / "patches"
    patches.mkdir()

    assert tm.load_patch_operation(ctn, "missing") is None

    bad_json = patches / "patch_badjson.json"
    bad_json.write_text("{broken", encoding="utf-8")
    assert tm.load_patch_operation(ctn, "badjson") is None

    op = _mk_patch_operation("badchecksum-op")
    data = op.serialize()
    data["checksum"] = "bad"
    (patches / "patch_badchecksum-op.json").write_text(
        json.dumps(data), encoding="utf-8"
    )
    assert tm.load_patch_operation(ctn, "badchecksum-op") is None


def test_update_patch_index_with_corrupt_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctn = tmp_path / ".ctn"
    patches = ctn / "patches"
    patches.mkdir(parents=True)
    (patches / "index.json").write_text("{broken", encoding="utf-8")

    monkeypatch.setattr(tm, "register_artifact", lambda *_a, **_k: True)
    tm.update_patch_index(ctn, _mk_patch_operation("idx-op"))

    index_data = json.loads((patches / "index.json").read_text(encoding="utf-8"))
    assert index_data["total_patches"] == 1


def test_list_patch_operations_filters_and_error_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctn = tmp_path / ".ctn"
    ctn.mkdir()
    monkeypatch.setattr(tm, "register_artifact", lambda *_a, **_k: True)

    op1 = _mk_patch_operation("op-a")
    op2 = _mk_patch_operation("op-b")
    op2.operation_type = "cherry_pick"
    payload = {k: v for k, v in op2.serialize().items() if k != "checksum"}
    op2.checksum = tm.compute_bytes_hash(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    )

    tm.save_patch_operation(ctn, op1)
    tm.save_patch_operation(ctn, op2)

    filtered = tm.list_patch_operations(ctn, filters={"operation_type": "cherry_pick"})
    assert len(filtered) == 1
    assert filtered[0].operation_id == "op-b"

    # Corrupt index path should return [] via exception handler.
    (ctn / "patches" / "index.json").write_text("{", encoding="utf-8")
    assert tm.list_patch_operations(ctn) == []


def test_get_patches_for_snapshot_and_build_patch_chain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctn = tmp_path / ".ctn"
    ctn.mkdir()

    p1 = _mk_patch_operation(
        "chain-a", timestamp=datetime.now(timezone.utc) - timedelta(seconds=10)
    )
    p1.new_snapshot_id = "snap-target"
    p1.patch_chain = ["root", "chain-a"]
    p2 = _mk_patch_operation("chain-b", timestamp=datetime.now(timezone.utc))
    p2.new_snapshot_id = "snap-target"
    p2.patch_chain = ["root", "chain-b"]

    monkeypatch.setattr(tm, "list_patch_operations", lambda *_a, **_k: [p1, p2])

    found = tm.get_patches_for_snapshot(ctn, "snap-target")
    assert len(found) == 2

    chain = tm.build_patch_chain(ctn, "snap-target", "chain-c")
    assert chain[-1] == "chain-c"
    assert "chain-b" in chain

    monkeypatch.setattr(tm, "get_patches_for_snapshot", lambda *_a, **_k: [])
    root_chain = tm.build_patch_chain(ctn, "none", "chain-z")
    assert root_chain == ["chain-z"]


def test_cleanup_old_patches_missing_dir_and_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctn_missing = tmp_path / "missing-ctn"
    assert (
        tm.cleanup_old_patches(
            ctn_missing, {"max_patch_history_days": 1, "max_patch_count": 1}
        )
        == 0
    )

    ctn = tmp_path / ".ctn"
    patches = ctn / "patches"
    patches.mkdir(parents=True)

    old = _mk_patch_operation(
        "old-op",
        timestamp=datetime.now(timezone.utc) - timedelta(days=365),
    )
    keep = _mk_patch_operation(
        "keep-op",
        timestamp=datetime.now(timezone.utc),
    )

    (patches / "patch_old-op.json").write_text(
        json.dumps(old.serialize()), encoding="utf-8"
    )
    (patches / "patch_keep-op.json").write_text(
        json.dumps(keep.serialize()), encoding="utf-8"
    )

    monkeypatch.setattr(tm, "list_patch_operations", lambda *_a, **_k: [keep, old])
    monkeypatch.setattr(tm, "update_patch_index", lambda *_a, **_k: None)

    cleaned = tm.cleanup_old_patches(
        ctn,
        {"max_patch_history_days": 0, "max_patch_count": 1},
    )
    assert cleaned >= 1
    assert not (patches / "patch_old-op.json").exists()


def test_estimate_tokens_and_parse_unified_diff() -> None:
    total = tm.estimate_token_changes(
        [
            _mk_change("a.py", FileChangeType.ADDED, None, "h", file_size=100),
            _mk_change("b.py", FileChangeType.MODIFIED, "a", "b", file_size=None),
        ]
    )
    assert total >= 108

    diff = "\n".join(
        [
            "diff --git a/new.py b/new.py",
            "index 0000000..1111111 100644",
            "new file mode 100644",
            "diff --git a/old.py b/old.py",
            "index 2222222..0000000 100644",
            "deleted file mode 100644",
            "diff --git a/mod.py b/mod.py",
            "index aaaaaaa..bbbbbbb 100644",
            "@@ -1 +1 @@",
            "@@ -2 +2 @@",  # duplicate hunk should not duplicate entry
        ]
    )
    parsed = tm.parse_unified_diff(diff)
    assert len(parsed) == 3
    kinds = {c.path: c.change_type for c in parsed}
    assert kinds["new.py"] == FileChangeType.ADDED
    assert kinds["old.py"] == FileChangeType.DELETED
    assert kinds["mod.py"] == FileChangeType.MODIFIED


def test_validate_patch_compatibility_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctn = tmp_path / ".ctn"
    ctn.mkdir()

    # Missing required field.
    assert (
        tm.validate_patch_compatibility({"changes_applied": []}, "snap", ctn) is False
    )

    # Missing base snapshot.
    monkeypatch.setattr(tm, "load_snapshot", lambda *_a, **_k: None)
    assert (
        tm.validate_patch_compatibility(
            {"changes_applied": [], "operation_type": "incremental_patch"},
            "snap",
            ctn,
        )
        is False
    )

    base_snapshot = {"graph": {"entities": [{"file_path": "src/a.py"}]}}
    monkeypatch.setattr(tm, "load_snapshot", lambda *_a, **_k: base_snapshot)

    # Invalid change payload.
    assert (
        tm.validate_patch_compatibility(
            {"changes_applied": [{}], "operation_type": "incremental_patch"},
            "snap",
            ctn,
        )
        is False
    )

    # Modified file missing in base snapshot.
    assert (
        tm.validate_patch_compatibility(
            {
                "changes_applied": [{"path": "missing.py", "change_type": "MODIFIED"}],
                "operation_type": "incremental_patch",
            },
            "snap",
            ctn,
        )
        is False
    )

    # Added existing file is warning-only and still valid.
    assert (
        tm.validate_patch_compatibility(
            {
                "changes_applied": [{"path": "src/a.py", "change_type": "ADDED"}],
                "operation_type": "incremental_patch",
            },
            "snap",
            ctn,
        )
        is True
    )

    # Dependency failure path.
    monkeypatch.setattr(tm, "_validate_patch_dependencies", lambda *_a, **_k: False)
    assert (
        tm.validate_patch_compatibility(
            {
                "changes_applied": [{"path": "src/a.py", "change_type": "ADDED"}],
                "operation_type": "incremental_patch",
                "dependencies": ["d1"],
            },
            "snap",
            ctn,
        )
        is False
    )

    # Non-dict change object branch.
    monkeypatch.setattr(tm, "_validate_patch_dependencies", lambda *_a, **_k: True)
    change_obj = SimpleNamespace(path="src/new.py", change_type="ADDED")
    assert (
        tm.validate_patch_compatibility(
            {
                "changes_applied": [change_obj],
                "operation_type": "incremental_patch",
            },
            "snap",
            ctn,
        )
        is True
    )


def test_validate_patch_dependencies_paths(tmp_path: Path) -> None:
    ctn = tmp_path / ".ctn"
    patches = ctn / "patches"
    patches.mkdir(parents=True)

    assert tm._validate_patch_dependencies(["missing"], "snap", ctn) is False

    (patches / "bad.json").write_text("{", encoding="utf-8")
    assert tm._validate_patch_dependencies(["bad"], "snap", ctn) is False

    (patches / "failed.json").write_text(
        json.dumps({"success": False}), encoding="utf-8"
    )
    assert tm._validate_patch_dependencies(["failed"], "snap", ctn) is False

    (patches / "ok.json").write_text(json.dumps({"success": True}), encoding="utf-8")
    assert tm._validate_patch_dependencies(["ok"], "snap", ctn) is True


def test_extract_patch_deltas_and_apply_deltas_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctn = tmp_path / ".ctn"
    ctn.mkdir()
    op = _mk_patch_operation("delta-op")

    deltas = tm.extract_patch_deltas(op)
    assert deltas["operation_id"] == "delta-op"

    # Validation failure path.
    monkeypatch.setattr(tm, "validate_patch_compatibility", lambda *_a, **_k: False)
    assert tm.apply_deltas_to_snapshot(ctn, "base", deltas) is None

    # Base snapshot missing path.
    monkeypatch.setattr(tm, "validate_patch_compatibility", lambda *_a, **_k: True)
    monkeypatch.setattr(tm, "load_snapshot", lambda *_a, **_k: None)
    assert tm.apply_deltas_to_snapshot(ctn, "base", deltas) is None

    # Success path using FileChange objects (non-dict branch).
    monkeypatch.setattr(tm, "load_snapshot", lambda *_a, **_k: {"graph": {}})
    monkeypatch.setattr(
        tm,
        "incremental_patch",
        lambda *_a, **_k: {"success": True, "new_snapshot_id": "new-snap"},
    )
    object_deltas = {
        "operation_id": "obj-op",
        "changes_applied": [
            _mk_change("a.py", FileChangeType.ADDED, None, "h"),
        ],
    }
    assert tm.apply_deltas_to_snapshot(ctn, "base", object_deltas) == "new-snap"

    # Incremental patch failure path.
    monkeypatch.setattr(
        tm,
        "incremental_patch",
        lambda *_a, **_k: {"success": False, "error": "bad"},
    )
    assert tm.apply_deltas_to_snapshot(ctn, "base", object_deltas) is None

    # Exception path (dict branch tries FileChange.from_dict and fails).
    dict_deltas = {
        "operation_id": "dict-op",
        "changes_applied": [{"path": "a.py", "change_type": "ADDED"}],
    }
    assert tm.apply_deltas_to_snapshot(ctn, "base", dict_deltas) is None
