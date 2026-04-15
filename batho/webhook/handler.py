"""High-level webhook handling orchestration."""

from __future__ import annotations

import ipaddress
import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from batho.utils.logging import get_logger

from .auth import verify_github_signature, verify_gitlab_token
from .config import WebhookConfig
from .processor import WebhookProcessor

logger = get_logger(__name__, component="webhook_handler")


@dataclass
class WebhookResult:
    """Webhook handling result."""

    status: str
    message: str
    http_status: int
    event_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_response(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "message": self.message,
        }
        if self.event_id:
            payload["event_id"] = self.event_id
        payload.update(self.details)
        return payload


class WebhookHandler:
    """Authenticates and processes webhook requests."""

    def __init__(self, config: WebhookConfig, repo_path: Path):
        self.config = config
        self.processor = WebhookProcessor(config=config, repo_path=repo_path)
        self._repo_rate_window: dict[str, deque[float]] = defaultdict(deque)
        self._delivery_seen: dict[str, float] = {}
        self._delivery_ttl_seconds = 3600

    def start(self) -> None:
        self.processor.start()

    def stop(self) -> None:
        self.processor.stop()

    def verify_github_signature(self, payload: bytes, signature: str) -> bool:
        return verify_github_signature(
            payload, signature, self.config.get_github_secret()
        )

    def verify_gitlab_token(self, token: str) -> bool:
        return verify_gitlab_token(token, self.config.get_gitlab_token())

    def handle_webhook(
        self,
        payload_bytes: bytes,
        headers: dict[str, str],
        source_ip: str | None = None,
    ) -> WebhookResult:
        if not self.config.enabled:
            return WebhookResult("disabled", "Webhook handling is disabled", 503)

        if not self._is_allowed_ip(source_ip):
            return WebhookResult("forbidden", "Source IP not allowed", 403)

        duplicate_result = self._check_and_track_delivery(headers)
        if duplicate_result is not None:
            return duplicate_result

        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except json.JSONDecodeError:
            return WebhookResult("error", "Invalid JSON payload", 400)

        auth_result = self._authenticate(payload_bytes, headers)
        if auth_result is not None:
            return auth_result

        repository = self._extract_repository(payload)
        if self._is_rate_limited(repository):
            logger.warning("webhook_rate_limited", repository=repository)
            return WebhookResult("rate_limited", "Rate limit exceeded", 429)

        result = self.processor.process_webhook(payload, headers)
        status = str(result.get("status", "error"))
        message = str(result.get("message", "Webhook processing failed"))
        event_id = result.get("event_id")

        if status == "queued":
            return WebhookResult(
                "accepted", "Webhook accepted for processing", 202, event_id
            )
        if status == "processed":
            return WebhookResult("processed", message, 200, event_id)
        if status == "ignored":
            return WebhookResult("ignored", message, 200, event_id)
        return WebhookResult("error", message, 400, event_id)

    def handle_github_webhook(
        self,
        payload_bytes: bytes,
        signature: str,
        headers: dict[str, str],
        source_ip: str | None = None,
    ) -> WebhookResult:
        merged_headers = dict(headers)
        merged_headers["X-Hub-Signature-256"] = signature
        if "X-GitHub-Event" not in merged_headers:
            merged_headers["X-GitHub-Event"] = "push"
        return self.handle_webhook(payload_bytes, merged_headers, source_ip)

    def handle_gitlab_webhook(
        self,
        payload_bytes: bytes,
        token: str,
        headers: dict[str, str],
        source_ip: str | None = None,
    ) -> WebhookResult:
        merged_headers = dict(headers)
        merged_headers["X-Gitlab-Token"] = token
        if "X-Gitlab-Event" not in merged_headers:
            merged_headers["X-Gitlab-Event"] = "Push Hook"
        return self.handle_webhook(payload_bytes, merged_headers, source_ip)

    def get_health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "queue_stats": self.processor.queue.get_stats(),
            "enabled": self.config.enabled,
        }

    def _authenticate(
        self, payload: bytes, headers: dict[str, str]
    ) -> WebhookResult | None:
        signature = self._header(headers, "X-Hub-Signature-256")
        token = self._header(headers, "X-Gitlab-Token")

        if signature:
            if not self.verify_github_signature(payload, signature):
                return WebhookResult("unauthorized", "Invalid GitHub signature", 401)
            return None

        if token:
            if not self.verify_gitlab_token(token):
                return WebhookResult("unauthorized", "Invalid GitLab token", 401)
            return None

        return WebhookResult(
            "unauthorized", "Missing webhook authentication header", 401
        )

    def _is_allowed_ip(self, source_ip: str | None) -> bool:
        allowed = self.config.get_allowed_ips()
        if not allowed:
            return True
        if not source_ip:
            return False

        try:
            remote_ip = ipaddress.ip_address(source_ip)
        except ValueError:
            return False

        for entry in allowed:
            try:
                if "/" in entry:
                    if remote_ip in ipaddress.ip_network(entry, strict=False):
                        return True
                elif remote_ip == ipaddress.ip_address(entry):
                    return True
            except ValueError:
                continue
        return False

    def _extract_repository(self, payload: dict[str, Any]) -> str:
        repository = payload.get("repository")
        if isinstance(repository, dict):
            full_name = repository.get("full_name")
            if full_name:
                return str(full_name)

        project = payload.get("project")
        if isinstance(project, dict):
            namespace = project.get("path_with_namespace") or project.get("name")
            if namespace:
                return str(namespace)

        return "unknown"

    def _is_rate_limited(self, repository: str) -> bool:
        limit = self.config.get_repo_rate_limit_per_hour()
        now = time.time()
        cutoff = now - 3600
        bucket = self._repo_rate_window[repository]

        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= limit:
            return True

        bucket.append(now)
        return False

    def _check_and_track_delivery(
        self, headers: dict[str, str]
    ) -> WebhookResult | None:
        now = time.time()
        expired = [
            k
            for k, ts in self._delivery_seen.items()
            if now - ts > self._delivery_ttl_seconds
        ]
        for key in expired:
            self._delivery_seen.pop(key, None)

        delivery_id = self._header(headers, "X-GitHub-Delivery")
        if not delivery_id:
            delivery_id = self._header(headers, "X-Gitlab-Event-UUID")

        if not delivery_id:
            return None

        if delivery_id in self._delivery_seen:
            return WebhookResult("duplicate", "Duplicate delivery ignored", 200)

        self._delivery_seen[delivery_id] = now
        return None

    @staticmethod
    def _header(headers: dict[str, str], name: str) -> str | None:
        target = name.lower()
        for key, value in headers.items():
            if key.lower() == target:
                return value
        return None
