"""BSG Autoresearch — Prepare (immutable environment bootstrap + baseline).

Responsibilities:
  - Load config + repo list
  - Clone/update repos into configured location
  - Enforce size/file thresholds
  - Build fixed train/holdout split (deterministic by hash)
  - Compute baseline metrics
  - Write baseline state
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add parent to path for service imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.config_loader import ConfigLoader
from services.repo_registry import split_repos
from services.repo_cloner import ensure_all_repos
from services.repo_filter import check_repo, collect_source_files
from services.evaluator import compute_baseline
from services.ledger import Ledger
from services.git_gate import check_tree_clean

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger(__name__)


def prepare(base_dir: Path, *, allow_dirty: bool = False) -> dict:
    """Execute the prepare phase. Returns a summary dict."""

    loader = ConfigLoader(base_dir)
    configs = loader.load_all()

    system = configs["system"]
    repos = configs["repositories"]
    metrics = configs["metrics"]

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

    _LOGGER.info("batho_root=%s", batho_root)
    _LOGGER.info("clone_root=%s", clone_root)
    _LOGGER.info("plugin_target=%s", plugin_target)

    # Check tree cleanliness
    check_tree_clean(batho_root, allow_dirty=allow_dirty)

    # Split repos into train/holdout
    train_repos, holdout_repos = split_repos(repos, holdout_count=2)
    _LOGGER.info("train repos: %s", [r["name"] for r in train_repos])
    _LOGGER.info("holdout repos: %s", [r["name"] for r in holdout_repos])

    # Clone/update all repos
    depth = int(system.get("git_clone_depth", 1))
    all_repos = train_repos + holdout_repos
    repo_paths = ensure_all_repos(all_repos, clone_root, depth=depth)

    # Filter repos by size thresholds
    max_size = float(system.get("max_repo_size_mb", 500))
    max_files = int(system.get("max_files", 200000))
    max_file_size = float(system.get("max_single_file_mb", 10))

    skipped_repos: list[str] = []
    for repo in all_repos:
        repo_path = repo_paths[repo["name"]]
        passes, reasons = check_repo(
            repo,
            repo_path,
            max_size_mb=max_size,
            max_files=max_files,
            max_single_file_mb=max_file_size,
        )
        if not passes:
            _LOGGER.warning("skipping %s: %s", repo["name"], "; ".join(reasons))
            skipped_repos.append(repo["name"])

    # Collect source files for passing repos
    repo_files: dict[str, list[Path]] = {}
    for repo in all_repos:
        if repo["name"] in skipped_repos:
            continue
        repo_path = repo_paths[repo["name"]]
        include = repo.get("include_globs", ["**/*"])
        exclude = repo.get("exclude_globs", [])
        files = collect_source_files(repo_path, include, exclude)
        repo_files[repo["name"]] = files
        _LOGGER.info("%s: %d source files", repo["name"], len(files))

    train_repo_paths = [
        repo_paths[repo["name"]]
        for repo in train_repos
        if repo["name"] not in skipped_repos
    ]
    holdout_repo_paths = [
        repo_paths[repo["name"]]
        for repo in holdout_repos
        if repo["name"] not in skipped_repos
    ]

    # Compute baseline
    baseline = compute_baseline(
        plugin_target,
        metrics,
        train_repo_paths=train_repo_paths,
        holdout_repo_paths=holdout_repo_paths,
        max_file_size_kb=max(1, int(max_file_size * 1024)),
        max_workers=0,
    )
    _LOGGER.info("baseline score: %.6f", baseline["score"])

    # Initialize ledger
    state_dir = base_dir / "state"
    ledger = Ledger(state_dir)

    # Write initial loop state
    ledger.write_loop_state(
        {
            "iteration": 0,
            "best_score": baseline["score"],
            "status": "prepared",
            "train_repos": [r["name"] for r in train_repos],
            "holdout_repos": [r["name"] for r in holdout_repos],
            "skipped_repos": skipped_repos,
        }
    )

    # Write baseline metrics
    ledger.append_metrics(
        0,
        {
            "phase": "baseline",
            "score": baseline["score"],
            "coverage": baseline["coverage"],
            "precision_proxy": baseline["precision_proxy"],
            "holdout_generalization": baseline["holdout_generalization"],
            "determinism": baseline["determinism"],
            "runtime_efficiency": baseline["runtime_efficiency"],
            "runtime_seconds": baseline["runtime_seconds"],
            "plugin_stats": baseline["plugin_stats"],
            "train_summary": baseline.get("train_summary", {}),
            "holdout_summary": baseline.get("holdout_summary", {}),
            "hard_gates": baseline.get("hard_gates", {}),
        },
    )

    summary = {
        "status": "prepared",
        "batho_root": str(batho_root),
        "clone_root": str(clone_root),
        "train_repos": [r["name"] for r in train_repos],
        "holdout_repos": [r["name"] for r in holdout_repos],
        "skipped_repos": skipped_repos,
        "repo_file_counts": {name: len(files) for name, files in repo_files.items()},
        "baseline_score": baseline["score"],
        "baseline_stats": baseline["plugin_stats"],
    }

    _LOGGER.info("prepare complete: %s", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="BSG Autoresearch — Prepare phase")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="BSGautoresearch base directory",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow running with a dirty Batho working tree",
    )
    args = parser.parse_args()

    prepare(args.base_dir, allow_dirty=args.allow_dirty)


if __name__ == "__main__":
    main()
