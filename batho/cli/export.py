"""CLI subcommand: batho export

Thin argparse wrapper around batho.orchestrator.export.run_export().
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def register_export_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the `export` subcommand on the given subparsers action."""
    parser = subparsers.add_parser(
        "export",
        help="Export BSG artifacts as JSON (storage, agent, overview, files, symbols, dependencies, delta)",
        description=(
            "Export the latest BSG artifact from a .batho database into one of "
            "several JSON views. Supports streaming mode for large repositories."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Repository root directory (default: current directory)",
    )
    parser.add_argument(
        "--view",
        type=str,
        default="storage",
        choices=["storage", "agent", "overview", "files", "symbols", "dependencies", "delta"],
        help=(
            "JSON view to export: "
            "storage (full fidelity), "
            "agent (LLM-optimized), "
            "overview (high-level stats), "
            "files (file-centric), "
            "symbols (flat symbol index), "
            "dependencies (dependency graph), "
            "delta (diff vs baseline). "
            "Default: storage"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--index-id",
        type=str,
        default=None,
        dest="index_id",
        metavar="ID",
        help="Specific index run ID to export (default: latest completed run)",
    )
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        dest="filter_pattern",
        metavar="GLOB",
        help="Glob pattern to filter files (e.g. 'src/**/*.py')",
    )
    parser.add_argument(
        "--format",
        type=str,
        default="json",
        choices=["json", "pretty"],
        dest="output_format",
        help="Output format: json (compact) or pretty (indented). Default: json",
    )
    parser.add_argument(
        "--category",
        type=str,
        default="all",
        choices=["source", "test", "doc", "config", "infra", "all"],
        help="Filter by BSG category. Default: all",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        default=False,
        help="Enable streaming mode for large repositories (memory-efficient)",
    )
    parser.add_argument(
        "--token-budget",
        type=int,
        default=None,
        dest="token_budget",
        metavar="N",
        help="Maximum token budget for the agent view (no limit by default)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        dest="baseline_path",
        metavar="PATH",
        help="Path to a previous export JSON for the delta view",
    )
    parser.set_defaults(func=cmd_export)


def cmd_export(args: argparse.Namespace) -> int:
    """Execute the export command."""
    from batho.orchestrator.export import ExportOptions, run_export

    options = ExportOptions(
        root=args.root,
        view=args.view,
        output=args.output,
        format=args.output_format,
        filter_pattern=args.filter_pattern,
        category=args.category,
        index_id=args.index_id,
        use_streaming=args.stream,
        token_budget=args.token_budget,
        baseline_path=args.baseline_path,
    )

    result = run_export(options)

    if not result.success:
        for err in result.errors:
            print(f"error: {err}", file=sys.stderr)
        return 1

    # If streaming to stdout, consume the generator
    if result.stream_generator is not None:
        try:
            for chunk in result.stream_generator:
                sys.stdout.write(chunk)
            sys.stdout.write("\n")
            sys.stdout.flush()
        except BrokenPipeError:
            pass  # e.g. piped to `head`

    # Print summary to stderr so it doesn't pollute stdout JSON
    summary_parts = [
        f"{result.file_count} files",
        f"{result.entity_count} entities",
    ]
    if result.output_path:
        summary_parts.append(f"→ {result.output_path}")
    print(
        f"Exported [{args.view}]: " + ", ".join(summary_parts),
        file=sys.stderr,
    )
    return 0
