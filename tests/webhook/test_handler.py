from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path

import pytest

from batho.webhook.config import RepositoryConfig, WebhookConfig
from batho.webhook.handler import WebhookHandler, WebhookResult


def _handler(tmp_path: Path) -> WebhookHandler:
    cfg = WebhookConfig(
        enabled=True,
        repository=RepositoryConfig(
            name="org/repo",
            platform="github",
            github_secret="secret",
            gitlab_token="token",
            branches=["main"],
            rate_limit_per_hour=100,
        ),
    )
    return WebhookHandler(cfg, tmp_path)


def test_handle_webhook_disabled_returns_503(tmp_path: Path) -> None:
    cfg = WebhookConfig(enabled=False)
    handler = WebhookHandler(cfg, tmp_path)
    result = handler.handle_webhook(b"{}", {}, source_ip=None)
    assert result.http_status == 503
    assert result.status == "disabled"


def test_handle_webhook_rejects_ip_and_invalid_json(tmp_path: Path) -> None:
    handler = _handler(tmp_path)
    handler.config.allowed_ips = ["10.0.0.0/8"]

    forbidden = handler.handle_webhook(b"{}", {}, source_ip="1.1.1.1")
    assert forbidden.http_status == 403

    handler.config.allowed_ips = []
    bad_json = handler.handle_webhook(b"{broken", {}, source_ip="127.0.0.1")
    assert bad_json.http_status == 400


def test_handle_webhook_auth_paths_and_status_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _handler(tmp_path)

    monkeypatch.setattr(handler, "verify_github_signature", lambda *_a, **_k: False)
    unauthorized = handler.handle_webhook(
        json.dumps({"repository": {"full_name": "org/repo"}}).encode("utf-8"),
        {"X-Hub-Signature-256": "sha256=bad", "X-GitHub-Event": "push"},
        source_ip="127.0.0.1",
    )
    assert unauthorized.http_status == 401

    monkeypatch.setattr(handler, "verify_github_signature", lambda *_a, **_k: True)

    def _proc(payload, headers):
        _ = payload, headers
        return {"status": "queued", "event_id": "evt-1", "message": "queued"}

    monkeypatch.setattr(handler.processor, "process_webhook", _proc)

    accepted = handler.handle_webhook(
        json.dumps({"repository": {"full_name": "org/repo"}}).encode("utf-8"),
        {"X-Hub-Signature-256": "sha256=ok", "X-GitHub-Event": "push"},
        source_ip="127.0.0.1",
    )
    assert accepted.http_status == 202
    assert accepted.event_id == "evt-1"

    monkeypatch.setattr(handler.processor, "process_webhook", lambda *_a, **_k: {"status": "processed", "message": "done", "event_id": "evt-2"})
    processed = handler.handle_webhook(
        json.dumps({"repository": {"full_name": "org/repo"}}).encode("utf-8"),
        {"X-Hub-Signature-256": "sha256=ok", "X-GitHub-Event": "push", "X-GitHub-Delivery": "d-1"},
        source_ip="127.0.0.1",
    )
    assert processed.http_status == 200

    monkeypatch.setattr(handler.processor, "process_webhook", lambda *_a, **_k: {"status": "ignored", "message": "skip"})
    ignored = handler.handle_webhook(
        json.dumps({"repository": {"full_name": "org/repo"}}).encode("utf-8"),
        {"X-Hub-Signature-256": "sha256=ok", "X-GitHub-Event": "push", "X-GitHub-Delivery": "d-2"},
        source_ip="127.0.0.1",
    )
    assert ignored.status == "ignored"

    monkeypatch.setattr(handler.processor, "process_webhook", lambda *_a, **_k: {"status": "error", "message": "bad"})
    errored = handler.handle_webhook(
        json.dumps({"repository": {"full_name": "org/repo"}}).encode("utf-8"),
        {"X-Hub-Signature-256": "sha256=ok", "X-GitHub-Event": "push", "X-GitHub-Delivery": "d-3"},
        source_ip="127.0.0.1",
    )
    assert errored.http_status == 400


