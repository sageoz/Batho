"""Evaluate candidate plugins against repository sets with weighted scoring."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

from batho.bsg import apply_rule_plugins
from batho.config import get_config_cached
from batho.context.codegraph import CodeGraphIndexer

_LOGGER = logging.getLogger(__name__)


def _compute_plugin_fingerprint(plugin_doc: dict[str, Any]) -> str:
    """Deterministic fingerprint of plugin rules (IDs + order)."""
    rules = plugin_doc.get("rules", [])
    ids = [r.get("rule_id", "") for r in rules]
    payload = json.dumps(ids, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_plugin_stats(plugin_doc: dict[str, Any]) -> dict[str, Any]:
    """Compute basic statistics about a plugin document."""

    rules = plugin_doc.get("rules", [])
    rule_ids = [r.get("rule_id", "") for r in rules]

    entity_type_counts: dict[str, int] = {}
    file_pattern_count = 0
    ast_edge_count = 0
    tag_count = 0

    for rule in rules:
        matchers = rule.get("matchers", {})
        for et in matchers.get("entity_types", []):
            entity_type_counts[et] = entity_type_counts.get(et, 0) + 1
        file_pattern_count += len(matchers.get("file_patterns", []))
        ast_edges = matchers.get("ast_edges", {})
        ast_edge_count += len(ast_edges.get("any", [])) + len(ast_edges.get("all", []))

        actions = rule.get("actions", {})
        tag_count += len(actions.get("add_usn_tags", []))

    return {
        "total_rules": len(rules),
        "rule_ids": rule_ids,
        "fingerprint": _compute_plugin_fingerprint(plugin_doc),
        "entity_type_counts": entity_type_counts,
        "file_pattern_count": file_pattern_count,
        "ast_edge_count": ast_edge_count,
        "tag_count": tag_count,
    }


@contextmanager
def _rules_temporarily_disabled() -> Any:
    original = os.environ.get("BATHO_RULES_ENABLED")
    os.environ["BATHO_RULES_ENABLED"] = "0"
    get_config_cached.cache_clear()
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("BATHO_RULES_ENABLED", None)
        else:
            os.environ["BATHO_RULES_ENABLED"] = original
        get_config_cached.cache_clear()


def _rules_config_for_candidate(candidate_plugin_path: Path) -> dict[str, Any]:
    return {
        "enabled": True,
        "builtin_plugins": [],
        "disabled_rules": [],
        "custom_rules_path": str(candidate_plugin_path.resolve()),
        "custom_rules_inline": [],
        "strict_validation": True,
        "cache_ttl": 0,
    }


def _evaluate_single_repo(
    repo_path: Path,
    candidate_plugin_path: Path,
    *,
    max_file_size_kb: int,
    max_workers: int,
) -> dict[str, Any]:
    repo_name = repo_path.name

    try:
        index_start = time.perf_counter()
        with _rules_temporarily_disabled():
            indexer = CodeGraphIndexer(root=str(repo_path))
            graph = indexer.build_graph(
                root=str(repo_path),
                max_workers=max_workers,
                max_file_size_kb=max_file_size_kb,
                verbose=False,
            )
            index_stats = dict(indexer.stats)
        index_elapsed = time.perf_counter() - index_start

        rules_start = time.perf_counter()
        rule_stats = apply_rule_plugins(
            graph=graph,
            root_path=repo_path,
            rules_config=_rules_config_for_candidate(candidate_plugin_path),
        )
        rules_elapsed = time.perf_counter() - rules_start

        entity_count = int(index_stats.get("entity_count", len(graph.entities)))
        entities_updated = int(rule_stats.get("entities_updated", 0))
        rules_loaded = int(rule_stats.get("rules_loaded", 0))
        matched_rules = len(rule_stats.get("rule_hits", {}))

        coverage = entities_updated / max(1, entity_count)
        precision_proxy = matched_rules / max(1, rules_loaded)

        return {
            "ok": True,
            "repo": repo_name,
            "path": str(repo_path),
            "entity_count": entity_count,
            "entities_updated": entities_updated,
            "rules_loaded": rules_loaded,
            "matched_rules": matched_rules,
            "coverage": coverage,
            "precision_proxy": precision_proxy,
            "index_elapsed_sec": round(index_elapsed, 4),
            "rules_elapsed_sec": round(rules_elapsed, 4),
            "runtime_seconds": round(index_elapsed + rules_elapsed, 4),
            "index_stats": index_stats,
            "rule_stats": rule_stats,
        }
    except Exception as exc:
        _LOGGER.warning("repo evaluation failed", repo=repo_name, error=str(exc))
        return {
            "ok": False,
            "repo": repo_name,
            "path": str(repo_path),
            "error": str(exc),
            "entity_count": 0,
            "entities_updated": 0,
            "rules_loaded": 0,
            "matched_rules": 0,
            "coverage": 0.0,
            "precision_proxy": 0.0,
            "runtime_seconds": 0.0,
        }


def _evaluate_repo_set(
    repo_paths: list[Path],
    candidate_plugin_path: Path,
    *,
    max_file_size_kb: int,
    max_workers: int,
) -> dict[str, Any]:
    results = [
        _evaluate_single_repo(
            path,
            candidate_plugin_path,
            max_file_size_kb=max_file_size_kb,
            max_workers=max_workers,
        )
        for path in repo_paths
    ]

    valid = [item for item in results if item.get("ok")]

    total_entities = int(sum(int(item.get("entity_count", 0)) for item in valid))
    total_updated = int(sum(int(item.get("entities_updated", 0)) for item in valid))
    total_rules_loaded = int(sum(int(item.get("rules_loaded", 0)) for item in valid))
    total_matched_rules = int(sum(int(item.get("matched_rules", 0)) for item in valid))
    runtime_seconds = float(sum(float(item.get("runtime_seconds", 0.0)) for item in valid))

    coverage = total_updated / max(1, total_entities)
    precision_proxy = total_matched_rules / max(1, total_rules_loaded)

    return {
        "repo_count": len(repo_paths),
        "repo_count_evaluated": len(valid),
        "repo_count_failed": len(results) - len(valid),
        "failed_repos": [item.get("repo") for item in results if not item.get("ok")],
        "total_entities": total_entities,
        "total_entities_updated": total_updated,
        "total_rules_loaded": total_rules_loaded,
        "total_matched_rules": total_matched_rules,
        "coverage": coverage,
        "precision_proxy": precision_proxy,
        "runtime_seconds": runtime_seconds,
        "repos": results,
    }


def score_plugin(
    plugin_doc: dict[str, Any],
    metrics_config: dict[str, Any],
    *,
    train_repo_paths: list[Path] | None = None,
    holdout_repo_paths: list[Path] | None = None,
    candidate_plugin_path: Path | None = None,
    baseline_stats: dict[str, Any] | None = None,
    max_file_size_kb: int = 500,
    max_workers: int = 0,
) -> dict[str, Any]:
    """Score a candidate plugin using the weighted metric formula.

    Returns a score dict with:
      - score: weighted scalar
      - coverage: observed entity update coverage over evaluated repos
      - precision_proxy: observed matched_rule / loaded_rule ratio
      - holdout_generalization: holdout quality normalized by train quality
      - determinism: 1.0 when deterministic stability check passes
      - runtime_efficiency: efficiency normalized against baseline runtime
      - hard_gates: dict of gate_name → passed bool
    """

    weights = metrics_config.get("weights", {})
    gates = metrics_config.get("hard_gates", {})

    stats = compute_plugin_stats(plugin_doc)

    # Hard gate checks
    try:
        from .plugin_validator import check_determinism, validate_plugin
    except ImportError:
        from services.plugin_validator import check_determinism, validate_plugin

    is_valid, schema_errors = validate_plugin(plugin_doc)

    temp_path: Path | None = None
    plugin_path: Path
    if candidate_plugin_path is not None:
        plugin_path = candidate_plugin_path.resolve()
    else:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
        temp_path = Path(tmp.name)
        tmp.write(
            yaml.safe_dump(
                plugin_doc,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
        )
        tmp.close()
        plugin_path = temp_path

    try:
        train_summary = _evaluate_repo_set(
            repo_paths=list(train_repo_paths or []),
            candidate_plugin_path=plugin_path,
            max_file_size_kb=max_file_size_kb,
            max_workers=max_workers,
        )
        holdout_summary = _evaluate_repo_set(
            repo_paths=list(holdout_repo_paths or []),
            candidate_plugin_path=plugin_path,
            max_file_size_kb=max_file_size_kb,
            max_workers=max_workers,
        )
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

    combined_entities = int(
        train_summary.get("total_entities", 0) + holdout_summary.get("total_entities", 0)
    )
    combined_entities_updated = int(
        train_summary.get("total_entities_updated", 0)
        + holdout_summary.get("total_entities_updated", 0)
    )

    coverage = combined_entities_updated / max(1, combined_entities)

    train_precision = float(train_summary.get("precision_proxy", 0.0))
    holdout_precision = float(holdout_summary.get("precision_proxy", 0.0))
    precision_proxy = (train_precision + holdout_precision) / 2.0

    train_quality = (
        float(train_summary.get("coverage", 0.0)) + float(train_summary.get("precision_proxy", 0.0))
    ) / 2.0
    holdout_quality = (
        float(holdout_summary.get("coverage", 0.0))
        + float(holdout_summary.get("precision_proxy", 0.0))
    ) / 2.0
    if train_quality <= 0 and holdout_quality <= 0:
        holdout_generalization = 1.0
    else:
        holdout_generalization = min(1.0, holdout_quality / max(train_quality, 1e-6))

    deterministic_stable = check_determinism(plugin_doc)
    determinism = 1.0 if deterministic_stable else 0.0

    runtime_seconds = float(train_summary.get("runtime_seconds", 0.0)) + float(
        holdout_summary.get("runtime_seconds", 0.0)
    )
    baseline_runtime = (
        float(baseline_stats.get("runtime_seconds", runtime_seconds))
        if baseline_stats
        else runtime_seconds
    )
    if baseline_runtime <= 0:
        runtime_overhead_pct = 0.0
    else:
        runtime_overhead_pct = ((runtime_seconds - baseline_runtime) / baseline_runtime) * 100.0

    if runtime_overhead_pct <= 0:
        runtime_efficiency = 1.0
    else:
        runtime_efficiency = max(0.0, 1.0 - (runtime_overhead_pct / 100.0))

    touched_entity_ratio = combined_entities_updated / max(1, combined_entities)

    score = (
        weights.get("coverage", 0.35) * coverage
        + weights.get("precision_proxy", 0.25) * precision_proxy
        + weights.get("holdout_generalization", 0.20) * holdout_generalization
        + weights.get("determinism", 0.10) * determinism
        + weights.get("runtime_efficiency", 0.10) * runtime_efficiency
    )

    hard_gates: dict[str, Any] = {
        "schema_valid": is_valid,
        "deterministic_stable": deterministic_stable,
        "no_holdout_regression": True,
        "max_runtime_overhead_pct": runtime_overhead_pct
        <= float(gates.get("max_runtime_overhead_pct", 20)),
        "max_touched_entity_ratio": touched_entity_ratio
        <= float(gates.get("max_touched_entity_ratio", 0.30)),
    }

    if baseline_stats:
        baseline_holdout = float(baseline_stats.get("holdout_quality", 0.0))
        hard_gates["no_holdout_regression"] = holdout_quality >= baseline_holdout

    return {
        "score": round(score, 6),
        "coverage": round(coverage, 4),
        "precision_proxy": round(precision_proxy, 4),
        "holdout_generalization": round(holdout_generalization, 4),
        "determinism": round(determinism, 4),
        "runtime_efficiency": round(runtime_efficiency, 4),
        "train_quality": round(train_quality, 4),
        "holdout_quality": round(holdout_quality, 4),
        "runtime_seconds": round(runtime_seconds, 4),
        "runtime_overhead_pct": round(runtime_overhead_pct, 4),
        "touched_entity_ratio": round(touched_entity_ratio, 4),
        "train_summary": train_summary,
        "holdout_summary": holdout_summary,
        "plugin_stats": stats,
        "hard_gates": hard_gates,
        "schema_errors": schema_errors if not is_valid else [],
    }


def compute_baseline(
    baseline_plugin_path: Path,
    metrics_config: dict[str, Any],
    *,
    train_repo_paths: list[Path] | None = None,
    holdout_repo_paths: list[Path] | None = None,
    max_file_size_kb: int = 500,
    max_workers: int = 0,
) -> dict[str, Any]:
    """Compute baseline score from an existing plugin file (or empty if none)."""

    baseline_doc: dict[str, Any] | None = None
    if baseline_plugin_path.exists():
        try:
            text = baseline_plugin_path.read_text(encoding="utf-8")
            plugin_doc = yaml.safe_load(text)
            if isinstance(plugin_doc, dict):
                baseline_doc = plugin_doc
        except Exception as exc:
            _LOGGER.warning("failed to load baseline plugin: %s", exc)

    # Empty baseline
    if baseline_doc is None:
        baseline_doc = {
            "schema_version": "bsg-plugin.v1",
            "plugin_id": "empty_baseline",
            "name": "Empty Baseline",
            "version": "0.0.0",
            "enabled": True,
            "rules": [],
        }

    return score_plugin(
        baseline_doc,
        metrics_config,
        train_repo_paths=list(train_repo_paths or []),
        holdout_repo_paths=list(holdout_repo_paths or []),
        candidate_plugin_path=baseline_plugin_path if baseline_plugin_path.exists() else None,
        baseline_stats=None,
        max_file_size_kb=max_file_size_kb,
        max_workers=max_workers,
    )
