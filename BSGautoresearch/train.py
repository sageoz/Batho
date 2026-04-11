"""BSG Autoresearch — Train (mutable hypothesis/candidate generation).

Responsibilities:
  - Mine conventions from train repos (naming patterns, file patterns, relationship motifs)
  - Generate candidate rule deltas deterministically
  - Compile candidate into full valid bsg-plugin.v1 YAML
  - Write candidate file to generated/candidate_plugin.yaml
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
from services.convention_miner import mine_conventions, aggregate_conventions
from services.rule_compiler import compile_rules, write_candidate
from services.llm_client import OpenRouterClient, merge_signals
from services.plugin_validator import validate_plugin_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger(__name__)


def train(base_dir: Path) -> dict:
    """Execute the train phase. Returns a summary dict."""

    loader = ConfigLoader(base_dir)
    configs = loader.load_all()

    system = configs["system"]
    repos = configs["repositories"]
    metrics = configs["metrics"]
    llm_cfg = system.get("llm") if isinstance(system.get("llm"), dict) else None

    # Resolve paths
    batho_root = (base_dir / system["batho_root"]).resolve()
    clone_root_str = system["clone_root"]
    clone_root = (
        (base_dir / clone_root_str).resolve()
        if not Path(clone_root_str).is_absolute()
        else Path(clone_root_str)
    )

    # Get train split
    train_repos, holdout_repos = split_repos(repos, holdout_count=2)

    # Clone/update train repos
    depth = int(system.get("git_clone_depth", 1))
    repo_paths = ensure_all_repos(train_repos, clone_root, depth=depth)

    # Filter and collect source files
    max_size = float(system.get("max_repo_size_mb", 500))
    max_files = int(system.get("max_files", 200000))
    max_file_size = float(system.get("max_single_file_mb", 10))

    repo_conventions: list[dict] = []
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
            _LOGGER.warning("skipping %s: %s", repo["name"], "; ".join(reasons))
            continue

        include = repo.get("include_globs", ["**/*"])
        exclude = repo.get("exclude_globs", [])
        files = collect_source_files(repo_path, include, exclude)
        _LOGGER.info("%s: mining %d files", repo["name"], len(files))

        conventions = mine_conventions(files, repo["language"], repo_path)
        repo_conventions.append(conventions)

    # Aggregate conventions across repos
    aggregated = aggregate_conventions(repo_conventions)
    base_signal_count = len(aggregated["signals"])

    llm_client = OpenRouterClient(llm_cfg or {}) if llm_cfg else None
    llm_enabled = bool(llm_client and llm_client.enabled)
    llm_configured = bool(llm_client and llm_client.configured)
    llm_signals: list[dict] = []

    if llm_client and llm_client.enabled:
        llm_signals = llm_client.propose_signals(
            aggregated,
            max_signals=int((llm_cfg or {}).get("max_signals", 6)),
        )
        if llm_signals:
            aggregated["signals"] = merge_signals(aggregated["signals"], llm_signals)

    _LOGGER.info(
        "aggregated %d signals from %d repos",
        len(aggregated["signals"]),
        aggregated["repo_count"],
    )

    # Compile rules
    plugin_doc = compile_rules(aggregated)
    _LOGGER.info("compiled %d rules", len(plugin_doc.get("rules", [])))

    # Write candidate
    candidate_path = base_dir / "generated" / "candidate_plugin.yaml"
    write_candidate(plugin_doc, candidate_path)

    # Validate candidate
    is_valid, errors, _ = validate_plugin_file(candidate_path)
    if not is_valid:
        _LOGGER.error("candidate plugin validation failed: %s", errors)
    else:
        _LOGGER.info("candidate plugin schema-valid")

    summary = {
        "status": "trained",
        "base_signals_count": base_signal_count,
        "llm_signals_count": len(llm_signals),
        "llm_enabled": llm_enabled,
        "llm_configured": llm_configured,
        "signals_count": len(aggregated["signals"]),
        "rules_count": len(plugin_doc.get("rules", [])),
        "candidate_path": str(candidate_path),
        "schema_valid": is_valid,
        "schema_errors": errors if not is_valid else [],
        "languages": aggregated.get("languages", []),
    }

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="BSG Autoresearch — Train phase")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="BSGautoresearch base directory",
    )
    args = parser.parse_args()

    train(args.base_dir)


if __name__ == "__main__":
    main()
