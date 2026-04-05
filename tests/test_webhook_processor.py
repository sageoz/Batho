"""Tests for webhook processor failure synthesis integration."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from batho_core.time_machine import FileChange, FileChangeType
from batho_core.webhook.config import RepositoryConfig, WebhookConfig
from batho_core.webhook.parser import (
    WebhookEvent,
    WebhookEventType,
    WebhookPlatform,
)
from batho_core.webhook.processor import WebhookProcessor
from batho_core.webhook.queue import QueueItem


def _github_push_payload() -> tuple[dict, dict]:
    payload = {
        "ref": "refs/heads/main",
        "after": "abc123",
        "repository": {"full_name": "user/repo"},
        "commits": [
            {
                "id": "abc123",
                "modified": ["src/service.py"],
                "added": [],
                "removed": [],
            }
        ],
    }
    headers = {"X-GitHub-Event": "push"}
    return payload, headers


def _change(path: str = "src/service.py") -> FileChange:
    return FileChange(
        path=path,
        change_type=FileChangeType.MODIFIED,
        old_hash=None,
        new_hash="abc123",
    )


def _event(
    *,
    repository: str = "user/repo",
    branch: str = "main",
    changes: list[FileChange] | None = None,
    event_type: WebhookEventType = WebhookEventType.GITHUB_PUSH,
) -> WebhookEvent:
    return WebhookEvent(
        platform=WebhookPlatform.GITHUB,
        event_type=event_type,
        repository=repository,
        branch=branch,
        commit_hash="abc123",
        changes=list(changes or []),
        raw_payload={},
    )


class TestWebhookProcessorEvolutionLedger:
    def test_records_failure_entry_when_incremental_patch_fails(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        config = WebhookConfig.from_dict(
            {
                "processing": {
                    "queue_backend": "sync",
                    "retry_attempts": 1,
                }
            }
        )
        processor = WebhookProcessor(config=config, repo_path=repo_path)

        monkeypatch.setattr(processor, "_find_latest_snapshot", lambda: "batho_base")
        monkeypatch.setattr(
            "batho_core.webhook.processor.incremental_patch",
            lambda _ctn, _base, _changes: {
                "success": False,
                "error": "Base snapshot not found",
                "operation_id": "op-1",
            },
        )

        payload, headers = _github_push_payload()
        queue_item = QueueItem(event_id="evt-1", event={"payload": payload, "headers": headers})

        ok = processor._handle_queue_item(queue_item)
        ledger_path = repo_path / ".ctn" / "evolution_ledger.json"

        assert ok is False
        assert ledger_path.exists()

        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        assert ledger.get("entries")
        latest = ledger["entries"][-1]
        assert latest.get("source") == "webhook.processor"
        assert "snapshot" in str(latest.get("dont_rule", "")).lower()


def test_process_webhook_returns_validation_error_for_repo_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = WebhookConfig(
        repository=RepositoryConfig(name="org/repo", platform="github", branches=["main"]),
    )
    processor = WebhookProcessor(config=config, repo_path=tmp_path)
    monkeypatch.setattr(
        "batho_core.webhook.processor.parse_webhook_event",
        lambda _payload, _headers: _event(repository="other/repo"),
    )

    result = processor.process_webhook({}, {})
    assert result["status"] == "error"
    assert "Repository mismatch" in result["message"]


def test_process_webhook_queue_unavailable_fallback_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = WebhookProcessor(config=WebhookConfig(), repo_path=tmp_path)
    monkeypatch.setattr(
        "batho_core.webhook.processor.parse_webhook_event",
        lambda _payload, _headers: _event(changes=[_change()]),
    )
    monkeypatch.setattr(processor.queue, "put", lambda _item: False)

    monkeypatch.setattr(processor, "_handle_queue_item", lambda _item: False)
    failed = processor.process_webhook({}, {})
    assert failed["status"] == "error"

    monkeypatch.setattr(processor, "_handle_queue_item", lambda _item: True)
    processed = processor.process_webhook({}, {})
    assert processed["status"] == "processed"
    assert processed["message"] == "Webhook processed synchronously"


def test_process_webhook_returns_queued_and_parse_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = WebhookProcessor(config=WebhookConfig(), repo_path=tmp_path)
    monkeypatch.setattr(
        "batho_core.webhook.processor.parse_webhook_event",
        lambda _payload, _headers: _event(changes=[_change()]),
    )
    monkeypatch.setattr(processor.queue, "put", lambda _item: True)

    queued = processor.process_webhook({}, {})
    assert queued["status"] == "queued"

    monkeypatch.setattr(
        "batho_core.webhook.processor.parse_webhook_event",
        lambda _payload, _headers: (_ for _ in ()).throw(ValueError("bad payload")),
    )
    errored = processor.process_webhook({}, {})
    assert errored["status"] == "error"
    assert "bad payload" in errored["message"]


def test_process_webhook_sync_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    processor = WebhookProcessor(config=WebhookConfig(), repo_path=tmp_path)
    monkeypatch.setattr(
        "batho_core.webhook.processor.parse_webhook_event",
        lambda _payload, _headers: _event(changes=[_change()]),
    )

    monkeypatch.setattr(processor, "_handle_queue_item", lambda _item: False)
    failed = processor.process_webhook_sync({}, {})
    assert failed["status"] == "error"
    assert "event_id" in failed

    monkeypatch.setattr(processor, "_handle_queue_item", lambda _item: True)
    processed = processor.process_webhook_sync({}, {})
    assert processed["status"] == "processed"

    monkeypatch.setattr(
        "batho_core.webhook.processor.parse_webhook_event",
        lambda _payload, _headers: (_ for _ in ()).throw(ValueError("sync failure")),
    )
    errored = processor.process_webhook_sync({}, {})
    assert errored["status"] == "error"
    assert "sync failure" in errored["message"]


def test_start_and_stop_delegate_to_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    processor = WebhookProcessor(config=WebhookConfig(), repo_path=tmp_path)
    calls = {"start": 0, "stop": 0}

    monkeypatch.setattr(
        processor.queue,
        "start_processing",
        lambda _handler: calls.__setitem__("start", calls["start"] + 1),
    )
    monkeypatch.setattr(
        processor.queue,
        "stop_processing",
        lambda: calls.__setitem__("stop", calls["stop"] + 1),
    )

    processor.start()
    processor.stop()

    assert calls == {"start": 1, "stop": 1}


def test_handle_queue_item_records_failure_when_no_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = WebhookProcessor(config=WebhookConfig(), repo_path=tmp_path)
    monkeypatch.setattr(
        "batho_core.webhook.processor.parse_webhook_event",
        lambda _payload, _headers: _event(changes=[_change("src/a.py")]),
    )
    monkeypatch.setattr(processor, "_find_latest_snapshot", lambda: None)

    recorded: dict[str, object] = {}

    def _record(**kwargs):
        recorded.update(kwargs)

    monkeypatch.setattr(processor, "_record_failure_entry", _record)

    queue_item = QueueItem(event_id="evt-1", event={"payload": {}, "headers": {}})
    ok = processor._handle_queue_item(queue_item)

    assert ok is False
    assert recorded["source"] == "webhook.processor"
    assert recorded["changed_files"] == ["src/a.py"]


def test_handle_queue_item_no_changes_short_circuit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = WebhookProcessor(config=WebhookConfig(), repo_path=tmp_path)
    monkeypatch.setattr(
        "batho_core.webhook.processor.parse_webhook_event",
        lambda _payload, _headers: _event(changes=[]),
    )
    monkeypatch.setattr(processor, "_find_latest_snapshot", lambda: "snap-1")

    queue_item = QueueItem(event_id="evt-2", event={"payload": {}, "headers": {}})
    assert processor._handle_queue_item(queue_item) is True


def test_handle_queue_item_incremental_success_and_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = WebhookProcessor(config=WebhookConfig(), repo_path=tmp_path)
    monkeypatch.setattr(processor, "_find_latest_snapshot", lambda: "base-snap")
    monkeypatch.setattr(
        "batho_core.webhook.processor.parse_webhook_event",
        lambda _payload, _headers: _event(changes=[_change("src/b.py")]),
    )

    monkeypatch.setattr(
        "batho_core.webhook.processor.incremental_patch",
        lambda _ctn, _base, _changes: {"success": True, "new_snapshot_id": "next-snap"},
    )
    success_item = QueueItem(event_id="evt-3", event={"payload": {}, "headers": {}})
    assert processor._handle_queue_item(success_item) is True
    assert processor._latest_snapshot_id == "next-snap"

    recorded: dict[str, object] = {}
    monkeypatch.setattr(
        "batho_core.webhook.processor.incremental_patch",
        lambda _ctn, _base, _changes: {
            "success": False,
            "error": "patch failed",
            "operation_id": "op-22",
        },
    )
    monkeypatch.setattr(processor, "_record_failure_entry", lambda **kwargs: recorded.update(kwargs))

    failed_item = QueueItem(event_id="evt-4", event={"payload": {}, "headers": {}})
    assert processor._handle_queue_item(failed_item) is False
    assert recorded["context"]["operation_id"] == "op-22"


def test_handle_queue_item_exception_records_unknown_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = WebhookProcessor(config=WebhookConfig(), repo_path=tmp_path)
    monkeypatch.setattr(
        "batho_core.webhook.processor.parse_webhook_event",
        lambda _payload, _headers: (_ for _ in ()).throw(RuntimeError("parse exploded")),
    )

    recorded: dict[str, object] = {}
    monkeypatch.setattr(processor, "_record_failure_entry", lambda **kwargs: recorded.update(kwargs))

    queue_item = QueueItem(event_id="evt-5", event={"payload": {}, "headers": {}})
    assert processor._handle_queue_item(queue_item) is False
    assert recorded["changed_files"] == []
    assert recorded["context"]["event_type"] == "unknown"


def test_record_failure_entry_swallows_recording_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = WebhookProcessor(config=WebhookConfig(), repo_path=tmp_path)
    monkeypatch.setattr(
        "batho_core.webhook.processor.record_failure_rule",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("write failed")),
    )

    processor._record_failure_entry(
        source="webhook.processor",
        error_message="boom",
        changed_files=["src/a.py"],
        context={"event_id": "evt-6"},
    )


def test_find_latest_snapshot_selects_newest_and_handles_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = WebhookProcessor(config=WebhookConfig(), repo_path=tmp_path)

    monkeypatch.setattr(
        "batho_core.time_machine.list_snapshots",
        lambda _ctn: [
            {"snapshot_id": "old", "created_at": "2024-01-01T00:00:00Z"},
            {"snapshot_id": "new", "created_at": "2024-02-01T00:00:00Z"},
        ],
    )
    assert processor._find_latest_snapshot() == "new"

    monkeypatch.setattr("batho_core.time_machine.list_snapshots", lambda _ctn: [])
    assert processor._find_latest_snapshot() is None


def test_validate_event_and_event_priority(tmp_path: Path) -> None:
    config = WebhookConfig(
        repository=RepositoryConfig(name="org/repo", platform="github", branches=["main"]),
    )
    processor = WebhookProcessor(config=config, repo_path=tmp_path)

    mismatch = processor._validate_event(_event(repository="other/repo"))
    assert mismatch is not None
    assert mismatch["status"] == "error"

    ignored = processor._validate_event(_event(repository="org/repo", branch="feature"))
    assert ignored is not None
    assert ignored["status"] == "ignored"

    assert processor._validate_event(_event(repository="org/repo", branch="main")) is None

    assert processor._event_priority(_event(event_type=WebhookEventType.GITHUB_PR_OPENED)) == 100
    assert (
        processor._event_priority(
            SimpleNamespace(event_type=SimpleNamespace(value="something_else"))
        )
        == 50
    )
