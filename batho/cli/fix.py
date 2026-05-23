"""CLI subcommand: batho fix

Integrity verification and repair for the artifact database.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def register_fix_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the `fix` subcommand."""
    parser = subparsers.add_parser(
        "fix",
        help="Verify and repair artifact database integrity",
        description=(
            "Comprehensive integrity check and automatic repair for the Batho artifact database. "
            "Detects corruption, validates data structures, and repairs issues where possible. "
            "Quick mode by default; use --deep for comprehensive verification."
        ),
    )

    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Repository root directory (default: current directory)",
    )

    parser.add_argument(
        "--deep",
        action="store_true",
        help="Perform deep verification (slower, checks all data)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check only, do not perform any repairs",
    )

    parser.add_argument(
        "--format",
        choices=["text", "json", "csv"],
        default="text",
        help="Report output format (default: text)",
    )

    parser.add_argument(
        "--output",
        type=Path,
        help="Write report to file instead of stdout",
    )

    parser.add_argument(
        "--rollback-to",
        metavar="SNAPSHOT_ID",
        help="Rollback database to specific snapshot ID or 'last-known-good'",
    )

    parser.add_argument(
        "--repair-only",
        nargs="+",
        choices=[
            "database",
            "registry",
            "index",
            "bsg",
            "snapshots",
            "cache",
            "views",
        ],
        help="Only run specific repair checks",
    )

    parser.add_argument(
        "--create-checkpoint",
        metavar="NAME",
        help="Create a named checkpoint before any repairs",
    )

    parser.add_argument(
        "--no-audit",
        action="store_true",
        help="Disable detailed audit logging",
    )

    parser.set_defaults(func=cmd_fix)


def cmd_fix(args: argparse.Namespace) -> int:
    """Execute the fix command."""
    from batho.integrity.engine import FixEngine
    from batho.integrity.report import ReportGenerator
    from batho.integrity.rollback import RollbackManager
    from batho.storage.engine import get_database

    root = args.root.resolve()

    # Check database exists
    from batho.storage.engine import artifact_filename
    db_path = root / artifact_filename(root)
    if not db_path.exists():
        # Try alternate naming
        candidates = list(root.glob("artifact_*.batho"))
        if not candidates:
            print(f"error: No artifact database found in {root}", file=sys.stderr)
            print("       Run 'batho build --root {}' first.".format(root), file=sys.stderr)
            return 1
        db_path = candidates[0]

    # Handle rollback first
    if args.rollback_to:
        return handle_rollback(args)

    # Create checkpoint if requested
    if args.create_checkpoint:
        try:
            db = get_database(root)
            rollback_manager = RollbackManager(db, str(root))
            checkpoint_id = rollback_manager.create_named_checkpoint(args.create_checkpoint)
            print(f"✅ Created checkpoint: {checkpoint_id}")
        except Exception as exc:
            print(f"error: Failed to create checkpoint: {exc}", file=sys.stderr)
            return 1

    # Run fix engine
    try:
        engine = FixEngine(
            root=root,
            deep_mode=args.deep,
            dry_run=args.dry_run,
            audit_log=not args.no_audit,
            repair_only=args.repair_only,
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


def handle_rollback(args: argparse.Namespace) -> int:
    """Handle rollback subcommand."""
    from batho.integrity.rollback import RollbackManager
    from batho.storage.engine import get_database

    root = args.root.resolve()
    target = args.rollback_to

    try:
        db = get_database(root)
        rollback_manager = RollbackManager(db, str(root))

        if target == "last-known-good":
            snapshot_id = rollback_manager.find_last_known_good()
            if not snapshot_id:
                print("error: No healthy snapshot found for rollback", file=sys.stderr)
                return 1
            print(f"Found last known good snapshot: {snapshot_id}")
        else:
            snapshot_id = target

        print(f"Rolling back to snapshot: {snapshot_id}")

        if args.dry_run:
            print("(dry-run mode, no changes made)")
            return 0

        success = rollback_manager.rollback_to_snapshot(snapshot_id)

        if success:
            print(f"✅ Successfully rolled back to {snapshot_id}")
            return 0
        else:
            print(f"error: Rollback to {snapshot_id} failed", file=sys.stderr)
            return 1

    except Exception as exc:
        print(f"error: Rollback failed: {exc}", file=sys.stderr)
        return 2


__all__ = ["register_fix_parser", "cmd_fix"]
