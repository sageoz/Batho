"""CLI subcommand: batho fix

Integrity verification and repair for the artifact database.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def register_fix_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the `fix` subcommand."""
    from batho.modules.integrity.cli import register_fix_parser as reg
    parser = reg(subparsers)
    parser.set_defaults(func=cmd_fix)


def cmd_fix(args: argparse.Namespace) -> int:
    """Execute the fix command."""
    from batho.modules.integrity.engine import FixEngine
    from batho.modules.integrity.report import ReportGenerator

    root = args.root.resolve()

    # Check database exists
    from batho.modules.storage.sqlite_registry.engine import resolve_db_path
    db_path = resolve_db_path(root)
    if not db_path.exists():
        # Try alternate naming
        candidates = list(root.glob("artifact_*.batho"))
        if not candidates:
            print(f"error: No artifact database found in {root}", file=sys.stderr)
            print("       Run 'batho build --root {}' first.".format(root), file=sys.stderr)
            return 1
        db_path = candidates[0]

    # Run fix engine
    try:
        engine = FixEngine(
            root=root,
            deep_mode=getattr(args, "deep", False),
            dry_run=getattr(args, "dry_run", False),
            target=getattr(args, "target", "all"),
            phase=getattr(args, "phase", None),
            parallel=getattr(args, "parallel", False),
            verbose=getattr(args, "verbose", False),
        )

        result = engine.run()

    except Exception as exc:
        print(f"error: Fix engine failed: {exc}", file=sys.stderr)
        return 2

    # Generate report
    try:
        generator = ReportGenerator(format=args.format)
        report = generator.generate(result)

        if args.output:
            args.output.write_text(report, encoding="utf-8")
            print(f"📁 Report saved to: {args.output}")
        else:
            print(report)

    except Exception as exc:
        print(f"error: Report generation failed: {exc}", file=sys.stderr)
        return 2

    return result.summary.exit_code


__all__ = ["register_fix_parser", "cmd_fix"]
