"""Tests for webhook functionality."""

import json
import pytest
from pathlib import Path

from batho_core.webhook import (
    WebhookConfig,
    WebhookEvent,
    parse_webhook_event,
    verify_github_signature,
    verify_gitlab_token,
)
from batho_core.webhook.auth import verify_github_signature, verify_gitlab_token


class TestWebhookConfig:
    """Test webhook configuration."""
    
    def test_from_file(self, tmp_path):
        """Test loading config from file."""
        config_data = {
            "server": {
                "host": "localhost",
                "port": 9000
            },
            "repository": {
                "name": "test/repo",
                "platform": "github",
                "secret": "test-secret",
                "branches": ["main"]
            },
            "processing": {
                "queue_backend": "sync"
            }
        }
        
        config_file = tmp_path / "webhook.yaml"
        import yaml
        config_file.write_text(yaml.dump(config_data))
        
        config = WebhookConfig.from_file(config_file)
        
        assert config.server.host == "localhost"
        assert config.server.port == 9000
        assert config.repository.name == "test/repo"
        assert config.repository.platform == "github"
        assert config.repository.secret == "test-secret"
        assert config.repository.branches == ["main"]
        assert config.processing.queue_backend == "sync"

    def test_helper_methods_for_secrets_ips_and_rate_limits(self):
        config = WebhookConfig.from_dict(
            {
                "github_secret": "top-secret",
                "allowed_ips": ["1.1.1.1", ""],
                "rate_limit": {"requests_per_hour": 20},
                "repository": {
                    "name": "org/repo",
                    "platform": "github",
                    "secret": "repo-secret",
                    "github_secret": "repo-gh",
                    "gitlab_token": "repo-gl",
                    "allowed_ips": ["2.2.2.2"],
                    "rate_limit_per_hour": 15,
                },
            }
        )

        assert config.get_github_secret() == "top-secret"
        assert config.get_gitlab_token() == "repo-gl"
        assert config.get_allowed_ips() == ["1.1.1.1", "2.2.2.2"]
        assert config.get_repo_rate_limit_per_hour() == 15

        config.github_secret = None
        config.gitlab_token = "top-gitlab"
        config.repository.rate_limit_per_hour = 0

        assert config.get_github_secret() == "repo-gh"
        assert config.get_gitlab_token() == "top-gitlab"
        assert config.get_repo_rate_limit_per_hour() == 20

    def test_from_dict_expands_environment_variables(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_TOKEN", "token-from-env")

        config = WebhookConfig.from_dict(
            {
                "gitlab_token": "${WEBHOOK_TOKEN}",
                "allowed_ips": ["${MISSING_IP:10.0.0.0/8}"],
                "repository": {
                    "name": "org/repo",
                    "platform": "github",
                    "secret": "${MISSING_SECRET:default-secret}",
                },
            }
        )

        assert config.gitlab_token == "token-from-env"
        assert config.allowed_ips == ["10.0.0.0/8"]
        assert config.repository.secret == "default-secret"


class TestWebhookAuth:
    """Test webhook authentication."""
    
    def test_github_signature_verification(self):
        """Test GitHub signature verification."""
        secret = "test-secret"
        payload = b'{"test": "payload"}'
        
        # Generate valid signature
        import hmac
        import hashlib
        signature = hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256
        ).hexdigest()
        signature_header = f"sha256={signature}"
        
        # Valid signature should pass
        assert verify_github_signature(payload, signature_header, secret)
        
        # Invalid signature should fail
        assert not verify_github_signature(payload, "sha256=invalid", secret)
        
        # Wrong secret should fail
        assert not verify_github_signature(payload, signature_header, "wrong-secret")

        # Missing or malformed signatures should fail
        assert not verify_github_signature(payload, "", secret)
        assert not verify_github_signature(payload, "sha1=abcd", secret)
        assert not verify_github_signature(payload, signature_header, None)
    
    def test_gitlab_token_verification(self):
        """Test GitLab token verification."""
        token = "test-secret"  # Token should match secret
        secret = "test-secret"
        
        # Valid token should pass
        assert verify_gitlab_token(token, secret)
        
        # Invalid token should fail
        assert not verify_gitlab_token("wrong-token", secret)
        
        # Wrong secret should fail
        assert not verify_gitlab_token(token, "wrong-secret")
        assert not verify_gitlab_token("", secret)
        assert not verify_gitlab_token(token, None)


