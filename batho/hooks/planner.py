from __future__ import annotations

from dataclasses import dataclass

from batho.hooks.constants import BUILTIN_TEMPLATE_CATALOG, SUPPORTED_GIT_CLIENT_HOOKS
from batho.hooks.models import HookPlan, HooksFile, OnFailurePolicy


@dataclass(frozen=True)
class ResolvedStage:
    name: str
    command: str
    timeout_seconds: int
    on_failure: OnFailurePolicy
    env: dict[str, str]
    source_template: str | None = None


class HookPlanningError(ValueError):
    pass


def is_supported_git_hook(name: str) -> bool:
    return name in SUPPORTED_GIT_CLIENT_HOOKS


def supported_git_hooks() -> list[str]:
    return list(SUPPORTED_GIT_CLIENT_HOOKS)


def _merged_templates(hooks_file: HooksFile) -> dict[str, dict[str, object]]:
    merged = {key: dict(value) for key, value in BUILTIN_TEMPLATE_CATALOG.items()}
    for key, template in hooks_file.templates.items():
        merged[key] = {
            "description": template.description,
            "run": template.run,
            "timeout_seconds": template.timeout_seconds,
            "on_failure": template.on_failure,
            "env": dict(template.env),
        }
    return merged


def configured_hook_names(hooks_file: HooksFile) -> list[str]:
    return sorted(hooks_file.hooks.keys())


def enabled_hook_names(hooks_file: HooksFile) -> list[str]:
    return sorted(name for name, hook in hooks_file.hooks.items() if hook.enabled)


def resolve_hook_plan(
    hooks_file: HooksFile, hook_name: str
) -> tuple[HookPlan, list[ResolvedStage]]:
    hook = hooks_file.hooks.get(hook_name)
    if hook is None:
        raise HookPlanningError(
            f"Hook '{hook_name}' is not defined in .batho/hooks.yaml"
        )
    if not hook.stages:
        raise HookPlanningError(f"Hook '{hook_name}' has no configured stages")

    templates = _merged_templates(hooks_file)
    default_policy: OnFailurePolicy = (
        "fail" if hooks_file.defaults.fail_fast else "warn"
    )

    resolved: list[ResolvedStage] = []
    for index, stage in enumerate(hook.stages, start=1):
        source_template = None
        stage_template: dict[str, object] | None = None
        if stage.template:
            source_template = stage.template
            stage_template = templates.get(stage.template)
            if stage_template is None:
                raise HookPlanningError(
                    f"Hook '{hook_name}' references unknown template '{stage.template}'"
                )

        command = stage.run or (
            str(stage_template.get("run")) if stage_template else None
        )
        if not command:
            raise HookPlanningError(
                f"Hook '{hook_name}' stage {index} has no runnable command"
            )

        timeout_seconds = int(
            stage.timeout_seconds
            or (stage_template.get("timeout_seconds") if stage_template else 0)
            or hook.timeout_seconds
            or hooks_file.defaults.timeout_seconds
        )

        on_failure = (
            stage.on_failure
            or (stage_template.get("on_failure") if stage_template else None)
            or hook.on_failure
            or default_policy
        )

        env: dict[str, str] = {}
        env.update({k: str(v) for k, v in hooks_file.defaults.env.items()})
        if stage_template:
            env.update(
                {k: str(v) for k, v in dict(stage_template.get("env") or {}).items()}
            )
        env.update({k: str(v) for k, v in stage.env.items()})

        resolved.append(
            ResolvedStage(
                name=stage.name or stage.template or f"stage-{index}",
                command=str(command),
                timeout_seconds=max(1, timeout_seconds),
                on_failure=on_failure,
                env=env,
                source_template=source_template,
            )
        )

    return hook, resolved


def list_template_catalog(hooks_file: HooksFile) -> dict[str, list[str]]:
    return {
        "builtin": sorted(BUILTIN_TEMPLATE_CATALOG.keys()),
        "custom": sorted(hooks_file.templates.keys()),
    }
