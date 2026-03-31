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
                "queue_backend": "memory"
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
        assert config.processing.queue_backend == "memory"


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
