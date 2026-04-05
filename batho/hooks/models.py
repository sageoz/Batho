from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from batho.hooks.constants import HOOKS_SCHEMA_VERSION


OnFailurePolicy = Literal["fail", "warn", "continue"]


class HooksDefaults(BaseModel):
    shell: str = Field(default="sh")
    timeout_seconds: int = Field(default=300, ge=1)
    fail_fast: bool = Field(default=True)
    env: dict[str, str] = Field(default_factory=dict)


class HooksTemplate(BaseModel):
    description: str | None = None
    run: str
    timeout_seconds: int | None = Field(default=None, ge=1)
    on_failure: OnFailurePolicy | None = None
    env: dict[str, str] = Field(default_factory=dict)


class HookStage(BaseModel):
    name: str | None = None
    template: str | None = None
    run: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)
    on_failure: OnFailurePolicy | None = None
    env: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_stage_source(self) -> "HookStage":
        if not self.template and not self.run:
            raise ValueError("stage must include either 'template' or 'run'")
        return self


class HookPlan(BaseModel):
    enabled: bool = True
    description: str | None = None
    stages: list[HookStage] = Field(default_factory=list)
    on_failure: OnFailurePolicy | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)


class HooksFile(BaseModel):
    version: str = Field(default=HOOKS_SCHEMA_VERSION)
    defaults: HooksDefaults = Field(default_factory=HooksDefaults)
    templates: dict[str, HooksTemplate] = Field(default_factory=dict)
    hooks: dict[str, HookPlan] = Field(default_factory=dict)

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        if value != HOOKS_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported hooks schema version: {value}. Expected: {HOOKS_SCHEMA_VERSION}"
            )
        return value

    @field_validator("hooks")
    @classmethod
    def _validate_hook_names(
        cls, value: dict[str, HookPlan], info: ValidationInfo
    ) -> dict[str, HookPlan]:
        normalized: dict[str, HookPlan] = {}
        for name, payload in value.items():
            key = str(name).strip()
            if not key:
                raise ValueError("Hook names must be non-empty")
            if key in normalized:
                raise ValueError(f"Duplicate hook name: {key}")
            normalized[key] = payload
        return normalized
