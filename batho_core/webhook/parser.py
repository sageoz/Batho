"""Webhook event parsing for GitHub and GitLab."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from batho_core.time_machine import FileChange, FileChangeType


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


def parse_webhook_event(payload: dict[str, Any], headers: dict[str, str]) -> WebhookEvent:
    """Parse webhook event from payload and headers.
    
    Args:
        payload: Parsed JSON payload
        headers: HTTP headers
        
    Returns:
        Parsed WebhookEvent
    """
    # Detect platform
    if "X-GitHub-Event" in headers:
        return _parse_github_event(payload, headers["X-GitHub-Event"])
    elif "X-Gitlab-Event" in headers:
        return _parse_gitlab_event(payload, headers["X-Gitlab-Event"])
    else:
        raise ValueError("Unable to detect webhook platform")


def _parse_github_event(payload: dict[str, Any], event: str) -> WebhookEvent:
    """Parse GitHub webhook event."""
    repo_info = payload["repository"]
    repo_name = repo_info["full_name"]
    
    if event == "push":
        # Extract branch from ref
        ref = payload["ref"]
        if not ref.startswith("refs/heads/"):
            raise ValueError(f"Unsupported ref type: {ref}")
        branch = ref[11:]  # Remove 'refs/heads/'
        
        # Get commit hash
        commit_hash = payload["after"]
        
        # Extract file changes from commits
        changes = []
        for commit in payload.get("commits", []):
            # Added files
            for path in commit.get("added", []):
                changes.append(FileChange(
                    path=path,
                    change_type=FileChangeType.ADDED,
                    old_hash=None,
                    new_hash=commit_hash
                ))
            # Modified files
            for path in commit.get("modified", []):
                changes.append(FileChange(
                    path=path,
                    change_type=FileChangeType.MODIFIED,
                    old_hash=None,  # GitHub doesn't provide old hash in push event
                    new_hash=commit_hash
                ))
            # Removed files
            for path in commit.get("removed", []):
                changes.append(FileChange(
                    path=path,
                    change_type=FileChangeType.DELETED,
                    old_hash=None,
                    new_hash=None
                ))
        
        return WebhookEvent(
            platform=WebhookPlatform.GITHUB,
            event_type=WebhookEventType.GITHUB_PUSH,
            repository=repo_name,
            branch=branch,
            commit_hash=commit_hash,
            changes=changes,
            raw_payload=payload
        )
    
    elif event == "pull_request":
        pr = payload["pull_request"]
        action = payload["action"]
        
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
            raw_payload=payload
        )
    
    else:
        raise ValueError(f"Unsupported GitHub event: {event}")


def _parse_gitlab_event(payload: dict[str, Any], event: str) -> WebhookEvent:
    """Parse GitLab webhook event."""
    project = payload["project"]
    repo_name = project["path_with_namespace"]
    
    if event == "Push Hook":
        # Extract branch from ref
        ref = payload["ref"]
        if not ref.startswith("refs/heads/"):
            raise ValueError(f"Unsupported ref type: {ref}")
        branch = ref[11:]  # Remove 'refs/heads/'
        
        # Get commit hash
        commit_hash = payload["after"]
        
        # Extract file changes from commits
        changes = []
        for commit in payload.get("commits", []):
            # Added files
            for path in commit.get("added", []):
                changes.append(FileChange(
                    path=path,
                    change_type=FileChangeType.ADDED,
                    old_hash=None,
                    new_hash=commit["id"]
                ))
            # Modified files
            for path in commit.get("modified", []):
                changes.append(FileChange(
                    path=path,
                    change_type=FileChangeType.MODIFIED,
                    old_hash=None,
                    new_hash=commit["id"]
                ))
            # Removed files
            for path in commit.get("removed", []):
                changes.append(FileChange(
                    path=path,
                    change_type=FileChangeType.DELETED,
                    old_hash=None,
                    new_hash=None
                ))
        
        return WebhookEvent(
            platform=WebhookPlatform.GITLAB,
            event_type=WebhookEventType.GITLAB_PUSH,
            repository=repo_name,
            branch=branch,
            commit_hash=commit_hash,
            changes=changes,
            raw_payload=payload
        )
    
    elif event == "Merge Request Hook":
        # TODO: Implement GitLab MR parsing
        raise NotImplementedError("GitLab MR parsing not yet implemented")
    
    else:
        raise ValueError(f"Unsupported GitLab event: {event}")