def test_duplicate_delivery_and_rate_limit_and_wrappers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _handler(tmp_path)
    monkeypatch.setattr(handler, "verify_github_signature", lambda *_a, **_k: True)
    monkeypatch.setattr(handler.processor, "process_webhook", lambda *_a, **_k: {"status": "processed", "message": "ok", "event_id": "evt"})

    payload = json.dumps({"repository": {"full_name": "org/repo"}}).encode("utf-8")
    headers = {"X-Hub-Signature-256": "sha256=ok", "X-GitHub-Event": "push", "X-GitHub-Delivery": "dup-1"}

    first = handler.handle_webhook(payload, headers, source_ip="127.0.0.1")
    second = handler.handle_webhook(payload, headers, source_ip="127.0.0.1")
    assert first.http_status == 200
    assert second.status == "duplicate"

    # Force rate limit path.
    handler.config.repository.rate_limit_per_hour = 1
    h2 = {"X-Hub-Signature-256": "sha256=ok", "X-GitHub-Event": "push", "X-GitHub-Delivery": "rl-1"}
    h3 = {"X-Hub-Signature-256": "sha256=ok", "X-GitHub-Event": "push", "X-GitHub-Delivery": "rl-2"}
    _ = handler.handle_webhook(payload, h2, source_ip="127.0.0.1")
    limited = handler.handle_webhook(payload, h3, source_ip="127.0.0.1")
    assert limited.http_status == 429

    gh = handler.handle_github_webhook(payload, "sha256=ok", {}, source_ip="127.0.0.1")
    assert gh.status in {"accepted", "processed", "ignored", "error", "rate_limited", "duplicate"}

    monkeypatch.setattr(handler, "verify_gitlab_token", lambda *_a, **_k: True)
    gl = handler.handle_gitlab_webhook(payload, "token", {}, source_ip="127.0.0.1")
    assert gl.status in {"accepted", "processed", "ignored", "error", "rate_limited", "duplicate"}


def test_get_health_and_header_and_repo_extraction(tmp_path: Path) -> None:
    handler = _handler(tmp_path)
    health = handler.get_health()
    assert "queue_stats" in health
    assert health["enabled"] is True

    assert handler._header({"X-Test": "v"}, "x-test") == "v"
    assert handler._header({}, "none") is None

    repo = handler._extract_repository({"repository": {"full_name": "org/repo"}})
    proj = handler._extract_repository({"project": {"path_with_namespace": "group/proj"}})
    unk = handler._extract_repository({})
    assert repo == "org/repo"
    assert proj == "group/proj"
    assert unk == "unknown"


def test_webhook_result_to_response_includes_event_id_and_details() -> None:
    result = WebhookResult(
        status="accepted",
        message="queued",
        http_status=202,
        event_id="evt-123",
        details={"retry_after": 10},
    )

    payload = result.to_response()
    assert payload["event_id"] == "evt-123"
    assert payload["retry_after"] == 10


def test_handler_start_stop_and_verify_wrappers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _handler(tmp_path)
    calls = {"start": 0, "stop": 0}

    monkeypatch.setattr(
        handler.processor,
        "start",
        lambda: calls.__setitem__("start", calls["start"] + 1),
    )
    monkeypatch.setattr(
        handler.processor,
        "stop",
        lambda: calls.__setitem__("stop", calls["stop"] + 1),
    )

    monkeypatch.setattr(
        "batho.webhook.handler.verify_github_signature",
        lambda _payload, _signature, secret: bool(secret),
    )
    monkeypatch.setattr(
        "batho.webhook.handler.verify_gitlab_token",
        lambda token, secret: token == secret,
    )

    handler.start()
    handler.stop()

    assert calls == {"start": 1, "stop": 1}
    assert handler.verify_github_signature(b"{}", "sha256=x") is True
    assert handler.verify_gitlab_token("token") is True


def test_authentication_ip_validation_and_cleanup_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _handler(tmp_path)

    monkeypatch.setattr(handler, "verify_gitlab_token", lambda _token: False)
    invalid_token = handler._authenticate(b"{}", {"X-Gitlab-Token": "bad"})
    assert invalid_token is not None
    assert invalid_token.http_status == 401

    missing_auth = handler._authenticate(b"{}", {})
    assert missing_auth is not None
    assert missing_auth.message.startswith("Missing webhook authentication")

    handler.config.allowed_ips = ["10.0.0.0/8", "127.0.0.1", "invalid-entry"]
    assert handler._is_allowed_ip(None) is False
    assert handler._is_allowed_ip("not-an-ip") is False
    assert handler._is_allowed_ip("10.1.2.3") is True
    assert handler._is_allowed_ip("127.0.0.1") is True
    assert handler._is_allowed_ip("8.8.8.8") is False

    handler.config.repository.rate_limit_per_hour = 1
    handler._repo_rate_window["org/repo"] = deque([time.time() - 7200])
    assert handler._is_rate_limited("org/repo") is False
    assert handler._is_rate_limited("org/repo") is True

    handler._delivery_seen = {"expired-delivery": time.time() - 7200}
    assert handler._check_and_track_delivery({}) is None
    assert "expired-delivery" not in handler._delivery_seen
