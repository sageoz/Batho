"""Webhook event parsing for GitHub and GitLab."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from batho.time_machine import FileChange, FileChangeType


class WebhookPlatform(Enum):
    """Webhook platform."""

    GITHUB = "github"
    GITLAB = "gitlab"


class WebhookEventType(Enum):
    """Webhook event types."""

    # GitHub
    GITHUB_PUSH = "push"
    GITHUB_PR_OPENED = "pull_request_opened"
    GITHUB_PR_SYNCED = "pull_request_synchronized"
    GITHUB_PR_CLOSED = "pull_request_closed"
    # GitLab
    GITLAB_PUSH = "push"
    GITLAB_MR_OPENED = "merge_request_opened"
    GITLAB_MR_UPDATED = "merge_request_updated"
    GITLAB_MR_CLOSED = "merge_request_closed"


@dataclass
class WebhookEvent:
    """Parsed webhook event."""

    platform: WebhookPlatform
    event_type: WebhookEventType
    repository: str
    branch: str
    commit_hash: str
    changes: list[FileChange]
    raw_payload: dict[str, Any]


def parse_webhook_event(
    payload: dict[str, Any], headers: dict[str, str]
) -> WebhookEvent:
    """Parse webhook event from payload and headers.

    Args:
        payload: Parsed JSON payload
        headers: HTTP headers

    Returns:
        Parsed WebhookEvent
    """
    github_event = _header(headers, "X-GitHub-Event")
    if github_event:
        return _parse_github_event(payload, github_event)

    gitlab_event = _header(headers, "X-Gitlab-Event")
    if gitlab_event:
        return _parse_gitlab_event(payload, gitlab_event)

    raise ValueError("Unable to detect webhook platform")


def _header(headers: dict[str, str], name: str) -> str | None:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def _require(payload: dict[str, Any], key: str) -> Any:
    if key not in payload:
        raise ValueError(f"Missing required field: {key}")
    return payload[key]


def _parse_github_event(payload: dict[str, Any], event: str) -> WebhookEvent:
    """Parse GitHub webhook event."""
    repo_info = _require(payload, "repository")
    repo_name = repo_info.get("full_name")
    if not repo_name:
        raise ValueError("Missing repository.full_name")

    if event == "push":
        # Extract branch from ref
        ref = _require(payload, "ref")
        if not ref.startswith("refs/heads/"):
            raise ValueError(f"Unsupported ref type: {ref}")
        branch = ref[11:]  # Remove 'refs/heads/'

        # Get commit hash
        commit_hash = _require(payload, "after")

        # Extract file changes from commits
        changes = []
        for commit in payload.get("commits", []):
            # Added files
            for path in commit.get("added", []):
                changes.append(
                    FileChange(
                        path=path,
                        change_type=FileChangeType.ADDED,
                        old_hash=None,
                        new_hash=commit_hash,
                    )
                )
            # Modified files
            for path in commit.get("modified", []):
                changes.append(
                    FileChange(
                        path=path,
                        change_type=FileChangeType.MODIFIED,
                        old_hash=None,  # GitHub doesn't provide old hash in push event
                        new_hash=commit_hash,
                    )
                )
            # Removed files
            for path in commit.get("removed", []):
                changes.append(
                    FileChange(
                        path=path,
                        change_type=FileChangeType.DELETED,
                        old_hash=None,
                        new_hash=None,
                    )
                )

        return WebhookEvent(
            platform=WebhookPlatform.GITHUB,
            event_type=WebhookEventType.GITHUB_PUSH,
            repository=repo_name,
            branch=branch,
            commit_hash=commit_hash,
            changes=changes,
            raw_payload=payload,
        )

    elif event == "pull_request":
        pr = _require(payload, "pull_request")
        action = _require(payload, "action")

        # Map action to event type
        event_map = {
            "opened": WebhookEventType.GITHUB_PR_OPENED,
            "synchronize": WebhookEventType.GITHUB_PR_SYNCED,
            "closed": WebhookEventType.GITHUB_PR_CLOSED,
        }

        if action not in event_map:
            raise ValueError(f"Unsupported PR action: {action}")

        # Get branch from PR head
        branch = pr["head"]["ref"]
        commit_hash = pr["head"]["sha"]

        # For PRs, we'll need to fetch the diff separately
        # For now, create an empty changes list
        changes = []

        return WebhookEvent(
            platform=WebhookPlatform.GITHUB,
            event_type=event_map[action],
            repository=repo_name,
            branch=branch,
            commit_hash=commit_hash,
            changes=changes,
            raw_payload=payload,
        )

    else:
        raise ValueError(f"Unsupported GitHub event: {event}")


def _parse_gitlab_event(payload: dict[str, Any], event: str) -> WebhookEvent:
    """Parse GitLab webhook event."""
    project = _require(payload, "project")
    repo_name = project.get("path_with_namespace") or project.get("name")
    if not repo_name:
        raise ValueError("Missing project.path_with_namespace")

    if event == "Push Hook":
        # Extract branch from ref
        ref = _require(payload, "ref")
        if not ref.startswith("refs/heads/"):
            raise ValueError(f"Unsupported ref type: {ref}")
        branch = ref[11:]  # Remove 'refs/heads/'

        # Get commit hash
        commit_hash = _require(payload, "after")

        # Extract file changes from commits
        changes = []
        for commit in payload.get("commits", []):
            # Added files
            for path in commit.get("added", []):
                changes.append(
                    FileChange(
                        path=path,
                        change_type=FileChangeType.ADDED,
                        old_hash=None,
                        new_hash=commit["id"],
                    )
                )
            # Modified files
            for path in commit.get("modified", []):
                changes.append(
                    FileChange(
                        path=path,
                        change_type=FileChangeType.MODIFIED,
                        old_hash=None,
                        new_hash=commit["id"],
                    )
                )
            # Removed files
            for path in commit.get("removed", []):
                changes.append(
                    FileChange(
                        path=path,
                        change_type=FileChangeType.DELETED,
                        old_hash=None,
                        new_hash=None,
                    )
                )

        return WebhookEvent(
            platform=WebhookPlatform.GITLAB,
            event_type=WebhookEventType.GITLAB_PUSH,
            repository=repo_name,
            branch=branch,
            commit_hash=commit_hash,
            changes=changes,
            raw_payload=payload,
        )

    elif event == "Merge Request Hook":
        attrs = _require(payload, "object_attributes")
        action = attrs.get("action") or attrs.get("state")

        event_map = {
            "open": WebhookEventType.GITLAB_MR_OPENED,
            "opened": WebhookEventType.GITLAB_MR_OPENED,
            "update": WebhookEventType.GITLAB_MR_UPDATED,
            "updated": WebhookEventType.GITLAB_MR_UPDATED,
            "close": WebhookEventType.GITLAB_MR_CLOSED,
            "closed": WebhookEventType.GITLAB_MR_CLOSED,
            "merge": WebhookEventType.GITLAB_MR_CLOSED,
            "merged": WebhookEventType.GITLAB_MR_CLOSED,
        }

        if action not in event_map:
            raise ValueError(f"Unsupported GitLab MR action: {action}")

        branch = attrs.get("source_branch") or attrs.get("target_branch") or ""
        last_commit = attrs.get("last_commit") or {}
        commit_hash = last_commit.get("id") or payload.get("checkout_sha") or ""

        return WebhookEvent(
            platform=WebhookPlatform.GITLAB,
            event_type=event_map[action],
            repository=repo_name,
            branch=branch,
            commit_hash=commit_hash,
            changes=[],
            raw_payload=payload,
        )

    else:
        raise ValueError(f"Unsupported GitLab event: {event}")
