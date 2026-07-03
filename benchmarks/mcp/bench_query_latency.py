"""Benchmark: MCP tool query latency.

Measures end-to-end latency for each MCP tool against a built artifact.
Usage: uv run python benchmarks/mcp/bench_query_latency.py --root /path/to/repo
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from batho.mcp.tools import _get_reader
from batho.mcp.graph_builder import build_dual_output
from batho.mcp.delta_reader import read_delta


def bench_graph_overview(root: Path, iterations: int = 10) -> float:
    reader = _get_reader(str(root))
    times = []
    for _ in range(iterations):
        t0 = time.monotonic()
        agent_table = reader._get_table("agent_views")
        rels_table = reader._get_table("rels_views")
        tracking = reader.get_all_file_tracking()
        runs = reader.get_all_runs()
        _ = agent_table.num_rows, rels_table.num_rows, len(tracking), len(runs)
        times.append(time.monotonic() - t0)
    return sum(times) / len(times) * 1000


def bench_graph_query(root: Path, iterations: int = 10) -> float:
    reader = _get_reader(str(root))
    agent_table = reader._get_table("agent_views")
    if agent_table.num_rows == 0:
        return 0.0
    times = []
    for _ in range(iterations):
        t0 = time.monotonic()
        rows = agent_table.to_pylist()[:50]
        file_paths = _file_paths_map(reader)
        md, _ = build_dual_output(rows, [], file_paths)
        times.append(time.monotonic() - t0)
    return sum(times) / len(times) * 1000


def bench_get_entity(root: Path, iterations: int = 10) -> float:
    import pyarrow.compute as pc
    reader = _get_reader(str(root))
    agent_table = reader._get_table("agent_views")
    if agent_table.num_rows == 0:
        return 0.0
    first_id = agent_table.to_pylist()[0]["entity_id"]
    times = []
    for _ in range(iterations):
        t0 = time.monotonic()
        mask = pc.equal(agent_table.column("entity_id"), first_id)
        _ = agent_table.filter(mask).to_pylist()
        times.append(time.monotonic() - t0)
    return sum(times) / len(times) * 1000


def bench_get_delta(root: Path, iterations: int = 10) -> float:
    reader = _get_reader(str(root))
    times = []
    for _ in range(iterations):
        t0 = time.monotonic()
        read_delta(reader)
        times.append(time.monotonic() - t0)
    return sum(times) / len(times) * 1000


def _file_paths_map(reader):
    tracking = reader.get_all_file_tracking()
    return {v.get("file_id", -1): k for k, v in tracking.items()}


def main():
    parser = argparse.ArgumentParser(description="Benchmark MCP tool query latency")
    parser.add_argument("--root", required=True, help="Repository root with .batho artifact")
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    print(f"\n=== MCP Query Latency Benchmark ===")
    print(f"Root: {root}")
    print(f"Iterations: {args.iterations}\n")

    results = {
        "graph_overview": bench_graph_overview(root, args.iterations),
        "graph_query": bench_graph_query(root, args.iterations),
        "get_entity": bench_get_entity(root, args.iterations),
        "get_delta": bench_get_delta(root, args.iterations),
    }

    print(f"{'Tool':<25} {'Avg Latency (ms)':>15}")
    print("-" * 42)
    for tool, latency in results.items():
        print(f"{tool:<25} {latency:>15.2f}")


if __name__ == "__main__":
    main()
