"""Configuration management for webhook server."""

from __future__ import annotations

import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional


@dataclass
class ServerConfig:
    """Server configuration."""
    host: str = "0.0.0.0"
    port: int = 8080
    workers: int = 4
    endpoint: str = "/webhook"
    health_endpoint: str = "/health"


@dataclass
class RepositoryConfig:
    """Repository configuration."""
    name: str
    platform: Literal["github", "gitlab"]
    secret: Optional[str] = None
    github_secret: Optional[str] = None
    gitlab_token: Optional[str] = None
    branches: list[str] = field(default_factory=lambda: ["main", "develop"])
    path: Optional[Path] = None
    allowed_ips: list[str] = field(default_factory=list)
    rate_limit_per_hour: int = 100


@dataclass
class ProcessingConfig:
    """Processing configuration."""
    queue_backend: Literal["celery", "sync"] = "celery"
    celery_broker_url: str = "memory://"
    celery_result_backend: str = "cache+memory://"
    task_always_eager: bool = True
    task_store_eager_result: bool = False
    batch_size: int = 100
    timeout_seconds: int = 300
    retry_attempts: int = 3


@dataclass
class RateLimitConfig:
    """Rate limiting configuration."""
    requests_per_hour: int = 100
    burst_size: int = 10


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    file: Optional[str] = None


@dataclass
class WebhookConfig:
    """Complete webhook configuration."""
    enabled: bool = True
    server: ServerConfig = field(default_factory=ServerConfig)
    repository: Optional[RepositoryConfig] = None
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    github_secret: Optional[str] = None
    gitlab_token: Optional[str] = None
    allowed_ips: list[str] = field(default_factory=list)

    def get_github_secret(self) -> Optional[str]:
        if self.github_secret:
            return self.github_secret
        if self.repository:
            return self.repository.github_secret or self.repository.secret
        return None

    def get_gitlab_token(self) -> Optional[str]:
        if self.gitlab_token:
            return self.gitlab_token
        if self.repository:
            return self.repository.gitlab_token or self.repository.secret
        return None

    def get_allowed_ips(self) -> list[str]:
        merged = list(self.allowed_ips)
        if self.repository:
            merged.extend(self.repository.allowed_ips)
        return [ip for ip in merged if ip]

    def get_repo_rate_limit_per_hour(self) -> int:
        if self.repository and self.repository.rate_limit_per_hour > 0:
            return self.repository.rate_limit_per_hour
        return max(1, self.rate_limit.requests_per_hour)

    @classmethod
    def from_dict(cls, data: dict) -> WebhookConfig:
        """Build webhook configuration from a dict section."""
        payload = cls._expand_env_vars(data or {})
        processing_data = payload.get("processing") or {}
        rate_limit_data = payload.get("rate_limit") or {}

        return cls(
            enabled=bool(payload.get("enabled", True)),
            server=ServerConfig(**(payload.get("server") or {})),
            repository=(
                RepositoryConfig(**payload["repository"])
                if payload.get("repository")
                else None
            ),
            processing=ProcessingConfig(**processing_data),
            rate_limit=RateLimitConfig(**rate_limit_data),
            logging=LoggingConfig(**(payload.get("logging") or {})),
            github_secret=payload.get("github_secret"),
            gitlab_token=payload.get("gitlab_token"),
            allowed_ips=payload.get("allowed_ips") or [],
        )

    @classmethod
    def from_file(cls, path: Path) -> WebhookConfig:
        """Load webhook configuration from a YAML file."""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data or {})
    
    @staticmethod
    def _expand_env_vars(data: dict) -> dict:
        """Recursively expand environment variables in config values."""
        if isinstance(data, dict):
            return {k: WebhookConfig._expand_env_vars(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [WebhookConfig._expand_env_vars(item) for item in data]
        elif isinstance(data, str) and data.startswith("${") and data.endswith("}"):
            env_var = data[2:-1]
            default_value = None
            if ":" in env_var:
                env_var, default_value = env_var.split(":", 1)
            return os.getenv(env_var, default_value)
        return data
