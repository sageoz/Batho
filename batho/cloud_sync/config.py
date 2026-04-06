"""Cloud sync configuration models."""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _expand_env_token(value: str) -> str:
    text = value.strip()
    if not text.startswith("${") or not text.endswith("}"):
        return value

    token = text[2:-1]
    default_value: str | None = None
    if ":" in token:
        token, default_value = token.split(":", 1)

    env_value = os.getenv(token)
    if env_value is not None:
        return env_value
    return default_value or ""


class CloudSyncConfig(BaseModel):
    enabled: bool = Field(default=False)
    endpoint: str = Field(default="")
    api_key: str = Field(default="")
    organization_id: str = Field(default="")
    project_id: str = Field(default="")
    timeout_seconds: int = Field(default=300, ge=1)
    max_retries: int = Field(default=3, ge=0, le=10)
    batch_size: int = Field(default=10, ge=1)

    @field_validator("endpoint", "api_key", "organization_id", "project_id", mode="before")
    @classmethod
    def _resolve_env_placeholder(cls, value: Any) -> Any:  # noqa: B902
        if not isinstance(value, str):
            return value
        return _expand_env_token(value)

    @field_validator("endpoint")
    @classmethod
    def _normalize_endpoint(cls, value: str) -> str:  # noqa: B902
        return value.strip().rstrip("/")

    def resolved_api_key(self) -> str:
        api_key = str(self.api_key or "").strip()
        if api_key:
            return api_key
        return str(os.getenv("BATHO_CLOUD_API_KEY", "")).strip()
