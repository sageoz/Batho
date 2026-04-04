"""Tests for webhook processor failure synthesis integration."""

from __future__ import annotations

import json
from pathlib import Path

from batho_core.webhook.config import WebhookConfig
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
