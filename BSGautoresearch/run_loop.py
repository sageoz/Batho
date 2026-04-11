"""BSG Autoresearch — Run Loop (orchestrator: propose -> evaluate -> keep/revert).

Orchestrates the full autoresearch loop:
  1. Prepare (if not already done)
  2. Train — mine conventions, generate candidate
  3. Evaluate — score candidate
  4. Gate — accept if strictly better, else revert
  5. Repeat until budget exhausted
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Add parent to path for service imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.config_loader import ConfigLoader
from services.repo_registry import split_repos
from services.repo_cloner import ensure_all_repos
from services.repo_filter import check_repo, collect_source_files
from services.convention_miner import mine_conventions, aggregate_conventions
from services.rule_compiler import compile_rules, write_candidate
from services.llm_client import OpenRouterClient, merge_signals
from services.plugin_validator import validate_plugin_file
from services.evaluator import score_plugin, compute_baseline
from services.git_gate import accept_candidate, revert_candidate, check_tree_clean
from services.ledger import Ledger

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger(__name__)


def _all_gates_passed(hard_gates: dict) -> bool:
    return all(hard_gates.values())


def _gate_failure_reasons(hard_gates: dict) -> list[str]:
    return [name for name, passed in hard_gates.items() if not passed]


def run_loop(
    base_dir: Path,
    *,
    max_iterations: int | None = None,
    allow_dirty: bool = False,
) -> dict:
    """Execute the full autoresearch loop.

    Returns a summary dict with final state.
    """

    loader = ConfigLoader(base_dir)
    configs = loader.load_all()

    system = configs["system"]
    repos = configs["repositories"]
    metrics = configs["metrics"]
    llm_cfg = system.get("llm") if isinstance(system.get("llm"), dict) else None
    llm_client = OpenRouterClient(llm_cfg or {}) if llm_cfg else None
    configured_max_iterations = int(system.get("max_iterations", 10))
    effective_max_iterations = (
        int(max_iterations) if max_iterations is not None else configured_max_iterations
    )

    # Resolve paths
    batho_root = (base_dir / system["batho_root"]).resolve()
    clone_root_str = system["clone_root"]
    clone_root = (
        (base_dir / clone_root_str).resolve()
        if not Path(clone_root_str).is_absolute()
        else Path(clone_root_str)
    )
    candidate_target = system["candidate_plugin_target"]
    plugin_target = batho_root / candidate_target
    accepted_dir = base_dir / "generated" / "accepted"

    _LOGGER.info("batho_root=%s", batho_root)
    _LOGGER.info("clone_root=%s", clone_root)
    _LOGGER.info("plugin_target=%s", plugin_target)

    # Check tree cleanliness
    check_tree_clean(batho_root, allow_dirty=allow_dirty)

    # Initialize ledger
    state_dir = base_dir / "state"
    ledger = Ledger(state_dir)

    # Check if prepare has been run
    loop_state = ledger.read_loop_state()
    if loop_state.get("status") not in ("prepared", "completed", "reverted"):
        _LOGGER.info("running prepare phase first...")
        from prepare import prepare

        prepare(base_dir, allow_dirty=allow_dirty)

    # Get train/holdout split
    train_repos, holdout_repos = split_repos(repos, holdout_count=2)

    # Clone all repos
    depth = int(system.get("git_clone_depth", 1))
    all_repos = train_repos + holdout_repos
    repo_paths = ensure_all_repos(all_repos, clone_root, depth=depth)

    # Filter
    max_size = float(system.get("max_repo_size_mb", 500))
    max_files = int(system.get("max_files", 200000))
    max_file_size = float(system.get("max_single_file_mb", 10))

    # Collect train files
    train_files_by_repo: dict[str, list[Path]] = {}
    for repo in train_repos:
        repo_path = repo_paths[repo["name"]]
        passes, reasons = check_repo(
            repo,
            repo_path,
            max_size_mb=max_size,
            max_files=max_files,
            max_single_file_mb=max_file_size,
        )
        if not passes:
            _LOGGER.warning(
                "skipping train repo %s: %s", repo["name"], "; ".join(reasons)
            )
            continue
        include = repo.get("include_globs", ["**/*"])
        exclude = repo.get("exclude_globs", [])
        files = collect_source_files(repo_path, include, exclude)
        train_files_by_repo[repo["name"]] = files

    # Collect holdout files
    holdout_files_by_repo: dict[str, list[Path]] = {}
    for repo in holdout_repos:
        repo_path = repo_paths[repo["name"]]
        passes, reasons = check_repo(
            repo,
            repo_path,
            max_size_mb=max_size,
            max_files=max_files,
            max_single_file_mb=max_file_size,
        )
        if not passes:
            _LOGGER.warning(
                "skipping holdout repo %s: %s", repo["name"], "; ".join(reasons)
            )
            continue
        include = repo.get("include_globs", ["**/*"])
        exclude = repo.get("exclude_globs", [])
        files = collect_source_files(repo_path, include, exclude)
        holdout_files_by_repo[repo["name"]] = files

    train_repo_paths = [repo_paths[name] for name in train_files_by_repo]
    holdout_repo_paths = [repo_paths[name] for name in holdout_files_by_repo]

    # Compute baseline
    baseline = compute_baseline(
        plugin_target,
        metrics,
        train_repo_paths=train_repo_paths,
        holdout_repo_paths=holdout_repo_paths,
        max_file_size_kb=max(1, int(max_file_size * 1024)),
        max_workers=0,
    )
    best_score = ledger.get_best_score()
    if best_score <= 0:
        best_score = baseline["score"]
        ledger.update_best_score(best_score)

    _LOGGER.info(
        "baseline score: %.6f, best score: %.6f", baseline["score"], best_score
    )

    # Main loop
    iteration_timeout = int(system.get("iteration_timeout_sec", 600))
    results: list[dict] = []

    for _ in range(effective_max_iterations):
        iter_num = ledger.increment_iteration()
        iter_start = time.time()

        _LOGGER.info("=== iteration %d ===", iter_num)

        try:
            # Train: mine conventions from train repos
            repo_conventions: list[dict] = []
            for repo in train_repos:
                if repo["name"] not in train_files_by_repo:
                    continue
                files = train_files_by_repo[repo["name"]]
                repo_path = repo_paths[repo["name"]]
                conventions = mine_conventions(files, repo["language"], repo_path)
                repo_conventions.append(conventions)

            if not repo_conventions:
                _LOGGER.error("no valid train repos with files")
                break

            # Aggregate + compile
            aggregated = aggregate_conventions(repo_conventions)
            if llm_client and llm_client.enabled:
                llm_signals = llm_client.propose_signals(
                    aggregated,
                    max_signals=int((llm_cfg or {}).get("max_signals", 6)),
                )
                if llm_signals:
                    aggregated["signals"] = merge_signals(
                        aggregated["signals"],
                        llm_signals,
                    )
            plugin_doc = compile_rules(aggregated)

            # Write candidate to Batho plugin target
            write_candidate(plugin_doc, plugin_target)

            # Also write to local candidate
            candidate_path = base_dir / "generated" / "candidate_plugin.yaml"
            write_candidate(plugin_doc, candidate_path)

            # Validate
            is_valid, schema_errors, _ = validate_plugin_file(candidate_path)
            if not is_valid:
                _LOGGER.error("candidate schema invalid: %s", schema_errors)
                decision = revert_candidate(
                    batho_root,
                    candidate_target,
                    iteration=iter_num,
                    score=0.0,
                    best_score=best_score,
                    reason=f"schema_invalid: {schema_errors}",
                )
                ledger.append_decision(decision)
                results.append({"iteration": iter_num, **decision})
                continue

            # Evaluate
            evaluation = score_plugin(
                plugin_doc,
                metrics,
                train_repo_paths=train_repo_paths,
                holdout_repo_paths=holdout_repo_paths,
                candidate_plugin_path=candidate_path,
                baseline_stats=baseline,
                max_file_size_kb=max(1, int(max_file_size * 1024)),
                max_workers=0,
            )
            candidate_score = evaluation["score"]
            hard_gates = evaluation["hard_gates"]

            _LOGGER.info(
                "iter %d: score=%.6f best=%.6f gates=%s",
                iter_num,
                candidate_score,
                best_score,
                hard_gates,
            )

            # Log metrics
            ledger.append_metrics(
                iter_num,
                {
                    "phase": "evaluate",
                    "score": candidate_score,
                    "coverage": evaluation["coverage"],
                    "precision_proxy": evaluation["precision_proxy"],
                    "holdout_generalization": evaluation["holdout_generalization"],
                    "determinism": evaluation["determinism"],
                    "runtime_efficiency": evaluation["runtime_efficiency"],
                    "runtime_seconds": evaluation.get("runtime_seconds", 0.0),
                    "runtime_overhead_pct": evaluation.get("runtime_overhead_pct", 0.0),
                    "touched_entity_ratio": evaluation.get("touched_entity_ratio", 0.0),
                    "train_summary": evaluation.get("train_summary", {}),
                    "holdout_summary": evaluation.get("holdout_summary", {}),
                    "plugin_stats": evaluation["plugin_stats"],
                    "hard_gates": hard_gates,
                },
            )

            # Gate decision
            if candidate_score > best_score and _all_gates_passed(hard_gates):
                decision = accept_candidate(
                    batho_root,
                    candidate_target,
                    iteration=iter_num,
                    score=candidate_score,
                    best_score=best_score,
                    plugin_doc=plugin_doc,
                    accepted_dir=accepted_dir,
                )
                best_score = candidate_score
                ledger.update_best_score(best_score)
                baseline = evaluation
            else:
                reasons = []
                if candidate_score <= best_score:
                    reasons.append(
                        f"score {candidate_score:.6f} <= best {best_score:.6f}"
                    )
                if not _all_gates_passed(hard_gates):
                    reasons.append(
                        f"gate failures: {_gate_failure_reasons(hard_gates)}"
                    )

                decision = revert_candidate(
                    batho_root,
                    candidate_target,
                    iteration=iter_num,
                    score=candidate_score,
                    best_score=best_score,
                    reason="; ".join(reasons),
                )

            ledger.append_decision(decision)
            elapsed = time.time() - iter_start
            decision["elapsed_sec"] = round(elapsed, 2)
            results.append({"iteration": iter_num, **decision})

            # Check timeout
            if elapsed > iteration_timeout:
                _LOGGER.warning(
                    "iteration %d exceeded timeout (%.1fs > %ds)",
                    iter_num,
                    elapsed,
                    iteration_timeout,
                )

        except Exception as exc:
            _LOGGER.error("iteration %d failed: %s", iter_num, exc, exc_info=True)
            try:
                revert_candidate(
                    batho_root,
                    candidate_target,
                    iteration=iter_num,
                    score=0.0,
                    best_score=best_score,
                    reason=f"exception: {exc}",
                )
            except Exception:
                pass

            ledger.append_decision(
                {
                    "iteration": iter_num,
                    "decision": "error",
                    "error": str(exc),
                }
            )

    # Final state
    final_state = ledger.read_loop_state()
    final_state.update(
        {
            "iteration": final_state.get("iteration", 0),
            "best_score": best_score,
            "status": "completed",
        }
    )
    ledger.write_loop_state(
        final_state
    )

    summary = {
        "status": "completed",
        "total_iterations": len(results),
        "best_score": best_score,
        "results": results,
    }

    _LOGGER.info(
        "run_loop complete: best_score=%.6f iterations=%d", best_score, len(results)
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="BSG Autoresearch — Run Loop")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="BSGautoresearch base directory",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum number of loop iterations",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow running with a dirty Batho working tree",
    )
    args = parser.parse_args()

    run_loop(
        args.base_dir, max_iterations=args.max_iterations, allow_dirty=args.allow_dirty
    )


if __name__ == "__main__":
    main()
