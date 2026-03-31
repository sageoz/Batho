"""Webhook handling for Batho - GitHub and GitLab integration.

Provides real-time code graph updates through webhook events.
"""

from .server import WebhookServer
from .auth import verify_github_signature, verify_gitlab_token
from .parser import WebhookEvent, parse_webhook_event
from .processor import WebhookProcessor
from .handler import WebhookHandler, WebhookResult
from .config import WebhookConfig

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
