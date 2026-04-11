"""Load and validate BSG Autoresearch YAML configuration files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

_LOGGER = logging.getLogger(__name__)

_REQUIRED_SYSTEM_KEYS = {
    "clone_root",
    "max_repo_size_mb",
    "max_files",
    "max_single_file_mb",
    "git_clone_depth",
    "iteration_timeout_sec",
    "max_iterations",
    "batho_root",
    "candidate_plugin_target",
}

_REQUIRED_LLM_KEYS = {
    "enabled",
    "provider",
    "api_base",
    "model",
    "api_key_env",
    "temperature",
    "max_tokens",
    "timeout_sec",
    "max_signals",
}

_REQUIRED_METRICS_WEIGHT_KEYS = {
    "coverage",
    "precision_proxy",
    "holdout_generalization",
    "determinism",
    "runtime_efficiency",
}

_REQUIRED_METRICS_GATE_KEYS = {
    "schema_valid",
    "deterministic_stable",
    "no_holdout_regression",
    "max_runtime_overhead_pct",
    "max_touched_entity_ratio",
}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"Config file must be a YAML mapping: {path}")
    return data


def _validate_system(cfg: dict[str, Any]) -> None:
    missing = _REQUIRED_SYSTEM_KEYS - set(cfg.keys())
    if missing:
        raise ValueError(f"system.yaml missing keys: {sorted(missing)}")

    try:
        max_iterations = int(cfg.get("max_iterations", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("system.yaml max_iterations must be an integer") from exc
    if max_iterations <= 0:
        raise ValueError("system.yaml max_iterations must be > 0")

    llm_cfg = cfg.get("llm")
    if llm_cfg is None:
        return
    _validate_llm(llm_cfg)


def _validate_llm(llm_cfg: Any) -> None:
    if not isinstance(llm_cfg, dict):
        raise ValueError("system.yaml llm must be a mapping")

    missing = _REQUIRED_LLM_KEYS - set(llm_cfg.keys())
    if missing:
        raise ValueError(f"system.yaml llm missing keys: {sorted(missing)}")

    provider = str(llm_cfg.get("provider", "")).strip().lower()
    if provider != "openrouter":
        raise ValueError("system.yaml llm.provider must be 'openrouter'")

    try:
        temperature = float(llm_cfg.get("temperature", 0.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("system.yaml llm.temperature must be a number") from exc
    if temperature < 0.0 or temperature > 2.0:
        raise ValueError("system.yaml llm.temperature must be within [0.0, 2.0]")

    try:
        max_tokens = int(llm_cfg.get("max_tokens", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("system.yaml llm.max_tokens must be an integer") from exc
    if max_tokens <= 0:
        raise ValueError("system.yaml llm.max_tokens must be > 0")

    try:
        timeout_sec = int(llm_cfg.get("timeout_sec", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("system.yaml llm.timeout_sec must be an integer") from exc
    if timeout_sec <= 0:
        raise ValueError("system.yaml llm.timeout_sec must be > 0")

    try:
        max_signals = int(llm_cfg.get("max_signals", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("system.yaml llm.max_signals must be an integer") from exc
    if max_signals < 0:
        raise ValueError("system.yaml llm.max_signals must be >= 0")


def _validate_repositories(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    repos = cfg.get("repositories")
    if not isinstance(repos, list) or not repos:
        raise ValueError(
            "repositories.yaml must contain a non-empty 'repositories' list"
        )

    required_repo_keys = {"name", "url", "language"}
    for i, repo in enumerate(repos):
        if not isinstance(repo, dict):
            raise ValueError(f"repositories[{i}] must be a mapping")
        missing = required_repo_keys - set(repo.keys())
        if missing:
            raise ValueError(
                f"repositories[{i}] ({repo.get('name', '?')}) missing keys: {sorted(missing)}"
            )
    return repos


def _validate_metrics(cfg: dict[str, Any]) -> None:
    weights = cfg.get("weights")
    if not isinstance(weights, dict):
        raise ValueError("metrics.yaml must contain a 'weights' mapping")
    missing_w = _REQUIRED_METRICS_WEIGHT_KEYS - set(weights.keys())
    if missing_w:
        raise ValueError(f"metrics.yaml weights missing keys: {sorted(missing_w)}")

    total = sum(weights.values())
    if abs(total - 1.0) > 0.01:
        raise ValueError(f"metrics.yaml weights must sum to 1.0, got {total}")

    gates = cfg.get("hard_gates")
    if not isinstance(gates, dict):
        raise ValueError("metrics.yaml must contain a 'hard_gates' mapping")
    missing_g = _REQUIRED_METRICS_GATE_KEYS - set(gates.keys())
    if missing_g:
        raise ValueError(f"metrics.yaml hard_gates missing keys: {sorted(missing_g)}")


class ConfigLoader:
    """Validated configuration bundle for BSG Autoresearch."""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir.resolve()

    def load_all(self) -> dict[str, Any]:
        system = _read_yaml(self._base / "config" / "system.yaml")
        _validate_system(system)

        repos = _read_yaml(self._base / "config" / "repositories.yaml")
        repo_list = _validate_repositories(repos)

        metrics = _read_yaml(self._base / "config" / "metrics.yaml")
        _validate_metrics(metrics)

        return {
            "system": system,
            "repositories": repo_list,
            "metrics": metrics,
        }

    @property
    def base_dir(self) -> Path:
        return self._base
