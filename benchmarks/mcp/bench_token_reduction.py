"""Benchmark: Token reduction — markdown vs JSON.

Measures the token savings of markdown `content` vs JSON `structuredContent`
across different response formats and entity counts.
Usage: uv run python benchmarks/mcp/bench_token_reduction.py --root /path/to/repo
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from batho.mcp.tools import _get_reader
from batho.mcp.graph_builder import (
    build_dual_output, format_concise, format_detailed,
    estimate_tokens, build_node_dict, build_edge_dict,
)


def bench_token_reduction(root: Path) -> None:
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

    print(f"\n=== Token Reduction Benchmark ===")
    print(f"Entities: {len(all_rows)}, Relationships: {len(all_rels)}\n")

    for batch_size in [10, 25, 50, 100, len(all_rows)]:
        if batch_size > len(all_rows):
            continue
        rows = all_rows[:batch_size]
        rels = all_rels[:batch_size * 2] if len(all_rels) > batch_size * 2 else all_rels

        md_concise = format_concise(rows, rels, file_paths)
        md_detailed = format_detailed(rows, rels, None, file_paths)

        nodes_json = [build_node_dict(r) for r in rows]
        edges_json = [build_edge_dict(r) for r in rels]
        json_str = json.dumps({"nodes": nodes_json, "edges": edges_json}, default=str)

        tokens_concise = estimate_tokens(md_concise)
        tokens_detailed = estimate_tokens(md_detailed)
        tokens_json = estimate_tokens(json_str)

        reduction_concise = (1 - tokens_concise / tokens_json) * 100 if tokens_json > 0 else 0
        reduction_detailed = (1 - tokens_detailed / tokens_json) * 100 if tokens_json > 0 else 0

        print(f"Batch={batch_size:>4} | JSON={tokens_json:>6} tok | "
              f"Concise={tokens_concise:>5} tok ({reduction_concise:+.1f}%) | "
              f"Detailed={tokens_detailed:>5} tok ({reduction_detailed:+.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="Benchmark markdown vs JSON token reduction")
    parser.add_argument("--root", required=True, help="Repository root with .batho artifact")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    bench_token_reduction(root)


if __name__ == "__main__":
    main()