class TestWebhookParser:
    """Test webhook event parsing."""
    
    def test_parse_github_push_event(self):
        """Test parsing GitHub push event."""
        payload = {
            "ref": "refs/heads/main",
            "after": "abc123",
            "repository": {
                "full_name": "user/repo"
            },
            "commits": [
                {
                    "id": "abc123",
                    "added": ["file1.py"],
                    "modified": ["file2.py"],
                    "removed": ["file3.py"]
                }
            ]
        }
        
        headers = {"X-GitHub-Event": "push"}
        event = parse_webhook_event(payload, headers)
        
        assert event.platform.value == "github"
        assert event.event_type.value == "push"
        assert event.repository == "user/repo"
        assert event.branch == "main"
        assert event.commit_hash == "abc123"
        assert len(event.changes) == 3
    
    def test_parse_gitlab_push_event(self):
        """Test parsing GitLab push event."""
        payload = {
            "ref": "refs/heads/main",
            "after": "def456",
            "project": {
                "path_with_namespace": "group/repo"
            },
            "commits": [
                {
                    "id": "def456",
                    "added": ["file1.py"],
                    "modified": ["file2.py"],
                    "removed": ["file3.py"]
                }
            ]
        }
        
        headers = {"X-Gitlab-Event": "Push Hook"}
        event = parse_webhook_event(payload, headers)
        
        assert event.platform.value == "gitlab"
        assert event.event_type.value == "push"
        assert event.repository == "group/repo"
        assert event.branch == "main"
        assert event.commit_hash == "def456"
        assert len(event.changes) == 3

    def test_parse_gitlab_merge_request_event(self):
        """Test parsing GitLab merge request event."""
        payload = {
            "project": {
                "path_with_namespace": "group/repo"
            },
            "object_attributes": {
                "action": "update",
                "source_branch": "feature/auth",
                "target_branch": "main",
                "last_commit": {
                    "id": "789abc"
                }
            }
        }

        headers = {"X-Gitlab-Event": "Merge Request Hook"}
        event = parse_webhook_event(payload, headers)

        assert event.platform.value == "gitlab"
        assert event.event_type.value == "merge_request_updated"
        assert event.repository == "group/repo"
        assert event.branch == "feature/auth"
        assert event.commit_hash == "789abc"
        assert event.changes == []

    def test_parse_github_pull_request_event(self):
        payload = {
            "action": "opened",
            "repository": {"full_name": "user/repo"},
            "pull_request": {
                "head": {
                    "ref": "feature/branch",
                    "sha": "abc999",
                }
            },
        }
        headers = {"X-GitHub-Event": "pull_request"}

        event = parse_webhook_event(payload, headers)
        assert event.event_type.value == "pull_request_opened"
        assert event.branch == "feature/branch"
        assert event.commit_hash == "abc999"
        assert event.changes == []

    def test_parser_error_paths(self):
        with pytest.raises(ValueError, match="Unable to detect webhook platform"):
            parse_webhook_event({}, {})

        # Missing repository full_name
        with pytest.raises(ValueError, match="repository.full_name"):
            parse_webhook_event(
                {"repository": {}, "ref": "refs/heads/main", "after": "x"},
                {"X-GitHub-Event": "push"},
            )

        # Unsupported refs and actions
        with pytest.raises(ValueError, match="Unsupported ref type"):
            parse_webhook_event(
                {
                    "repository": {"full_name": "user/repo"},
                    "ref": "refs/tags/v1",
                    "after": "abc",
                },
                {"X-GitHub-Event": "push"},
            )

        with pytest.raises(ValueError, match="Unsupported PR action"):
            parse_webhook_event(
                {
                    "repository": {"full_name": "user/repo"},
                    "action": "reopened_and_weird",
                    "pull_request": {"head": {"ref": "x", "sha": "y"}},
                },
                {"X-GitHub-Event": "pull_request"},
            )

        with pytest.raises(ValueError, match="Unsupported GitHub event"):
            parse_webhook_event(
                {"repository": {"full_name": "user/repo"}},
                {"X-GitHub-Event": "issues"},
            )

        with pytest.raises(ValueError, match="Missing project.path_with_namespace"):
            parse_webhook_event(
                {"project": {}, "ref": "refs/heads/main", "after": "abc"},
                {"X-Gitlab-Event": "Push Hook"},
            )

        with pytest.raises(ValueError, match="Unsupported ref type"):
            parse_webhook_event(
                {
                    "project": {"path_with_namespace": "group/repo"},
                    "ref": "refs/tags/v1",
                    "after": "abc",
                },
                {"X-Gitlab-Event": "Push Hook"},
            )

        with pytest.raises(ValueError, match="Unsupported GitLab MR action"):
            parse_webhook_event(
                {
                    "project": {"path_with_namespace": "group/repo"},
                    "object_attributes": {"action": "strange_action"},
                },
                {"X-Gitlab-Event": "Merge Request Hook"},
            )

        with pytest.raises(ValueError, match="Unsupported GitLab event"):
            parse_webhook_event(
                {"project": {"path_with_namespace": "group/repo"}},
                {"X-Gitlab-Event": "Issue Hook"},
            )
