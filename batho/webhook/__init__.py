"""Webhook handling for Batho - GitHub and GitLab integration.

Provides real-time code graph updates through webhook events.
"""

from .auth import verify_github_signature, verify_gitlab_token
from .config import WebhookConfig
from .handler import WebhookHandler, WebhookResult
from .parser import WebhookEvent, parse_webhook_event
from .processor import WebhookProcessor
from .server import WebhookServer

__all__ = [
    "WebhookServer",
    "verify_github_signature",
    "verify_gitlab_token",
    "WebhookEvent",
    "parse_webhook_event",
    "WebhookProcessor",
    "WebhookHandler",
    "WebhookResult",
    "WebhookConfig",
]
