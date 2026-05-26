"""CLI command helpers for ``batho plugins`` subcommands (test / trace).

These helpers are kept in a dedicated module so they can evolve independently
of the main CLI file and be imported by tests directly. The parent
``batho_cli.py`` wires them as subcommands.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from batho.bsg import load_effective_rules
from batho.bsg.rules import apply_rule_plugins, validate_plugin_file
from batho.bsg.testing import (
    FixtureError,
    FixtureReport,
    run_fixture_directory,
    run_plugin_fixture,
    summarize_reports,
)
from batho.config import get_config_cached, set_active_root


def _resolve_root(args: argparse.Namespace) -> Path:
    root_value = getattr(args, "root", None) or "."
    return Path(root_value).resolve()


def cmd_plugins_test(args: argparse.Namespace) -> int:
    """Run plugin fixtures and emit a structured report.

    The runner treats each YAML file under ``--fixtures`` (or a single
    ``--fixture`` file) as an independent test case.
    """

    fixtures_dir = getattr(args, "fixtures", None)
    fixture_file = getattr(args, "fixture", None)

    if not fixtures_dir and not fixture_file:
        print("error: must pass --fixtures <dir> or --fixture <file>")
        return 2

    reports: list[FixtureReport] = []
    try:
        if fixture_file:
            reports.append(
                run_plugin_fixture(
                    Path(fixture_file).resolve(),
                    root_path=(
                        Path(getattr(args, "root", ".")).resolve()
                        if getattr(args, "root", None)
                        else None
                    ),
                )
            )
        if fixtures_dir:
            reports.extend(
                run_fixture_directory(
                    Path(fixtures_dir).resolve(),
                    root_path=(
                        Path(getattr(args, "root", ".")).resolve()
                        if getattr(args, "root", None)
                        else None
                    ),
                )
            )
    except FixtureError as exc:
        print(f"fixture error: {exc}")
        return 2

    summary = summarize_reports(reports)
    output = {
        "summary": summary,
        "results": [
            {
                "fixture": r.name,
                "path": r.fixture_path,
                "passed": r.passed,
                "failures": list(r.failures),
            }
            for r in reports
        ],
    }

    if getattr(args, "json", False):
        print(json.dumps(output, indent=2))
    else:
        print(
            f"{summary['passed']}/{summary['total']} fixtures passed"
        )
        for r in reports:
            status = "PASS" if r.passed else "FAIL"
            print(f"  [{status}] {r.name}")
            for failure in r.failures:
                print(f"         - {failure}")

    return 0 if summary["failed"] == 0 else 1


def cmd_plugins_validate_strict(args: argparse.Namespace) -> int:
    """Wrap ``validate_plugin_file`` with strict-mode promotion."""

    plugin_path = Path(args.plugin_file).resolve()
    result = validate_plugin_file(plugin_path, strict=bool(getattr(args, "strict", False)))
    print(json.dumps(result, indent=2))
    return 0 if result.get("valid") else 1


def cmd_plugins_trace(args: argparse.Namespace) -> int:
    """Run the full rule engine with trace/profile instrumentation.

    By default we only run the loader to avoid requiring a built code graph.
    ``--apply`` forces a full ``apply_rule_plugins`` run; this requires that
    ``.batho`` already contains a code graph for the target repository, or an
    empty graph is used in which case no entities will match.
    """

    root = _resolve_root(args)
    if not root.exists() or not root.is_dir():
        print(f"root does not exist or is not a directory: {root}")
        return 1

    set_active_root(root)
    cfg = get_config_cached()
    rules_cfg = (cfg.get("bsg", {}) or {}).get("rules", {}) if isinstance(cfg, dict) else {}

    if not getattr(args, "apply", False):
        rules, stats = load_effective_rules(rules_cfg, root_path=root)
        payload = {
            "root": str(root),
            "rules_loaded": len(rules),
            "stats": stats,
        }
        print(json.dumps(payload, indent=2, default=str))
        return 0 if not stats.get("errors") else 1

    # Apply path: reload the cached graph from the .batho database
    try:
        from batho.context.graph_cache import load_cached_graph
        from batho.storage.engine import get_database
    except Exception as exc:  # pragma: no cover - import side-effect
        print(f"cannot load graph cache module: {exc}")
        return 1

    db = get_database(root)
    current_index_id = db.get_latest_run_id()
    if not current_index_id:
        print("no completed index run found — run 'batho index' first to use --apply")
        return 1

    try:
        graph = load_cached_graph(root, current_index_id)
    except Exception as exc:
        print(f"failed to load cached graph: {exc}")
        return 1

    if graph is None:
        print(f"no cached graph for index_id={current_index_id}")
        return 1

    summary = apply_rule_plugins(
        graph=graph,
        root_path=root,
        rules_config=rules_cfg,
        profile=bool(getattr(args, "profile", False)),
        trace=True,
    )

    # The default summary carries the trace_log directly. Output as JSON for
    # downstream post-processing.
    print(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_plugins_verify_bidirectional(args: argparse.Namespace) -> int:
    """Validate bidirectional flow integrity via BSG plugins."""
    root = _resolve_root(args)
    if not root.exists() or not root.is_dir():
        print(f"root does not exist or is not a directory: {root}")
        return 1

    set_active_root(root)
    cfg = get_config_cached()
    rules_cfg = (cfg.get("bsg", {}) or {}).get("rules", {}) if isinstance(cfg, dict) else {}

    try:
        from batho.context.graph_cache import load_cached_graph
        from batho.storage.engine import get_database
    except Exception as exc:  # pragma: no cover
        print(f"cannot load graph cache module: {exc}")
        return 1

    db = get_database(root)
    current_index_id = db.get_latest_run_id()
    if not current_index_id:
        print("no completed index run found — run 'batho index' first")
        return 1

    try:
        graph = load_cached_graph(root, current_index_id)
    except Exception as exc:
        print(f"failed to load cached graph: {exc}")
        return 1

    if graph is None:
        print(f"no cached graph for index_id={current_index_id}")
        return 1

    summary = apply_rule_plugins(
        graph=graph,
        root_path=root,
        rules_config=rules_cfg,
        profile=bool(getattr(args, "profile", False)),
        trace=bool(getattr(args, "trace", False)),
        bidirectional_only=True,
    )

    print(json.dumps(summary, indent=2, default=str))
    return 0


def register_cli_subcommands(plugins_sub: argparse._SubParsersAction[Any]) -> None:
    """Attach ``test``, ``validate-strict``, ``trace`` and ``verify-bidirectional`` subparsers to
    an existing ``plugins`` subparser group (see ``batho_cli.build_parser``).
    """

    test_parser = plugins_sub.add_parser(
        "test",
        help="Run BSG plugin fixture tests (YAML given/expect files)",
    )
    test_parser.add_argument(
        "--fixtures",
        default=None,
        help="Directory containing *.yaml fixture files",
    )
    test_parser.add_argument(
        "--fixture",
        default=None,
        help="Path to a single fixture YAML file",
    )
    test_parser.add_argument(
        "--root",
        default=None,
        help="Optional root path to use when the fixture relies on file-content matchers",
    )
    test_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON output instead of the human summary",
    )
    test_parser.set_defaults(func=cmd_plugins_test)

    validate_strict = plugins_sub.add_parser(
        "validate-strict",
        help="Validate a plugin YAML with strict-mode (promotes warnings to errors)",
    )
    validate_strict.add_argument(
        "plugin_file", help="Path to plugin YAML file to validate"
    )
    validate_strict.add_argument(
        "--strict",
        action="store_true",
        default=True,
        help="Promote structural warnings (unreachable rules, conflicts) into errors",
    )
    validate_strict.set_defaults(func=cmd_plugins_validate_strict)

    trace_parser = plugins_sub.add_parser(
        "trace",
        help="Inspect rule resolution and (optionally) apply rules with a trace log",
    )
    trace_parser.add_argument("--root", required=True, help="Repository root")
    trace_parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply rules against the cached graph and emit a per-entity trace log",
    )
    trace_parser.add_argument(
        "--profile",
        action="store_true",
        help="Collect per-rule timing and persist .batho-config/metrics/bsg_perf.json",
    )
    trace_parser.set_defaults(func=cmd_plugins_trace)

    verify_bidir_parser = plugins_sub.add_parser(
        "verify-bidirectional",
        help="Validate bidirectional flow integrity via BSG plugins",
    )
    verify_bidir_parser.add_argument("--root", required=True, help="Repository root")
    verify_bidir_parser.add_argument(
        "--profile",
        action="store_true",
        help="Collect per-rule timing and persist .batho-config/metrics/bsg_perf.json",
    )
    verify_bidir_parser.add_argument(
        "--trace",
        action="store_true",
        help="Emit detailed trace log for bidirectional plugin execution",
    )
    verify_bidir_parser.set_defaults(func=cmd_plugins_verify_bidirectional)


__all__ = [
    "cmd_plugins_test",
    "cmd_plugins_trace",
    "cmd_plugins_validate_strict",
    "cmd_plugins_verify_bidirectional",
    "register_cli_subcommands",
]
