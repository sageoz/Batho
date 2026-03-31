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


@dataclass
class RepositoryConfig:
    """Repository configuration."""
    name: str
    platform: Literal["github", "gitlab"]
    secret: str
    branches: list[str] = field(default_factory=lambda: ["main", "develop"])
    path: Optional[Path] = None


@dataclass
class ProcessingConfig:
    """Processing configuration."""
    queue_backend: Literal["memory", "redis"] = "memory"
    redis_url: Optional[str] = None
    batch_size: int = 100
    timeout_seconds: int = 300


@dataclass
class RateLimitConfig:
    """Rate limiting configuration."""
    requests_per_minute: int = 60
    burst_size: int = 10


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    file: Optional[str] = None


@dataclass
class WebhookConfig:
    """Complete webhook configuration."""
    server: ServerConfig = field(default_factory=ServerConfig)
    repository: Optional[RepositoryConfig] = None
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_file(cls, path: Path) -> WebhookConfig:
        """Load configuration from YAML file."""
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        
        # Expand environment variables
        data = cls._expand_env_vars(data)
        
        return cls(
            server=ServerConfig(**data.get("server", {})),
            repository=RepositoryConfig(**data["repository"]) if "repository" in data else None,
            processing=ProcessingConfig(**data.get("processing", {})),
            rate_limit=RateLimitConfig(**data.get("rate_limit", {})),
            logging=LoggingConfig(**data.get("logging", {})),
        )
    
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
