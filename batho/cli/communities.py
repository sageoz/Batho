"""batho communities — community inspection + post-build labeling (T16).

`batho communities label` is the compile-time LLM half of community naming:
it reads communities.ipc, builds deterministic cards, calls the configured
model, and persists labels back into the artifact. All later reads are
deterministic and LLM-free.
"""

from __future__ import annotations

import argparse
import json
import sys

import structlog

LOGGER = structlog.get_logger("cli.communities")


def register_communities_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register `batho communities` and its subcommands."""
    cmd = subparsers.add_parser(
        "communities",
        help="Community commands (label, list)",
        description="Post-build community operations on the existing artifact.",
    )
    sub = cmd.add_subparsers(
        dest="communities_command", required=True, metavar="command"
    )

    from batho.cli._utils import create_base_parser

    p_label = sub.add_parser(
        "label",
        parents=[create_base_parser()],
        help="LLM-label communities (writes labels into the artifact)",
        description=(
            "Post-build community labeling. Reads communities.ipc, builds a "
            "deterministic card per community, calls the configured LLM "
            "(community_detection.llm + BATHO_LLM_API_KEY), and persists "
            "labels + label_source/label_input_hash back. Incremental: only "
            "communities whose card changed are re-labeled. Off by default — "
            "disabled config or missing key → clean no-op."
        ),
    )
    p_label.add_argument(
        "--dry-run", action="store_true",
        help="Build cards and report what WOULD be labeled (no writes, no LLM calls).",
    )
    p_label.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Emit JSON result.",
    )

    p_list = sub.add_parser(
        "list",
        parents=[create_base_parser()],
        help="List communities with hierarchy + labels",
    )
    p_list.add_argument(
        "--tree", action="store_true",
        help="Render the parent/level hierarchy as an indented tree.",
    )
    p_list.add_argument(
        "--top", type=int, default=30, help="Max rows (default 30).",
    )
    p_list.add_argument("--json", action="store_true", dest="json_output")

    cmd.set_defaults(func=cmd_communities)


def cmd_communities(args: argparse.Namespace) -> int:
    from pathlib import Path

    from batho.core.config.loader import set_active_root

    root = Path(args.root).resolve()
    set_active_root(root)
    if args.communities_command == "label":
        return _cmd_label(args, root)
    if args.communities_command == "list":
        return _cmd_list(args, root)
    print(f"error: unknown communities command {args.communities_command!r}", file=sys.stderr)
    return 2


def _cmd_label(args: argparse.Namespace, root) -> int:
    """Post-build LLM labeling — persisted, incremental, off-by-default."""
    from batho.modules.graph.community_labels import (
        build_community_card, card_input_hash, community_edge_profiles,
        llm_label_communities,
    )
    from batho.modules.storage.arrow_bundle.bundle import BathoBundle
    from batho.modules.storage.arrow_bundle.schemas import COMMUNITIES_SCHEMA
    from batho.modules.storage.arrow_bundle.writer import write_simple_ipc
    from batho.mcp.community_summaries import load_communities
    from batho.orchestrator.plugins_apply import _load_graph_from_artifact

    from batho.core.config.loader import get_config_cached

    cfg = get_config_cached()
    llm_cfg = ((cfg.get("community_detection") or {}).get("llm")) or {}

    db = BathoBundle(root)
    artifact_dir = db.artifact_dir
    rows = load_communities(artifact_dir)
    if not rows:
        msg = "no communities.ipc — run `batho build` (with communities enabled) first."
        if args.json_output:
            print(json.dumps({"labeled": 0, "errors": [msg]}))
        else:
            print(msg)
        return 0

    # COM-03: the disabled path must not pay for a full graph load (which
    # defaults to include_storage=True and reads every storage blob). Check
    # the enablement gate before loading; --dry-run still loads since it
    # previews cards.
    import os
    llm_enabled = bool(llm_cfg.get("enabled")) and bool(
        os.getenv("BATHO_LLM_API_KEY")
    )
    if not llm_enabled and not args.dry_run:
        msg = (
            "community_detection.llm disabled or BATHO_LLM_API_KEY unset "
            "— nothing to do."
        )
        if args.json_output:
            print(json.dumps({"labeled": 0, "disabled": True}))
        else:
            print(msg)
        return 0

    run_uuid = db.get_latest_run_id()
    internal = db.get_run_internal_id(run_uuid) if run_uuid else None
    graph = None
    if internal is not None:
        # Read-only consumer: labels/cards never need raw_content blobs.
        graph, _views, _tracking, _eid_map = _load_graph_from_artifact(
            db, internal, root, include_storage=False
        )

    if args.dry_run:
        max_tokens = int(llm_cfg.get("max_card_tokens", 200))
        by_id = {r.get("community_id"): r for r in rows}
        edge_profiles = community_edge_profiles(graph, rows)
        preview = []
        for row in sorted(rows, key=lambda r: r.get("community_id", 0)):
            parent = by_id.get(row.get("parent_id"))
            card = build_community_card(
                row, graph,
                (parent or {}).get("llm_label") or (parent or {}).get("heuristic_label"),
                max_tokens,
                edge_profile=edge_profiles.get(row.get("community_id")),
            )
            digest = card_input_hash(card)
            changed = row.get("label_input_hash") != digest
            preview.append({
                "community_id": row.get("community_id"),
                "heuristic_label": row.get("heuristic_label"),
                "would_relabel": changed,
                "card": card,
            })
        out = {
            "dry_run": True,
            "communities": len(rows),
            "would_relabel": sum(1 for p in preview if p["would_relabel"]),
            "enabled": bool(llm_cfg.get("enabled")),
            "preview": preview,
        }
        print(json.dumps(out, indent=2, default=str) if args.json_output
              else _human_dry(out))
        return 0

    stats = llm_label_communities(rows, graph, llm_cfg, logger=LOGGER)
    if stats.get("disabled"):
        msg = "community_detection.llm disabled or BATHO_LLM_API_KEY unset — nothing to do."
        if stats.get("reason"):
            msg = stats["reason"] + " — nothing to do."
        if args.json_output:
            print(json.dumps({"labeled": 0, "disabled": True, **{k: v for k, v in stats.items() if k != 'disabled'}}))
        else:
            print(msg)
        return 0

    # Persist only when something actually changed.
    if stats["labeled"] or stats["fallback"]:
        final_path = artifact_dir / "communities.ipc"
        tmp = artifact_dir / "communities.label.tmp.ipc"
        write_simple_ipc(rows, COMMUNITIES_SCHEMA, tmp)
        tmp.replace(final_path)
        LOGGER.info(
            "communities_labeled",
            labeled=stats["labeled"],
            fallback=stats["fallback"],
            skipped=stats["skipped_unchanged"],
        )

    if args.json_output:
        print(json.dumps(stats))
    else:
        print(
            f"labeled={stats['labeled']} skipped(unchanged)={stats['skipped_unchanged']} "
            f"heuristic_fallback={stats['fallback']}"
        )
    return 0


def _human_dry(out: dict) -> str:
    lines = [f"dry-run: {out['communities']} communities, {out['would_relabel']} would be re-labeled",
             f"llm.enabled={out['enabled']}"]
    for p in out["preview"][:10]:
        mark = "*" if p["would_relabel"] else " "
        lines.append(f" [{mark}] #{p['community_id']} {p['heuristic_label']}")
    return "\n".join(lines)


def _cmd_list(args: argparse.Namespace, root) -> int:
    """List communities — optional indented hierarchy view."""
    from batho.modules.storage.arrow_bundle.bundle import BathoBundle
    from batho.mcp.community_summaries import load_communities

    db = BathoBundle(root)
    rows = load_communities(db.artifact_dir)
    if not rows:
        print("no communities.ipc — run `batho build` first.")
        return 0

    def _disp(r):
        return r.get("llm_label") or r.get("heuristic_label") or r.get("name") or "?"

    if args.json_output:
        print(json.dumps(rows, indent=2, default=str))
        return 0

    if args.tree:
        children: dict = {}
        roots = []
        for r in rows:
            pid = r.get("parent_id")
            if pid is None:
                roots.append(r)
            else:
                children.setdefault(pid, []).append(r)
        roots.sort(key=lambda r: (-(r.get("entity_count") or 0), r.get("community_id", 0)))
        printed = [0]

        def _emit(r, indent):
            if printed[0] >= args.top:
                return
            print(f"{'  ' * indent}#{r.get('community_id')} {_disp(r)} "
                  f"({r.get('entity_count', 0)} entities, level {r.get('level') or 0})")
            printed[0] += 1
            for c in sorted(children.get(r.get("community_id"), []),
                            key=lambda x: (-(x.get("entity_count") or 0), x.get("community_id", 0))):
                _emit(c, indent + 1)

        for r in roots:
            _emit(r, 0)
        return 0

    rows_sorted = sorted(rows, key=lambda r: (-(r.get("entity_count") or 0), r.get("community_id", 0)))
    for r in rows_sorted[: args.top]:
        pid = r.get("parent_id")
        src = r.get("label_source") or "-"
        print(f"#{r.get('community_id'):<4} L{r.get('level') or 0} {_disp(r):<36} "
              f"{r.get('entity_count', 0):>5} entities  parent={pid if pid is not None else '-':<4} src={src}")
    return 0
