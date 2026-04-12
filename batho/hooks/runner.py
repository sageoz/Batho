from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from batho.hooks.planner import ResolvedStage
from batho.utils.logging import get_logger


LOGGER = get_logger(__name__, component="hooks_runner")


class HookExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class StageExecutionResult:
    stage: str
    command: str
    returncode: int
    elapsed_seconds: float
    timed_out: bool
    outcome: str


@dataclass(frozen=True)
class HookExecutionResult:
    hook: str
    success: bool
    stage_results: list[StageExecutionResult]

    def to_dict(self) -> dict[str, object]:
        return {
            "hook": self.hook,
            "success": self.success,
            "stages": [asdict(item) for item in self.stage_results],
        }


def _resolve_shell(shell_name: str) -> str:
    shell = shell_name.strip() or "sh"
    path = shutil.which(shell)
    if path:
        return path
    raise HookExecutionError(f"Configured shell not found: {shell}")


def execute_hook(
    *,
    hook_name: str,
    root: Path,
    stages: list[ResolvedStage],
    shell: str,
    dry_run: bool = False,
    verbose: bool = False,
) -> HookExecutionResult:
    shell_path = _resolve_shell(shell)
    stage_results: list[StageExecutionResult] = []

    for stage in stages:
        if dry_run:
            stage_results.append(
                StageExecutionResult(
                    stage=stage.name,
                    command=stage.command,
                    returncode=0,
                    elapsed_seconds=0.0,
                    timed_out=False,
                    outcome="dry-run",
                )
            )
            continue

        env = os.environ.copy()
        env.update(stage.env)

        timed_out = False
        started_at = time.perf_counter()
        try:
            completed = subprocess.run(
                stage.command,
                shell=True,
                cwd=str(root),
                executable=shell_path,
                env=env,
                timeout=stage.timeout_seconds,
                check=False,
            )
            rc = int(completed.returncode)
            elapsed = time.perf_counter() - started_at
        except subprocess.TimeoutExpired:
            timed_out = True
            rc = 124
            elapsed = time.perf_counter() - started_at

        if timed_out:
            outcome = "timeout"
        elif rc == 0:
            outcome = "ok"
        else:
            outcome = "failed"

        stage_result = StageExecutionResult(
            stage=stage.name,
            command=stage.command,
            returncode=rc,
            elapsed_seconds=round(elapsed, 4),
            timed_out=timed_out,
            outcome=outcome,
        )
        stage_results.append(stage_result)

        if verbose:
            LOGGER.info(
                "hook_stage_executed",
                hook=hook_name,
                stage=stage.name,
                outcome=outcome,
                returncode=stage_result.returncode,
                timeout_seconds=stage.timeout_seconds,
            )

        if stage_result.returncode == 0:
            continue

        if stage.on_failure == "continue":
            continue
        if stage.on_failure == "warn":
            LOGGER.warning(
                "hook_stage_failed_warn",
                hook=hook_name,
                stage=stage.name,
                returncode=stage_result.returncode,
            )
            continue

        return HookExecutionResult(hook=hook_name, success=False, stage_results=stage_results)

    return HookExecutionResult(hook=hook_name, success=True, stage_results=stage_results)
