"""Benchmark: Token efficiency across response_format variants.

Compares token counts for summary, concise, and detailed formats
at different entity counts to validate the 34-38% reduction claim.
Usage: uv run python benchmarks/mcp/bench_token_efficiency.py --root /path/to/repo
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from batho.mcp.tools import _get_reader
from batho.mcp.graph_builder import (
    format_concise, format_detailed, format_summary,
    estimate_tokens, build_node_dict, build_edge_dict,
)


def bench_token_efficiency(root: Path) -> None:
    reader = _get_reader(str(root))
    agent_table = reader._get_table("agent_views")
    rels_table = reader._get_table("rels_views")
    if agent_table.num_rows == 0:
        print("No entities found.")
        return

    tracking = reader.get_all_file_tracking()
    file_paths = {v.get("file_id", -1): k for k, v in tracking.items()}

    all_rows = agent_table.to_pylist()
    all_rels = rels_table.to_pylist() if rels_table.num_rows > 0 else []

    stats = {
        "total_entities": agent_table.num_rows,
        "total_relationships": rels_table.num_rows,
        "total_files": len(tracking),
        "relationship_breakdown": {},
    }

    print(f"\n=== Token Efficiency Benchmark ===")
    print(f"Entities: {len(all_rows)}, Relationships: {len(all_rels)}\n")

    summary_md = format_summary(stats)
    tokens_summary = estimate_tokens(summary_md)

    print(f"{'Format':<12} {'Tokens':>8} {'vs JSON':>10}")
    print("-" * 34)

    json_full = json.dumps({
        "nodes": [build_node_dict(r) for r in all_rows],
        "edges": [build_edge_dict(r) for r in all_rels],
    }, default=str)
    tokens_json = estimate_tokens(json_full)
    print(f"{'JSON':<12} {tokens_json:>8} {'baseline':>10}")

    print(f"{'summary':<12} {tokens_summary:>8} {(1 - tokens_summary / tokens_json) * 100:>+9.1f}%")

    for batch in [10, 25, 50, 100, len(all_rows)]:
        if batch > len(all_rows):
            continue
        rows = all_rows[:batch]
        rels = all_rels[:batch * 2] if len(all_rels) > batch * 2 else all_rels

        md_c = format_concise(rows, rels, file_paths)
        md_d = format_detailed(rows, rels, None, file_paths)
        json_batch = json.dumps({
            "nodes": [build_node_dict(r) for r in rows],
            "edges": [build_edge_dict(r) for r in rels],
        }, default=str)

        t_c = estimate_tokens(md_c)
        t_d = estimate_tokens(md_d)
        t_j = estimate_tokens(json_batch)

        print(f"concise[{batch:>3}] {t_c:>8} {(1 - t_c / t_j) * 100:>+9.1f}%")
        print(f"detailed[{batch:>3}] {t_d:>8} {(1 - t_d / t_j) * 100:>+9.1f}%")


def main():
    parser = argparse.ArgumentParser(description="Benchmark token efficiency across response formats")
    parser.add_argument("--root", required=True, help="Repository root with .batho artifact")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    bench_token_efficiency(root)


if __name__ == "__main__":
    main()
